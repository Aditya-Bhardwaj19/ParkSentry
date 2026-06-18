"""
Step 7 -- Hotspot detection & Enforcement Priority Index (EPI).

REASONING
=========
The grid gives us cells, but an enforcement zone is usually a *cluster* of
adjacent busy cells (a market frontage, a metro exit, a stretch of main road).
So we group cells into hotspots with DBSCAN on the haversine distance:

  * DBSCAN, not k-means -- we do not know the number of hotspots in advance and
    they are irregular shapes; DBSCAN discovers density-based clusters and
    needs only a radius (eps = config.DBSCAN_EPS_M, currently 250 m, i.e. the
    8-neighbourhood of a ~150-165 m grid cell) and a min density.
  * Haversine metric -- clustering must respect real ground distance, so we
    feed lat/lon in radians with the haversine metric, eps in earth-radii.
  * Noise = micro-hotspot -- an isolated but very busy cell is still worth
    enforcing, so DBSCAN 'noise' points become their own single-cell hotspots
    rather than being discarded.

ENFORCEMENT PRIORITY INDEX
    Targeted enforcement needs ONE rankable number per hotspot that fuses
    "how much illegal parking will happen" with "how badly each instance hurts
    flow":

        EPI_raw  =  predicted_daily_violations  x  mean_impact_per_violation
                 =  predicted daily CONGESTION HARM

    We then min-max scale EPI_raw to 0-100 for a readable priority score. The
    predicted volume comes from the trained model (the future), and the impact
    per violation comes from the documented Congestion Impact heuristic -- so
    the index combines a learned forecast with a transparent harm weighting.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402


def per_cell_risk(panel: pd.DataFrame, pred_col: str = "pred") -> pd.DataFrame:
    """Aggregate model predictions + actuals to per-cell daily risk on the test
    horizon (the forecast period), plus the cell's peak time block."""
    test = panel[panel["split"] == "test"].copy()
    n_days = test["date"].nunique()

    by_cell = test.groupby("cell").agg(
        pred_daily_viol=(pred_col, lambda s: s.sum() / n_days),
        actual_daily_viol=("viol_count", lambda s: s.sum() / n_days),
        pred_total=(pred_col, "sum"),
    ).reset_index()

    # peak block = block with the most predicted volume in the cell.
    # Deterministic tie-break: on equal predicted sums, pick the earliest block
    # (stable mergesort so runs/pandas versions agree).
    blk = (test.groupby(["cell", "time_block"])[pred_col].sum()
           .reset_index()
           .sort_values([pred_col, "time_block"], ascending=[False, True], kind="mergesort")
           .drop_duplicates("cell")[["cell", "time_block"]]
           .rename(columns={"time_block": "peak_block"}))
    by_cell = by_cell.merge(blk, on="cell", how="left")
    by_cell["peak_block_label"] = by_cell["peak_block"].map(
        lambda b: config.TIME_BLOCKS.get(int(b), ("?", 0))[0] if pd.notna(b) else "?")
    return by_cell


def _normalize_epi(raw: pd.Series) -> pd.Series:
    """Scale EPI to a readable 0-100 display score (STRICTLY MONOTONIC in `raw`).

    Plain min-max is dominated by one outlier cell (the central market core is
    ~3.5x the 99th percentile), compressing ~90% of cells toward 0. Winsorizing
    instead saturates the top tail and ties the highest-priority cells together
    -- both are bad. We use a LOG compression: only the single maximum reaches
    100, every other cell gets a strictly smaller, distinct score, and the dense
    bulk is lifted off zero. Because it is monotonic, the ranking is identical to
    ranking on `raw` -- this only sets the displayed magnitude / colour scale.

    NOTE: ranking is always done on `epi_raw`, not on this score, so display
    rounding never affects the order of the top cells.
    """
    m = float(raw.max())
    if not (m > 0):                                    # degenerate: all zero
        return raw * 0.0 + 50.0
    return (100 * np.log1p(raw.clip(lower=0)) / np.log1p(m)).round(1)


def detect(cell_meta: pd.DataFrame, cell_risk: pd.DataFrame,
           verbose: bool = True) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Build the enforcement priority products.

    Returns (cell_priority, zones, cells_annotated):
      * cell_priority   -- PRIMARY actionable output: every ~150 m cell ranked
                           by its own Enforcement Priority Index. A cell is a
                           specific road stretch a patrol can be sent to.
      * zones           -- SECONDARY analytical grouping: DBSCAN density zones,
                           useful for understanding spatial structure and beat
                           allocation. In dense contiguous cores DBSCAN chains
                           many cells into one large zone, so zones are NOT used
                           as the targeting unit (that would mean "patrol the
                           whole market") -- cells are.
      * cells_annotated -- all cells with EPI + zone id, for mapping.
    """
    log = (lambda *a: print("  [hotspots]", *a)) if verbose else (lambda *a: None)
    cells = cell_meta.merge(cell_risk, on="cell", how="left").fillna({
        "pred_daily_viol": 0.0, "actual_daily_viol": 0.0, "pred_total": 0.0})

    # === PRIMARY: per-cell Enforcement Priority Index ==================== #
    cells["mean_impact_per_viol"] = (
        cells["cell_impact_sum"] / cells["total_events"].clip(lower=1)).round(3)
    cells["epi_raw"] = cells["pred_daily_viol"] * cells["mean_impact_per_viol"]
    cells["EPI"] = _normalize_epi(cells["epi_raw"])

    # === SECONDARY: DBSCAN density zones (haversine) ==================== #
    coords = np.radians(cells[["cell_lat", "cell_lon"]].to_numpy())
    eps = config.DBSCAN_EPS_M / config.EARTH_RADIUS_M
    db = DBSCAN(eps=eps, min_samples=config.DBSCAN_MIN_SAMPLES,
                metric="haversine").fit(coords)
    labels = db.labels_.copy()
    next_id = labels.max() + 1 if labels.max() >= 0 else 0          # noise -> own zone
    noise = labels == -1
    labels[noise] = np.arange(next_id, next_id + noise.sum())
    cells["zone_id"] = labels
    n_multi = len(set(db.labels_[db.labels_ >= 0]))
    log(f"{n_multi} density zones + {int(noise.sum())} singletons; "
        f"per-CELL priority is the primary targeting unit")

    # --- cell priority table (ranked on epi_raw, the strict priority) ---- #
    cell_priority = (
        cells.sort_values("epi_raw", ascending=False, kind="mergesort").reset_index(drop=True)
        [["cell", "cell_lat", "cell_lon", "EPI", "epi_raw", "pred_daily_viol",
          "actual_daily_viol", "mean_impact_per_viol", "total_events",
          "peak_block", "peak_block_label", "dom_police_station",
          "dom_junction", "cell_junction_share", "zone_id"]]
        .rename(columns={"cell_lat": "lat", "cell_lon": "lon"})
    )
    cell_priority.insert(0, "rank", np.arange(1, len(cell_priority) + 1))

    # --- zone summary (secondary) --------------------------------------- #
    def _wmean(v, w):
        w = np.asarray(w, float)
        return float(np.average(v, weights=w)) if w.sum() > 0 else float(np.mean(v))

    zrows = []
    for zid, grp in cells.groupby("zone_id"):
        tot = grp["total_events"].sum()
        zrows.append({
            "zone_id": zid, "n_cells": len(grp),
            "lat": _wmean(grp["cell_lat"], grp["total_events"]),
            "lon": _wmean(grp["cell_lon"], grp["total_events"]),
            "total_events": int(tot),
            "pred_daily_viol": round(float(grp["pred_daily_viol"].sum()), 2),
            "mean_impact_per_viol": round(float(grp["cell_impact_sum"].sum() / max(tot, 1)), 3),
            "dom_police_station": grp.sort_values("total_events").iloc[-1]["dom_police_station"],
        })
    zones = pd.DataFrame(zrows)
    zones["epi_raw"] = zones["pred_daily_viol"] * zones["mean_impact_per_viol"]
    zones["zone_EPI"] = _normalize_epi(zones["epi_raw"])
    zones = zones.sort_values("epi_raw", ascending=False, kind="mergesort").reset_index(drop=True)
    zones.insert(0, "rank", np.arange(1, len(zones) + 1))

    top = cell_priority.iloc[0]
    log(f"top CELL: EPI={top['EPI']} ~{top['pred_daily_viol']:.1f}/day "
        f"@ {top['peak_block_label']} ({top['dom_police_station']} / {top['dom_junction']})")
    return cell_priority, zones, cells


if __name__ == "__main__":
    from src import ingest, impact, aggregate, features, feature_selection, model
    d = impact.add_event_impact(ingest.run(cache=True))
    panel, cmeta = aggregate.build_panel(d, verbose=False)
    panel, cols, enc = features.build_features(panel, cmeta, verbose=False)
    keep, _ = feature_selection.select(panel, cols, verbose=False)
    out = model.train_and_evaluate(panel, keep, save=False, verbose=False)
    panel["pred"] = np.clip(out["best_model"].predict(panel[keep].astype(float)), 0, None)
    risk = per_cell_risk(panel)
    cell_priority, zones, cells = detect(cmeta, risk)
    print("=== TOP CELLS (primary) ===")
    print(cell_priority.head(10).to_string(index=False))
    print("\n=== TOP ZONES (secondary) ===")
    print(zones.head(5).to_string(index=False))
