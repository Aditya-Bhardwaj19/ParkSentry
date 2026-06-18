"""
Inference module -- deployable forecaster.

REASONING
=========
A model is only a prototype if it can score a NEW (place, day, time) the way it
would in production. This module reconstructs the exact feature vector the
model was trained on, for any (cell, date, time_block), from saved artifacts:

    best_model.joblib      -- the trained estimator
    feature_cols.json      -- the selected feature order
    encoders.joblib        -- leak-safe cell priors + police-station encoding
    cell_static.parquet    -- per-cell location & static descriptors
    recent_history.parquet -- last ~40 days of (cell,block,date) counts for lags

Crucially, the autoregressive lags are rebuilt CAUSALLY from history strictly
before the target timestamp -- the same discipline as training, so there is no
leakage and the forecaster works for the next day(s) beyond the data.

Example:
    from predict import Forecaster
    fc = Forecaster()
    fc.predict_cell("123_456", "2024-04-10", time_block=2)   # one slot
    fc.rank("2024-04-10", time_block=2, top=20)              # busiest cells
"""
from __future__ import annotations

import json
import os
import sys

import joblib
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config

ART = config.ARTIFACTS_DIR


class Forecaster:
    def __init__(self):
        self.model = joblib.load(os.path.join(ART, "best_model.joblib"))
        with open(os.path.join(ART, "feature_cols.json")) as f:
            self.features = json.load(f)
        self.enc = joblib.load(os.path.join(ART, "encoders.joblib"))
        self.cell_static = pd.read_parquet(os.path.join(ART, "cell_static.parquet")).set_index("cell")
        hist = pd.read_parquet(os.path.join(ART, "recent_history.parquet"))
        hist["date"] = pd.to_datetime(hist["date"])
        self.hist = hist
        # fast lookup: (cell, block) -> date-indexed count series
        self._series = {
            k: g.set_index("date")["viol_count"].sort_index()
            for k, g in hist.groupby(["cell", "time_block"])
        }
        self.cell_blk_hist = self.enc["cell_blk_hist"].set_index(["cell", "time_block"])
        self.cellstat = self.enc["cellstat"].set_index("cell")

    # ----------------------------------------------------------------- #
    def _lags(self, cell, date, block) -> dict:
        date = pd.Timestamp(date)
        s = self._series.get((cell, block))
        if s is None:
            return dict(lag1=0., lag2=0., lag7=0., roll7_mean=0., roll28_mean=0.)
        past = s[s.index < date]

        def at(days):
            d = date - pd.Timedelta(days=days)
            return float(s.get(d, 0.0))

        last7 = past[past.index >= date - pd.Timedelta(days=7)]
        last28 = past[past.index >= date - pd.Timedelta(days=28)]
        return dict(
            lag1=at(1), lag2=at(2), lag7=at(7),
            roll7_mean=float(last7.mean()) if len(last7) else 0.0,
            roll28_mean=float(last28.mean()) if len(last28) else 0.0,
        )

    def _cell_roll_day(self, cell, date, block) -> float:
        date = pd.Timestamp(date)
        h = self.hist[(self.hist["cell"] == cell)]
        h = h[(h["date"] < date) | ((h["date"] == date) & (h["time_block"] < block))]
        h = h.sort_values(["date", "time_block"]).tail(6)
        return float(h["viol_count"].mean()) if len(h) else 0.0

    def _row(self, cell, date, block) -> pd.DataFrame:
        date = pd.Timestamp(date)
        cs = self.cell_static.loc[cell] if cell in self.cell_static.index else None
        f = {}
        # calendar / cyclical
        f["time_block"] = block
        f["dow"] = date.dayofweek
        f["is_weekend"] = int(date.dayofweek >= 5)
        f["month"] = date.month
        f["day"] = date.day
        f["peak_w"] = config.TIME_BLOCKS[block][1]
        f["block_sin"] = np.sin(2 * np.pi * block / config.N_TIME_BLOCKS)
        f["block_cos"] = np.cos(2 * np.pi * block / config.N_TIME_BLOCKS)
        f["dow_sin"] = np.sin(2 * np.pi * date.dayofweek / 7)
        f["dow_cos"] = np.cos(2 * np.pi * date.dayofweek / 7)
        f["month_sin"] = np.sin(2 * np.pi * date.month / 12)
        f["month_cos"] = np.cos(2 * np.pi * date.month / 12)
        # spatial
        f["cell_lat"] = float(cs["cell_lat"]) if cs is not None else 0.0
        f["cell_lon"] = float(cs["cell_lon"]) if cs is not None else 0.0
        # lags
        f.update(self._lags(cell, date, block))
        f["cell_roll_day"] = self._cell_roll_day(cell, date, block)
        # priors
        if (cell, block) in self.cell_blk_hist.index:
            h = self.cell_blk_hist.loc[(cell, block)]
            f["cell_blk_mean"] = float(h["cell_blk_mean"])
            f["cell_blk_nonzero"] = float(h["cell_blk_nonzero"])
        else:
            f["cell_blk_mean"] = self.enc["global_mean"]
            f["cell_blk_nonzero"] = self.enc["global_nz"]
        if cell in self.cellstat.index:
            cst = self.cellstat.loc[cell]
            f["cell_sev"], f["cell_veh"], f["cell_jshare"] = (
                float(cst["cell_sev"]), float(cst["cell_veh"]), float(cst["cell_jshare"]))
        else:
            d = self.enc["cellstat_defaults"]
            f["cell_sev"], f["cell_veh"], f["cell_jshare"] = (
                d["cell_sev"], d["cell_veh"], d["cell_jshare"])
        f["ps_target_enc"] = float(cs["ps_target_enc"]) if cs is not None else self.enc["ps_global_mean"]
        f["log_total_events"] = float(cs["log_total_events"]) if cs is not None else 0.0
        return pd.DataFrame([f])[self.features].astype(float)

    # ----------------------------------------------------------------- #
    def predict_cell(self, cell: str, date, time_block: int) -> float:
        """Expected parking-violation count for one cell-date-block."""
        row = self._row(cell, date, time_block)
        return float(np.clip(self.model.predict(row)[0], 0, None))

    def rank(self, date, time_block: int, top: int = 20) -> pd.DataFrame:
        """Score every known cell for a date+block and return the busiest."""
        cells = self.cell_static.index.tolist()
        rows = pd.concat([self._row(c, date, time_block) for c in cells], ignore_index=True)
        pred = np.clip(self.model.predict(rows), 0, None)
        out = pd.DataFrame({
            "cell": cells,
            "pred_viol": pred.round(3),
            "cell_lat": self.cell_static.loc[cells, "cell_lat"].values,
            "cell_lon": self.cell_static.loc[cells, "cell_lon"].values,
            "police_station": self.cell_static.loc[cells, "dom_police_station"].values,
        }).sort_values("pred_viol", ascending=False).head(top).reset_index(drop=True)
        return out


if __name__ == "__main__":
    fc = Forecaster()
    busiest = fc.cell_static.sort_values("total_events", ascending=False).index[0]
    print("demo cell:", busiest)
    print("predicted (2024-04-10, morning peak):",
          round(fc.predict_cell(busiest, "2024-04-10", 2), 2))
    print("\nTop-10 predicted cells for 2024-04-10 morning peak:")
    print(fc.rank("2024-04-10", 2, top=10).to_string(index=False))
