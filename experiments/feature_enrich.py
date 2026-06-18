"""
Part 2 — feature-enrichment ceiling test for ParkSentry.

The hotspot-forecasting literature says SPATIAL clustering and richer temporal
memory drive the capture/PAI metric. This script measures how much extra signal
the following *inference-reconstructable* features add, on top of the existing
22, using the best model family from Part 1 (tuned LightGBM-Tweedie):

  + holiday          calendar flag for Indian public holidays / festivals
  + ewm7             EWMA(span 7) of the cell-block's own past (smoother memory)
  + lag14, roll14    longer autoregressive memory
  + nbr_roll7        DYNAMIC: mean roll7 of the 8 grid-neighbour cells (spatial)
  + nbr_blk_mean     STATIC : mean historical intensity of the 8 neighbours

Each added feature is causal / leak-safe (shifted target, train-only priors) and
can be rebuilt for a single (cell, date, block) at inference time.

Run:  python experiments/feature_enrich.py
"""
from __future__ import annotations

import os
import sys
import time
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import config  # noqa: E402
from src import ingest, impact, aggregate, features, feature_selection  # noqa: E402
from src.model import evaluate, top_k_capture, TARGET  # noqa: E402

RS = config.RANDOM_STATE

# Indian public holidays / major festivals within the data window (Nov'23–Apr'24).
HOLIDAYS = {
    "2023-11-12", "2023-11-13", "2023-11-14", "2023-11-27",  # Diwali cluster, Guru Nanak
    "2023-12-25",                                            # Christmas
    "2024-01-01", "2024-01-15", "2024-01-26",                # New Year, Sankranti, Republic Day
    "2024-03-08", "2024-03-25", "2024-03-29",                # Shivaratri, Holi, Good Friday
    "2024-04-09",                                            # Ugadi
}


def add_enriched(panel: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    panel = panel.sort_values(["cell", "time_block", "date"]).copy()
    g = panel.groupby(["cell", "time_block"])[TARGET]

    panel["lag14"] = g.shift(14)
    panel["roll14_mean"] = g.transform(lambda s: s.shift(1).rolling(14, min_periods=1).mean())
    panel["ewm7"] = g.transform(lambda s: s.shift(1).ewm(span=7, min_periods=1).mean())

    d = pd.to_datetime(panel["date"]).dt.strftime("%Y-%m-%d")
    panel["holiday"] = d.isin(HOLIDAYS).astype(int)

    # --- spatial neighbours (8-connected grid) --------------------------- #
    rc = panel["cell"].str.split("_", expand=True).astype(int)
    panel["r"], panel["c"] = rc[0], rc[1]
    src = panel[["cell", "date", "time_block", "roll7_mean", "cell_blk_mean", "r", "c"]]
    lut = src.set_index(["r", "c", "date", "time_block"])[["roll7_mean", "cell_blk_mean"]]

    nbr_roll_sum = np.zeros(len(panel)); nbr_blk_sum = np.zeros(len(panel)); nbr_cnt = np.zeros(len(panel))
    offsets = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
    key_base = list(zip(panel["r"], panel["c"], panel["date"], panel["time_block"]))
    for dr, dc in offsets:
        idx = pd.MultiIndex.from_arrays(
            [panel["r"] + dr, panel["c"] + dc, panel["date"], panel["time_block"]])
        got = lut.reindex(idx)
        rr = got["roll7_mean"].to_numpy()
        bb = got["cell_blk_mean"].to_numpy()
        present = ~np.isnan(rr)
        nbr_roll_sum += np.where(present, np.nan_to_num(rr), 0.0)
        nbr_blk_sum += np.where(present, np.nan_to_num(bb), 0.0)
        nbr_cnt += present.astype(float)
    panel["nbr_roll7"] = nbr_roll_sum / np.maximum(nbr_cnt, 1)
    panel["nbr_blk_mean"] = nbr_blk_sum / np.maximum(nbr_cnt, 1)

    new = ["holiday", "ewm7", "lag14", "roll14_mean", "nbr_roll7", "nbr_blk_mean"]
    panel[new] = panel[new].fillna(0.0)
    return panel, new


def lgbm_tw_tuned():
    from lightgbm import LGBMRegressor
    return LGBMRegressor(objective="tweedie", tweedie_variance_power=1.5,
                         n_estimators=2000, learning_rate=0.03, num_leaves=95,
                         min_child_samples=60, subsample=0.8, colsample_bytree=0.8,
                         reg_lambda=1.0, n_jobs=-1, random_state=RS, verbose=-1)


def fit_es(model, S):
    import lightgbm as lgb
    model.fit(S["Xfit"], S["yfit"], eval_set=[(S["Xval"], S["yval"])], eval_metric="rmse",
              callbacks=[lgb.early_stopping(60, verbose=False), lgb.log_evaluation(0)])
    best = model.best_iteration_ or model.n_estimators
    model.set_params(n_estimators=int(best))
    model.fit(S["Xtr"], S["ytr"])
    return model, best


def run():
    t0 = time.time()
    d = impact.add_event_impact(ingest.run(cache=True))
    panel, cmeta = aggregate.build_panel(d, verbose=False)
    panel, cols, enc = features.build_features(panel, cmeta, verbose=False)
    base_feats, _ = feature_selection.select(panel, cols, verbose=False)
    panel, new_feats = add_enriched(panel)
    enriched_feats = base_feats + new_feats
    print(f"[data] {len(panel):,} rows | base {len(base_feats)} | "
          f"enriched {len(enriched_feats)} | {time.time()-t0:.1f}s")

    dt = pd.to_datetime(panel["date"])
    train_end = pd.Timestamp(config.TRAIN_END_DATE)
    inner_cut = train_end - pd.Timedelta(days=21)
    tr = panel[panel["split"] == "train"]; te = panel[panel["split"] == "test"]
    fit = panel[dt <= inner_cut]; val = panel[(dt > inner_cut) & (dt <= train_end)]
    yte = te[TARGET].astype(float).values

    def make_S(feats):
        f = lambda df: (df[feats].astype(float).values, df[TARGET].astype(float).values)
        return {"Xtr": f(tr)[0], "ytr": f(tr)[1], "Xte": f(te)[0],
                "Xfit": f(fit)[0], "yfit": f(fit)[1], "Xval": f(val)[0], "yval": f(val)[1]}

    rows = []
    for label, feats in [("base(22)", base_feats), ("enriched(+6)", enriched_feats)]:
        S = make_S(feats)
        m, it = fit_es(lgbm_tw_tuned(), S)
        r = evaluate(f"LGBM-Tw-tuned [{label}] it={it}", yte, np.clip(m.predict(S["Xte"]), 0, None))
        rows.append(r)
        print(f"  {label:14s} RMSE={r['RMSE']:.4f}  cap@5%={r['capture@5%']:.4f}  "
              f"cap@1%={r['capture@1%']:.4f}")
        if label.startswith("enriched"):
            imp = pd.Series(m.feature_importances_, index=feats).sort_values(ascending=False)
            print("    new-feature importances:",
                  {k: int(imp[k]) for k in new_feats if k in imp.index})

    df = pd.DataFrame(rows).set_index("model")[
        ["RMSE", "MAE", "R2", "PoissonDev", "capture@1%", "capture@5%", "capture@10%"]]
    df.round(4).to_csv(os.path.join(ROOT, "experiments", "feature_enrich_results.csv"))
    print("\n" + "=" * 70)
    print(df.round(4).to_string())
    print("\nsaved -> experiments/feature_enrich_results.csv")


if __name__ == "__main__":
    run()
