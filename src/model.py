"""
Step 6 -- Modelling & evaluation.

REASONING
=========
We are forecasting a non-negative, zero-inflated COUNT (violations per
cell-date-block). That dictates the modelling choices:

  * Loss = POISSON, not squared error. The target is count data; a Poisson /
    log-link objective respects "counts are >= 0 and variance grows with the
    mean" and avoids the negative, heteroscedastic predictions a plain MSE
    regressor produces. The gradient-boosting models therefore use a Poisson
    objective; the linear baseline is included for contrast.

  * Temporal split, never random. Train = Nov-2023..Feb-2024,
    Test = Mar-2024..Apr-2024. Forecasting skill must be measured on the
    future, and the lag features make a random split leak trivially.

  * A model is only useful if it beats the honest baseline. Baseline =
    "historical mean for this cell-block" (cell_blk_mean) -- exactly what an
    analyst would do with a spreadsheet. Beating it is the bar.

  * Metrics chosen for the job, not by reflex:
      - MAE / RMSE     : standard error magnitude.
      - Poisson deviance: proper scoring rule for counts.
      - R^2            : variance explained (reported, but treated with care
                         on a zero-inflated target).
      - TOP-K CAPTURE  : the operational metric. Patrols are scarce, so we ask
                         "if we visit the top-K% highest-predicted cell-time
                         slots, what share of all violations do we catch?"
                         This is what 'targeted enforcement' actually means.
"""
from __future__ import annotations

import json
import os
import sys

import joblib
import numpy as np
import pandas as pd
from sklearn.dummy import DummyRegressor
from sklearn.ensemble import RandomForestRegressor, HistGradientBoostingRegressor
from sklearn.linear_model import PoissonRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402

TARGET = "viol_count"


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #
def poisson_deviance(y_true, y_pred) -> float:
    """Mean Poisson deviance (lower is better). Guards log(0)."""
    yt = np.asarray(y_true, float)
    yp = np.clip(np.asarray(y_pred, float), 1e-9, None)
    # y*log(y/yhat) -> 0 as y->0; compute the log term only where y>0 to avoid
    # the 0*log(0) warning, which is mathematically a removable singularity.
    term = np.zeros_like(yt)
    pos = yt > 0
    term[pos] = yt[pos] * np.log(yt[pos] / yp[pos])
    return float(2.0 * np.mean(term - (yt - yp)))


def top_k_capture(y_true, y_pred, ks=(0.01, 0.05, 0.10, 0.20)) -> dict:
    """Share of actual violations captured in the top-K% predicted slots.

    This is the enforcement-efficiency curve: rank every cell-time slot by
    predicted risk, 'patrol' the top K%, and measure how much of the real
    violation volume that captures. A perfect-by-volume target is also the
    upper bound (rank by truth).
    """
    yt = np.asarray(y_true, float)
    yp = np.asarray(y_pred, float)
    n, total = len(yt), yt.sum()
    order = np.argsort(-yp)
    order_oracle = np.argsort(-yt)
    out = {}
    for k in ks:
        m = max(1, int(round(k * n)))
        out[f"capture@{int(k*100)}%"] = float(yt[order[:m]].sum() / total) if total else 0.0
        out[f"oracle@{int(k*100)}%"] = float(yt[order_oracle[:m]].sum() / total) if total else 0.0
    return out


def evaluate(name, y_true, y_pred) -> dict:
    y_pred = np.clip(y_pred, 0, None)
    res = {
        "model": name,
        "MAE": float(mean_absolute_error(y_true, y_pred)),
        "RMSE": float(np.sqrt(mean_squared_error(y_true, y_pred))),
        "R2": float(r2_score(y_true, y_pred)),
        "PoissonDev": poisson_deviance(y_true, y_pred),
    }
    res.update(top_k_capture(y_true, y_pred))
    return res


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
def build_models() -> dict:
    """Challenger models. Gradient boosters use a Poisson objective."""
    models = {
        "Baseline(hist-mean)": "BASELINE",  # special-cased: uses cell_blk_mean
        "Poisson-GLM": make_pipeline(
            StandardScaler(),
            PoissonRegressor(alpha=1e-3, max_iter=500),
        ),
        "RandomForest": RandomForestRegressor(
            n_estimators=120, max_depth=20, min_samples_leaf=40,
            max_samples=0.5, n_jobs=-1, random_state=config.RANDOM_STATE,
        ),
        "HistGB-Poisson": HistGradientBoostingRegressor(
            loss="poisson", max_iter=400, learning_rate=0.06,
            max_depth=8, min_samples_leaf=80, l2_regularization=1.0,
            random_state=config.RANDOM_STATE,
        ),
    }
    # Optional best-in-class boosters if installed.
    try:
        from xgboost import XGBRegressor
        models["XGBoost-Poisson"] = XGBRegressor(
            objective="count:poisson", n_estimators=500, learning_rate=0.06,
            max_depth=7, subsample=0.8, colsample_bytree=0.8,
            min_child_weight=5, reg_lambda=1.0, n_jobs=-1,
            random_state=config.RANDOM_STATE, tree_method="hist",
        )
    except Exception:
        pass
    try:
        from lightgbm import LGBMRegressor
        models["LightGBM-Poisson"] = LGBMRegressor(
            objective="poisson", n_estimators=600, learning_rate=0.05,
            num_leaves=63, min_child_samples=80, subsample=0.8,
            colsample_bytree=0.8, reg_lambda=1.0, n_jobs=-1,
            random_state=config.RANDOM_STATE, verbose=-1,
        )
    except Exception:
        pass
    return models


# --------------------------------------------------------------------------- #
# Train + evaluate all
# --------------------------------------------------------------------------- #
def train_and_evaluate(panel: pd.DataFrame, feature_cols: list[str],
                       save: bool = True, verbose: bool = True) -> dict:
    log = (lambda *a: print("  [model]", *a)) if verbose else (lambda *a: None)
    tr = panel[panel["split"] == "train"]
    te = panel[panel["split"] == "test"]
    Xtr, ytr = tr[feature_cols].astype(float), tr[TARGET].astype(float)
    Xte, yte = te[feature_cols].astype(float), te[TARGET].astype(float)
    log(f"train {len(tr):,} | test {len(te):,} | features {len(feature_cols)}")

    results, fitted = [], {}
    for name, mdl in build_models().items():
        if mdl == "BASELINE":
            pred = te["cell_blk_mean"].to_numpy()  # leak-safe historical prior
            results.append(evaluate(name, yte, pred))
            log(f"{name:22s} done (baseline)")
            continue
        mdl.fit(Xtr, ytr)
        pred = mdl.predict(Xte)
        res = evaluate(name, yte, pred)
        results.append(res)
        fitted[name] = mdl
        log(f"{name:22s} MAE={res['MAE']:.4f} RMSE={res['RMSE']:.3f} "
            f"R2={res['R2']:.3f} cap@5%={res['capture@5%']:.3f}")

    res_df = pd.DataFrame(results).set_index("model")
    # Pick best challenger (exclude baseline) by RMSE; tie-break by capture@5%.
    challengers = res_df.drop(index="Baseline(hist-mean)", errors="ignore")
    best_name = challengers.sort_values(["RMSE", "capture@5%"],
                                        ascending=[True, False]).index[0]
    best_model = fitted[best_name]
    log(f"BEST: {best_name}")

    out = {
        "results": res_df,
        "best_name": best_name,
        "best_model": best_model,
        "feature_cols": feature_cols,
    }

    if save:
        joblib.dump(best_model, os.path.join(config.ARTIFACTS_DIR, "best_model.joblib"))
        with open(os.path.join(config.ARTIFACTS_DIR, "feature_cols.json"), "w") as f:
            json.dump(feature_cols, f, indent=2)
        res_df.round(4).to_csv(os.path.join(config.ARTIFACTS_DIR, "model_comparison.csv"))
        with open(os.path.join(config.ARTIFACTS_DIR, "metrics.json"), "w") as f:
            json.dump({"best": best_name,
                       "scores": res_df.round(5).reset_index().to_dict("records")},
                      f, indent=2)
        log(f"saved best model + metrics to {config.ARTIFACTS_DIR}")

    return out


def feature_importance(model, feature_cols: list[str]) -> pd.Series:
    """Best-effort feature importance for the chosen model."""
    if hasattr(model, "feature_importances_"):
        imp = model.feature_importances_
    elif hasattr(model, "coef_"):
        imp = np.abs(model.coef_)
    else:  # pipeline -> last step
        last = model[-1] if hasattr(model, "__getitem__") else model
        imp = getattr(last, "feature_importances_",
                      np.abs(getattr(last, "coef_", np.zeros(len(feature_cols)))))
    return pd.Series(imp, index=feature_cols).sort_values(ascending=False)


if __name__ == "__main__":
    from src import ingest, impact, aggregate, features, feature_selection
    d = impact.add_event_impact(ingest.run(cache=True))
    panel, cmeta = aggregate.build_panel(d, verbose=False)
    panel, cols, enc = features.build_features(panel, cmeta, verbose=False)
    keep, _ = feature_selection.select(panel, cols, verbose=False)
    out = train_and_evaluate(panel, keep)
    print("\n", out["results"].round(4).to_string())
