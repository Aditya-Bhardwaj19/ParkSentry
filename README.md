# ParkSentry - Parking-Induced Congestion Intelligence

ParkSentry turns a stream of **illegal-parking violations** into a forward-looking
**enforcement plan**: it forecasts where and when illegal parking will occur,
weights each spot by its likely **traffic-congestion harm**, and ranks the
~150 m road cells a patrol should visit next - shown on an interactive map.

> **Why parking → congestion?** Illegally parked vehicles block carriageway and
> back up junctions. The dataset has no traffic-flow speeds, so we *forecast the
> violation pressure* that drives congestion and weight it by a transparent,
> recalibratable impact heuristic. Enforcement becomes **predictive and targeted**
> instead of reactive.

**Headline result:** patrolling the model's **top 5%** of (cell, time) slots
captures **57.1%** of all violations - an **11× lift over random** - using a
single LightGBM-Tweedie forecaster (capture@5% **0.5713**, MAE **0.2531**).
Full modeling story in [docs/MODELS.md](docs/MODELS.md); feature work in
[docs/FEATURE_ENGINEERING.md](docs/FEATURE_ENGINEERING.md).

---

## What it produces
- **Priority map** - every ~150 m cell scored by an **Enforcement Priority Index (EPI)** = `predicted daily violations × mean congestion impact`, plotted on Mappls maps.
- **Priority list** - the ranked cells with station, junction, peak block and predicted volume.
- **Live forecaster** - score *any* (cell, date, 4-hour block) on demand, including future dates.
- **Model & EDA** - challenger comparison, capture curve, feature importance, data diagnostics.

## Architecture

```
  Raw violations CSV  ──►  pipeline.py  ──►  artifacts/ + outputs/
  (Nov 2023–Apr 2024)      ingest → impact → aggregate → features →
                           feature-selection → model → score → EPI/zones

  Browser (React + Vite, Mappls SDK)
        │ /api/*
        ▼
  Node/Express gateway  :8000   ── mints Mappls token, serves SPA, proxies /api
        │
        ▼
  FastAPI ML service    :8001   ── reads outputs/+artifacts/, wraps predict.Forecaster
```

## Techniques used
- **Cleaning & framing** - JSON violation parsing, parking-only filter, geo/UTC→local validation, conservative `rejected`/`duplicate` drop.
- **Congestion-impact heuristic** - `severity × vehicle footprint × peak × junction`, multiplicative, weights in `config.py` (declared proxy, recalibratable).
- **Spatio-temporal panel** - ~150 m grid × date × 4-hour block, zero-filled (1.26 M rows, ~4.7% non-zero).
- **Leak-safe feature engineering** - causal autoregressive lags, rolling mean/nonzero-rate, EWMA, 8-neighbour spatial features, train-only cell priors, and **leak-safe expanding-window target encoding**.
- **Modeling** - gradient boosting with a **Tweedie** objective for the zero-inflated count target; **temporal** train/test split; **top-K capture** as the operational metric.
- **Targeting** - per-cell **EPI** (forecast × impact) + secondary **DBSCAN** density zones.
- **Deployable inference** - `predict.Forecaster` rebuilds the exact feature vector causally from saved artifacts (no leakage, works for next-day forecasts).
- **App** - React + Node/Express + FastAPI, **Mappls** interactive maps.

## Repository layout

```
config.py            All tunables: grid, bbox, time blocks, impact weights, split date
pipeline.py          End-to-end run → writes artifacts/ + outputs/
predict.py           Deployable Forecaster (causal feature reconstruction)
src/                 Pipeline stages: ingest, impact, aggregate, features,
                     feature_selection, model, hotspots, visualize
artifacts/           Trained model, encoders, feature list, metrics (committed)
outputs/             Rankings, scored panel, plots, run_summary (committed)
experiments/         Offline studies (deep learning, feature ablation, blending) + tests
webapp/              React + Node gateway + FastAPI app
docs/                FEATURE_ENGINEERING.md, MODELS.md
```

---

## Quickstart

### Prerequisites
- **Python ≥ 3.10**, **Node ≥ 20.6** (the gateway uses Node's native `--env-file`).
- The raw violations CSV is **not** published; `artifacts/` and `outputs/` are
  committed so the app runs from a fresh clone **without** re-running the pipeline.

### 1. Install
```bash
pip install -r requirements.txt          # Python: pandas, sklearn, lightgbm, fastapi, ...
cd webapp && npm run install:all         # Node: root + gateway + frontend deps
```

### 2. (Optional) regenerate the model
Only needed if you change features/config or have the raw CSV (place it in the
repo's **parent** directory, per `config.RAW_CSV`):
```bash
python pipeline.py                       # rewrites artifacts/ + outputs/ (~3 min)
```

### 3. Add Mappls map keys
```bash
cd webapp
cp .env.example .env                     # then edit .env and paste your keys
```
Create an app at <https://apps.mappls.com> (enable the Map SDK) to get a
`CLIENT_ID` / `CLIENT_SECRET`. `webapp/.env` is **gitignored** - secrets never
get committed. Without keys, everything works except the interactive map.

### 4. Run on http://localhost:8000
```bash
cd webapp
npm run build                            # frontend → frontend/dist
npm start                                # gateway :8000  +  FastAPI :8001
```
Open **http://localhost:8000**.

For hot-reload development instead: `npm run dev` → open **http://localhost:5173**
(Vite proxies `/api` to the gateway).

---

## Documentation
- **[docs/FEATURE_ENGINEERING.md](docs/FEATURE_ENGINEERING.md)** - preprocessing, every feature family, and what failed vs. succeeded (incl. the leak-safe-encoding swing).
- **[docs/MODELS.md](docs/MODELS.md)** - every model tried, best hyperparameters, and head-to-head results (trees vs. deep learning vs. blending).
- **[webapp/README.md](webapp/README.md)** - web-app architecture and the FastAPI endpoint reference.
- Per-module rationale lives in each file's docstring.
