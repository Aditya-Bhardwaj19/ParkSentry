"""
Experiment -- blending / stacking of diverse base models.

Five base learners with different inductive biases:
    LightGBM-Tweedie, XGBoost-Poisson, HistGB-Poisson, RandomForest, RankGauss-MLP

Clean 3-way temporal split so the blend-tuning slice is NEVER used to train or
early-stop any base model:
    fit         : train, date <= TRAIN_END - 21d   (base models train here)
    blend-val   : last 21d of train                 (tune blend weights here)
    test        : after TRAIN_END                    (final, untouched)
(The NN gets its own early-stop slice carved from the END of `fit`, so blend-val
stays clean for everyone.)

Strategies compared (all evaluated on test capture@5%):
    best single base | equal mean | equal rank-mean
    capture-optimised weights (Dirichlet search on blend-val)
    capture-optimised rank weights
    positive linear stack (meta-learner fit on blend-val base preds)

Run:  python experiments/stacking.py [seed]
"""
from __future__ import annotations

import os
import sys
import json
import time

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "experiments")):
    if p not in sys.path:
        sys.path.insert(0, p)

import config  # noqa: E402
from src import model as M  # noqa: E402
from sklearn.ensemble import RandomForestRegressor, HistGradientBoostingRegressor  # noqa: E402
from sklearn.linear_model import LinearRegression  # noqa: E402
from sklearn.preprocessing import QuantileTransformer  # noqa: E402
from lightgbm import LGBMRegressor  # noqa: E402
import feature_engineering as FE  # noqa: E402
import nn_preprocessing as NP  # noqa: E402

TARGET = "viol_count"
SEED = int(sys.argv[1]) if len(sys.argv) > 1 else config.RANDOM_STATE


def log(*a):
    print("  [stack]", *a, flush=True)


def cap5(y, p):
    """Fast capture@5% (top-5% of predicted slots -> share of real volume)."""
    n = len(y)
    m = max(1, int(round(0.05 * n)))
    idx = np.argpartition(-p, m)[:m]
    tot = y.sum()
    return float(y[idx].sum() / tot) if tot else 0.0


def main():
    t0 = time.time()
    rng = np.random.RandomState(SEED)
    panel, base, cmeta = FE.build_base()
    log(f"features={len(base)} seed={SEED}")

    split = panel["split"].values
    tr = split == "train"
    dt = panel["date"].values
    cut = np.datetime64(pd.Timestamp(config.TRAIN_END_DATE) - pd.Timedelta(days=21))
    cut_nn = np.datetime64(pd.Timestamp(config.TRAIN_END_DATE) - pd.Timedelta(days=35))
    m_fit = tr & (dt <= cut)                 # base-model training data
    m_bval = tr & (dt > cut)                 # blend-tuning holdout (clean)
    m_te = split == "test"
    m_nnfit = tr & (dt <= cut_nn)            # NN training
    m_nnes = tr & (dt > cut_nn) & (dt <= cut)  # NN early-stop (inside fit)
    y = panel[TARGET].astype("float32").values
    yb, yt = y[m_bval], y[m_te]
    log(f"fit {m_fit.sum():,} | blend-val {m_bval.sum():,} | test {m_te.sum():,}")

    Xall = panel[base].astype(float)

    def tree_preds(mdl):
        mdl.fit(Xall[m_fit], y[m_fit])
        return mdl.predict(Xall[m_bval]), mdl.predict(Xall[m_te])

    preds_b, preds_t, names = [], [], []

    log("LightGBM-Tweedie ...")
    pb, pt = tree_preds(LGBMRegressor(
        objective="tweedie", tweedie_variance_power=1.5, n_estimators=220,
        learning_rate=0.03, num_leaves=95, min_child_samples=60, subsample=0.8,
        colsample_bytree=0.8, reg_lambda=1.0, n_jobs=-1, random_state=SEED, verbose=-1))
    preds_b.append(pb); preds_t.append(pt); names.append("LGBM-Tweedie")

    log("XGBoost-Poisson ...")
    try:
        from xgboost import XGBRegressor
        pb, pt = tree_preds(XGBRegressor(
            objective="count:poisson", n_estimators=400, learning_rate=0.06, max_depth=7,
            subsample=0.8, colsample_bytree=0.8, min_child_weight=5, reg_lambda=1.0,
            n_jobs=-1, random_state=SEED, tree_method="hist"))
        preds_b.append(pb); preds_t.append(pt); names.append("XGB-Poisson")
    except Exception as e:
        log(f"  xgb skipped ({e})")

    log("HistGB-Poisson ...")
    pb, pt = tree_preds(HistGradientBoostingRegressor(
        loss="poisson", max_iter=400, learning_rate=0.06, max_depth=8,
        min_samples_leaf=80, l2_regularization=1.0, random_state=SEED))
    preds_b.append(pb); preds_t.append(pt); names.append("HistGB-Poisson")

    log("RandomForest ...")
    pb, pt = tree_preds(RandomForestRegressor(
        n_estimators=120, max_depth=20, min_samples_leaf=40, max_samples=0.5,
        n_jobs=-1, random_state=SEED))
    preds_b.append(pb); preds_t.append(pt); names.append("RandomForest")

    log("RankGauss-MLP ...")
    fam = {}
    panel2, fam = FE.enrich(panel.copy(), cmeta)   # for temporal/calendar numerics
    all_num = base + fam["temporal"] + fam["spatial"] + fam["calendar"]
    seen = set(); all_num = [c for c in all_num if not (c in seen or seen.add(c))]
    num_cols = [c for c in all_num if c not in ("time_block", "dow")]
    binary = [c for c in ("is_weekend", "holiday") if c in num_cols]
    qt_cols = [c for c in num_cols if c not in binary]
    qt = QuantileTransformer(output_distribution="normal", n_quantiles=1000,
                             subsample=200_000, random_state=SEED)
    Xq = np.nan_to_num(panel2[qt_cols].astype("float32").values)
    qt.fit(Xq[m_nnfit])
    Xq = qt.transform(Xq).astype("float32")
    Xb = (np.nan_to_num(panel2[binary].astype("float32").values)
          if binary else np.zeros((len(panel2), 0), "float32"))
    num = np.concatenate([Xq, Xb], axis=1).astype("float32")
    import torch
    torch.manual_seed(SEED)
    net = NP.EmbMLP(num.shape[1])
    net = NP.train(net, num, None, y, m_nnfit, m_nnes, name="rankgauss")
    preds_b.append(NP.predict(net, num, None, m_bval))
    preds_t.append(NP.predict(net, num, None, m_te))
    names.append("RankGauss-MLP")

    Vp = np.vstack(preds_b).T.astype(float)   # (n_bval, M)
    Tp = np.vstack(preds_t).T.astype(float)   # (n_test, M)
    M_ = len(names)

    # individual base capture@5%
    base_caps = {names[i]: cap5(yt, Tp[:, i]) for i in range(M_)}
    best_name = max(base_caps, key=base_caps.get)
    best_base = base_caps[best_name]

    # prediction correlation (diversity check)
    corr = np.corrcoef(Tp.T)

    # rank transforms
    def ranks(A):
        return np.column_stack([pd.Series(A[:, j]).rank(pct=True).to_numpy() for j in range(A.shape[1])])
    Vr, Tr = ranks(Vp), ranks(Tp)

    results = {f"base:{k}": v for k, v in base_caps.items()}
    results["blend:equal-mean"] = cap5(yt, Tp.mean(1))
    results["blend:equal-rankmean"] = cap5(yt, Tr.mean(1))

    # capture-optimised convex weights (search on blend-val, apply to test)
    def search(Vmat, Tmat, n=4000):
        bw, bc = None, -1
        for _ in range(n):
            w = rng.dirichlet(np.ones(M_))
            c = cap5(yb, Vmat @ w)
            if c > bc:
                bc, bw = c, w
        return bw, cap5(yt, Tmat @ bw)
    w_raw, c_raw = search(Vp, Tp)
    w_rank, c_rank = search(Vr, Tr)
    results["blend:capopt-weights(raw)"] = c_raw
    results["blend:capopt-weights(rank)"] = c_rank

    # positive linear stack (meta-learner on blend-val base preds)
    meta = LinearRegression(positive=True).fit(Vp, yb)
    results["stack:positive-linear"] = cap5(yt, np.clip(meta.predict(Tp), 0, None))

    out = dict(sorted(results.items(), key=lambda kv: -kv[1]))
    print("\n=============== BLENDING / STACKING (test capture@5%) ===============")
    for k, v in out.items():
        flag = "  <- best base" if k == f"base:{best_name}" else ""
        print(f"  {k:34s} {v:.4f}{flag}")
    print(f"\nbest single base: {best_name} = {best_base:.4f}")
    print(f"best blend/stack: {max((k for k in out if not k.startswith('base:')), key=out.get)} "
          f"= {max(v for k, v in out.items() if not k.startswith('base:')):.4f}")
    print("\nprediction correlation (test):")
    print("        " + "  ".join(f"{n[:7]:>7}" for n in names))
    for i, n in enumerate(names):
        print(f"  {n[:7]:>7} " + "  ".join(f"{corr[i, j]:7.3f}" for j in range(M_)))
    print(f"\ncapopt raw weights : " + ", ".join(f"{names[i][:7]}={w_raw[i]:.2f}" for i in range(M_)))

    payload = {"seed": SEED, "best_base_name": best_name, "best_base": best_base,
               "results": out, "weights_raw": {names[i]: float(w_raw[i]) for i in range(M_)}}
    print("\nRESULT " + json.dumps(payload))
    fp = os.path.join(config.ARTIFACTS_DIR, f"stacking_seed{SEED}.json")
    json.dump(payload, open(fp, "w"), indent=2)
    log(f"saved -> {fp} | runtime {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
