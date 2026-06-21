"""
Experiment -- can better PREPROCESSING close the NN gap to the GBM?

Takes the enriched feature set and applies the research's top NN levers:
  * RankGauss: QuantileTransformer(output_distribution='normal') on numerics
    (rank-based -> de-skews the heavy-tailed count features; invariant to log1p).
  * Entity embeddings for high-cardinality IDs (cell, police-station) + small
    embeddings for time_block / dow, instead of raw integers / target-encoding.

Two variants isolate the effect:
  * MLP+rankgauss        -- numeric preprocessing only.
  * MLP+rankgauss+emb    -- preprocessing + entity embeddings.

Same temporal split / Tweedie loss / metrics as the rest. Compared against the
plain MLP (0.5469) and the LightGBM-Tweedie champion (0.5646).

Run from project root:   python experiments/nn_preprocessing.py
"""
from __future__ import annotations

import os
import sys
import time

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "experiments")):
    if p not in sys.path:
        sys.path.insert(0, p)

import config  # noqa: E402
from src import model as M  # noqa: E402
import feature_engineering as FE  # build_base + enrich  # noqa: E402

from sklearn.preprocessing import QuantileTransformer  # noqa: E402
import torch  # noqa: E402
import torch.nn as nn  # noqa: E402

TARGET = "viol_count"
SEED = config.RANDOM_STATE
np.random.seed(SEED)
torch.manual_seed(SEED)
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
TWEEDIE_P = 1.5


def log(*a):
    print("  [nnprep]", *a, flush=True)


def tweedie_loss(eta, y, p=TWEEDIE_P):
    mu = torch.exp(eta).clamp(1e-6, 1e6)
    y = y.clamp(min=0)
    a = torch.pow(y, 2 - p) / ((1 - p) * (2 - p))
    b = y * torch.pow(mu, 1 - p) / (1 - p)
    c = torch.pow(mu, 2 - p) / (2 - p)
    return (2 * (a - b + c)).mean()


class EmbMLP(nn.Module):
    def __init__(self, n_num, cat_dims=None, emb_dims=None, h=256):
        super().__init__()
        self.has_emb = bool(cat_dims)
        extra = 0
        if self.has_emb:
            self.embs = nn.ModuleList([nn.Embedding(c, d) for c, d in zip(cat_dims, emb_dims)])
            extra = sum(emb_dims)
        self.net = nn.Sequential(
            nn.Linear(n_num + extra, h), nn.ReLU(), nn.BatchNorm1d(h), nn.Dropout(0.15),
            nn.Linear(h, h), nn.ReLU(), nn.BatchNorm1d(h), nn.Dropout(0.15),
            nn.Linear(h, 1),
        )

    def forward(self, xnum, xcat=None):
        if self.has_emb:
            es = [emb(xcat[:, i]) for i, emb in enumerate(self.embs)]
            x = torch.cat([xnum] + es, dim=1)
        else:
            x = xnum
        return self.net(x).squeeze(-1)


def train(model, num, cat, y, m_fit, m_val, name, epochs=40, bs=8192, lr=1e-3, patience=5):
    model = model.to(DEVICE)
    opt = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=1e-5)
    num_t = torch.tensor(num)
    y_t = torch.tensor(y)
    cat_t = torch.tensor(cat) if cat is not None else None
    fit_idx = np.where(m_fit)[0]
    vnum = num_t[m_val].to(DEVICE)
    vy = y_t[m_val].to(DEVICE)
    vcat = cat_t[m_val].to(DEVICE) if cat_t is not None else None
    best, best_state, bad = 1e18, None, 0
    for ep in range(epochs):
        model.train()
        perm = np.random.permutation(fit_idx)
        run = 0.0
        for i in range(0, len(perm), bs):
            idx = perm[i:i + bs]
            xb = num_t[idx].to(DEVICE)
            yb = y_t[idx].to(DEVICE)
            cb = cat_t[idx].to(DEVICE) if cat_t is not None else None
            opt.zero_grad()
            loss = tweedie_loss(model(xb, cb), yb)
            loss.backward()
            opt.step()
            run += loss.item() * len(idx)
        model.eval()
        with torch.no_grad():
            vl = 0.0
            for i in range(0, len(vnum), bs):
                cb = vcat[i:i + bs] if vcat is not None else None
                vl += tweedie_loss(model(vnum[i:i + bs], cb), vy[i:i + bs]).item() * len(vnum[i:i + bs])
            vl /= len(vnum)
        imp = vl < best - 1e-4
        if imp:
            best, bad = vl, 0
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
        else:
            bad += 1
        log(f"{name:18s} ep {ep + 1:2d} train_dev={run / len(perm):.4f} val_dev={vl:.4f}{' *' if imp else ''}")
        if bad >= patience:
            break
    if best_state:
        model.load_state_dict(best_state)
    return model


def predict(model, num, cat, mask, bs=8192):
    model.eval()
    num_t = torch.tensor(num[mask])
    cat_t = torch.tensor(cat[mask]) if cat is not None else None
    out = []
    with torch.no_grad():
        for i in range(0, len(num_t), bs):
            xb = num_t[i:i + bs].to(DEVICE)
            cb = cat_t[i:i + bs].to(DEVICE) if cat_t is not None else None
            out.append(torch.exp(model(xb, cb)).clamp(max=1e6).cpu().numpy())
    return np.concatenate(out)


def main():
    t0 = time.time()
    log(f"device={DEVICE}")
    panel, base, cmeta = FE.build_base()
    panel, fam = FE.enrich(panel, cmeta)

    # CLEAN feature set: exclude the overfit-prone naive target encodings, which
    # hurt the GBM by -3.5pp and confound the preprocessing comparison.
    all_num = base + fam["temporal"] + fam["spatial"] + fam["calendar"]
    # de-dup, drop columns we will embed instead, separate binaries
    seen = set()
    all_num = [c for c in all_num if not (c in seen or seen.add(c))]
    emb_cols = ["time_block", "dow"]
    num_cols = [c for c in all_num if c not in emb_cols]
    binary = [c for c in ("is_weekend", "holiday") if c in num_cols]
    qt_cols = [c for c in num_cols if c not in binary]

    split = panel["split"].values
    tr = split == "train"
    cut = pd.Timestamp(config.TRAIN_END_DATE) - pd.Timedelta(days=M.INNER_VAL_DAYS)
    dt = panel["date"].values
    m_fit = tr & (dt <= np.datetime64(cut))
    m_val = tr & (dt > np.datetime64(cut))
    m_te = split == "test"
    y = panel[TARGET].astype("float32").values
    yte = y[m_te]

    # ---- RankGauss numeric matrix (fit on train) ----
    qt = QuantileTransformer(output_distribution="normal", n_quantiles=1000,
                             subsample=200_000, random_state=SEED)
    Xq = np.nan_to_num(panel[qt_cols].astype("float32").values)
    qt.fit(Xq[tr])
    Xq = qt.transform(Xq).astype("float32")
    Xb = np.nan_to_num(panel[binary].astype("float32").values) if binary else np.zeros((len(panel), 0), "float32")
    num = np.concatenate([Xq, Xb], axis=1).astype("float32")
    log(f"numeric matrix {num.shape} (qt {len(qt_cols)} + binary {len(binary)})")

    # ---- categorical codes for embeddings ----
    cat_specs = [("cell", 16), ("dom_police_station", 8), ("time_block", 4), ("dow", 4)]
    cat_arrs, cat_dims, emb_dims = [], [], []
    for col, d in cat_specs:
        codes = panel[col].astype("category").cat.codes.values.astype("int64")
        cat_arrs.append(codes)
        cat_dims.append(int(codes.max()) + 1)
        emb_dims.append(d)
    cat = np.stack(cat_arrs, axis=1)
    log(f"embeddings: " + ", ".join(f"{c}->{dim}x{e}" for (c, _), dim, e in zip(cat_specs, cat_dims, emb_dims)))

    results = []

    # ---- variant 1: RankGauss only (no embeddings) ----
    m1 = EmbMLP(num.shape[1])
    m1 = train(m1, num, None, y, m_fit, m_val, name="rankgauss")
    p1 = predict(m1, num, None, m_te)
    results.append(M.evaluate("MLP+rankgauss", yte, p1))
    log(f"rankgauss cap@5%={results[-1]['capture@5%']:.4f}")

    # ---- variant 2: RankGauss + entity embeddings ----
    m2 = EmbMLP(num.shape[1], cat_dims=cat_dims, emb_dims=emb_dims)
    m2 = train(m2, num, cat, y, m_fit, m_val, name="rankgauss+emb")
    p2 = predict(m2, num, cat, m_te)
    results.append(M.evaluate("MLP+rankgauss+emb", yte, p2))
    log(f"rankgauss+emb cap@5%={results[-1]['capture@5%']:.4f}")

    df = pd.DataFrame(results).set_index("model")
    ref = {"LightGBM-Tweedie (champion)": 0.5646, "MLP(tabular, plain)": 0.5469,
           "Baseline(hist-mean)": 0.5372}
    print("\n========== NN PREPROCESSING (test set) ==========")
    print(df[["MAE", "RMSE", "R2", "PoissonDev", "capture@1%", "capture@5%",
              "capture@10%", "capture@20%"]].round(4).to_string())
    print("\nReference capture@5%:")
    for k, v in ref.items():
        print(f"  {k:32s} {v:.4f}")
    out = os.path.join(config.ARTIFACTS_DIR, "nn_preprocessing.csv")
    df.round(5).to_csv(out)
    print(f"saved -> {out}")
    log(f"runtime {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
