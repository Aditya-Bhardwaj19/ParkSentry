# Models, Hyperparameters & Results

Every model we tried, the hyperparameters that worked best, and the head-to-head
numbers. Feature work is in [FEATURE_ENGINEERING.md](FEATURE_ENGINEERING.md).

- **Target:** violation count per `(cell × date × 4-hour block)` - non-negative, **zero-inflated** (~95% zeros), right-skewed.
- **Split:** temporal - train ≤ `2024-02-29`, test after.
- **Primary metric:** **capture@5%** (operational: patrol the top-5% predicted slots, measure share of real violations caught). Also MAE, RMSE, Poisson deviance, R².
- **Selection rule:** rank challengers by **capture@5%** (tie-break RMSE); a model must not regress RMSE vs. the baseline. R² is reported but **not** used to choose - it is unreliable on a 95%-zero target.

---

## The champion: LightGBM with a Tweedie objective

```python
LGBMRegressor(
    objective="tweedie", tweedie_variance_power=1.5,
    n_estimators=2000,          # early-stopped to ~205 (see below)
    learning_rate=0.03, num_leaves=95, min_child_samples=60,
    subsample=0.8, colsample_bytree=0.8, reg_lambda=1.0,
    random_state=42,
)
```

**Why Tweedie (variance power 1.5)?** The target is a compound Poisson–Gamma
shape - a pile of exact zeros plus a continuous positive tail. `p = 1.5` sits
between Poisson (`p=1`) and Gamma (`p=2`) and models that shape directly; it
beats a plain Poisson objective on the *same* trees (see table). The M5
competition - the closest large analog - was swept by Tweedie-LightGBM.

**Early-stopping protocol** (`src/model.py`): fit on `train − last 21 days`,
early-stop on those 21 days (`eval_metric="rmse"`, patience 60), then **refit on
the full train** at the chosen iteration count - capacity is data-driven, not
hand-fixed.

**Production result (35 features):** capture@5% **0.5713**, MAE **0.2531**,
RMSE **1.4499**, capture@1% 0.292, capture@20% 0.818.

---

## Full challenger comparison (test set, 35 features)

| Model | MAE ↓ | RMSE ↓ | R² ↑ | PoisDev ↓ | cap@1% | **cap@5%** | cap@10% | cap@20% |
|---|---|---|---|---|---|---|---|---|
| **LightGBM-Tweedie** ⭐ | **0.2531** | **1.4499** | 0.193 | 0.938 | **0.292** | **0.5713** | **0.702** | 0.818 |
| LightGBM-Poisson | 0.2610 | 1.4663 | 0.175 | 0.888 | 0.284 | 0.5705 | 0.697 | 0.820 |
| XGBoost-Poisson | 0.2644 | 1.4624 | 0.179 | **0.879** | 0.291 | 0.5685 | 0.699 | 0.820 |
| RandomForest | 0.2789 | 1.446 | **0.197** | 0.958 | 0.287 | 0.5668 | 0.697 | 0.813 |
| HistGB-Poisson | 0.2714 | 1.4923 | 0.145 | 0.892 | 0.280 | 0.5659 | 0.699 | 0.820 |
| Baseline (hist-mean) | 0.2876 | 1.4735 | 0.167 | 1.003 | 0.269 | 0.5372 | 0.668 | 0.800 |
| Poisson-GLM | 0.2986 | 1.589 | 0.031 | 0.888 | 0.271 | 0.5319 | 0.661 | 0.788 |

The gradient boosters cluster tightly at the top; **LightGBM-Tweedie leads on the
operational metric and on MAE/RMSE**. The linear Poisson-GLM actually
*underperforms* the historical-mean baseline. (`R²` is low across the board - expected
on a 95%-zero target; capture@K is the metric that matters.)

### Challenger hyperparameters (`src/model.py`)
| Model | Key settings |
|---|---|
| Baseline | `cell_blk_mean` - the train historical mean per (cell, block) |
| Poisson-GLM | `StandardScaler` → `PoissonRegressor(alpha=1e-3, max_iter=500)` |
| RandomForest | `n_estimators=120, max_depth=20, min_samples_leaf=40, max_samples=0.5` |
| HistGB-Poisson | `loss="poisson", max_iter=400, lr=0.06, max_depth=8, min_samples_leaf=80, l2=1.0` |
| XGBoost-Poisson | `count:poisson, n_estimators=500, lr=0.06, max_depth=7, subsample=0.8, colsample=0.8, min_child_weight=5, reg_lambda=1.0` |
| LightGBM-Poisson | `poisson, n_estimators=600, lr=0.05, num_leaves=63, min_child_samples=80, subsample=0.8, colsample=0.8, reg_lambda=1.0` |
| LightGBM-Tweedie ⭐ | see the block above (`p=1.5`, `lr=0.03`, `num_leaves=95`, early-stopped) |

---

## Deep learning - tried and lost

We implemented an **MLP**, an **LSTM**, and a **GRU** in PyTorch on the *same*
split, the *same* features, and a Tweedie loss, scored with the *same* metrics.
(Sequence models used per-`(cell, block)` windows of the last 14 days; all used a
Tweedie deviance loss with an `exp` rate head, Adam, early stopping.)

| Model | capture@5% | MAE | vs. tree champion |
|---|---|---|---|
| MLP (tabular) | 0.5469 | 0.320 | −1.8pp |
| GRU | 0.5337 | 0.345 | below baseline |
| LSTM | 0.5078 | 0.345 | well below baseline |

**No neural model beat the trees**, and the sequence models lost to even the
historical-mean baseline (0.5372). This is the **expected** result for short
(~150-day), zero-inflated, engineered-tabular data - and it matches the
literature (Grinsztajn et al. 2022; the M5 competition). Interestingly the MLP
had the *best* Poisson deviance (good probabilistic calibration) but worse
*ranking* - calibration ≠ top-K, and top-K is what we optimize for.

### Closing the NN gap with preprocessing
Trees are scale-invariant; NNs are not. Applying **RankGauss**
(`QuantileTransformer → normal`) to the heavy-tailed count features lifted the
MLP from **0.5469 → 0.5578** (+1.1pp) and cut MAE **0.32 → 0.28** (≈ the GBM).
Entity embeddings for cell/station did **not** help (overfit on the short panel).
The NN reached *parity on error* but never beat the GBM on **ranking** - exactly
what the literature predicts ("target parity, not dominance").

---

## Blending & stacking - marginal, not shipped

Five diverse base learners (LGBM-Tweedie, XGBoost-Poisson, HistGB-Poisson,
RandomForest, RankGauss-MLP) combined by equal mean, **rank-mean**,
capture-optimised weights, and a positive-linear stack.

- A **tree-only rank-mean blend** beats the single champion by a **small but consistent ~+0.10pp** (0.5713 → ~0.5724; +0.05 / +0.11 / +0.13pp across 3 seeds). The lift comes from the decorrelated HistGB/RandomForest members - *diversity beats individual accuracy*.
- **Adding the RankGauss-MLP *hurts*** every blend (drags to ~0.569) - it is weaker and gets over-weighted in rank space.
- An earlier +0.3pp blend lift was a **mirage**: it only appeared when base models were data-starved (trained on `train−21d`, making them weak *and* decorrelated). On full data the bases are strong and 0.96+ correlated, so the diversity gain evaporates.

**Decision: not shipped.** +0.10pp is not worth running 4 models instead of 1
(4× training/inference, and `predict.py` would need all four loaded + rank-averaged).
The single LightGBM-Tweedie captures ~99.8% of the blend's performance at 25% of
the cost.

---

## Key lessons
1. **Trees beat deep learning here** - and it's the expected outcome for short, zero-inflated, engineered-tabular data, not a tuning failure.
2. **The objective matters** - Tweedie > Poisson on the *same* trees; capture@5% (ranking) is what we select on, not RMSE/R².
3. **Preprocessing helps NNs, not trees** - RankGauss closed most of the NN gap; trees ignore scaling.
4. **The model is at its signal ceiling (~0.572)** - feature engineering gave the only real win (+0.67pp); deep learning lost; blending adds a marginal, complexity-heavy +0.10pp. Further gains require **new data**, not a cleverer algorithm.

## Reproduce
- `experiments/deep_models.py` - MLP / LSTM / GRU vs. trees
- `experiments/nn_preprocessing.py` - RankGauss + entity embeddings
- `experiments/stacking.py` - 5-model blending/stacking (blend-tuning regime)
- `experiments/blend_fulltrain.py` - full-train blend vs. champion (multi-seed)
- `experiments/improve_all.py` - expanding-window encoding + ensemble
- The champion + challenger numbers come straight from `python pipeline.py`
  (`artifacts/model_comparison.csv`, `outputs/run_summary.json`).

> Note: the deep-learning experiments require **PyTorch** (`pip install torch`),
> which is intentionally *not* in `requirements.txt` - it is not needed for the
> pipeline or the app.
