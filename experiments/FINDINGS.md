# Modeling findings — can we beat the LightGBM-Tweedie champion?

**Short answer:** We pushed the operational metric from **capture@5% 0.5646 → 0.5713 (+0.67pp)** and cut **MAE 0.2697 → 0.2531 (−6.2%)** — all from *feature engineering + leak-safe preprocessing on the existing data*. Deep learning did **not** beat gradient-boosted trees, and the model is now at the **signal ceiling** for this dataset: further gains require *new data sources*, not more statistics derived from the violation counts.

## Setup (unchanged throughout)
- **Task:** parking-induced traffic congestion — predict illegal-parking violation count per `(cell × date × 4-hour block)`; the EPI = predicted daily congestion harm.
- **Data:** the single parking-violation dataset, **Nov 2023 – Apr 2024** (~248k cleaned events, 1,389 cells). No external data.
- **Split:** temporal — train ≤ 2024-02-29, test after. Never random (lag features would leak).
- **Metric:** **capture@5%** = share of real violations caught by patrolling the top-5% highest-predicted slots (the operational target). Also track MAE / RMSE / Poisson deviance.
- Every result below uses the **same split, same Tweedie objective, and the same `src.model.evaluate`** so numbers are directly comparable.

## Everything we tried (test set, sorted by capture@5%)

| Approach | capture@5% | MAE | Verdict |
|---|---|---|---|
| Tree rank-mean blend (4 models) | ~0.5724 | — | +0.10pp, consistent — not worth 4× models |
| **GBM + spatial + expanding-TE** (shipped) | **0.5713** | **0.253** | ✅ **production champion** |
| GBM + spatial + expanding-TE + q90-OOF | 0.5714 | 0.254 | flat — not worth the complexity |
| Ensemble (0.7·GBM + 0.3·RankGauss-NN) | 0.5697 | 0.273 | works, but needs 2 models — skipped |
| GBM + spatial neighbours only | 0.5684 | 0.270 | subset of shipped |
| GBM + extra temporal features | 0.5659 | 0.270 | marginal |
| **Original champion** (26 feats) | 0.5646 | 0.270 | baseline |
| RandomForest / XGBoost / LightGBM-Poisson | 0.561–0.564 | ~0.28 | tree pack |
| MLP (RankGauss preprocessing) | 0.5578 | 0.282 | NN best — still < GBM |
| Baseline (historical mean) | 0.5372 | 0.288 | the bar to beat |
| GRU / LSTM (sequence models) | 0.534 / 0.508 | 0.345 | **below baseline** |
| GBM + **naive** target encoding | 0.5296 | 0.272 | ❌ **−3.5pp leak trap** |

## What shipped (commit on `main`)
**LightGBM-Tweedie** with two new, leak-safe feature families (`src/features.py`, reconstructed at inference in `predict.py`):
1. **Spatial neighbours** — `nbr_lag1`, `nbr_nz7` (8-connected grid neighbours' yesterday count & recent nonzero rate). *+0.38pp.*
2. **Expanding-window target encoding** — `exp_cb`, `exp_cdb`, `exp_db` for `(cell, block)`, `(cell, dow, block)`, `(dow, block)`: each train row sees only its group's **prior** history; future rows use the full-train shrunk mean. *+0.33pp on top of spatial.*

## Key lessons
1. **Trees beat deep learning here.** On short (~150-day), zero-inflated, engineered-tabular data, LSTM/GRU underperformed even the historical-mean baseline; the best NN (RankGauss MLP) reached parity on MAE but never matched the GBM on ranking. Matches the literature (Grinsztajn 2022; M5 was swept by Tweedie-LightGBM).
2. **Preprocessing matters for NNs, not for trees.** RankGauss lifted the MLP +1.1pp and halved its MAE gap; trees are scale-invariant and ignore it.
3. **Encoding leak-safety is a 4-point swing.** The *same* `(cell×dow×block)` target encoding cost −3.5pp as a naive train-wide mean but gained +0.7pp as a causal expanding-window encoder. Implementation detail > feature choice.
4. **The signal is saturated.** q90 (high-quantile) out-of-fold encoding — which directly targets the top-K tail — came back **flat**, because the existing features (`cell_blk_nonzero`, `exp_*`, neighbours, lags) already encode hotspot severity. There is no more juice in re-deriving statistics from the violation counts.

## Blending / stacking (diverse base models)
Tested whether combining models beats the single champion. Five base learners
(LGBM-Tweedie, XGBoost-Poisson, HistGB-Poisson, RandomForest, RankGauss-MLP),
blended by equal mean, equal rank-mean, capture-optimised weights, and a
positive-linear stack.

- A **tree-only rank-mean blend** beats the single champion by a **small but consistent ~+0.10pp** (0.5713 → ~0.5724; +0.05 / +0.11 / +0.13pp across seeds 42 / 1 / 7 — all positive). The lift comes from the decorrelated HistGB/RandomForest members.
- **Including the RankGauss-MLP *hurts*** every blend (drags to ~0.569) — it's weaker and gets over-weighted in rank space.
- An earlier +0.3pp blend lift was a **mirage**: it only appeared when base models were data-starved (trained on train−21d), which made them weak *and* decorrelated. On full data the bases are strong and 0.96+ correlated, so the diversity gain mostly evaporates.

**Decision: not shipped.** +0.10pp is not worth running 4 models instead of 1 (4× training/inference, and `predict.py` would need all four loaded + rank-averaged). The single LightGBM-Tweedie captures ~99.8% of the blend's performance at 25% of the cost.

## Conclusion
The forecaster is at its ceiling on this data. Feature engineering and leak-safe encoding gave the only meaningful win (+0.67pp); deep learning lost, and blending/stacking adds only a marginal, complexity-heavy +0.10pp. The only path to a *meaningful* further gain is **new signal** the model can't currently see — and that is out of scope for this project (congestion from the violation dataset only). Recommended stopping point.

## Reproduce
- `experiments/deep_models.py` — MLP / LSTM / GRU vs trees
- `experiments/feature_engineering.py` — feature-family ablation (GBM)
- `experiments/nn_preprocessing.py` — RankGauss + entity embeddings
- `experiments/improve_all.py` — expanding-window encoding + ensemble
- `experiments/q90_encoder.py` — q90 out-of-fold encoding
- `experiments/stacking.py` — 5-model blending/stacking (blend-tuning regime)
- `experiments/blend_fulltrain.py` — full-train blend vs champion (multi-seed)
- Result tables / per-seed JSON saved alongside in `artifacts/`.
