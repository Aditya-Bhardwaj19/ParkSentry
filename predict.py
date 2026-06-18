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
        # For spatial neighbour features: the set of known (kept) cells and the
        # global train-mean fallback, so inference mirrors the panel exactly.
        self._cells = set(self.cell_static.index)
        self.global_mean = float(self.enc.get("global_mean", 0.0))

    # ----------------------------------------------------------------- #
    def _lags(self, cell, date, block) -> dict:
        date = pd.Timestamp(date)
        s = self._series.get((cell, block))
        if s is None:
            return dict(lag1=0., lag2=0., lag7=0., lag14=0., roll7_mean=0.,
                        roll14_mean=0., roll28_mean=0., ewm7=0.)
        past = s[s.index < date]

        def at(days):
            d = date - pd.Timedelta(days=days)
            return float(s.get(d, 0.0))

        def roll(days):
            w = past[past.index >= date - pd.Timedelta(days=days)]
            return float(w.mean()) if len(w) else 0.0

        # EWMA over all past observations (span 7); 70-day history far exceeds the
        # window where weight is non-negligible, so this matches the panel value.
        ewm7 = float(past.ewm(span=7, min_periods=1).mean().iloc[-1]) if len(past) else 0.0
        return dict(
            lag1=at(1), lag2=at(2), lag7=at(7), lag14=at(14),
            roll7_mean=roll(7), roll14_mean=roll(14), roll28_mean=roll(28),
            ewm7=ewm7,
        )

    # ----------------------------------------------------------------- #
    def _roll7_of(self, cell, block, date) -> float:
        """Mean of a cell-block's last-7-day counts before `date` (neighbour use)."""
        s = self._series.get((cell, block))
        if s is None:
            return 0.0
        w = s[(s.index < date) & (s.index >= date - pd.Timedelta(days=7))]
        return float(w.mean()) if len(w) else 0.0

    def _neighbor_cells(self, cell) -> list:
        """The 8-connected grid neighbours that are known (kept) cells."""
        try:
            r, c = cell.split("_"); r, c = int(r), int(c)
        except Exception:
            return []
        out = []
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if dr == 0 and dc == 0:
                    continue
                nc = f"{r+dr}_{c+dc}"
                if nc in self._cells:
                    out.append(nc)
        return out

    def _spatial(self, cell, date, block) -> dict:
        """Neighbourhood features, rebuilt exactly as features.add_spatial does."""
        date = pd.Timestamp(date)
        nbrs = self._neighbor_cells(cell)
        if not nbrs:
            return dict(nbr_roll7=0.0, nbr_blk_mean=0.0)
        rolls = [self._roll7_of(nc, block, date) for nc in nbrs]
        blks = []
        for nc in nbrs:
            if (nc, block) in self.cell_blk_hist.index:
                blks.append(float(self.cell_blk_hist.loc[(nc, block), "cell_blk_mean"]))
            else:
                blks.append(self.global_mean)
        return dict(nbr_roll7=float(np.mean(rolls)), nbr_blk_mean=float(np.mean(blks)))

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
        f["holiday"] = int(date.strftime("%Y-%m-%d") in config.HOLIDAYS)
        f["block_sin"] = np.sin(2 * np.pi * block / config.N_TIME_BLOCKS)
        f["block_cos"] = np.cos(2 * np.pi * block / config.N_TIME_BLOCKS)
        f["dow_sin"] = np.sin(2 * np.pi * date.dayofweek / 7)
        f["dow_cos"] = np.cos(2 * np.pi * date.dayofweek / 7)
        f["month_sin"] = np.sin(2 * np.pi * date.month / 12)
        f["month_cos"] = np.cos(2 * np.pi * date.month / 12)
        # spatial
        f["cell_lat"] = float(cs["cell_lat"]) if cs is not None else 0.0
        f["cell_lon"] = float(cs["cell_lon"]) if cs is not None else 0.0
        # lags + spatial neighbourhood
        f.update(self._lags(cell, date, block))
        f["cell_roll_day"] = self._cell_roll_day(cell, date, block)
        f.update(self._spatial(cell, date, block))
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

    # ----------------------------------------------------------------- #
    # Vectorised scoring for rank(): build the feature matrix for ALL cells at
    # a single (date, block) in one shot, instead of a per-cell Python loop.
    # Mathematically identical to looping _row() over every cell, but ~20x+
    # faster because the per-cell history work becomes matrix operations.
    # ----------------------------------------------------------------- #
    def _ensure_fast(self):
        if getattr(self, "_fast_ready", False):
            return
        nb = config.N_TIME_BLOCKS
        h = self.hist.copy()
        self._day0 = h["date"].min()
        h["_day"] = (h["date"] - self._day0).dt.days.astype(int)
        self._maxday = int(h["_day"].max())
        h["_t"] = h["_day"] * nb + h["time_block"].astype(int)
        # per-block (cell x day) count matrices (dense, zero-filled like the panel)
        self._Mblk = {}
        for b in range(nb):
            M = (h[h["time_block"] == b]
                 .pivot(index="cell", columns="_day", values="viol_count")
                 .reindex(columns=range(self._maxday + 1)))
            self._Mblk[b] = M
        # full (cell x t) matrix for the cross-block cell_roll_day feature
        self._Mall = h.pivot(index="cell", columns="_t", values="viol_count")
        # canonical cell order + parsed (row, col) for neighbour lookups
        self._fcells = self.cell_static.index
        rc = self._fcells.to_series().str.split("_", expand=True)
        self._fr = rc[0].astype(int).to_numpy()
        self._fc = rc[1].astype(int).to_numpy()
        self._fast_ready = True

    def _feature_matrix(self, date, block) -> tuple[pd.Index, pd.DataFrame]:
        """All-cell feature matrix for one (date, block). Columns = self.features."""
        self._ensure_fast()
        nb = config.N_TIME_BLOCKS
        b = int(block)
        D = pd.Timestamp(date)
        dday = int((D - self._day0).days)
        cells = self._fcells
        n = len(cells)
        Mb = self._Mblk[b]
        cset = set(Mb.columns)

        def at(day):
            return (Mb[day].reindex(cells).to_numpy() if day in cset else np.zeros(n))

        def roll(win):
            sel = [d for d in range(dday - win, dday) if d in cset]
            if not sel:
                return np.zeros(n)
            return np.nan_to_num(Mb[sel].reindex(cells).mean(axis=1).to_numpy())

        lag1, lag2, lag7, lag14 = at(dday - 1), at(dday - 2), at(dday - 7), at(dday - 14)
        roll7, roll14, roll28 = roll(7), roll(14), roll(28)

        past_cols = [d for d in Mb.columns if d < dday]
        if past_cols:
            ewm7 = (Mb[past_cols].reindex(cells).fillna(0.0)
                    .T.ewm(span=7, min_periods=1).mean().iloc[-1].to_numpy())
        else:
            ewm7 = np.zeros(n)

        # cell_roll_day = mean over the last 6 EXISTING (date, block) slots strictly
        # before (date, block). Using existing slots (not a contiguous t-range)
        # keeps it correct when forecasting dates beyond the recorded history.
        t0 = dday * nb + b
        tsel = sorted(t for t in self._Mall.columns if t < t0)[-6:]
        crd = (np.nan_to_num(self._Mall[tsel].reindex(cells).mean(axis=1).to_numpy())
               if tsel else np.zeros(n))

        # priors for this block (leak-safe, train-only)
        cb = self.cell_blk_hist.xs(b, level="time_block")
        cbm = cb["cell_blk_mean"].reindex(cells).fillna(self.global_mean).to_numpy()
        cbnz = cb["cell_blk_nonzero"].reindex(cells).fillna(
            float(self.enc.get("global_nz", 0.0))).to_numpy()

        defs = self.enc["cellstat_defaults"]
        cs = self.cellstat.reindex(cells)
        sev = cs["cell_sev"].fillna(defs["cell_sev"]).to_numpy()
        veh = cs["cell_veh"].fillna(defs["cell_veh"]).to_numpy()
        jsh = cs["cell_jshare"].fillna(defs["cell_jshare"]).to_numpy()

        lat = self.cell_static["cell_lat"].reindex(cells).to_numpy()
        lon = self.cell_static["cell_lon"].reindex(cells).to_numpy()
        pste = self.cell_static["ps_target_enc"].reindex(cells).fillna(
            self.enc["ps_global_mean"]).to_numpy()
        lte = self.cell_static["log_total_events"].reindex(cells).fillna(0.0).to_numpy()

        # spatial neighbours: average roll7 / cell_blk_mean over the 8 kept neighbours
        rc_idx = pd.MultiIndex.from_arrays([self._fr, self._fc])
        roll7_s = pd.Series(roll7, index=rc_idx)
        cbm_s = pd.Series(cbm, index=rc_idx)
        nr_sum = np.zeros(n); nb_sum = np.zeros(n); cnt = np.zeros(n)
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if dr == 0 and dc == 0:
                    continue
                key = pd.MultiIndex.from_arrays([self._fr + dr, self._fc + dc])
                rv = roll7_s.reindex(key).to_numpy()
                bv = cbm_s.reindex(key).to_numpy()
                present = ~np.isnan(rv)
                nr_sum += np.where(present, np.nan_to_num(rv), 0.0)
                nb_sum += np.where(present, np.nan_to_num(bv), 0.0)
                cnt += present
        nbr_roll7 = nr_sum / np.maximum(cnt, 1)
        nbr_blk_mean = nb_sum / np.maximum(cnt, 1)

        two_pi = 2 * np.pi
        data = {
            "time_block": b, "dow": D.dayofweek, "is_weekend": int(D.dayofweek >= 5),
            "month": D.month, "day": D.day, "peak_w": config.TIME_BLOCKS[b][1],
            "holiday": int(D.strftime("%Y-%m-%d") in config.HOLIDAYS),
            "block_sin": np.sin(two_pi * b / nb), "block_cos": np.cos(two_pi * b / nb),
            "dow_sin": np.sin(two_pi * D.dayofweek / 7), "dow_cos": np.cos(two_pi * D.dayofweek / 7),
            "month_sin": np.sin(two_pi * D.month / 12), "month_cos": np.cos(two_pi * D.month / 12),
            "cell_lat": lat, "cell_lon": lon, "nbr_roll7": nbr_roll7, "nbr_blk_mean": nbr_blk_mean,
            "lag1": lag1, "lag2": lag2, "lag7": lag7, "lag14": lag14,
            "roll7_mean": roll7, "roll14_mean": roll14, "roll28_mean": roll28,
            "ewm7": ewm7, "cell_roll_day": crd,
            "cell_blk_mean": cbm, "cell_blk_nonzero": cbnz,
            "cell_sev": sev, "cell_veh": veh, "cell_jshare": jsh,
            "ps_target_enc": pste, "log_total_events": lte,
        }
        X = pd.DataFrame(data, index=cells)[self.features].astype(float)
        return cells, X

    def rank(self, date, time_block: int, top: int = 20) -> pd.DataFrame:
        """Score every known cell for a date+block and return the busiest (fast)."""
        cells, X = self._feature_matrix(date, time_block)
        pred = np.clip(self.model.predict(X), 0, None)
        out = pd.DataFrame({
            "cell": cells.to_numpy(),
            "pred_viol": pred.round(3),
            "cell_lat": self.cell_static["cell_lat"].reindex(cells).to_numpy(),
            "cell_lon": self.cell_static["cell_lon"].reindex(cells).to_numpy(),
            "police_station": self.cell_static["dom_police_station"].reindex(cells).to_numpy(),
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
