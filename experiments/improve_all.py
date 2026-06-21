"""
Experiment -- "try everything": (A) leak-safe expanding-window target encoding,
(B) GBM(+spatial) + RankGauss-NN ensemble.

Builds on the ablation findings: the new GBM champion is base + spatial
(nbr_lag1, nbr_nz7) at capture@5% ~= 0.568. Here we ask:

  A. Does target encoding help when done RIGHT (causal expanding window, so a
     train row never sees its own group's full-train mean)? The naive train-wide
     version cost -3.5pp; the leak-safe version should at least not hurt.
  B. Can a GBM + RankGauss-NN ENSEMBLE beat either alone? They now have similar
     accuracy but different errors -- the textbook case for averaging.

Same split / Tweedie / metrics throughout. Run from project root:
    python experiments/improve_all.py
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
import lightgbm as lgb  # noqa: E402
from lightgbm import LGBMRegressor  # noqa: E402
from sklearn.preprocessing import QuantileTransformer  # noqa: E402
import torch  # noqa: E402

import feature_engineering as FE  # build_base, enrich  # noqa: E402
import nn_preprocessing as NP     # EmbMLP, train, predict, tweedie_loss  # noqa: E402

TARGET = "viol_count"
SEED = config.RANDOM_STATE
np.random.seed(SEED)
torch.manual_seed(SEED)


def log(*a):
    print("  [all]", *a, flush=True)


# --------------------------------------------------------------------------- #
# Leak-safe expanding-window target encoder
# --------------------------------------------------------------------------- #
def expanding_te(panel, keys, name, smoothing=20.0):
    """Causal shrunk target encoding: each TRAIN row sees only its group's PRIOR
    train targets; TEST rows see the full-train group mean. Test targets never
    contribute (zeroed), so there is no leakage in either direction."""
    p = panel.sort_values(["date", "time_block"]).copy()
    gm = float(p.loc[p["split"] == "train", TARGET].mean())
    p["_t"] = p[TARGET].where(p["split"] == "train", 0.0).astype(float)
    p["_i"] = (p["split"] == "train").astype(float)
    g = p.groupby(keys, sort=False)
    csum = g["_t"].cumsum() - p["_t"]     # prior-train sum (exclude current row)
    ccnt = g["_i"].cumsum() - p["_i"]     # prior-train count
    enc = (csum + gm * smoothing) / (ccnt + smoothing)
    return enc.reindex(panel.index)       # back to original panel order


# --------------------------------------------------------------------------- #
# Champion LightGBM-Tweedie -> returns metrics + aligned test predictions
# --------------------------------------------------------------------------- #
def _gbm():
    return LGBMRegressor(
        objective="tweedie", tweedie_variance_power=1.5, n_estimators=2000,
        learning_rate=0.03, num_leaves=95, min_child_samples=60, subsample=0.8,
        colsample_bytree=0.8, reg_lambda=1.0, n_jobs=-1, random_state=SEED, verbose=-1,
    )


def train_gbm(panel, feats, name):
    tr = panel[panel["split"] == "train"]
    te = panel[panel["split"] == "test"]
    cut = pd.Timestamp(config.TRAIN_END_DATE) - pd.Timedelta(days=M.INNER_VAL_DAYS)
    fit_m = (pd.to_datetime(tr["date"]) <= cut).values
    Xtr, ytr = tr[feats], tr[TARGET].astype(float)
    mdl = _gbm()
    mdl.fit(Xtr[fit_m], ytr[fit_m], eval_set=[(Xtr[~fit_m], ytr[~fit_m])], eval_metric="rmse",
            callbacks=[lgb.early_stopping(60, verbose=False), lgb.log_evaluation(0)])
    mdl.set_params(n_estimators=int(mdl.best_iteration_ or mdl.n_estimators))
    mdl.fit(Xtr, ytr)
    pred = np.clip(mdl.predict(te[feats]), 0, None)
    res = M.evaluate(name, te[TARGET].astype(float).values, pred)
    log(f"{name:28s} cap@5%={res['capture@5%']:.4f} RMSE={res['RMSE']:.4f}")
    return res, pred, te[TARGET].astype(float).values


# --------------------------------------------------------------------------- #
# RankGauss NN (clean features, no embeddings = the winning variant) -> preds
# --------------------------------------------------------------------------- #
def train_rankgauss_nn(panel, base, fam):
    all_num = base + fam["temporal"] + fam["spatial"] + fam["calendar"]
    seen = set()
    all_num = [c for c in all_num if not (c in seen or seen.add(c))]
    num_cols = [c for c in all_num if c not in ("time_block", "dow")]
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

    qt = QuantileTransformer(output_distribution="normal", n_quantiles=1000,
                             subsample=200_000, random_state=SEED)
    Xq = np.nan_to_num(panel[qt_cols].astype("float32").values)
    qt.fit(Xq[tr])
    Xq = qt.transform(Xq).astype("float32")
    Xb = np.nan_to_num(panel[binary].astype("float32").values) if binary else np.zeros((len(panel), 0), "float32")
    num = np.concatenate([Xq, Xb], axis=1).astype("float32")

    net = NP.EmbMLP(num.shape[1])
    net = NP.train(net, num, None, y, m_fit, m_val, name="rankgauss")
    pred = NP.predict(net, num, None, m_te)
    return pred  # aligned to panel[split=="test"] order


def _ranks(x):
    return pd.Series(x).rank(pct=True).to_numpy()


def main():
    t0 = time.time()
    panel, base, cmeta = FE.build_base()
    panel, fam = FE.enrich(panel, cmeta)
    champ = base + fam["spatial"]          # new champion feature set (base + spatial)

    rows = []

    # ---------- A. leak-safe expanding-window target encoding ---------- #
    log("building leak-safe expanding-window encodings ...")
    panel["exp_cb"] = expanding_te(panel, ["cell", "time_block"], "exp_cb")
    panel["exp_cdb"] = expanding_te(panel, ["cell", "dow", "time_block"], "exp_cdb")
    panel["exp_db"] = expanding_te(panel, ["dow", "time_block"], "exp_db")
    exp_feats = ["exp_cb", "exp_cdb", "exp_db"]

    res_champ, pred_gbm, yte = train_gbm(panel, champ, "GBM (base+spatial)")
    rows.append(res_champ)
    res_naive, _, _ = train_gbm(panel, base + fam["encoding"], "GBM +NAIVE_TE (ref)")
    rows.append(res_naive)
    res_exp, _, _ = train_gbm(panel, champ + exp_feats, "GBM +expanding_TE")
    rows.append(res_exp)

    # ---------- B. RankGauss-NN + ensemble ---------- #
    log("training RankGauss NN ...")
    pred_nn = train_rankgauss_nn(panel, base, fam)
    assert len(pred_nn) == len(pred_gbm) == len(yte), "alignment mismatch"
    rows.append(M.evaluate("NN (rankgauss)", yte, pred_nn))
    log(f"NN cap@5%={rows[-1]['capture@5%']:.4f}")

    # raw-count averages (meaningful MAE/RMSE)
    for w in (0.3, 0.5, 0.7):
        ens = w * pred_gbm + (1 - w) * pred_nn
        rows.append(M.evaluate(f"Ensemble mean w_gbm={w}", yte, ens))
    # rank-average (capture-optimal; MAE/RMSE off-scale, ignore those)
    rg, rn = _ranks(pred_gbm), _ranks(pred_nn)
    for w in (0.5, 0.7):
        rows.append(M.evaluate(f"Ensemble rank w_gbm={w}", yte, w * rg + (1 - w) * rn))

    df = pd.DataFrame(rows).set_index("model")
    cols = ["MAE", "RMSE", "R2", "PoissonDev", "capture@1%", "capture@5%", "capture@10%", "capture@20%"]
    champ_cap = res_champ["capture@5%"]
    df["d_cap@5%"] = (df["capture@5%"] - champ_cap).round(4)
    out = df[cols + ["d_cap@5%"]].sort_values("capture@5%", ascending=False)

    print("\n=============== TRY-EVERYTHING (test set, sorted by capture@5%) ===============")
    print(out.round(4).to_string())
    print(f"\n(GBM base+spatial cap@5% = {champ_cap:.4f}; rank-ensemble MAE/RMSE are off-scale by design)")
    fp = os.path.join(config.ARTIFACTS_DIR, "improve_all.csv")
    out.round(5).to_csv(fp)
    print(f"saved -> {fp}")
    log(f"runtime {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
