"""
Central configuration for the ViolationProto pipeline (Theme 1).

Everything that a reviewer might want to tune -- paths, the spatial grid
resolution, the time-block definitions, and the heuristic weights that drive
the Congestion Impact Score -- lives here so the rest of the codebase stays
declarative and the assumptions are auditable in one place.

WHY a single config:
    The Congestion Impact Score is a *heuristic* (we have no ground-truth
    traffic-flow speeds in this dataset). Keeping its weights in one visible,
    documented place is the honest way to ship a heuristic: the assumptions
    are explicit and a domain expert (or real flow data) can recalibrate them
    without touching pipeline logic.
"""
from __future__ import annotations

import os

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(PROJECT_DIR)

# Source dataset lives in the parent directory (Theme 1 instruction).
RAW_CSV = os.path.join(PARENT_DIR, "jan to may police violation_anonymized791b166.csv")

ARTIFACTS_DIR = os.path.join(PROJECT_DIR, "artifacts")   # models, encoders, metrics
OUTPUTS_DIR = os.path.join(PROJECT_DIR, "outputs")       # hotspot rankings, maps, plots
DATA_DIR = os.path.join(PROJECT_DIR, "data")             # cached intermediate parquet/csv

for _d in (ARTIFACTS_DIR, OUTPUTS_DIR, DATA_DIR):
    os.makedirs(_d, exist_ok=True)

# --------------------------------------------------------------------------- #
# Geographic sanity bounds (Bengaluru metropolitan area)
# Coordinates outside this box are GPS errors / placeholder zeros and are dropped.
# --------------------------------------------------------------------------- #
BENGALURU_BBOX = {
    "lat_min": 12.70, "lat_max": 13.25,
    "lon_min": 77.30, "lon_max": 77.85,
}

# Minimum total events for a cell to enter the modelling panel.
# Violations are highly concentrated: cells with >=20 events cover ~93% of all
# events while being only ~28% of cells. Modelling the long tail of 1-2 event
# cells adds millions of structural-zero rows and little enforcement value.
MIN_CELL_EVENTS = 20

# --------------------------------------------------------------------------- #
# Spatial grid
#   0.0015 deg ~= 165 m at Bengaluru's latitude. A ~150 m cell is a sensible
#   enforcement-zone granularity: small enough to point a patrol at a stretch
#   of road, large enough to pool a meaningful event count per time-block.
# --------------------------------------------------------------------------- #
GRID_SIZE_DEG = 0.0015

# --------------------------------------------------------------------------- #
# Time blocks (4-hour bins). Index -> (label, peak multiplier).
#   Peak multiplier encodes how much a violation during that block hurts flow:
#   a blocked lane at 18:00 is far costlier than at 03:00.
# --------------------------------------------------------------------------- #
TIME_BLOCKS = {
    0: ("Late Night (00-04)", 0.6),
    1: ("Early Morning (04-08)", 0.9),
    2: ("Morning Peak (08-12)", 1.5),
    3: ("Afternoon (12-16)", 1.1),
    4: ("Evening Peak (16-20)", 1.5),
    5: ("Night (20-24)", 0.8),
}
N_TIME_BLOCKS = len(TIME_BLOCKS)


def hour_to_block(hour: int) -> int:
    """Map an hour (0-23, local time) to its 4-hour block index."""
    return int(hour) // 4


# --------------------------------------------------------------------------- #
# Local-time handling
#   created_datetime is stored in UTC (+00). Bengaluru is UTC+5:30. We convert
#   to local time so that "Morning Peak" actually means the local morning.
# --------------------------------------------------------------------------- #
LOCAL_TZ = "Asia/Kolkata"

# Indian public holidays / major festivals within the data window (Nov-2023..
# Apr-2024). Used as a calendar feature -- enforcement-relevant traffic patterns
# shift on these days. Extend this set as the deployment window grows.
HOLIDAYS = {
    "2023-11-12", "2023-11-13", "2023-11-14", "2023-11-27",  # Diwali cluster · Guru Nanak
    "2023-12-25",                                            # Christmas
    "2024-01-01", "2024-01-15", "2024-01-26",                # New Year · Sankranti · Republic Day
    "2024-03-08", "2024-03-25", "2024-03-29",                # Shivaratri · Holi · Good Friday
    "2024-04-09",                                            # Ugadi
}

# --------------------------------------------------------------------------- #
# Congestion-impact heuristic weights (documented assumptions)
# --------------------------------------------------------------------------- #

# Severity weight = how much this violation TYPE obstructs carriageway flow.
# Blocking a main road / double parking is worse than a footpath encroachment.
VIOLATION_SEVERITY = {
    "PARKING IN A MAIN ROAD": 1.00,
    "DOUBLE PARKING": 1.00,
    "PARKING NEAR ROAD CROSSING": 0.90,
    "PARKING NEAR TRAFFIC LIGHT OR ZEBRA CROSS": 0.90,
    "PARKING OPPOSITE TO ANOTHER PARKED VEHICLE": 0.75,
    "WRONG PARKING": 0.70,
    "NO PARKING": 0.60,
    "PARKING NEAR BUSTOP/SCHOOL/HOSPITAL ETC": 0.60,
    "PARKING OTHER THAN BUS STOP": 0.50,
    "PARKING ON FOOTPATH": 0.40,  # blocks pedestrians more than carriageway
}
DEFAULT_SEVERITY = 0.50  # any other parking-ish token

# Vehicle footprint weight = physical obstruction of a parked unit.
VEHICLE_WEIGHT = {
    "HGV": 1.5, "LORRY/GOODS VEHICLE": 1.5, "BUS (BMTC/KSRTC)": 1.5,
    "PRIVATE BUS": 1.5, "H T V": 1.5,
    "LGV": 1.2, "MAXI-CAB": 1.2, "TEMPO": 1.2, "VAN": 1.2,
    "GOODS AUTO": 1.2, "JEEP": 1.2, "LORRY": 1.2,
    "CAR": 1.0, "PASSENGER AUTO": 1.0,
    "MOTOR CYCLE": 0.6, "SCOOTER": 0.6, "MOPED": 0.6,
}
DEFAULT_VEHICLE_WEIGHT = 1.0

# Junction proximity multiplier: a violation at a signalled junction propagates
# congestion across multiple approaches, so weight it up.
JUNCTION_MULTIPLIER = 1.30
NO_JUNCTION_TOKENS = {"No Junction", "", "NULL", "nan"}

# --------------------------------------------------------------------------- #
# Modeling
# --------------------------------------------------------------------------- #
# Temporal split: train on the earlier portion, test on the later portion.
# This simulates real deployment (predict the future from the past) and is the
# only honest way to evaluate a forecasting model -- a random split would leak
# future information into training.
TRAIN_END_DATE = "2024-02-29"   # train: <= this date ; test: > this date
RANDOM_STATE = 42

# Days of (cell, date, block) history the inference store retains so the
# forecaster can rebuild lag/rolling features. Must exceed the longest lookback
# (roll28_mean = 28 days) with margin so the window is never truncated relative
# to training.
HISTORY_RETENTION_DAYS = 70

# Hotspot label: a cell-timeblock is a "hotspot" if its violation count is in
# the top quantile. Used for the secondary classification framing.
HOTSPOT_QUANTILE = 0.90

# --------------------------------------------------------------------------- #
# DBSCAN hotspot clustering (haversine metric, radians)
# --------------------------------------------------------------------------- #
EARTH_RADIUS_M = 6_371_000.0
DBSCAN_EPS_M = 250.0           # merge cells within ~250 m into one enforcement zone
DBSCAN_MIN_SAMPLES = 3         # min distinct cells to form a multi-cell hotspot

# Top-K hotspots to surface in the enforcement priority report.
TOP_K_HOTSPOTS = 50
