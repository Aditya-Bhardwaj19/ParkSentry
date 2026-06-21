"""
Experiment -- q90 (high-quantile) target encoding, computed leak-safe.

Mean encoding (what the shipped exp_* features use) is dominated by the zeros and
undersells bursty hotspots. A high quantile (q90) of a group's target encodes
"how severe does this place get when it's bad" -- the quantity top-K capture
rewards. Quantiles aren't cumulative, so the expanding-window trick used for the
means doesn't apply; we use OUT-OF-FOLD cross-fitting instead, two ways:

  * q90_oof    -- random K-fold OOF (each train fold encoded from the other folds;
                  test from full train). Uniform encoding quality across train.
  * q90_causal -- time-ordered expanding folds (each chronological chunk encoded
                  from STRICTLY EARLIER chunks; test from full train). Causal, but
                  the earliest chunk falls back to the global q90.

Both are leak-safe in the critical sense: no train row ever sees its own target.
Keys: (cell, time_block) and (cell, dow, time_block). Tested ON TOP of the current
production champion (35 features, capture@5% ~= 0.571).

Run from project root:   python experiments/q90_encoder.py
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
import feature_engineering as FE  # build_base  # noqa: E402

TARGET = "viol_count"
SEED = config.RANDOM_STATE
Q = 0.9
MIN_COUNT = 8


def log(*a):
    print("  [q90]", *a, flush=True)


def _grp_quantile(df, keys, q=Q, min_count=MIN_COUNT):
    """q-quantile per group, dropping groups with < min_count rows (noisy)."""
    g = df.groupby(keys)[TARGET]
    qv = g.quantile(q)
    cnt = g.size()
    return qv[cnt.reindex(qv.index) >= min_count]


def _map(panel_slice, keys, table, fallback):
    mi = pd.MultiIndex.from_arrays([panel_slice[k].values for k in keys])
    vals = table.reindex(mi).to_numpy()
    return np.where(np.isnan(vals), fallback, vals)


def q90_oof(panel, keys, name, K=5):
    """Random K-fold OOF q90: train folds encoded from other folds, test from full train."""
    tr_mask = (panel["split"] == "train").values
    tr = panel.loc[tr_mask]
    gq = float(tr[TARGET].quantile(Q))
    out = np.full(len(panel), gq, dtype="float64")

    rng = np.random.RandomState(SEED)
    fold = rng.randint(0, K, size=len(tr))
    tr_pos = np.where(tr_mask)[0]
    for k in range(K):
        src = tr.iloc[fold != k]
        table = _grp_quantile(src, keys)
        dst = tr.iloc[fold == k]
        out[tr_pos[fold == k]] = _map(dst, keys, table, gq)

    full = _grp_quantile(tr, keys)
    te_pos = np.where(~tr_mask)[0]
    out[te_pos] = _map(panel.loc[~tr_mask], keys, full, gq)
    panel[name] = out
    return panel


def q90_causal(panel, keys, name, K=4):
    """Time-ordered expanding-fold q90: each chunk encoded from strictly earlier chunks."""
    tr_mask = (panel["split"] == "train").values
    tr = panel.loc[tr_mask].sort_values(["date", "time_block"])
    gq = float(tr[TARGET].quantile(Q))
    out = np.full(len(panel), gq, dtype="float64")

    n = len(tr)
    bnd = [int(n * i / K) for i in range(K + 1)]
    enc = np.full(n, gq)
    for i in range(1, K):
        table = _grp_quantile(tr.iloc[:bnd[i]], keys)          # strictly earlier
        chunk = tr.iloc[bnd[i]:bnd[i + 1]]
        enc[bnd[i]:bnd[i + 1]] = _map(chunk, keys, table, gq)
    # chunk 0 keeps global gq
    out[panel.index.get_indexer(tr.index)] = enc

    full = _grp_quantile(panel.loc[tr_mask], keys)
    te_pos = np.where(~tr_mask)[0]
    out[te_pos] = _map(panel.loc[~tr_mask], keys, full, gq)
    panel[name] = out
    return panel


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
    res["n_feats"] = len(feats)
    log(f"{name:28s} feats={len(feats):2d} cap@5%={res['capture@5%']:.4f} RMSE={res['RMSE']:.4f}")
    return res


def main():
    t0 = time.time()
    panel, base, cmeta = FE.build_base()   # base = current production 35 features
    log(f"production champion feature count: {len(base)}")

    # build q90 encodings (both variants, both keys)
    keys_cb = ["cell", "time_block"]
    keys_cdb = ["cell", "dow", "time_block"]
    panel = q90_oof(panel, keys_cb, "q90oof_cb")
    panel = q90_oof(panel, keys_cdb, "q90oof_cdb")
    panel = q90_causal(panel, keys_cb, "q90cau_cb")
    panel = q90_causal(panel, keys_cdb, "q90cau_cdb")

    oof = ["q90oof_cb", "q90oof_cdb"]
    cau = ["q90cau_cb", "q90cau_cdb"]

    rows = []
    rows.append(train_gbm(panel, base, "champion (production)"))
    rows.append(train_gbm(panel, base + oof, "+ q90 OOF (kfold)"))
    rows.append(train_gbm(panel, base + cau, "+ q90 causal (time-folds)"))
    rows.append(train_gbm(panel, base + ["q90oof_cdb"], "+ q90 OOF cell*dow*blk only"))

    df = pd.DataFrame(rows).set_index("model")
    cols = ["n_feats", "MAE", "RMSE", "R2", "PoissonDev",
            "capture@1%", "capture@5%", "capture@10%", "capture@20%"]
    champ = df.loc["champion (production)", "capture@5%"]
    df["d_cap@5%"] = (df["capture@5%"] - champ).round(4)
    out = df[cols + ["d_cap@5%"]].sort_values("capture@5%", ascending=False)

    print("\n=============== q90 OUT-OF-FOLD ENCODING (test set) ===============")
    print(out.round(4).to_string())
    print(f"\n(production champion cap@5% = {champ:.4f})")
    fp = os.path.join(config.ARTIFACTS_DIR, "q90_encoder.csv")
    out.round(5).to_csv(fp)
    print(f"saved -> {fp}")
    log(f"runtime {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
