"""
ViolationProto -- Python ML/data service (FastAPI).

Role in the stack:
    Browser (React) -> Node/Express gateway -> *this* FastAPI service.

    The Node gateway owns the browser-facing concerns (serving the SPA, minting
    the Mappls map token so the client secret never reaches the browser, and
    proxying /api/* here). This service owns the *data and the model*: it reads
    the pipeline's output artifacts and wraps the deployable `predict.Forecaster`
    so the React app can score any (cell, date, time-block) on demand.

    Nothing here is web-framework-specific to the ML; we simply expose the
    existing, framework-agnostic Python (config.py + predict.py + the outputs/
    CSVs) over HTTP.

Run:
    uvicorn api.main:app --port 8000 --reload     # from the webapp/ directory
"""
from __future__ import annotations

import json
import os
import sys
import threading

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

# --------------------------------------------------------------------------- #
# Make the existing ViolationProto Python package importable.
# webapp/api/main.py -> webapp/api -> webapp -> ViolationProto (project root)
# --------------------------------------------------------------------------- #
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import config  # noqa: E402  (path set above)

OUT, ART = config.OUTPUTS_DIR, config.ARTIFACTS_DIR
PLOTS = os.path.join(OUT, "plots")

app = FastAPI(title="ParkSentry API",
              description="Parking-congestion intelligence: hotspots, model, forecaster.",
              version="1.0.0")


# --------------------------------------------------------------------------- #
# Cached data loads (read once; the CSVs are static pipeline outputs)
# --------------------------------------------------------------------------- #
def _records(df: pd.DataFrame) -> list[dict]:
    """DataFrame -> JSON-safe list of dicts (NaN/inf -> null)."""
    clean = df.replace({np.nan: None, np.inf: None, -np.inf: None})
    return clean.to_dict(orient="records")


_cache: dict[str, object] = {}
_fc_lock = threading.Lock()
_forecaster = None  # lazily loaded (best_model.joblib is large)


def _hotspots() -> pd.DataFrame:
    if "hs" not in _cache:
        _cache["hs"] = pd.read_csv(os.path.join(OUT, "cell_priority_ranked.csv"))
    return _cache["hs"]


def _zones() -> pd.DataFrame:
    if "zones" not in _cache:
        _cache["zones"] = pd.read_csv(os.path.join(OUT, "hotspot_zones.csv"))
    return _cache["zones"]


def _comparison() -> pd.DataFrame:
    if "comp" not in _cache:
        _cache["comp"] = pd.read_csv(os.path.join(ART, "model_comparison.csv"))
    return _cache["comp"]


def _summary() -> dict:
    if "summary" not in _cache:
        with open(os.path.join(OUT, "run_summary.json")) as f:
            _cache["summary"] = json.load(f)
    return _cache["summary"]


def _get_forecaster():
    global _forecaster
    if _forecaster is None:
        with _fc_lock:
            if _forecaster is None:
                from predict import Forecaster
                _forecaster = Forecaster()
    return _forecaster


def _require_outputs():
    if not os.path.exists(os.path.join(OUT, "cell_priority_ranked.csv")):
        raise HTTPException(
            status_code=503,
            detail="Pipeline outputs not found. Run `python pipeline.py` first.")


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@app.get("/api/health")
def health():
    ready = os.path.exists(os.path.join(OUT, "cell_priority_ranked.csv"))
    return {"status": "ok", "outputs_ready": ready}


@app.get("/api/summary")
def summary():
    _require_outputs()
    return _summary()


@app.get("/api/blocks")
def blocks():
    """Time-block index -> human label (e.g. 2 -> 'Morning Peak (08-12)')."""
    return {i: config.TIME_BLOCKS[i][0] for i in range(config.N_TIME_BLOCKS)}


@app.get("/api/stations")
def stations():
    _require_outputs()
    return sorted(_hotspots()["dom_police_station"].dropna().unique().tolist())


@app.get("/api/hotspots")
def hotspots(
    top: int = Query(100, ge=1, le=2000),
    blocks: str | None = Query(None, description="Comma-separated peak_block_label values"),
    stations: str | None = Query(None, description="Comma-separated police stations"),
):
    """EPI-ranked enforcement cells, optionally filtered by peak block / station."""
    _require_outputs()
    df = _hotspots()
    if blocks:
        wanted = [b.strip() for b in blocks.split(",") if b.strip()]
        df = df[df["peak_block_label"].isin(wanted)]
    if stations:
        wanted = [s.strip() for s in stations.split(",") if s.strip()]
        df = df[df["dom_police_station"].isin(wanted)]
    df = df.head(top)
    return {"count": int(len(df)), "cells": _records(df)}


@app.get("/api/zones")
def zones():
    _require_outputs()
    df = _zones()
    return {"count": int(len(df)), "zones": _records(df)}


@app.get("/api/model-comparison")
def model_comparison():
    _require_outputs()
    return {"models": _records(_comparison())}


@app.get("/api/forecast")
def forecast(
    date: str = Query(..., description="YYYY-MM-DD"),
    block: int = Query(..., ge=0, le=5),
    top: int = Query(15, ge=1, le=200),
):
    """Score every known cell for a date+block; return the busiest `top` cells."""
    _require_outputs()
    try:
        ranked = _get_forecaster().rank(date, int(block), top=int(top))
    except Exception as e:  # bad date, model error, etc.
        raise HTTPException(status_code=400, detail=f"Forecast failed: {e}")
    block_label = config.TIME_BLOCKS[int(block)][0]
    return {"date": date, "block": int(block), "block_label": block_label,
            "count": int(len(ranked)), "cells": _records(ranked)}


@app.get("/api/plots/{name}")
def plot(name: str):
    """Serve a pipeline-generated PNG (EDA / model diagnostics)."""
    if not name.endswith(".png") or "/" in name or "\\" in name or ".." in name:
        raise HTTPException(status_code=400, detail="Invalid plot name.")
    path = os.path.join(PLOTS, name)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail=f"Plot '{name}' not found.")
    return FileResponse(path, media_type="image/png")


@app.get("/api/plots")
def list_plots():
    if not os.path.isdir(PLOTS):
        return {"plots": []}
    return {"plots": sorted(f for f in os.listdir(PLOTS) if f.endswith(".png"))}
