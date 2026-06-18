# REASONING — design decisions, step by step

This document is the "why" behind every big step. Each module's docstring holds
the local rationale; this is the consolidated narrative a reviewer can read
top-to-bottom.

---

## 0. Framing the problem from the data (not the other way round)

Before designing anything we profiled the dataset:

- 298k rows; after de-dup/cleaning **248k** usable events.
- **~95 % of all citations are parking violations** (WRONG PARKING, NO PARKING,
  PARKING IN A MAIN ROAD, …) — so this dataset is, in effect, a *parking*
  dataset, which is exactly Theme 1.
- Clean lat/lon, local timestamps recoverable, junction tags, vehicle types,
  severity-relevant violation types.
- **No traffic-flow speeds / delay** anywhere.

That last point is decisive: we **cannot measure** congestion impact, so we must
**estimate** it transparently and **forecast** the violation pressure that drives
it. Hence the three-part solution: forecast + impact heuristic + priority index.

**Why not just a heatmap?** A static heatmap of past violations is what the theme
says already fails ("enforcement is reactive"). The value-add is *prediction*
(where next) and *prioritization* (impact-weighted), not description.

---

## 1. Ingestion & cleaning — make every field mean what it says

Decisions and why:

- **Parse JSON violation arrays** → token lists; a citation can carry several
  violation types.
- **Parking filter:** keep rows with a parking token (or substring `PARK`). Drops
  the ~5 % off-theme noise (helmet, mobile, etc.) so the model is not diluted.
- **Geo-validation:** numeric lat/lon inside a Bengaluru bounding box. Placeholder
  zeros and GPS errors would poison every spatial step.
- **Local time:** `created_datetime` is UTC; congestion is local. We convert to
  Asia/Kolkata *before* deriving hour/time-block — otherwise the evening peak
  lands at midnight.
- **Validation status:** drop only explicit `rejected`/`duplicate` (confirmed
  non-violations). Keep `NULL` (~42 %) = "unreviewed", not "invalid" — dropping it
  would discard ~half the genuine signal.

Result: 248k tidy one-row-per-event records, 83 % of raw retained.

---

## 2. Congestion Impact Score — an honest heuristic

`impact = severity(violation) × footprint(vehicle) × peak(time) × junction`

- **Multiplicative**, because the factors compound (a lorry on a main road at
  evening peak by a junction is far worse than the sum of parts).
- **Severity (max over tokens):** main-road / double parking block more lanes than
  a footpath encroachment.
- **Footprint:** a parked lorry occupies more carriageway than a scooter.
- **Peak:** the same blockage costs more delay under high demand.
- **Junction:** a blockage at a signalled junction back-propagates across
  approaches.

All weights live in `config.py`. We explicitly document this is a **proxy**, and
that with real junction-level delay data the *same structure* can be re-fit (only
the constants change). Shipping a heuristic honestly = make the assumptions
visible and calibratable.

---

## 3. Spatio-temporal aggregation — pick the right unit of analysis

A patrol goes to a *place* at a *time*, so the modelling unit is
**(grid cell × date × 4-hour block)** and the target is the **violation count**.

- **~150 m grid cells** pool sparse points into a stable enforcement-zone signal
  with a fixed identity across time (needed for lags & panels).
- **Keep cells with ≥20 events** (1,389 cells) — they cover **93 %** of all
  violations while excluding a long tail of 1–2-event cells that would add
  millions of structural zeros and no enforcement value.
- **Zero-fill** the (cell × date × block) grid: the unobserved combinations are
  genuine zeros and form the negative class of the risk surface (so the model can
  learn *when a hotspot is quiet*).

Panel: **1.26 M rows, 4.7 % non-zero** — a realistic zero-inflated count problem.

---

## 4. Feature engineering & encoding — three signal families, zero leakage

- **Calendar / cyclical:** sin/cos for block, day-of-week, month (so "block 5" is
  adjacent to "block 0"); plus `peak_w`.
- **Autoregressive lags** (the strongest signal): lag-1/2/7 and rolling 7/28-day
  means **per (cell, block)**, each *shifted* so a row only sees its own past →
  leak-safe even across the split.
- **Cell-static priors / encodings**, fit on **train only** and mapped to all rows:
  historical cell-block mean & non-zero rate, cell severity/vehicle/junction mix,
  and a **smoothed target-encoding of the police station**. These give a prior for
  "cold" cells with no recent activity.

Leakage is the cardinal sin of forecasting, so everything that touches the target
is fit on the train split and the lags are causal. Validated by re-running with
warnings-as-errors and 0 NaNs.

---

## 5. Feature selection — three complementary filters

Keep a feature if it survives: (1) not near-constant, (2) not redundant
(|r| > 0.95 — drop the partner less correlated with the target), (3) has signal
by **Pearson OR mutual information** (MI catches non-linear signal a correlation
misses). 27 → **22** features; dropped weak calendar duplicates. We always
*report* what was dropped and why (`selection_report.json`).

---

## 6. Modelling & evaluation — match the method to the data

- **Poisson objective** for the gradient boosters (count target, ≥0, variance
  grows with mean) — not plain MSE.
- **Temporal split** (train ≤ Feb-2024, test after) — the only honest way to
  measure forecasting skill; a random split leaks through the lags.
- **Baseline = historical cell-block mean** (what a spreadsheet analyst would do);
  a model must beat it to justify itself.
- **Metrics for the job:** MAE, RMSE, **Poisson deviance**, R² (read with care on
  a zero-inflated target), and the **top-K capture curve** — the operational
  metric that says "patrol the top-K % highest-risk slots, catch X % of
  violations".

Outcome: all challengers beat the baseline; **RandomForest** wins on RMSE/capture.
The lift is modest in RMSE (the historical mean is already strong) but the model
generalizes, forecasts unseen slots, and the capture lift is large (top 5 % ⇒
56 %). We report this honestly rather than overclaiming.

---

## 7. Hotspots & Enforcement Priority Index — what to actually do Monday morning

- **Primary = per-CELL EPI**: `EPI_raw = predicted_daily_violations ×
  mean_impact_per_violation`, min-max scaled to 0–100. A cell is a specific
  ~150 m road stretch a patrol can be sent to — *targeted* enforcement.
- **Secondary = DBSCAN density zones** (haversine, ~250 m, noise → singletons) for
  beat-level grouping. We deliberately do **not** target at the zone level: in
  dense contiguous cores DBSCAN chains 100+ cells into one city-sized blob, which
  would mean "patrol the whole market" — the opposite of targeted. This was a real
  failure mode we caught and corrected (the first design ranked a 135-cell blob
  #1; the fix makes the #1 a single junction cell).

EPI fuses a **learned forecast** (volume) with a **transparent harm weighting**
(impact) into one rankable number. The 0–100 score is **winsorized at the 99th
percentile** before scaling so a single extreme cell (the central market core)
does not compress every other hotspot toward zero on the map — the rank is
unchanged, only the displayed magnitude is made readable.

---

## 8. Prototype — make it usable & deployable

- `predict.py` — a `Forecaster` that rebuilds the exact feature vector causally
  for *any* (cell, date, block) from saved artifacts and scores it. True
  inference, no leakage, works for next-day forecasts.
- `app.py` — a Streamlit dashboard: KPI strip, priority map (pydeck), filterable
  priority table, a live forecaster, and the model/EDA evidence.

---

## What a critic might ask, and the answer

- *"Your R² is low."* — Correct, and expected for a 95 %-zero count series; the
  decision-relevant metric is **capture@K**, which is strong, plus we beat the
  honest baseline on every metric.
- *"Impact score is made up."* — It is a **declared heuristic** with documented,
  recalibratable weights; we never present it as measured delay.
- *"Counts ≠ true illegal parking."* — Acknowledged observability bias; the target
  is *detected* pressure, which is the right quantity for routing patrols.
- *"Did you leak the future?"* — No: temporal split, train-only encoders, causal
  lags; re-validated with warnings-as-errors **and an independent adversarial
  multi-agent review** (see below).

---

## 9. Post-build adversarial review & hardening

After the first working build we ran an **independent multi-agent code review**
(4 reviewer agents × 4 risk dimensions — leakage, train/inference consistency,
correctness, methodology — each finding then confirmed or refuted by a separate
skeptic agent). 15 of 19 raw findings were confirmed real and fixed:

**Two genuine high-severity defects (both caught, both fixed & re-verified):**

1. **Leakage via `log_total_events`.** `total_events` was summed over the whole
   period (train+test); since it is a monotone function of the target, it leaked
   test information into a training feature — ironically the one cell-static
   feature that broke our own train-only discipline. **Fix:** compute it from
   **train events only** (`train_events`), with a global fallback for cells
   unseen in train. Re-running showed metrics essentially unchanged
   (RMSE 1.4501 → 1.4494), proving the model never depended on the leak — the
   result is honest.

2. **Train/inference mismatch in `roll28_mean`.** The inference store kept only
   40 days of history, so the 28-day rolling window was truncated for early
   scoring dates and diverged from training (up to 1.79 off). **Fix:** retain
   **70 days** (`HISTORY_RETENTION_DAYS`) so the longest lookback is always
   fully covered. Re-verified: all 27 features now reproduce training to
   **max |diff| = 0** across sampled deploy-window rows.

**Medium / low fixes:** winsorized the EPI scale (one outlier was compressing
~90 % of cells toward 0 on the map); made the police-station mode train-only;
hardened `mode()` against empty groups; normalized the cached `tokens` dtype;
made `peak_block` tie-breaking deterministic; added zero-guards to the degenerate
EPI and capture-curve paths; fixed EDA bars to show explicit zeros; reconciled
the DBSCAN eps docstring (250 m); and corrected the README's model labelling
(RandomForest is squared-error, not Poisson — disclosed openly).

The lesson reinforced: **a pipeline that *claims* leak-safety still needs an
adversary to prove it.** The review found exactly the kind of subtle,
self-inconsistent leak that unit tests miss.
