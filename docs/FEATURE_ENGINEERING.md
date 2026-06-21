# Preprocessing & Feature Engineering

How the raw violation citations become a leak-safe modeling panel, every feature
family the model uses, and — at the end — **what we tried to add and whether it
helped**. The companion doc [MODELS.md](MODELS.md) covers the models themselves.

- **Data:** one parking-violation dataset, **Nov 2023 – Apr 2024** (~248k cleaned events, 1,389 cells). No external data.
- **Unit of analysis:** `(grid cell × date × 4-hour block)`; target = **violation count**.
- **Split:** temporal — train ≤ `2024-02-29`, test after (never random — the lags would leak).
- **Operational metric:** **capture@5%** = share of real violations caught in the top-5% highest-predicted slots.

---

## 1. Ingestion & cleaning (`src/ingest.py`)
- **Parse JSON violation arrays** → token lists (a citation can carry several violation types).
- **Parking-only filter:** keep rows with a parking token (~95% of all citations) — drops off-theme noise (helmet, mobile, …) so the signal isn't diluted.
- **Geo-validation:** numeric lat/lon inside a Bengaluru bounding box — placeholder zeros / GPS errors would poison every spatial step.
- **UTC → local:** `created_datetime` is UTC; we convert to `Asia/Kolkata` **before** deriving hour/time-block, or the evening peak lands at midnight.
- **Validation status:** drop only explicit `rejected` / `duplicate`; **keep `NULL` (~42%)** = "unreviewed", not "invalid" — dropping it would discard half the genuine signal.

→ **298k raw → 248k tidy events** (83% retained).

## 2. Congestion-impact score (`src/impact.py`)
No traffic-flow data exists, so impact is an **honest, multiplicative heuristic**:

```
impact = severity(violation) × footprint(vehicle) × peak(time-block) × junction
```

Multiplicative because the factors compound (a lorry on a main road at evening
peak by a junction is far worse than the sum of parts). All weights live in
`config.py` and are documented as a **proxy** — with real junction-level delay
data the *same structure* re-fits, only the constants change. This score feeds
the **EPI** (it is **not** a model input — it never sees the target).

## 3. Spatio-temporal aggregation (`src/aggregate.py`)
- **~150 m grid cells** pool sparse points into a stable enforcement-zone signal with a fixed identity across time (needed for lags & panels).
- **Keep cells with ≥ 20 events** → **1,389 cells** covering **93%** of violations; the 1–2-event long tail would add millions of structural zeros and no enforcement value.
- **Zero-fill** the full `(cell × date × block)` grid — unobserved combinations are genuine zeros and form the negative class, so the model learns *when a hotspot is quiet*.

→ Panel: **1.26 M rows, ~4.7% non-zero** — a realistic zero-inflated count problem.

## 4. Feature families (`src/features.py`)
All features are **causal** (a row only ever sees its own past) and anything that
touches the target is **fit on the train split only** — leak-safe even across the
train/test boundary. The shipped model uses **35** selected features:

| Family | Features | Notes |
|---|---|---|
| **Calendar / cyclical** | `time_block`, `peak_w`, `block_sin`, `dow_sin/cos`, `month_cos` | sin/cos so "block 5" is adjacent to "block 0" |
| **Autoregressive lags** | `lag1/2/7/14`, `roll7/14/28_mean`, `ewm7`, `roll7_nz`, `cell_roll_day` | per `(cell, block)`, shifted; `roll7_nz` = recent nonzero rate |
| **Spatial (8-neighbour)** | `nbr_roll7`, `nbr_blk_mean`, **`nbr_lag1`**, **`nbr_nz7`** | grid-neighbour activity; bold = added in this work |
| **Cell-static priors** | `cell_blk_mean`, `cell_blk_nonzero`, `cell_sev`, `cell_veh`, `cell_jshare`, `ps_target_enc`, `log_total_events` | train-only; a prior for "cold" cells |
| **Expanding-window target enc.** | **`exp_cb`**, **`exp_cdb`**, **`exp_db`** | leak-safe `(cell,blk)`, `(cell,dow,blk)`, `(dow,blk)` — added in this work |

**The leak-safe expanding encoder** is the subtle one. A naive train-wide target
mean used as a feature leaks: a train row sees its own group's full-train average
and the model over-trusts it. Instead, each **train** row sees only its group's
**prior** target history (a causal expanding window); **future** rows use the
full-train shrunk mean (a static lookup at inference). No row ever sees its own
target.

## 5. Feature selection (`src/feature_selection.py`)
Keep a feature only if it survives three filters (decided on **train only**):
1. **not near-constant** (variance ≥ 1e-9),
2. **not redundant** (|r| > 0.95 — drop the partner less correlated with the target),
3. **has signal** by **Pearson OR mutual information** (MI catches non-linear signal a correlation misses).

→ **38 engineered → 35 kept**; dropped weak calendar duplicates. Everything
dropped is logged with the reason in `artifacts/selection_report.json`.

---

## 6. What we tried — and whether it helped
Every variant below was trained with the **same** split, Tweedie objective, and
metrics, so the deltas are trustworthy. Starting point: the original 26-feature
champion at **capture@5% 0.5646**.

| Added on top of the base | capture@5% | Δ | Verdict |
|---|---|---|---|
| **Spatial neighbours** (`nbr_lag1`, `nbr_nz7`) | 0.5684 | **+0.38pp** | ✅ shipped |
| **Expanding-window target enc.** (on top of spatial) | **0.5713** | **+0.33pp** | ✅ shipped (→ production) |
| Extra temporal (recency, rolling std, more lags, multi-span EWMA) | 0.5659 | +0.13pp | marginal — not shipped |
| Revived calendar flags (weekend, holiday, 2nd harmonic) | 0.5642 | −0.05pp | neutral — not shipped |
| **q90 out-of-fold** high-quantile encoding | ~0.5714 | +0.02pp | flat — signal already captured |
| **Naive** train-wide target encoding | 0.5296 | **−3.5pp** | ❌ the leak trap |
| Everything stacked together | 0.5192 | −4.5pp | ❌ noise on a 150-day panel |

### The headline lesson: encoding *leak-safety* is a 4-point swing
The **same** `(cell × dow × block)` target encoding **cost −3.5pp** as a naive
train-wide mean but **gained +0.7pp** (and lowered MAE 0.27 → 0.25) as a causal
expanding-window encoder. The implementation detail mattered far more than the
feature choice — the single biggest preprocessing finding in the project.

### Why more features stopped helping (the signal ceiling)
`q90` high-quantile encoding directly targets the top-K tail, yet came back
**flat** — because `cell_blk_nonzero`, the `exp_*` encodings, the neighbour
features and the lags already encode hotspot severity. Re-deriving more
statistics from the violation counts has no juice left; a *meaningful* further
gain would need **new signal** (not in scope for this congestion-only dataset).

## 7. Preprocessing for neural nets (separate track)
Gradient-boosted trees are scale-invariant, so they ignore feature scaling.
**Neural nets are not** — feeding them raw, heavy-tailed count features cripples
them. The fix that closed most of the NN's gap was **RankGauss**
(`QuantileTransformer(output_distribution="normal")`), which lifted the MLP's
capture@5% **+1.1pp** and cut its MAE 0.32 → 0.28. (Details in
[MODELS.md](MODELS.md).) Entity embeddings for cell/station did **not** help —
they overfit identities on the short panel.

## 8. Leakage discipline & adversarial hardening
Leakage is the cardinal sin of forecasting, so the split boundary is respected
throughout, and the inference path is verified to reproduce training features
exactly (`experiments/verify_skew.py`). An independent adversarial review caught
two real defects, both fixed and re-verified:
- **`log_total_events` leak** — it was summed over train **+** test; since it is a
  monotone function of the target, it leaked test info into a training feature.
  Fixed to **train-only** volume; metrics essentially unchanged, proving the model
  never depended on the leak.
- **`roll28_mean` train/serve skew** — the inference store kept only 40 days, so the
  28-day window truncated for early dates. Fixed to retain **70 days**
  (`HISTORY_RETENTION_DAYS`); all features now reproduce training to `max|diff| = 0`.

The lesson: *a pipeline that claims leak-safety still needs an adversary to prove it.*

---

## Reproduce
- `experiments/feature_engineering.py` — the feature-family ablation (table in §6)
- `experiments/improve_all.py` — leak-safe expanding-window encoding + ensemble
- `experiments/q90_encoder.py` — q90 out-of-fold encoding
- `experiments/nn_preprocessing.py` — RankGauss + entity embeddings (NN track)
- `experiments/verify_skew.py` — confirms inference reconstructs training features exactly
