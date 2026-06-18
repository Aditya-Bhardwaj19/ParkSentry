"""
Step 1 -- Ingestion & cleaning.

REASONING
=========
Raw enforcement logs are messy: violation types are JSON-encoded arrays,
timestamps are UTC strings, coordinates contain placeholder zeros, and a
chunk of records are flagged 'rejected'/'duplicate'. Before any modelling we
turn this into a tidy one-row-per-event table where every field means exactly
what it says.

Key cleaning decisions (each is a judgement call, so each is documented):

  * Parking filter -- Theme 1 is specifically about *parking*-induced
    congestion. ~95% of rows are already parking violations; we keep only rows
    whose violation tokens are parking-related and drop the handful of
    helmet/mobile-phone/etc. records so the model isn't diluted by off-theme
    noise.

  * Coordinate validation -- (lat, lon) must be numeric and inside the
    Bengaluru bounding box. Zeros and out-of-box GPS errors are dropped; a
    hotspot map built on bad coordinates is worse than useless.

  * Local time -- created_datetime is UTC. Congestion is a *local* phenomenon
    ("evening peak" = local 16-20h), so we convert to Asia/Kolkata before
    deriving the hour / time-block. Skipping this would shift every event 5.5h
    and put the evening peak at midnight.

  * Validation status -- we drop only rows explicitly 'rejected' or
    'duplicate' (confirmed non-violations / double counts). NULL status (~42%)
    means "not yet reviewed", not "invalid", so we keep it -- dropping it would
    throw away nearly half the genuine signal.

  * De-duplication -- drop exact duplicate ids.
"""
from __future__ import annotations

import ast
import sys
import os

import numpy as np
import pandas as pd

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402


# Tokens we treat as parking violations (substring 'PARK' also caught below).
_PARKING_TOKENS = set(config.VIOLATION_SEVERITY.keys())

# Statuses that mean "this was not a real, countable violation".
_DROP_STATUSES = {"rejected", "duplicate"}


def _parse_tokens(raw) -> list[str]:
    """Parse a violation_type / offence cell into a clean list of upper tokens.

    The column is usually a JSON-ish array string like
    '["WRONG PARKING","NO PARKING"]'. We fall back gracefully to a single
    token if it is not parseable.
    """
    if raw is None or (isinstance(raw, float) and np.isnan(raw)):
        return []
    s = str(raw).strip()
    if s in ("", "NULL", "nan", "[]"):
        return []
    try:
        val = ast.literal_eval(s)
        if isinstance(val, (list, tuple)):
            return [str(t).strip().upper() for t in val if str(t).strip()]
        return [str(val).strip().upper()]
    except (ValueError, SyntaxError):
        return [s.upper()]


def _is_parking(tokens: list[str]) -> bool:
    """A row is in-scope if any token is a known parking token or mentions PARK."""
    for t in tokens:
        if t in _PARKING_TOKENS or "PARK" in t:
            return True
    return False


def load_raw(path: str | None = None, nrows: int | None = None) -> pd.DataFrame:
    """Load the raw CSV with NULL handling and string dtypes (we parse later)."""
    path = path or config.RAW_CSV
    usecols = [
        "id", "latitude", "longitude", "location", "vehicle_type",
        "updated_vehicle_type", "violation_type", "offence_code",
        "created_datetime", "police_station", "center_code",
        "junction_name", "validation_status", "device_id",
    ]
    df = pd.read_csv(
        path, usecols=usecols, dtype=str,
        na_values=["NULL", ""], keep_default_na=True, nrows=nrows,
    )
    return df


def clean(df: pd.DataFrame, verbose: bool = True) -> pd.DataFrame:
    """Run the full cleaning pipeline; returns one tidy row per parking event."""
    n0 = len(df)
    log = (lambda *a: print("  [ingest]", *a)) if verbose else (lambda *a: None)

    # --- 1. de-duplicate exact ids -------------------------------------- #
    df = df.drop_duplicates(subset="id").copy()
    log(f"dropped {n0 - len(df):,} duplicate ids -> {len(df):,}")

    # --- 2. parse violation tokens + parking filter --------------------- #
    df["tokens"] = df["violation_type"].map(_parse_tokens)
    mask_parking = df["tokens"].map(_is_parking)
    df = df[mask_parking].copy()
    log(f"kept {len(df):,} parking rows (dropped {int((~mask_parking).sum()):,} off-theme)")
    df["n_violations"] = df["tokens"].map(len)

    # --- 3. drop confirmed non-violations ------------------------------- #
    status = df["validation_status"].fillna("unreviewed").str.lower()
    keep = ~status.isin(_DROP_STATUSES)
    df = df[keep].copy()
    log(f"dropped {int((~keep).sum()):,} rejected/duplicate-status rows -> {len(df):,}")

    # --- 4. coordinate validation --------------------------------------- #
    df["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")
    df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")
    bb = config.BENGALURU_BBOX
    geo_ok = (
        df["latitude"].between(bb["lat_min"], bb["lat_max"])
        & df["longitude"].between(bb["lon_min"], bb["lon_max"])
    )
    df = df[geo_ok].copy()
    log(f"dropped {int((~geo_ok).sum()):,} bad/out-of-box coords -> {len(df):,}")

    # --- 5. timestamp -> local time + calendar parts -------------------- #
    ts = pd.to_datetime(df["created_datetime"], errors="coerce", utc=True)
    local = ts.dt.tz_convert(config.LOCAL_TZ)
    df = df[local.notna()].copy()
    local = local[local.notna()]
    df["dt_local"] = local
    df["date"] = local.dt.date.astype("datetime64[ns]")
    df["hour"] = local.dt.hour.astype(int)
    df["time_block"] = df["hour"].map(config.hour_to_block).astype(int)
    df["dow"] = local.dt.dayofweek.astype(int)            # 0=Mon
    df["is_weekend"] = (df["dow"] >= 5).astype(int)
    df["month"] = local.dt.month.astype(int)
    log(f"parsed timestamps; range {df['date'].min().date()} -> {df['date'].max().date()}")

    # --- 6. vehicle type: prefer corrected value if present ------------- #
    df["vehicle_type_clean"] = (
        df["updated_vehicle_type"].fillna(df["vehicle_type"]).fillna("UNKNOWN")
        .str.upper().str.strip()
    )

    # --- 7. junction flag ----------------------------------------------- #
    jn = df["junction_name"].fillna("No Junction").astype(str)
    df["is_junction"] = (~jn.isin(config.NO_JUNCTION_TOKENS)).astype(int)
    df["junction_name"] = jn

    # --- 8. tidy categoricals ------------------------------------------- #
    df["police_station"] = df["police_station"].fillna("UNKNOWN").str.strip()
    df["center_code"] = df["center_code"].fillna("UNKNOWN").astype(str)

    # --- 9. final column set -------------------------------------------- #
    keep_cols = [
        "id", "latitude", "longitude", "location", "vehicle_type_clean",
        "tokens", "n_violations", "police_station", "center_code",
        "junction_name", "is_junction", "validation_status",
        "dt_local", "date", "hour", "time_block", "dow", "is_weekend", "month",
    ]
    df = df[keep_cols].reset_index(drop=True)
    log(f"FINAL clean rows: {len(df):,} ({len(df)/max(n0,1)*100:.1f}% of raw)")
    return df


def run(path: str | None = None, nrows: int | None = None, cache: bool = True) -> pd.DataFrame:
    """Load + clean, with an optional parquet cache for fast re-runs."""
    cache_fp = os.path.join(config.DATA_DIR, "clean_events.parquet")
    if cache and nrows is None and os.path.exists(cache_fp):
        print("  [ingest] loading cached clean_events.parquet")
        df = pd.read_parquet(cache_fp)
        # parquet round-trips the list column as a numpy ndarray; normalise back
        # to Python lists so cached and fresh runs are byte-for-byte equivalent.
        df["tokens"] = df["tokens"].map(lambda t: list(t) if t is not None else [])
        return df
    df = clean(load_raw(path, nrows=nrows))
    if cache and nrows is None:
        # tokens is a list column -> parquet handles it fine via pyarrow;
        # fall back to dropping it for the cache if the engine complains.
        try:
            df.to_parquet(cache_fp, index=False)
        except Exception as e:  # pragma: no cover
            print(f"  [ingest] parquet cache skipped ({e})")
    return df


if __name__ == "__main__":
    out = run()
    print(out.head())
    print(out.dtypes)
