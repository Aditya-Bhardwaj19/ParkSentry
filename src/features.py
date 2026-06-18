"""
Step 4 -- Feature engineering & encoding (leak-safe).

REASONING
=========
The target (violation count per cell-date-block) is a zero-inflated count
forecast. Three families of signal drive it, and each needs careful, *causal*
construction so we never leak the future into the past:

  A. CALENDAR / CYCLICAL -- hour-block, day-of-week and month are cyclical
     (block 5 is adjacent to block 0). Encoding them as raw integers tells a
     linear model that "Sunday (6) is far from Monday (0)". We add sin/cos
     pairs so the geometry is correct, and keep peak_w (the rush-hour weight).

  B. AUTOREGRESSIVE LAGS -- the single strongest predictor of "violations here
     now" is "violations here recently". We build lag-1, lag-7 and rolling
     means PER (cell, time_block), each SHIFTED so a row only ever sees its own
     past. Shifting makes these leak-safe even across the train/test boundary
     (a legitimate forecast may use the test period's own history).

  C. CELL-STATIC PRIORS (leak-safe encoding) -- for a "cold" cell-block with no
     recent activity, the model still needs a prior: how active is this place
     historically, how severe, how junction-y, what police station. These are
     computed ON THE TRAIN SPLIT ONLY and mapped to every row -- this is the
     correct way to do target/frequency encoding without leakage. Cells unseen
     in train fall back to the global train mean.

LEAKAGE is the cardinal sin of a forecasting model, so the split boundary is
respected throughout: anything that aggregates the target is fit on train rows
only.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402

TARGET = "viol_count"


def _cyclical(values: pd.Series, period: int, name: str) -> pd.DataFrame:
    """sin/cos encoding of a cyclical integer feature."""
    rad = 2 * np.pi * values / period
    return pd.DataFrame({f"{name}_sin": np.sin(rad), f"{name}_cos": np.cos(rad)})


def add_calendar(panel: pd.DataFrame) -> pd.DataFrame:
    panel = panel.copy()
    panel = pd.concat([
        panel,
        _cyclical(panel["time_block"], config.N_TIME_BLOCKS, "block"),
        _cyclical(panel["dow"], 7, "dow"),
        _cyclical(panel["month"], 12, "month"),
    ], axis=1)
    return panel


def add_lags(panel: pd.DataFrame) -> pd.DataFrame:
    """Causal autoregressive features per (cell, time_block), ordered by date."""
    panel = panel.sort_values(["cell", "time_block", "date"]).copy()
    g = panel.groupby(["cell", "time_block"])[TARGET]

    panel["lag1"] = g.shift(1)
    panel["lag2"] = g.shift(2)
    panel["lag7"] = g.shift(7)
    # rolling means of the *past* (shift(1) first so current row is excluded)
    panel["roll7_mean"] = g.transform(lambda s: s.shift(1).rolling(7, min_periods=1).mean())
    panel["roll28_mean"] = g.transform(lambda s: s.shift(1).rolling(28, min_periods=1).mean())

    # cell-level recent activity across ALL blocks (broader context)
    gc = panel.sort_values(["cell", "date", "time_block"]).groupby("cell")[TARGET]
    panel["cell_roll_day"] = gc.transform(lambda s: s.shift(1).rolling(6, min_periods=1).mean())

    lag_cols = ["lag1", "lag2", "lag7", "roll7_mean", "roll28_mean", "cell_roll_day"]
    panel[lag_cols] = panel[lag_cols].fillna(0.0)  # no history -> no recent activity
    return panel


def add_cell_priors(panel: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Leak-safe cell-static priors and target/frequency encodings (train-only).

    The train split is derived from the panel's `split` column so the function
    is robust to index changes from upstream merges (no carried boolean mask).
    """
    panel = panel.reset_index(drop=True).copy()
    train = panel[panel["split"] == "train"]
    enc: dict = {}

    # --- historical intensity per (cell, block) ------------------------- #
    hist = (
        train.groupby(["cell", "time_block"])[TARGET]
        .agg(cell_blk_mean="mean", cell_blk_nonzero=lambda s: (s > 0).mean())
        .reset_index()
    )
    global_mean = float(train[TARGET].mean())
    global_nz = float((train[TARGET] > 0).mean())
    panel = panel.merge(hist, on=["cell", "time_block"], how="left")
    panel["cell_blk_mean"] = panel["cell_blk_mean"].fillna(global_mean)
    panel["cell_blk_nonzero"] = panel["cell_blk_nonzero"].fillna(global_nz)
    enc["global_mean"] = global_mean
    enc["global_nz"] = global_nz
    enc["cell_blk_hist"] = hist

    # --- cell-static obstruction mix (from observed train rows) --------- #
    obs = train[train[TARGET] > 0]
    cellstat = (
        obs.groupby("cell")
        .agg(cell_sev=("sev_mean", "mean"),
             cell_veh=("veh_mean", "mean"),
             cell_jshare=("junction_share", "mean"))
        .reset_index()
    )
    defaults = {
        "cell_sev": float(obs["sev_mean"].mean()),
        "cell_veh": float(obs["veh_mean"].mean()),
        "cell_jshare": float(obs["junction_share"].mean()),
    }
    panel = panel.merge(cellstat, on="cell", how="left")
    for k, v in defaults.items():
        panel[k] = panel[k].fillna(v)
    enc["cellstat"] = cellstat
    enc["cellstat_defaults"] = defaults

    return panel, enc


def add_categorical_encoding(panel: pd.DataFrame, cell_meta: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Target-encode the dominant police station per cell (train-only means).

    Both inputs are leak-safe: `dom_police_station` and `train_events` are
    computed from train events only in aggregate.build_panel, and the encoding
    means below are fit on train rows only.
    """
    panel = panel.merge(cell_meta[["cell", "dom_police_station", "train_events"]],
                        on="cell", how="left").reset_index(drop=True)
    enc: dict = {}

    # target (mean count) encoding of police station, smoothed, train-only
    train = panel[panel["split"] == "train"]
    global_mean = float(train[TARGET].mean())
    agg = train.groupby("dom_police_station")[TARGET].agg(["mean", "count"])
    smoothing = 50.0  # shrink small stations toward the global mean
    ps_te = (agg["mean"] * agg["count"] + global_mean * smoothing) / (agg["count"] + smoothing)
    panel["ps_target_enc"] = panel["dom_police_station"].map(ps_te).fillna(global_mean)
    enc["ps_target_enc"] = ps_te.to_dict()
    enc["ps_global_mean"] = global_mean

    # log cell exposure (train-period volume) -- a stable scale signal, leak-safe
    panel["log_total_events"] = np.log1p(panel["train_events"].fillna(0))
    return panel, enc


# Canonical model feature list (order matters for inference reproducibility).
FEATURE_COLUMNS = [
    # calendar / cyclical
    "time_block", "dow", "is_weekend", "month", "day", "peak_w",
    "block_sin", "block_cos", "dow_sin", "dow_cos", "month_sin", "month_cos",
    # spatial
    "cell_lat", "cell_lon",
    # autoregressive lags
    "lag1", "lag2", "lag7", "roll7_mean", "roll28_mean", "cell_roll_day",
    # cell-static priors / encodings
    "cell_blk_mean", "cell_blk_nonzero", "cell_sev", "cell_veh", "cell_jshare",
    "ps_target_enc", "log_total_events",
]


def build_features(panel: pd.DataFrame, cell_meta: pd.DataFrame,
                   verbose: bool = True) -> tuple[pd.DataFrame, list, dict]:
    """Full feature build. Returns (panel_with_features, feature_cols, encoders)."""
    log = (lambda *a: print("  [features]", *a)) if verbose else (lambda *a: None)
    train_mask = pd.to_datetime(panel["date"]) <= pd.Timestamp(config.TRAIN_END_DATE)
    log(f"train rows {int(train_mask.sum()):,} | test rows {int((~train_mask).sum()):,}")

    panel = add_calendar(panel)
    panel = add_lags(panel)
    # Stamp the split as a column so downstream steps derive the mask freshly
    # (robust to index resets from merges) rather than carrying a boolean mask.
    panel["split"] = np.where(
        pd.to_datetime(panel["date"]) <= pd.Timestamp(config.TRAIN_END_DATE),
        "train", "test",
    )
    panel, e1 = add_cell_priors(panel)
    panel, e2 = add_categorical_encoding(panel, cell_meta)

    encoders = {**e1, **e2}
    log(f"built {len(FEATURE_COLUMNS)} features")
    return panel, FEATURE_COLUMNS, encoders


if __name__ == "__main__":
    from src import ingest, impact, aggregate
    d = impact.add_event_impact(ingest.run(cache=True))
    panel, cmeta = aggregate.build_panel(d)
    panel, cols, enc = build_features(panel, cmeta)
    print(panel[cols].describe().T.round(3).to_string())
    print("\nNaNs in features:", int(panel[cols].isna().sum().sum()))
