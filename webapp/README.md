# ParkSentry — Full-stack web app (React + Node + Python)

A three-tier replacement for the old Streamlit prototype, with **Mappls
(MapmyIndia)** interactive maps.

```
Browser (React + Vite, Mappls JS SDK)
      │  /api/*  (Vite proxy in dev)
      ▼
Node/Express gateway        :3000   gateway/server.js
   • GET /api/maptoken  → mints a short-lived Mappls token (secret stays server-side)
   • /api/*             → proxies to FastAPI
      │
      ▼
Python FastAPI ML service   :8000   api/main.py
   • reads ../outputs/*.csv + ../artifacts/* (pipeline outputs)
   • wraps predict.Forecaster for live scoring
```

The browser only ever talks to the gateway. The Python ML code
(`config.py`, `predict.py`, the `outputs/` CSVs) is reused unchanged — this app
is just an HTTP + UI layer over it.

## Prerequisites

- The pipeline must have been run once so `../outputs/` and `../artifacts/`
  exist: `cd .. && python pipeline.py`.
- Node ≥ 18 and Python ≥ 3.10 with the project requirements installed
  (`pip install -r ../requirements.txt`, which includes `fastapi` + `uvicorn`).

## Mappls credentials (environment variables)

Set these in the shell **before** starting the gateway (it mints the token):

```powershell
# Windows PowerShell
$env:MAPPLS_CLIENT_ID     = "<client_id>"
$env:MAPPLS_CLIENT_SECRET = "<client_secret>"
$env:MAPPLS_MAP_SDK_KEY   = "<map_sdk_key>"   # optional static fallback
```

Without them the data, tables, charts and forecaster all still work; only the
maps show a "credentials not configured" notice.

## Install & run (dev)

```bash
cd webapp
npm run install:all        # root (concurrently) + gateway + frontend deps
npm run dev                # starts FastAPI :8000, gateway :3000, Vite :5173
```

Open **http://localhost:5173**.

## Build & run (production-style)

```bash
npm run build              # frontend → frontend/dist
npm run start:prod         # FastAPI :8000 + gateway :3000 (gateway serves dist)
# open http://localhost:3000
```

## API endpoints (FastAPI)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/summary` | headline metrics (run_summary.json) |
| GET | `/api/blocks` | time-block index → label |
| GET | `/api/stations` | distinct police stations |
| GET | `/api/hotspots?top=&blocks=&stations=` | EPI-ranked cells (filtered) |
| GET | `/api/zones` | DBSCAN density zones |
| GET | `/api/model-comparison` | challenger metrics table |
| GET | `/api/forecast?date=&block=&top=` | live Forecaster scoring |
| GET | `/api/plots` / `/api/plots/{name}` | EDA / diagnostic PNGs |

Gateway-only: `GET /api/maptoken` → `{ configured, token, source }`.

Interactive API docs: http://localhost:8000/docs
