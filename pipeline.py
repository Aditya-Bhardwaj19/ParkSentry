"""
End-to-end orchestration for ViolationProto (Theme 1).

Runs the full chain and persists every artifact the inference module and the
web app (webapp/) need:

    ingest -> impact -> aggregate -> features -> feature-selection
           -> model -> score -> hotspots/EPI -> visualize -> save

Usage:
    python pipeline.py              # full run on the whole dataset
    python pipeline.py --sample 40000   # quick smoke run on a subset

Each stage prints a short reasoned banner so a run is self-documenting.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import joblib
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from src import (ingest, impact, aggregate, features, feature_selection,
                 model, hotspots, visualize)


def _banner(step, why):
    print(f"\n{'='*72}\n# {step}\n#   {why}\n{'='*72}")


def run(sample: int | None = None, make_plots: bool = True) -> dict:
    t0 = time.time()

    _banner("1/8 INGEST & CLEAN",
            "parse JSON violations, filter to parking, validate geo, localise time")
    events = ingest.run(nrows=sample, cache=(sample is None))

    _banner("2/8 CONGESTION IMPACT",
            "score each event by severity x vehicle x peak x junction")
    events = impact.add_event_impact(events)

    _banner("3/8 SPATIO-TEMPORAL AGGREGATION",
            "build the (cell x date x time-block) panel with zero-fill")
    panel, cell_meta = aggregate.build_panel(events)

    _banner("4/8 FEATURE ENGINEERING & ENCODING",
            "calendar/cyclical + causal lags + leak-safe cell priors & target encoding")
    panel, feat_cols, encoders = features.build_features(panel, cell_meta)

    _banner("5/8 FEATURE SELECTION",
            "drop near-constant, redundant (|r|>0.95) and weak-signal features")
    selected, sel_report = feature_selection.select(panel, feat_cols)

    _banner("6/8 MODELLING & EVALUATION",
            "baseline vs GLM/RF/HistGB/XGB/LGBM, temporal split, Poisson + capture metrics")
    mout = model.train_and_evaluate(panel, selected, save=True)
    best, best_name = mout["best_model"], mout["best_name"]
    importance = model.feature_importance(best, selected)

    _banner("7/8 SCORING & PRIORITY RANKING",
            "predict per cell-block risk; per-CELL Enforcement Priority Index + DBSCAN zones")
    panel["pred"] = np.clip(best.predict(panel[selected].astype(float)), 0, None)
    cell_risk = hotspots.per_cell_risk(panel)
    cell_priority, zones, cells_annot = hotspots.detect(cell_meta, cell_risk)

    _banner("8/8 OUTPUTS & VISUALS",
            "write priority ranking, scored cells, encoders, plots, run summary")
    _persist(events, panel, cell_meta, encoders, selected, sel_report,
             mout, cell_priority, zones, cells_annot)

    if make_plots:
        te = panel[panel["split"] == "test"]
        visualize.make_all(events, mout["results"], importance,
                           te["viol_count"], te["pred"], cells_annot, cell_priority)

    summary = _summary(events, panel, mout, cell_priority, zones, selected, time.time() - t0)
    with open(os.path.join(config.OUTPUTS_DIR, "run_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)

    _print_summary(summary)
    return summary


def _persist(events, panel, cell_meta, encoders, selected, sel_report,
             mout, cell_priority, zones, cells_annot):
    # primary cell priority ranking + secondary zones + annotated cells
    cell_priority.to_csv(os.path.join(config.OUTPUTS_DIR, "cell_priority_ranked.csv"), index=False)
    zones.to_csv(os.path.join(config.OUTPUTS_DIR, "hotspot_zones.csv"), index=False)
    cells_annot.to_csv(os.path.join(config.OUTPUTS_DIR, "cells_annotated.csv"), index=False)

    # scored panel (compact) for the dashboard time-block views
    keep = ["cell", "date", "time_block", "viol_count", "pred"]
    panel[keep].to_parquet(os.path.join(config.OUTPUTS_DIR, "scored_panel.parquet"),
                           index=False)

    # --- inference artifacts ------------------------------------------- #
    # cell-static feature store (everything needed to score a cell-block except lags).
    # log_total_events uses TRAIN-only volume to stay consistent with training (leak-safe).
    cell_static = (
        cell_meta[["cell", "cell_lat", "cell_lon", "total_events", "train_events",
                   "dom_police_station", "cell_sev_mean", "cell_veh_mean",
                   "cell_junction_share"]]
        .merge(encoders["cellstat"], on="cell", how="left")
        .copy()
    )
    cell_static["log_total_events"] = np.log1p(cell_static["train_events"].fillna(0))
    cell_static["ps_target_enc"] = (
        cell_static["dom_police_station"].map(encoders["ps_target_enc"])
        .fillna(encoders["ps_global_mean"])
    )
    cell_static.to_parquet(os.path.join(config.ARTIFACTS_DIR, "cell_static.parquet"),
                           index=False)

    # recent history so the forecaster can rebuild lag features. We keep enough
    # days that the longest lookback (roll28_mean = 28 days) is FULLY covered for
    # any scoring date in the recent deploy window -- otherwise inference would
    # truncate the 28-day window and diverge from training. 28 + 42 margin.
    cutoff = pd.to_datetime(panel["date"]).max() - pd.Timedelta(days=config.HISTORY_RETENTION_DAYS)
    recent = panel[pd.to_datetime(panel["date"]) >= cutoff][
        ["cell", "date", "time_block", "viol_count"]]
    recent.to_parquet(os.path.join(config.ARTIFACTS_DIR, "recent_history.parquet"),
                      index=False)

    joblib.dump(encoders, os.path.join(config.ARTIFACTS_DIR, "encoders.joblib"))
    with open(os.path.join(config.ARTIFACTS_DIR, "selection_report.json"), "w") as f:
        json.dump({k: v for k, v in sel_report.items() if k != "cell_blk_hist"},
                  f, indent=2, default=str)


def _summary(events, panel, mout, cell_priority, zones, selected, secs) -> dict:
    res = mout["results"]
    best = res.loc[mout["best_name"]]
    base = res.loc["Baseline(hist-mean)"]
    top = cell_priority.iloc[0]
    return {
        "events_clean": int(len(events)),
        "date_range": [str(events["date"].min().date()), str(events["date"].max().date())],
        "panel_rows": int(len(panel)),
        "n_cells": int(panel["cell"].nunique()),
        "n_zones": int(zones["zone_id"].nunique()),
        "n_features_selected": len(selected),
        "best_model": mout["best_name"],
        "best_RMSE": round(float(best["RMSE"]), 4),
        "baseline_RMSE": round(float(base["RMSE"]), 4),
        "best_MAE": round(float(best["MAE"]), 4),
        "best_R2": round(float(best["R2"]), 4),
        "capture_at_5pct": round(float(best["capture@5%"]), 4),
        "capture_at_1pct": round(float(best["capture@1%"]), 4),
        "top_cell": {
            "rank": int(top["rank"]),
            "EPI": float(top["EPI"]),
            "police_station": str(top["dom_police_station"]),
            "junction": str(top["dom_junction"]),
            "pred_daily_viol": float(top["pred_daily_viol"]),
            "peak_block": str(top["peak_block_label"]),
        },
        "runtime_sec": round(secs, 1),
    }


def _print_summary(s):
    print(f"\n{'#'*72}\n# RUN COMPLETE in {s['runtime_sec']}s\n{'#'*72}")
    print(f"clean events      : {s['events_clean']:,} ({s['date_range'][0]} -> {s['date_range'][1]})")
    print(f"panel / cells     : {s['panel_rows']:,} rows over {s['n_cells']:,} cells")
    print(f"best model        : {s['best_model']}  "
          f"(RMSE {s['best_RMSE']} vs baseline {s['baseline_RMSE']}, R2 {s['best_R2']})")
    print(f"enforcement lift  : top 5% of slots capture "
          f"{s['capture_at_5pct']*100:.1f}% of violations "
          f"(top 1% -> {s['capture_at_1pct']*100:.1f}%)")
    print(f"priority targets  : {s['n_cells']} cells / {s['n_zones']} zones | top cell = "
          f"{s['top_cell']['police_station']} / {s['top_cell']['junction']} "
          f"(~{s['top_cell']['pred_daily_viol']:.0f}/day, {s['top_cell']['peak_block']})")
    print("\nartifacts -> ./artifacts   outputs/plots -> ./outputs")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=None,
                    help="rows to sample for a quick smoke run (default: full)")
    ap.add_argument("--no-plots", action="store_true")
    args = ap.parse_args()
    run(sample=args.sample, make_plots=not args.no_plots)
