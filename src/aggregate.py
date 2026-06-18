"""
Step 3 -- Spatio-temporal aggregation into the modelling panel.

REASONING
=========
Individual citations are not the right unit for *forecasting enforcement
pressure*. A patrol is dispatched to a place at a time, so the natural unit of
analysis is:

        (grid cell  x  calendar date  x  4-hour time block)

and the thing we want to predict is the VIOLATION COUNT in that unit -- a
direct measure of "how much illegal parking is happening here, now".

Two design decisions worth defending:

  1. Grid cells, not raw points. We snap each event to a ~150 m grid cell.
     This pools sparse points into a stable enforcement-zone signal and gives
     every cell a fixed identity across time so we can build a panel and lag
     features.

  2. Zero-filling. We expand to the full (active-cell x date x block) grid and
     fill unobserved combinations with count 0. Without this, the model would
     only ever see "a violation happened" rows and could not learn WHEN a
     hotspot is quiet. The zeros are the negative class of the risk surface.

OBSERVABILITY CAVEAT (documented honestly):
    Counts are *detected* violations, so they reflect enforcement effort as
    well as true illegal parking. A zero can mean "no patrol came" rather than
    "no violation". The model therefore predicts *detected* parking pressure --
    still the correct target for "where should the next patrol go", but the
    caveat matters and is surfaced in the README.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402


def assign_cells(df: pd.DataFrame) -> pd.DataFrame:
    """Snap each event to a grid cell and attach row/col indices."""
    df = df.copy()
    bb, g = config.BENGALURU_BBOX, config.GRID_SIZE_DEG
    df["cell_row"] = np.floor((df["latitude"] - bb["lat_min"]) / g).astype(int)
    df["cell_col"] = np.floor((df["longitude"] - bb["lon_min"]) / g).astype(int)
    df["cell"] = df["cell_row"].astype(str) + "_" + df["cell_col"].astype(str)
    return df


def cell_centroids(df: pd.DataFrame) -> pd.DataFrame:
    """Mean lat/lon per cell (more faithful than the grid centre)."""
    return (
        df.groupby("cell")
        .agg(cell_lat=("latitude", "mean"), cell_lon=("longitude", "mean"))
        .reset_index()
    )


def _safe_mode(s: pd.Series, default: str) -> str:
    """Most frequent value, robust to empty / all-NaN groups (mode() can be empty)."""
    m = s.dropna().mode()
    return m.iat[0] if not m.empty else default


def build_panel(df: pd.DataFrame, train_end_date: str | None = None,
                verbose: bool = True) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (panel, cell_meta).

    panel    : one row per (cell, date, time_block) including zero-count rows.
    cell_meta: static per-cell descriptors. Anything that becomes a MODEL
               FEATURE (train_events -> log_total_events, dom_police_station ->
               target encoding) is computed on the TRAIN split only, so no
               test-period information leaks into training. Pure display /
               severity descriptors (total_events, dom_vehicle, impact mix) and
               the centroid are computed on the full data -- they are not used
               to predict the target, only to report and to weight the
               post-hoc Congestion Impact Score.
    """
    log = (lambda *a: print("  [aggregate]", *a)) if verbose else (lambda *a: None)
    train_end = pd.Timestamp(train_end_date or config.TRAIN_END_DATE)
    df = assign_cells(df)

    # Keep enforcement-relevant cells only.
    totals = df.groupby("cell").size()
    keep_cells = totals[totals >= config.MIN_CELL_EVENTS].index
    df = df[df["cell"].isin(keep_cells)].copy()
    log(f"kept {len(keep_cells):,} cells (>= {config.MIN_CELL_EVENTS} events), "
        f"{len(df):,} events")

    # ---- observed aggregates per (cell, date, block) ------------------- #
    grp = df.groupby(["cell", "date", "time_block"])
    obs = grp.agg(
        viol_count=("id", "size"),
        impact_sum=("impact_score", "sum"),
        impact_mean=("impact_score", "mean"),
        sev_mean=("severity_w", "mean"),
        veh_mean=("vehicle_w", "mean"),
        nviol_mean=("n_violations", "mean"),
        junction_share=("is_junction", "mean"),
    ).reset_index()

    # ---- full panel skeleton (zero-fill) ------------------------------- #
    cells = pd.Index(keep_cells, name="cell")
    dates = pd.Index(sorted(df["date"].unique()), name="date")
    blocks = pd.Index(range(config.N_TIME_BLOCKS), name="time_block")
    skeleton = (
        pd.MultiIndex.from_product([cells, dates, blocks],
                                   names=["cell", "date", "time_block"])
        .to_frame(index=False)
    )
    panel = skeleton.merge(obs, on=["cell", "date", "time_block"], how="left")

    # zero-count rows: counts/impacts are genuinely 0; mix descriptors are
    # "not applicable" -> left NaN, to be filled with cell-static history later.
    for c in ["viol_count", "impact_sum"]:
        panel[c] = panel[c].fillna(0.0)
    log(f"panel rows: {len(panel):,}  "
        f"(nonzero {int((panel.viol_count>0).mean()*100)}% )")

    # ---- calendar features (recompute from date, robust to zero rows) -- #
    d = pd.to_datetime(panel["date"])
    panel["dow"] = d.dt.dayofweek.astype(int)
    panel["is_weekend"] = (panel["dow"] >= 5).astype(int)
    panel["month"] = d.dt.month.astype(int)
    panel["day"] = d.dt.day.astype(int)
    panel["peak_w"] = panel["time_block"].map(lambda b: config.TIME_BLOCKS[b][1])

    # ---- cell metadata ------------------------------------------------- #
    cmeta = cell_centroids(df)  # geography (not target-derived) -> full data ok

    # FULL-DATA descriptors: display volume + severity mix (post-hoc weighting,
    # never used as model inputs to predict the count target).
    dom = (
        df.groupby("cell")
        .agg(
            total_events=("id", "size"),
            dom_vehicle=("vehicle_type_clean", lambda s: _safe_mode(s, "UNKNOWN")),
            dom_junction=("junction_name", lambda s: _safe_mode(s, "No Junction")),
            cell_junction_share=("is_junction", "mean"),
            cell_sev_mean=("severity_w", "mean"),
            cell_veh_mean=("vehicle_w", "mean"),
            cell_impact_sum=("impact_score", "sum"),
        )
        .reset_index()
    )

    # TRAIN-ONLY descriptors: these feed model features, so they must not see
    # the test window. Cells with no train events get a deterministic fallback.
    df_train = df[df["date"] <= train_end]
    train_dom = (
        df_train.groupby("cell")
        .agg(
            train_events=("id", "size"),
            dom_police_station=("police_station", lambda s: _safe_mode(s, "UNKNOWN")),
        )
        .reset_index()
    )
    cell_meta = (
        cmeta.merge(dom, on="cell", how="left")
             .merge(train_dom, on="cell", how="left")
    )
    cell_meta["train_events"] = cell_meta["train_events"].fillna(0).astype(int)
    cell_meta["dom_police_station"] = cell_meta["dom_police_station"].fillna("UNKNOWN")
    log(f"cell_meta: {len(cell_meta):,} cells "
        f"({int((cell_meta['train_events'] == 0).sum())} with no train events -> fallback)")

    panel = panel.merge(cmeta, on="cell", how="left")
    return panel, cell_meta


if __name__ == "__main__":
    from src import ingest, impact
    d = ingest.run(cache=True)
    d = impact.add_event_impact(d)
    panel, cmeta = build_panel(d)
    print(panel.head())
    print("\npanel shape", panel.shape, "| cell_meta shape", cmeta.shape)
