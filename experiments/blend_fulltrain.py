"""
Decisive test -- does a FULL-TRAIN blend beat the production champion (0.5713)?

The stacking experiment showed blends beat the best single base by +0.3-0.4pp, but
on base models handicapped to train-minus-21d. Here every base model trains on the
FULL train set (like production), and we test the UNTUNED equal blends (no weight
fitting => no overfitting risk, directly deployable):

    equal mean  and  equal rank-mean  of the base models' test predictions.

Compared head-to-head with the shipped LightGBM-Tweedie champion (capture@5% 0.5713).

Run:  python experiments/blend_fulltrain.py [seed]
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
from sklearn.preprocessing import QuantileTransformer  # noqa: E402
from lightgbm import LGBMRegressor  # noqa: E402
import feature_engineering as FE  # noqa: E402
import nn_preprocessing as NP  # noqa: E402

TARGET = "viol_count"
SEED = int(sys.argv[1]) if len(sys.argv) > 1 else config.RANDOM_STATE
CHAMP = 0.5713


def log(*a):
    print("  [blend]", *a, flush=True)


def cap(y, p, k=0.05):
    n = len(y); m = max(1, int(round(k * n)))
    idx = np.argpartition(-p, m)[:m]
    tot = y.sum()
    return float(y[idx].sum() / tot) if tot else 0.0


def main():
    t0 = time.time()
    panel, base, cmeta = FE.build_base()
    log(f"features={len(base)} seed={SEED}")
    split = panel["split"].values
    m_tr = split == "train"
    m_te = split == "test"
    dt = panel["date"].values
    es_cut = np.datetime64(pd.Timestamp(config.TRAIN_END_DATE) - pd.Timedelta(days=21))
    y = panel[TARGET].astype("float32").values
    yt = y[m_te]
    X = panel[base].astype(float)

    preds, names = [], []

    def fit_tree(mdl, label):
        mdl.fit(X[m_tr], y[m_tr])
        preds.append(mdl.predict(X[m_te])); names.append(label)
        log(f"{label:16s} cap@5%={cap(yt, preds[-1]):.4f}")

    fit_tree(LGBMRegressor(objective="tweedie", tweedie_variance_power=1.5, n_estimators=205,
             learning_rate=0.03, num_leaves=95, min_child_samples=60, subsample=0.8,
             colsample_bytree=0.8, reg_lambda=1.0, n_jobs=-1, random_state=SEED, verbose=-1),
             "LGBM-Tweedie")
    try:
        from xgboost import XGBRegressor
        fit_tree(XGBRegressor(objective="count:poisson", n_estimators=400, learning_rate=0.06,
                 max_depth=7, subsample=0.8, colsample_bytree=0.8, min_child_weight=5,
                 reg_lambda=1.0, n_jobs=-1, random_state=SEED, tree_method="hist"), "XGB-Poisson")
    except Exception as e:
        log(f"xgb skipped ({e})")
    fit_tree(HistGradientBoostingRegressor(loss="poisson", max_iter=400, learning_rate=0.06,
             max_depth=8, min_samples_leaf=80, l2_regularization=1.0, random_state=SEED),
             "HistGB-Poisson")
    fit_tree(RandomForestRegressor(n_estimators=120, max_depth=20, min_samples_leaf=40,
             max_samples=0.5, n_jobs=-1, random_state=SEED), "RandomForest")

    # NN (full train, early-stop on last 21d)
    log("RankGauss-MLP ...")
    panel2, fam = FE.enrich(panel.copy(), cmeta)
    all_num = base + fam["temporal"] + fam["spatial"] + fam["calendar"]
    seen = set(); all_num = [c for c in all_num if not (c in seen or seen.add(c))]
    num_cols = [c for c in all_num if c not in ("time_block", "dow")]
    binary = [c for c in ("is_weekend", "holiday") if c in num_cols]
    qt_cols = [c for c in num_cols if c not in binary]
    qt = QuantileTransformer(output_distribution="normal", n_quantiles=1000,
                             subsample=200_000, random_state=SEED)
    Xq = np.nan_to_num(panel2[qt_cols].astype("float32").values)
    qt.fit(Xq[m_tr]); Xq = qt.transform(Xq).astype("float32")
    Xb = (np.nan_to_num(panel2[binary].astype("float32").values)
          if binary else np.zeros((len(panel2), 0), "float32"))
    num = np.concatenate([Xq, Xb], axis=1).astype("float32")
    m_nnfit = m_tr & (dt <= es_cut); m_nnes = m_tr & (dt > es_cut)
    import torch
    torch.manual_seed(SEED)
    net = NP.train(NP.EmbMLP(num.shape[1]), num, None, y, m_nnfit, m_nnes, name="rankgauss")
    preds.append(NP.predict(net, num, None, m_te)); names.append("RankGauss-MLP")
    log(f"RankGauss-MLP    cap@5%={cap(yt, preds[-1]):.4f}")

    Tp = np.vstack(preds).T.astype(float)
    Tr = np.column_stack([pd.Series(Tp[:, j]).rank(pct=True).to_numpy() for j in range(Tp.shape[1])])

    base_caps = {names[i]: cap(yt, Tp[:, i]) for i in range(len(names))}
    best_name = max(base_caps, key=base_caps.get)

    res = {f"base:{k}": v for k, v in base_caps.items()}
    res["blend:equal-mean(all)"] = cap(yt, Tp.mean(1))
    res["blend:equal-rankmean(all)"] = cap(yt, Tr.mean(1))
    # tree-only (drop NN, which barely contributes)
    ti = [i for i, n in enumerate(names) if n != "RankGauss-MLP"]
    res["blend:equal-rankmean(trees)"] = cap(yt, Tr[:, ti].mean(1))
    # diversity pair that the weight search liked: HistGB + RandomForest
    di = [i for i, n in enumerate(names) if n in ("HistGB-Poisson", "RandomForest")]
    res["blend:rankmean(HistGB+RF)"] = cap(yt, Tr[:, di].mean(1))
    # champion + most-diverse base (LGBM-Tweedie + HistGB)
    pi = [i for i, n in enumerate(names) if n in ("LGBM-Tweedie", "HistGB-Poisson")]
    res["blend:rankmean(LGBM+HistGB)"] = cap(yt, Tr[:, pi].mean(1))

    out = dict(sorted(res.items(), key=lambda kv: -kv[1]))
    print("\n=============== FULL-TRAIN BLEND vs CHAMPION (test capture@5%) ===============")
    for k, v in out.items():
        tag = ""
        if k == f"base:{best_name}":
            tag = "  <- best single base"
        if v > CHAMP:
            tag += "  ** beats champion **"
        print(f"  {k:32s} {v:.4f} (vs champ {CHAMP}: {v - CHAMP:+.4f}){tag}")
    payload = {"seed": SEED, "champion": CHAMP, "results": out}
    print("\nRESULT " + json.dumps(payload))
    json.dump(payload, open(os.path.join(config.ARTIFACTS_DIR, f"blend_fulltrain_seed{SEED}.json"), "w"), indent=2)
    log(f"runtime {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
