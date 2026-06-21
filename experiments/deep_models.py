"""
Experiment -- can NON-TREE models beat the LightGBM-Tweedie champion?

We test three neural approaches on the SAME temporal split, the SAME 26 selected
features, and the SAME metrics (reusing src.model.evaluate / top_k_capture):

  * MLP   -- feed-forward net on the per-row feature vector (pure tabular DL;
             the most direct "deep net vs GBM on identical features" test).
  * LSTM  -- per (cell, time-block) sequence of the last L days of
             [features + realised count]; 1-step-ahead forecast of the count.
  * GRU   -- same sequence setup, gated-recurrent cell.

All three use a TWEEDIE deviance loss (variance power 1.5) so the objective
matches the shipped LightGBM-Tweedie -- this isolates the model CLASS, not the
loss. Predictions are a non-negative rate mu = exp(eta).

Comparability notes (kept honest):
  * Temporal split is identical (train <= TRAIN_END_DATE, test after); features
    are the same causal columns the trees use, so neither side leaks the future.
  * The RNNs warm up on L days; because every series spans the full history,
    NO test rows are dropped -> the test population is identical to the trees'.
  * NN inputs are standardised on train statistics; the trees are not (they do
    not need it). The realised-count channel uses ACTUAL past counts, exactly
    what the trees' lag features use.

Run from the project root:   python experiments/deep_models.py
"""
from __future__ import annotations

import os
import sys
import json
import time

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import config  # noqa: E402
from src import ingest, impact, aggregate, features, feature_selection  # noqa: E402
from src import model as M  # reuse evaluate() + top_k_capture()  # noqa: E402

import torch  # noqa: E402
import torch.nn as nn  # noqa: E402

SEED = config.RANDOM_STATE
np.random.seed(SEED)
torch.manual_seed(SEED)
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

L = 14                # RNN look-back window (days)
TWEEDIE_P = 1.5       # match LightGBM-Tweedie's tweedie_variance_power
TARGET = "viol_count"


def log(*a):
    print("  [deep]", *a, flush=True)


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #
def build_panel():
    log("rebuilding panel via the pipeline (ingest -> aggregate -> features) ...")
    d = impact.add_event_impact(ingest.run(cache=True))
    panel, cmeta = aggregate.build_panel(d, verbose=False)
    panel, cols, enc = features.build_features(panel, cmeta, verbose=False)
    keep, _ = feature_selection.select(panel, cols, verbose=False)
    panel = panel.copy()
    panel["date"] = pd.to_datetime(panel["date"])
    panel = panel.sort_values(["cell", "time_block", "date"]).reset_index(drop=True)
    log(f"panel {panel.shape} | features {len(keep)} | "
        f"train {(panel['split']=='train').sum():,} test {(panel['split']=='test').sum():,}")
    return panel, list(keep)


def _inner_cut():
    return np.datetime64(pd.Timestamp(config.TRAIN_END_DATE) - pd.Timedelta(days=M.INNER_VAL_DAYS))


def mlp_data(panel, keep):
    """Per-row tabular tensors. Scaler fit on full train; val = last INNER_VAL_DAYS of train."""
    feat = np.nan_to_num(panel[keep].astype("float32").values)
    y = panel[TARGET].astype("float32").values
    split = panel["split"].values
    dt = panel["date"].values
    tr, te = split == "train", split == "test"
    mu, sd = feat[tr].mean(0), feat[tr].std(0) + 1e-6
    Z = (feat - mu) / sd
    val = tr & (dt > _inner_cut())
    fit = tr & (dt <= _inner_cut())
    return (Z[fit], y[fit]), (Z[val], y[val]), (Z[te], y[te]), np.where(te)[0]


def seq_data(panel, keep, L):
    """Per (cell, time-block) windows of [features + realised count].

    Window j covers feature-days [j .. j+L-1]; the target is the count on day
    j+L (a true 1-step-ahead forecast). Returns the window tensor plus masks for
    fit / val / test and the ORIGINAL panel row index of each target day.
    """
    from numpy.lib.stride_tricks import sliding_window_view

    chans = keep + [TARGET]
    arr = np.nan_to_num(panel[chans].astype("float32").values)
    y = panel[TARGET].astype("float32").values
    split = panel["split"].values
    tr = split == "train"
    mu, sd = arr[tr].mean(0), arr[tr].std(0) + 1e-6
    Z = (arr - mu) / sd
    F = Z.shape[1]

    key = (panel["cell"].astype(str) + "|" + panel["time_block"].astype(str)).values
    bounds = np.where(key[1:] != key[:-1])[0] + 1
    seg_starts = np.concatenate([[0], bounds])
    seg_ends = np.concatenate([bounds, [len(key)]])

    win, tgt, tsp, tog = [], [], [], []
    rows = np.arange(len(panel))
    for s, e in zip(seg_starts, seg_ends):
        T = e - s
        if T <= L:
            continue
        Zi = Z[s:e]
        W = sliding_window_view(Zi, (L, F))[:, 0]   # (T-L+1, L, F), window starts j=0..T-L
        W = W[:-1]                                   # keep j=0..T-L-1 (target day j+L <= T-1)
        idx = np.arange(L, T)                        # target day indices within the series
        win.append(W)
        tgt.append(y[s:e][idx])
        tsp.append(split[s:e][idx])
        tog.append(rows[s:e][idx])

    W = np.concatenate(win).astype("float32")
    tgt = np.concatenate(tgt).astype("float32")
    sp = np.concatenate(tsp)
    og = np.concatenate(tog)
    dtt = panel["date"].values[og]
    cut = _inner_cut()
    fit = (sp == "train") & (dtt <= cut)
    val = (sp == "train") & (dtt > cut)
    te = sp == "test"
    log(f"sequences: {W.shape} | fit {fit.sum():,} val {val.sum():,} test {te.sum():,}")
    return W, tgt, fit, val, te, og


# --------------------------------------------------------------------------- #
# Tweedie deviance loss (p in (1,2)); eta = log(mu)
# --------------------------------------------------------------------------- #
def tweedie_loss(eta, y, p=TWEEDIE_P):
    mu = torch.exp(eta).clamp(1e-6, 1e6)
    y = y.clamp(min=0)
    a = torch.pow(y, 2 - p) / ((1 - p) * (2 - p))
    b = y * torch.pow(mu, 1 - p) / (1 - p)
    c = torch.pow(mu, 2 - p) / (2 - p)
    return (2 * (a - b + c)).mean()


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
class MLP(nn.Module):
    def __init__(self, fin, h=128):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(fin, h), nn.ReLU(), nn.Dropout(0.1),
            nn.Linear(h, h), nn.ReLU(), nn.Dropout(0.1),
            nn.Linear(h, 1),
        )

    def forward(self, x):
        return self.net(x).squeeze(-1)


class RecurNet(nn.Module):
    def __init__(self, fin, h=64, kind="lstm"):
        super().__init__()
        cell = nn.LSTM if kind == "lstm" else nn.GRU
        self.rnn = cell(fin, h, num_layers=1, batch_first=True)
        self.head = nn.Sequential(nn.Linear(h, h), nn.ReLU(), nn.Linear(h, 1))

    def forward(self, x):
        out, _ = self.rnn(x)
        return self.head(out[:, -1, :]).squeeze(-1)


# --------------------------------------------------------------------------- #
# Train / predict
# --------------------------------------------------------------------------- #
def train(model, Xtr, ytr, Xval, yval, name, epochs=30, bs=8192, lr=1e-3, patience=4):
    model = model.to(DEVICE)
    opt = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=1e-5)
    Xtr_t, ytr_t = torch.tensor(Xtr), torch.tensor(ytr)
    Xval_t, yval_t = torch.tensor(Xval).to(DEVICE), torch.tensor(yval).to(DEVICE)
    n = len(Xtr_t)
    best, best_state, bad = 1e18, None, 0
    for ep in range(epochs):
        model.train()
        perm = torch.randperm(n)
        run = 0.0
        for i in range(0, n, bs):
            idx = perm[i:i + bs]
            xb, yb = Xtr_t[idx].to(DEVICE), ytr_t[idx].to(DEVICE)
            opt.zero_grad()
            loss = tweedie_loss(model(xb), yb)
            loss.backward()
            opt.step()
            run += loss.item() * len(idx)
        model.eval()
        with torch.no_grad():
            vl, m = 0.0, len(Xval_t)
            for i in range(0, m, bs):
                vl += tweedie_loss(model(Xval_t[i:i + bs]), yval_t[i:i + bs]).item() * len(Xval_t[i:i + bs])
            vl /= m
        improved = vl < best - 1e-4
        if improved:
            best, bad = vl, 0
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
        else:
            bad += 1
        log(f"{name:5s} epoch {ep + 1:2d} train_dev={run / n:.4f} val_dev={vl:.4f}{' *' if improved else ''}")
        if bad >= patience:
            break
    if best_state:
        model.load_state_dict(best_state)
    return model


def predict(model, X, bs=8192):
    model.eval()
    Xt = torch.tensor(X)
    out = []
    with torch.no_grad():
        for i in range(0, len(Xt), bs):
            eta = model(Xt[i:i + bs].to(DEVICE))
            out.append(torch.exp(eta).clamp(max=1e6).cpu().numpy())
    return np.concatenate(out)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main():
    t0 = time.time()
    log(f"device={DEVICE} torch={torch.__version__}")
    panel, keep = build_panel()
    results = []

    # ---- MLP (tabular) ----
    (Xf, yf), (Xv, yv), (Xte, yte), te_idx = mlp_data(panel, keep)
    log(f"MLP tensors: fit {Xf.shape} val {Xv.shape} test {Xte.shape}")
    mlp = train(MLP(Xf.shape[1]), Xf, yf, Xv, yv, name="MLP")
    pred = predict(mlp, Xte)
    results.append(M.evaluate("MLP(tabular)", yte, pred))
    log(f"MLP done: capture@5%={results[-1]['capture@5%']:.4f} RMSE={results[-1]['RMSE']:.4f}")

    # ---- LSTM / GRU (sequence) ----
    W, tgt, fit, val, te, og = seq_data(panel, keep, L)
    # sanity: RNN test population must equal the full panel test set
    n_test_panel = int((panel["split"] == "test").sum())
    assert te.sum() == n_test_panel, f"RNN test rows {te.sum()} != panel test {n_test_panel}"
    yte_seq = tgt[te]
    for kind, label in [("lstm", "LSTM"), ("gru", "GRU")]:
        net = train(RecurNet(W.shape[2], kind=kind), W[fit], tgt[fit], W[val], tgt[val],
                    name=label, bs=4096)
        pred = predict(net, W[te], bs=4096)
        results.append(M.evaluate(label, yte_seq, pred))
        log(f"{label} done: capture@5%={results[-1]['capture@5%']:.4f} RMSE={results[-1]['RMSE']:.4f}")

    nn_df = pd.DataFrame(results).set_index("model")

    # ---- merge with the existing tree comparison ----
    tree_fp = os.path.join(config.ARTIFACTS_DIR, "model_comparison.csv")
    cols_order = ["MAE", "RMSE", "R2", "PoissonDev",
                  "capture@1%", "capture@5%", "capture@10%", "capture@20%"]
    if os.path.exists(tree_fp):
        tree_df = pd.read_csv(tree_fp, index_col=0)
        combined = pd.concat([tree_df, nn_df], axis=0)
    else:
        combined = nn_df
    combined = combined[[c for c in cols_order if c in combined.columns]]
    combined = combined.sort_values("capture@5%", ascending=False)

    out_csv = os.path.join(config.ARTIFACTS_DIR, "deep_vs_tree_comparison.csv")
    combined.round(5).to_csv(out_csv)
    with open(os.path.join(config.ARTIFACTS_DIR, "deep_vs_tree.json"), "w") as f:
        json.dump({"L": L, "tweedie_p": TWEEDIE_P, "device": DEVICE,
                   "results": combined.round(5).reset_index().to_dict("records")}, f, indent=2)

    print("\n================ DEEP vs TREE (test set, sorted by capture@5%) ================")
    print(combined.round(4).to_string())
    print(f"\nsaved -> {out_csv}")
    log(f"total runtime {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
