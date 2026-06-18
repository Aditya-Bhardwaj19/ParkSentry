# ViolationProto — Parking-Induced Congestion Intelligence (Theme 1)

> **Problem (Theme 1):** On-street illegal parking near commercial areas, metro
> stations and events chokes carriageways. Enforcement today is patrol-based and
> reactive — there is no heatmap of parking violations vs. congestion impact and
> no way to prioritize enforcement zones.
>
> **This project:** An end-to-end pipeline that turns 248k raw Bengaluru parking
> citations into (1) a **forecast** of where & when illegal parking will spike,
> (2) a transparent **congestion-impact** quantification, and (3) a ranked,
> map-ready **enforcement priority** list — served through an interactive
> dashboard and a deployable inference module.

---

## 1. What it does (the three questions the theme asks)

| Theme need | What we built |
|---|---|
| *Detect illegal-parking hotspots* | ~150 m grid cells + DBSCAN density zones over 248k geo-tagged citations |
| *Quantify impact on traffic flow* | **Congestion Impact Score** = severity × vehicle footprint × peak-hour × junction (transparent, calibratable heuristic) |
| *Enable targeted enforcement* | **Spatio-temporal risk model** (forecasts violations per cell-time) → **Enforcement Priority Index** ranking every cell; **top 5 % of slots capture ~56 % of all violations** |

---

## 2. Headline results (temporal hold-out: train Nov 2023–Feb 2024, test Mar–Apr 2024)

- **248,357** clean parking events → **1,389** enforcement cells → **1.26 M** cell-date-block panel rows.
- **Best model: RandomForest** (squared-error regressor) — RMSE **1.450** vs analyst baseline **1.474**, R² **0.19**, MAE **0.283**. Selected on **RMSE + top-K capture** (the operational metric), where it narrowly leads the Poisson-objective boosters (HistGB/XGB/LightGBM, all within ~0.003 capture@5%). *Disclosure:* on Poisson deviance the **Poisson-GLM** is best; we report all five challengers in `artifacts/model_comparison.csv` and select on the metric enforcement actually cares about.
- **Enforcement efficiency:** patrolling the **top 5 %** of predicted cell-time slots captures **~56 %** of all violations; the **top 1 %** captures **~28 %** (≈ 28× better than random).
- **#1 priority cell:** Shivajinagar / Safina Plaza Junction — ~30 violations/day, **Morning Peak (08–12)**.
- Operational insight: violations concentrate heavily in **morning/daytime local hours** (enforcement-shift pattern) and a handful of commercial cores (Shivajinagar, KR/City Market, Upparpet, HAL Old Airport).

> **Honest framing:** the historical per-cell average is already a strong
> predictor, so the ML lift over the baseline is real but modest in RMSE. The
> model's value is the **smooth, generalizable risk surface**, the ability to
> **forecast unseen future slots**, and the **capture-curve efficiency** that
> directly translates into patrol routing.

---

## 3. Pipeline architecture

```
 raw CSV (298k rows, JSON violation arrays, UTC, dirty geo)
   │
   ▼  src/ingest.py        parse · parking filter · geo-validate · localise time · de-dupe
 clean events (248k)
   │
   ▼  src/impact.py        per-event Congestion Impact Score
   │
   ▼  src/aggregate.py     (cell × date × 4h-block) panel, zero-filled  → 1.26M rows
   │
   ▼  src/features.py      calendar/cyclical + causal lags + LEAK-SAFE cell priors & target encoding (27 feats)
   │
   ▼  src/feature_selection.py   variance · |r|>0.95 redundancy · MI/Pearson signal  → 22 feats
   │
   ▼  src/model.py         baseline vs GLM/RF/HistGB/XGB/LGBM · temporal split · Poisson + capture metrics
   │
   ▼  src/hotspots.py      per-CELL Enforcement Priority Index (primary) + DBSCAN zones (secondary)
   │
   ▼  src/visualize.py     EDA + model diagnostics + spatial map
   │
   ├─ predict.py           deployable Forecaster (scores any cell/date/block)
   └─ app.py               Streamlit dashboard
```

Each module's docstring contains the **reasoning** for its design choices; see
also [REASONING.md](REASONING.md) for the consolidated narrative.

---

## 4. How to run

```bash
cd ViolationProto
pip install -r requirements.txt

# Full end-to-end run (reads the parent-folder CSV, ~2 min)
python pipeline.py

# Quick smoke test on a subset
python pipeline.py --sample 40000

# Deployable inference demo
python predict.py

# Interactive prototype dashboard
streamlit run app.py
```

The pipeline reads `../jan to may police violation_anonymized791b166.csv`
(configurable in `config.py`).

### Maps: Mappls (MapmyIndia)

The dashboard renders its Priority Map and Live Forecaster on **Mappls** vector
tiles when credentials are present, and silently falls back to pydeck/`st.map`
otherwise. Credentials are read from environment variables:

```bash
# Windows PowerShell (current session)
$env:MAPPLS_CLIENT_ID     = "<client_id>"
$env:MAPPLS_CLIENT_SECRET = "<client_secret>"
$env:MAPPLS_MAP_SDK_KEY   = "<map_sdk_key>"   # optional static-key fallback

streamlit run app.py
```

The OAuth pair (`client_id`/`client_secret`) is used to mint a 24h access token
automatically; `MAPPLS_MAP_SDK_KEY` is an optional fallback. See
[mappls_map.py](mappls_map.py) for the integration.

---

## 5. Outputs

| File | Meaning |
|---|---|
| `outputs/cell_priority_ranked.csv` | **Primary** — every cell ranked by Enforcement Priority Index |
| `outputs/hotspot_zones.csv` | Secondary — DBSCAN density zones for beat allocation |
| `outputs/cells_annotated.csv` | All cells with EPI + zone id + coords (mapping) |
| `outputs/scored_panel.parquet` | Per cell-date-block actual vs predicted |
| `outputs/run_summary.json` | Headline metrics |
| `outputs/plots/*.png` | EDA, model comparison, capture curve, feature importance, hotspot map |
| `artifacts/best_model.joblib` + `encoders.joblib` + `cell_static.parquet` + `recent_history.parquet` | Everything `predict.py` needs to score new slots |
| `artifacts/model_comparison.csv`, `metrics.json`, `selection_report.json` | Reproducible evaluation record |

---

## 6. Key design decisions (why it is "full-proof")

- **No leakage.** Temporal train/test split; every target-derived feature
  (historical means, target encoding, cell priors) is fit on **train only**;
  lag features are causally shifted. A random split would inflate scores.
- **Right loss for the data.** The target is a zero-inflated **count**, so the
  gradient-boosters and the GLM use a **Poisson** objective (the GLM wins on
  Poisson deviance). The shipped RandomForest optimizes squared error and is
  selected because it leads on RMSE and the operational top-K capture metric —
  a choice we state openly rather than retrofitting the loss narrative onto it.
- **Operational metric, not just statistical.** The **top-K capture curve**
  measures what enforcement actually cares about: with scarce patrols, how much
  of the violation volume do we catch?
- **Honest impact model.** No traffic-flow speeds exist in the data, so the
  Congestion Impact Score is a **documented, multiplicative heuristic** whose
  weights live in `config.py` and can be recalibrated against real delay data.
- **Actionable unit.** Targeting is at the **cell** (~150 m road stretch);
  DBSCAN zones are kept only as a coarser analytical grouping because density
  clustering chains dense cores into city-sized blobs.

## 7. Caveats (stated honestly)

- **Observability bias:** counts are *detected* violations, so they partly
  reflect enforcement effort. The model forecasts *detected* parking pressure —
  the correct target for "where to send the next patrol", but not a census of
  all illegal parking.
- **Impact score is a proxy**, not measured delay. Structure is sound; constants
  need field calibration.
- Data covers Nov 2023–Apr 2024 (the file is named "Jan–May"); the pipeline is
  date-agnostic and will use whatever range the CSV contains.
```
