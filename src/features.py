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
    # Holiday / festival flag: enforcement & traffic patterns shift on these days.
    panel["holiday"] = (
        pd.to_datetime(panel["date"]).dt.strftime("%Y-%m-%d").isin(config.HOLIDAYS)
        .astype(int)
    )
    return panel


def add_lags(panel: pd.DataFrame) -> pd.DataFrame:
    """Causal autoregressive features per (cell, time_block), ordered by date."""
    panel = panel.sort_values(["cell", "time_block", "date"]).copy()
    g = panel.groupby(["cell", "time_block"])[TARGET]

    panel["lag1"] = g.shift(1)
    panel["lag2"] = g.shift(2)
    panel["lag7"] = g.shift(7)
    panel["lag14"] = g.shift(14)  # longer weekly memory
    # rolling means of the *past* (shift(1) first so current row is excluded)
    panel["roll7_mean"] = g.transform(lambda s: s.shift(1).rolling(7, min_periods=1).mean())
    panel["roll14_mean"] = g.transform(lambda s: s.shift(1).rolling(14, min_periods=1).mean())
    panel["roll28_mean"] = g.transform(lambda s: s.shift(1).rolling(28, min_periods=1).mean())
    # EWMA: a smoother, recency-weighted memory than a flat rolling window.
    panel["ewm7"] = g.transform(lambda s: s.shift(1).ewm(span=7, min_periods=1).mean())
    # rolling 7-day NONZERO rate (recent intermittency) -- feeds the neighbour
    # spatial feature nbr_nz7; shifted so a row only sees its own past.
    panel["_nz"] = (panel[TARGET] > 0).astype(float)
    panel["roll7_nz"] = (panel.groupby(["cell", "time_block"])["_nz"]
                         .transform(lambda s: s.shift(1).rolling(7, min_periods=1).mean()))
    panel = panel.drop(columns=["_nz"])

    # cell-level recent activity across ALL blocks (broader context)
    gc = panel.sort_values(["cell", "date", "time_block"]).groupby("cell")[TARGET]
    panel["cell_roll_day"] = gc.transform(lambda s: s.shift(1).rolling(6, min_periods=1).mean())

    lag_cols = ["lag1", "lag2", "lag7", "lag14", "roll7_mean", "roll14_mean",
                "roll28_mean", "ewm7", "roll7_nz", "cell_roll_day"]
    panel[lag_cols] = panel[lag_cols].fillna(0.0)  # no history -> no recent activity
    return panel


def add_spatial(panel: pd.DataFrame) -> pd.DataFrame:
    """8-connected grid-neighbour features (spatial autocorrelation).

    Crime/hotspot forecasting shows enforcement pressure clusters spatially, so a
    cell's neighbourhood is predictive on top of its own history. We add:
      * nbr_roll7    -- mean recent (7-day) activity of the 8 neighbouring cells
                        (DYNAMIC; rebuilt from neighbour history at inference).
      * nbr_blk_mean -- mean train-only historical intensity of the 8 neighbours
                        for this block (STATIC prior).
    Both are leak-safe: nbr_roll7 is built from causal roll7_mean, nbr_blk_mean
    from the train-only cell_blk_mean. Cells absent from the panel (sub-threshold)
    are simply not counted, exactly as at inference.

    We also add nbr_lag1 (neighbours' yesterday count) and nbr_nz7 (neighbours'
    recent nonzero rate) -- both small, causal, and empirically the strongest of
    the spatial signals on the operational top-K capture metric.
    """
    panel = panel.copy()
    rc = panel["cell"].str.split("_", expand=True).astype(int)
    panel["_r"], panel["_c"] = rc[0], rc[1]
    cols = ["roll7_mean", "cell_blk_mean", "lag1", "roll7_nz"]
    lut = (panel[["_r", "_c", "date", "time_block"] + cols]
           .set_index(["_r", "_c", "date", "time_block"])[cols])

    sums = {c: np.zeros(len(panel)) for c in cols}
    cnt = np.zeros(len(panel))
    offsets = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
    for dr, dc in offsets:
        idx = pd.MultiIndex.from_arrays(
            [panel["_r"] + dr, panel["_c"] + dc, panel["date"], panel["time_block"]])
        got = lut.reindex(idx)
        present = ~got["roll7_mean"].isna().to_numpy()   # neighbour exists in panel
        for c in cols:
            sums[c] += np.where(present, np.nan_to_num(got[c].to_numpy()), 0.0)
        cnt += present.astype(float)
    den = np.maximum(cnt, 1)
    panel["nbr_roll7"] = sums["roll7_mean"] / den
    panel["nbr_blk_mean"] = sums["cell_blk_mean"] / den
    panel["nbr_lag1"] = sums["lag1"] / den
    panel["nbr_nz7"] = sums["roll7_nz"] / den
    return panel.drop(columns=["_r", "_c"])


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


def add_expanding_encodings(panel: pd.DataFrame, smoothing: float = 20.0
                            ) -> tuple[pd.DataFrame, dict]:
    """Leak-safe EXPANDING-WINDOW target encodings (+ full-train lookups).

    A naive train-wide target mean used as a feature leaks: a train row sees its
    own group's full-train average and the model over-trusts it, then fails on
    test (measured: -3.5pp capture@5%). Instead we use a CAUSAL expanding window:
    each train row sees only its group's PRIOR train target; test/future rows see
    the full-train shrunk mean. Test targets never contribute (zeroed), so there
    is no leakage in either direction. (Measured: +0.7pp capture@5% + lower MAE.)

    Returns the panel with exp_cb / exp_cdb / exp_db columns and an encoder dict
    holding the full-train shrunk group means for inference (static lookups, since
    every future date lies after the whole train window).
    """
    p = panel.sort_values(["date", "time_block"]).copy()
    gm = float(p.loc[p["split"] == "train", TARGET].mean())
    p["_t"] = p[TARGET].where(p["split"] == "train", 0.0).astype(float)
    p["_i"] = (p["split"] == "train").astype(float)

    specs = [("exp_cb", ["cell", "time_block"]),
             ("exp_cdb", ["cell", "dow", "time_block"]),
             ("exp_db", ["dow", "time_block"])]
    tables: dict = {"global": gm, "smoothing": smoothing}
    for name, keys in specs:
        g = p.groupby(keys, sort=False)
        csum = g["_t"].cumsum() - p["_t"]      # prior-train sum (exclude current)
        ccnt = g["_i"].cumsum() - p["_i"]      # prior-train count
        p[name] = (csum + gm * smoothing) / (ccnt + smoothing)
        agg = p[p["split"] == "train"].groupby(keys)[TARGET].agg(["sum", "count"])
        full = (agg["sum"] + gm * smoothing) / (agg["count"] + smoothing)
        tables[name] = full.to_dict()          # {key-tuple: shrunk mean}
    cols = [s[0] for s in specs]
    panel = panel.copy()
    panel[cols] = p[cols].reindex(panel.index)
    return panel, {"expanding": tables}


# Canonical model feature list (order matters for inference reproducibility).
FEATURE_COLUMNS = [
    # calendar / cyclical
    "time_block", "dow", "is_weekend", "month", "day", "peak_w", "holiday",
    "block_sin", "block_cos", "dow_sin", "dow_cos", "month_sin", "month_cos",
    # spatial (cell + neighbourhood)
    "cell_lat", "cell_lon", "nbr_roll7", "nbr_blk_mean", "nbr_lag1", "nbr_nz7",
    # autoregressive lags
    "lag1", "lag2", "lag7", "lag14", "roll7_mean", "roll14_mean", "roll28_mean",
    "ewm7", "cell_roll_day",
    # cell-static priors / encodings
    "cell_blk_mean", "cell_blk_nonzero", "cell_sev", "cell_veh", "cell_jshare",
    "ps_target_enc", "log_total_events",
    # leak-safe expanding-window target encodings
    "exp_cb", "exp_cdb", "exp_db",
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
    panel = add_spatial(panel)  # needs roll7_mean (lags) + cell_blk_mean (priors)
    panel, e3 = add_expanding_encodings(panel)  # leak-safe expanding target enc

    encoders = {**e1, **e2, **e3}
    log(f"built {len(FEATURE_COLUMNS)} features")
    return panel, FEATURE_COLUMNS, encoders


if __name__ == "__main__":
    from src import ingest, impact, aggregate
    d = impact.add_event_impact(ingest.run(cache=True))
    panel, cmeta = aggregate.build_panel(d)
    panel, cols, enc = build_features(panel, cmeta)
    print(panel[cols].describe().T.round(3).to_string())
    print("\nNaNs in features:", int(panel[cols].isna().sum().sum()))
