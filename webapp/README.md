# ParkSentry - web app (React + Node + Python)

A three-tier app over the ML pipeline, with **Mappls (MapmyIndia)** interactive
maps. For project overview and full setup, see the [root README](../README.md);
this file documents the web-app internals.

```
Browser (React + Vite, Mappls JS SDK)
      │  /api/*   (Vite proxy in dev; same origin in prod)
      ▼
Node/Express gateway        :8000   gateway/server.js
   • GET /api/maptoken  → mints a short-lived Mappls token (secret stays server-side)
   • serves the built SPA (frontend/dist) in production
   • /api/*             → proxies to FastAPI
      │
      ▼
Python FastAPI ML service   :8001   api/main.py
   • reads ../outputs/*.csv + ../artifacts/* (pipeline outputs)
   • wraps predict.Forecaster for live scoring
```

The browser only ever talks to the gateway. The Python ML code (`config.py`,
`predict.py`, the `outputs/` CSVs) is reused unchanged - this app is an HTTP + UI
layer over it.

## Prerequisites
- The pipeline must have run once so `../outputs/` and `../artifacts/` exist
  (they are committed, so a fresh clone works as-is). To regenerate: `cd .. && python pipeline.py`.
- **Node ≥ 20.6** (gateway uses the native `--env-file`) and **Python ≥ 3.10**
  with `pip install -r ../requirements.txt` (includes `fastapi` + `uvicorn`).

## Mappls credentials (`.env`)
```bash
cp .env.example .env        # then edit .env and paste your Mappls keys
```
`.env` is **gitignored**. The gateway loads it automatically (`--env-file-if-exists=.env`)
and mints the map token from `MAPPLS_CLIENT_ID` / `MAPPLS_CLIENT_SECRET`. Without
keys, the data, tables, charts and forecaster all still work - only the map shows
a "credentials not configured" notice.

## Install & run
```bash
npm run install:all         # root (concurrently) + gateway + frontend deps

# production (single port):
npm run build               # frontend → frontend/dist
npm start                   # gateway :8000 (serves SPA) + FastAPI :8001
# open http://localhost:8000

# development (hot reload):
npm run dev                 # FastAPI :8001, gateway :8000, Vite :5173
# open http://localhost:5173
```

## API endpoints (FastAPI)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/summary` | headline metrics (`run_summary.json`) |
| GET | `/api/blocks` | time-block index → label |
| GET | `/api/stations` | distinct police stations |
| GET | `/api/hotspots?top=&blocks=&stations=` | EPI-ranked cells (filtered) |
| GET | `/api/zones` | DBSCAN density zones |
| GET | `/api/model-comparison` | challenger metrics table |
| GET | `/api/forecast?date=&block=&top=` | live Forecaster scoring |
| GET | `/api/plots` / `/api/plots/{name}` | EDA / diagnostic PNGs |

Gateway-only: `GET /api/maptoken` → `{ configured, token, source }`.
Interactive FastAPI docs (direct, bypassing the gateway): http://localhost:8001/docs
