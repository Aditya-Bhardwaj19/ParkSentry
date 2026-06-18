"""
Step 2 -- Congestion Impact Score (per event).

REASONING
=========
Theme 1 asks us to *quantify the impact on traffic flow*. The honest problem:
this dataset has no traffic-flow speeds, volumes, or delay measurements. So we
cannot *measure* congestion impact -- we must *estimate* it from the
attributes that domain knowledge says drive obstruction. We make that estimate
transparent and calibratable rather than pretending it is ground truth.

Per-event impact  =  severity(violation type)
                   x vehicle_footprint(vehicle type)
                   x peak_multiplier(time block)
                   x junction_multiplier(at a junction?)

Each factor is justified:
  * severity   -- blocking a main road obstructs more lanes than a footpath.
  * footprint  -- a parked lorry occupies far more carriageway than a scooter.
  * peak       -- the same blockage causes more delay when demand is high.
  * junction   -- a blockage at a signalled junction back-propagates across
                  several approaches, not just one road.

This is a multiplicative model because the factors compound: a lorry on a main
road at evening peak by a junction is *much* worse than the sum of its parts.

HOW TO CALIBRATE WITH REAL DATA (documented for production):
    If/when junction-level flow or delay data is available, fit the weights by
    regressing observed delay on these factors -- the structure stays, only the
    constants change. The code is written so only config.py needs editing.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402


def _severity_of_tokens(tokens: list[str]) -> float:
    """Max severity across the violation tokens on a single citation.

    We take the MAX (not the sum): the worst obstruction on the record defines
    how badly that parked vehicle blocks flow; stacking 'WRONG PARKING' +
    'NO PARKING' does not double the physical blockage.
    """
    if tokens is None or len(tokens) == 0:
        return config.DEFAULT_SEVERITY
    return max(config.VIOLATION_SEVERITY.get(t, config.DEFAULT_SEVERITY) for t in tokens)


def add_event_impact(df: pd.DataFrame) -> pd.DataFrame:
    """Add per-event impact factor columns and the composite `impact_score`."""
    df = df.copy()

    df["severity_w"] = df["tokens"].map(_severity_of_tokens)
    df["vehicle_w"] = (
        df["vehicle_type_clean"].map(config.VEHICLE_WEIGHT).fillna(config.DEFAULT_VEHICLE_WEIGHT)
    )
    df["peak_w"] = df["time_block"].map(lambda b: config.TIME_BLOCKS[b][1])
    df["junction_w"] = np.where(df["is_junction"] == 1, config.JUNCTION_MULTIPLIER, 1.0)

    df["impact_score"] = (
        df["severity_w"] * df["vehicle_w"] * df["peak_w"] * df["junction_w"]
    )
    return df


def summarize(df: pd.DataFrame) -> pd.Series:
    """Quick diagnostic summary of the impact distribution."""
    return df["impact_score"].describe()


if __name__ == "__main__":
    from src import ingest
    d = ingest.run(nrows=20000, cache=False)
    d = add_event_impact(d)
    print(summarize(d))
    print(d[["severity_w", "vehicle_w", "peak_w", "junction_w", "impact_score"]].head())
