"""
Experiment -- does MORE feature engineering / preprocessing lift the GBM?

We rebuild the champion's panel + 26 features, then add evidence-backed feature
families (recency, volatility, rolling nonzero-rate, extra lags, multi-span
EWMA, trend, neighbour-lag spatial, train-only target encodings incl. a
high-quantile and a (cell x dow x block) encoding, revived calendar flags), and
test native LightGBM categoricals. Each config trains the EXACT champion model
(LightGBM-Tweedie, same hyperparams + early-stopping refit) on the SAME temporal
split and is scored with the SAME metrics (src.model.evaluate) -- so every delta
vs the reproduced champion (capture@5% ~= 0.565) is trustworthy.

Run from project root:   python experiments/feature_engineering.py
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
from src import model as M  # reuse evaluate()  # noqa: E402

import lightgbm as lgb  # noqa: E402
from lightgbm import LGBMRegressor  # noqa: E402

TARGET = "viol_count"
SEED = config.RANDOM_STATE


def log(*a):
    print("  [fe]", *a, flush=True)


# --------------------------------------------------------------------------- #
# Base panel + champion features
# --------------------------------------------------------------------------- #
def build_base():
    d = impact.add_event_impact(ingest.run(cache=True))
    panel, cmeta = aggregate.build_panel(d, verbose=False)
    panel, cols, enc = features.build_features(panel, cmeta, verbose=False)
    keep, _ = feature_selection.select(panel, cols, verbose=False)
    panel = panel.sort_values(["cell", "time_block", "date"]).reset_index(drop=True)
    panel["date"] = pd.to_datetime(panel["date"])
    return panel, list(keep), cmeta


# --------------------------------------------------------------------------- #
# Enriched feature families (all causal / leak-safe)
# --------------------------------------------------------------------------- #
def _days_since_last(panel):
    """Per (cell, time-block) days since the most recent PRIOR nonzero day."""
    key = (panel["cell"].astype(str) + "|" + panel["time_block"].astype(str)).values
    viol = (panel[TARGET].values > 0)
    bounds = np.where(key[1:] != key[:-1])[0] + 1
    starts = np.concatenate([[0], bounds])
    ends = np.concatenate([bounds, [len(key)]])
    res = np.empty(len(panel), dtype="float32")
    for s, e in zip(starts, ends):
        vi = viol[s:e]
        pos = np.where(vi)[0]
        idx = np.arange(e - s)
        if len(pos) == 0:
            res[s:e] = np.minimum(idx + 1, 60)
            continue
        c = np.searchsorted(pos, idx, side="left") - 1   # last positive strictly before idx
        dist = np.where(c >= 0, idx - pos[np.clip(c, 0, None)], idx + 1).astype("float32")
        res[s:e] = np.minimum(dist, 60)
    return res


def _neighbour_mean(panel, cols):
    """8-connected grid-neighbour mean of `cols` (same date/block), leak-safe."""
    rc = panel["cell"].str.split("_", expand=True).astype(int)
    r, c = rc[0].values, rc[1].values
    lut = panel[["date", "time_block"]].copy()
    lut["_r"], lut["_c"] = r, c
    for col in cols:
        lut[col] = panel[col].values
    lut = lut.set_index(["_r", "_c", "date", "time_block"])[cols]
    sums = {col: np.zeros(len(panel)) for col in cols}
    cnt = np.zeros(len(panel))
    offs = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
    dates, blocks = panel["date"].values, panel["time_block"].values
    for dr, dc in offs:
        idx = pd.MultiIndex.from_arrays([r + dr, c + dc, dates, blocks])
        got = lut.reindex(idx)
        present = ~got[cols[0]].isna().values
        for col in cols:
            sums[col] += np.where(present, np.nan_to_num(got[col].values), 0.0)
        cnt += present.astype(float)
    return {col: (sums[col] / np.maximum(cnt, 1)).astype("float32") for col in cols}


def enrich(panel, cmeta):
    """Add new feature families; return (panel, families: dict[name->cols])."""
    panel = panel.sort_values(["cell", "time_block", "date"]).reset_index(drop=True)
    g = panel.groupby(["cell", "time_block"])[TARGET]
    fam = {}

    # ---- temporal ---------------------------------------------------- #
    panel["lag3"] = g.shift(3)
    panel["lag21"] = g.shift(21)
    panel["lag28"] = g.shift(28)
    panel["roll7_std"] = g.transform(lambda s: s.shift(1).rolling(7, min_periods=2).std())
    panel["roll14_std"] = g.transform(lambda s: s.shift(1).rolling(14, min_periods=2).std())
    panel["roll28_std"] = g.transform(lambda s: s.shift(1).rolling(28, min_periods=2).std())
    panel["roll7_max"] = g.transform(lambda s: s.shift(1).rolling(7, min_periods=1).max())
    panel["roll28_max"] = g.transform(lambda s: s.shift(1).rolling(28, min_periods=1).max())
    panel["ewm3"] = g.transform(lambda s: s.shift(1).ewm(span=3, min_periods=1).mean())
    panel["ewm14"] = g.transform(lambda s: s.shift(1).ewm(span=14, min_periods=1).mean())
    panel["ewm28"] = g.transform(lambda s: s.shift(1).ewm(span=28, min_periods=1).mean())
    panel["trend_s_l"] = panel["roll7_mean"] - panel["roll28_mean"]
    panel["ewm_mom"] = panel["ewm3"] - panel["ewm28"]
    nz = (panel[TARGET] > 0).astype("float32")
    panel["_nz"] = nz
    gnz = panel.groupby(["cell", "time_block"])["_nz"]
    panel["roll7_nz"] = gnz.transform(lambda s: s.shift(1).rolling(7, min_periods=1).mean())
    panel["roll28_nz"] = gnz.transform(lambda s: s.shift(1).rolling(28, min_periods=1).mean())
    panel["days_since_last"] = _days_since_last(panel)
    fam["temporal"] = ["lag3", "lag21", "lag28", "roll7_std", "roll14_std", "roll28_std",
                       "roll7_max", "roll28_max", "ewm3", "ewm14", "ewm28", "trend_s_l",
                       "ewm_mom", "roll7_nz", "roll28_nz", "days_since_last"]

    # ---- spatial (neighbour lag / neighbour recent nonzero) ---------- #
    nb = _neighbour_mean(panel, ["lag1", "roll7_nz"])
    panel["nbr_lag1"] = nb["lag1"]
    panel["nbr_nz7"] = nb["roll7_nz"]
    fam["spatial"] = ["nbr_lag1", "nbr_nz7"]

    # ---- calendar (revive flags + 2nd harmonic) ---------------------- #
    rad = 2 * np.pi * panel["time_block"] / config.N_TIME_BLOCKS
    panel["block_sin2"] = np.sin(2 * rad)
    panel["block_cos2"] = np.cos(2 * rad)
    drad = 2 * np.pi * panel["dow"] / 7
    panel["dow_sin2"] = np.sin(2 * drad)
    fam["calendar"] = ["is_weekend", "holiday", "dow", "month", "day",
                       "block_sin2", "block_cos2", "dow_sin2"]

    # ---- encodings (TRAIN-ONLY target statistics; backward-looking) -- #
    train = panel[panel["split"] == "train"]
    gm = float(train[TARGET].mean())

    dowblk = train.groupby(["dow", "time_block"])[TARGET].mean().rename("dowblk_te").reset_index()
    panel = panel.merge(dowblk, on=["dow", "time_block"], how="left")

    a = train.groupby(["cell", "dow"])[TARGET].agg(["mean", "count"])
    sm = 20.0
    cd = ((a["mean"] * a["count"] + gm * sm) / (a["count"] + sm)).rename("celldow_te").reset_index()
    panel = panel.merge(cd, on=["cell", "dow"], how="left")

    a2 = train.groupby(["cell", "dow", "time_block"])[TARGET].agg(["mean", "count"])
    sm2 = 10.0
    cdb = ((a2["mean"] * a2["count"] + gm * sm2) / (a2["count"] + sm2)).rename("celldowblk_te").reset_index()
    panel = panel.merge(cdb, on=["cell", "dow", "time_block"], how="left")

    q90 = train.groupby(["cell", "time_block"])[TARGET].quantile(0.9).rename("cellblk_q90").reset_index()
    panel = panel.merge(q90, on=["cell", "time_block"], how="left")

    for col, fill in [("dowblk_te", gm), ("celldow_te", gm), ("celldowblk_te", gm), ("cellblk_q90", 0.0)]:
        panel[col] = panel[col].fillna(fill)
    fam["encoding"] = ["dowblk_te", "celldow_te", "celldowblk_te", "cellblk_q90"]

    # ---- native categoricals (preprocessing, not features) ----------- #
    if "dom_police_station" not in panel.columns:  # build_features already merged it
        panel = panel.merge(cmeta[["cell", "dom_police_station"]], on="cell", how="left")
    panel["cell_cat"] = panel["cell"].astype("category")
    panel["ps_cat"] = panel["dom_police_station"].astype("category")
    panel["tb_cat"] = panel["time_block"].astype("category")
    fam["native_cat"] = ["cell_cat", "ps_cat", "tb_cat"]

    # fill any residual NaNs in numeric new features with 0 (no history)
    numeric_new = fam["temporal"] + fam["spatial"]
    panel[numeric_new] = panel[numeric_new].fillna(0.0)
    return panel, fam


# --------------------------------------------------------------------------- #
# Champion LightGBM-Tweedie + early-stopping refit (replicates src.model)
# --------------------------------------------------------------------------- #
def _model():
    return LGBMRegressor(
        objective="tweedie", tweedie_variance_power=1.5, n_estimators=2000,
        learning_rate=0.03, num_leaves=95, min_child_samples=60, subsample=0.8,
        colsample_bytree=0.8, reg_lambda=1.0, n_jobs=-1, random_state=SEED, verbose=-1,
    )


def run_cfg(panel, feats, name, cat=None):
    tr = panel[panel["split"] == "train"]
    te = panel[panel["split"] == "test"]
    cut = pd.Timestamp(config.TRAIN_END_DATE) - pd.Timedelta(days=M.INNER_VAL_DAYS)
    fit_m = (pd.to_datetime(tr["date"]) <= cut).values
    Xtr, ytr = tr[feats], tr[TARGET].astype(float)
    Xte, yte = te[feats], te[TARGET].astype(float)
    kw = {"categorical_feature": cat} if cat else {}
    mdl = _model()
    mdl.fit(Xtr[fit_m], ytr[fit_m], eval_set=[(Xtr[~fit_m], ytr[~fit_m])], eval_metric="rmse",
            callbacks=[lgb.early_stopping(60, verbose=False), lgb.log_evaluation(0)], **kw)
    best = int(mdl.best_iteration_ or mdl.n_estimators)
    mdl.set_params(n_estimators=best)
    mdl.fit(Xtr, ytr, **kw)
    pred = np.clip(mdl.predict(Xte), 0, None)
    res = M.evaluate(name, yte, pred)
    res["n_feats"] = len(feats)
    res["best_iter"] = best
    log(f"{name:26s} feats={len(feats):3d} cap@5%={res['capture@5%']:.4f} "
        f"RMSE={res['RMSE']:.4f} iters={best}")
    return res


def main():
    t0 = time.time()
    log("building base panel + champion features ...")
    panel, base, cmeta = build_base()
    log(f"base features: {len(base)}")
    panel, fam = enrich(panel, cmeta)
    log(f"enriched families: " + ", ".join(f"{k}({len(v)})" for k, v in fam.items()))

    configs = [
        ("champion(base)", base, None),
        ("+temporal", base + fam["temporal"], None),
        ("+spatial", base + fam["spatial"], None),
        ("+encoding", base + fam["encoding"], None),
        ("+calendar", base + fam["calendar"], None),
        ("+ALL", base + fam["temporal"] + fam["spatial"] + fam["encoding"] + fam["calendar"], None),
        ("+ALL+native_cat",
         base + fam["temporal"] + fam["spatial"] + fam["encoding"] + fam["calendar"] + fam["native_cat"],
         fam["native_cat"]),
        # clean stacks = everything EXCEPT the naive (overfit-prone) encodings
        ("+CLEAN(temp+spat+cal)", base + fam["temporal"] + fam["spatial"] + fam["calendar"], None),
        ("+CLEAN+native_cat",
         base + fam["temporal"] + fam["spatial"] + fam["calendar"] + fam["native_cat"],
         fam["native_cat"]),
    ]

    rows = []
    for name, feats, cat in configs:
        # de-dup while preserving order (base may overlap revived calendar cols)
        seen, ff = set(), []
        for c in feats:
            if c not in seen:
                seen.add(c); ff.append(c)
        rows.append(run_cfg(panel, ff, name, cat=cat))

    df = pd.DataFrame(rows).set_index("model")
    keepcols = ["n_feats", "best_iter", "MAE", "RMSE", "R2", "PoissonDev",
                "capture@1%", "capture@5%", "capture@10%", "capture@20%"]
    df = df[keepcols]
    champ = df.loc["champion(base)", "capture@5%"]
    df["d_cap@5%"] = (df["capture@5%"] - champ).round(4)

    out = os.path.join(config.ARTIFACTS_DIR, "feature_ablation.csv")
    df.round(5).to_csv(out)
    print("\n=============== FEATURE ABLATION (LightGBM-Tweedie, test set) ===============")
    print(df.round(4).to_string())
    print(f"\n(champion reproduced cap@5% = {champ:.4f}; deltas in d_cap@5%)")
    print(f"saved -> {out}")
    log(f"runtime {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
