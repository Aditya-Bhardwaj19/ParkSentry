"""
Offline model-improvement search for ViolationProto / ParkSentry.

GOAL
----
Find a model that beats the current best (RandomForest, RMSE ~1.449,
capture@5% ~0.559) on the SAME temporal hold-out and the SAME metrics, with NO
leakage. This script is read-only w.r.t. production: it never writes to
artifacts/ — it just trains candidates and prints a comparison table.

WHAT IT TRIES (motivated by the research)
  * Tweedie objective (LGBM/XGB) — designed for zero-inflated counts; the
    literature shows it beats Poisson on this data shape. Variance power swept.
  * Tuned boosters with EARLY STOPPING on a temporal inner-validation slice
    (last 21 days of train) — capacity + regularisation chosen by data.
  * Hurdle / two-stage model — P(count>0) classifier × E[count|>0] regressor;
    a direct attack on zero-inflation.
  * Stacked ensemble — non-negative least-squares blend of diverse base models,
    weights fit on the inner-validation slice (leak-safe).

All candidates use the EXISTING selected feature set so the winner stays
drop-in compatible with predict.py (Part 2, run separately, probes the feature
ceiling).

Run:  python experiments/improve_model.py
"""
from __future__ import annotations

import os
import sys
import time
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import config  # noqa: E402
from src import ingest, impact, aggregate, features, feature_selection  # noqa: E402
from src.model import evaluate, TARGET  # noqa: E402

RS = config.RANDOM_STATE
INNER_VAL_DAYS = 21  # last N days of train held out for early stopping / blend weights


# --------------------------------------------------------------------------- #
def load_panel():
    t0 = time.time()
    d = impact.add_event_impact(ingest.run(cache=True))
    panel, cmeta = aggregate.build_panel(d, verbose=False)
    panel, cols, enc = features.build_features(panel, cmeta, verbose=False)
    keep, _ = feature_selection.select(panel, cols, verbose=False)
    print(f"[data] panel {len(panel):,} rows | {len(keep)} features | "
          f"{time.time()-t0:.1f}s")
    return panel, keep


def temporal_splits(panel, feature_cols):
    """train / test (production split) + an inner fit/val slice for tuning."""
    dt = pd.to_datetime(panel["date"])
    train_end = pd.Timestamp(config.TRAIN_END_DATE)
    inner_cut = train_end - pd.Timedelta(days=INNER_VAL_DAYS)

    tr = panel[panel["split"] == "train"]
    te = panel[panel["split"] == "test"]
    fit = panel[dt <= inner_cut]
    val = panel[(dt > inner_cut) & (dt <= train_end)]

    def XY(df):
        return df[feature_cols].astype(float).values, df[TARGET].astype(float).values

    return {
        "Xtr": XY(tr)[0], "ytr": XY(tr)[1],
        "Xte": XY(te)[0], "yte": XY(te)[1],
        "Xfit": XY(fit)[0], "yfit": XY(fit)[1],
        "Xval": XY(val)[0], "yval": XY(val)[1],
        "test_df": te,
    }


def cap5(y, p):
    from src.model import top_k_capture
    return top_k_capture(y, p)["capture@5%"]


# --------------------------------------------------------------------------- #
# Candidate trainers — each returns test-set predictions (and logs val tuning).
# --------------------------------------------------------------------------- #
def ref_models():
    """The current production zoo, retrained here for an apples-to-apples table."""
    from sklearn.ensemble import RandomForestRegressor, HistGradientBoostingRegressor
    from sklearn.linear_model import PoissonRegressor
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    m = {
        "Poisson-GLM": make_pipeline(StandardScaler(),
                                     PoissonRegressor(alpha=1e-3, max_iter=500)),
        "RandomForest": RandomForestRegressor(
            n_estimators=120, max_depth=20, min_samples_leaf=40, max_samples=0.5,
            n_jobs=-1, random_state=RS),
        "HistGB-Poisson": HistGradientBoostingRegressor(
            loss="poisson", max_iter=400, learning_rate=0.06, max_depth=8,
            min_samples_leaf=80, l2_regularization=1.0, random_state=RS),
    }
    return m


def lgbm(obj, **kw):
    from lightgbm import LGBMRegressor
    base = dict(n_estimators=800, learning_rate=0.05, num_leaves=63,
                min_child_samples=80, subsample=0.8, colsample_bytree=0.8,
                reg_lambda=1.0, n_jobs=-1, random_state=RS, verbose=-1)
    base.update(kw)
    return LGBMRegressor(objective=obj, **base)


def xgb(obj, **kw):
    from xgboost import XGBRegressor
    base = dict(n_estimators=800, learning_rate=0.05, max_depth=7, subsample=0.8,
                colsample_bytree=0.8, min_child_weight=5, reg_lambda=1.0,
                n_jobs=-1, random_state=RS, tree_method="hist")
    base.update(kw)
    return XGBRegressor(objective=obj, **base)


def fit_es_lgbm(model, S, refit_full=True):
    """Fit LGBM with early stopping on the inner val slice; refit on full train."""
    import lightgbm as lgb
    model.fit(S["Xfit"], S["yfit"], eval_set=[(S["Xval"], S["yval"])],
              eval_metric="rmse",
              callbacks=[lgb.early_stopping(60, verbose=False), lgb.log_evaluation(0)])
    best_it = model.best_iteration_ or model.n_estimators
    if refit_full:
        model.set_params(n_estimators=int(best_it))
        model.fit(S["Xtr"], S["ytr"])
    return model, best_it


def fit_es_xgb(model, S, refit_full=True):
    model.set_params(early_stopping_rounds=60, eval_metric="rmse")
    model.fit(S["Xfit"], S["yfit"], eval_set=[(S["Xval"], S["yval"])], verbose=False)
    best_it = int(getattr(model, "best_iteration", model.n_estimators) or model.n_estimators) + 1
    if refit_full:
        model.set_params(n_estimators=best_it, early_stopping_rounds=None)
        model.fit(S["Xtr"], S["ytr"])
    return model, best_it


# --------------------------------------------------------------------------- #
def run():
    panel, feats = load_panel()
    S = temporal_splits(panel, feats)
    yte = S["yte"]
    results, preds = [], {}

    def record(name, p):
        p = np.clip(p, 0, None)
        results.append(evaluate(name, yte, p))
        preds[name] = p
        r = results[-1]
        print(f"  {name:26s} RMSE={r['RMSE']:.4f}  cap@5%={r['capture@5%']:.4f}  "
              f"cap@1%={r['capture@1%']:.4f}  PoisDev={r['PoissonDev']:.4f}")

    # ---- Baseline + reference zoo --------------------------------------- #
    print("\n[1] reference models")
    record("Baseline(hist-mean)", S["test_df"]["cell_blk_mean"].to_numpy())
    for name, m in ref_models().items():
        m.fit(S["Xtr"], S["ytr"])
        record(name, m.predict(S["Xte"]))

    # ---- Poisson boosters (current configs, refit here) ----------------- #
    print("\n[2] Poisson boosters")
    mp = lgbm("poisson", n_estimators=600); mp.fit(S["Xtr"], S["ytr"])
    record("LGBM-Poisson", mp.predict(S["Xte"]))
    xp = xgb("count:poisson", n_estimators=500); xp.fit(S["Xtr"], S["ytr"])
    record("XGB-Poisson", xp.predict(S["Xte"]))

    # ---- Tweedie sweep (LGBM) ------------------------------------------- #
    print("\n[3] Tweedie objective (variance-power sweep on inner val)")
    best_pw, best_pw_score = None, -1
    for pw in (1.1, 1.3, 1.5, 1.7):
        m = lgbm("tweedie", tweedie_variance_power=pw, n_estimators=600)
        m.fit(S["Xfit"], S["yfit"])
        sc = cap5(S["yval"], np.clip(m.predict(S["Xval"]), 0, None))
        print(f"    power {pw}: val cap@5%={sc:.4f}")
        if sc > best_pw_score:
            best_pw, best_pw_score = pw, sc
    mt = lgbm("tweedie", tweedie_variance_power=best_pw, n_estimators=600)
    mt.fit(S["Xtr"], S["ytr"])
    record(f"LGBM-Tweedie(p={best_pw})", mt.predict(S["Xte"]))
    xt = xgb("reg:tweedie", tweedie_variance_power=best_pw, n_estimators=600)
    xt.fit(S["Xtr"], S["ytr"])
    record(f"XGB-Tweedie(p={best_pw})", xt.predict(S["Xte"]))

    # ---- Tuned boosters with early stopping ----------------------------- #
    print("\n[4] tuned boosters (early stopping on inner val)")
    lt = lgbm("poisson", n_estimators=2000, num_leaves=95, learning_rate=0.03,
              min_child_samples=60)
    lt, it1 = fit_es_lgbm(lt, S)
    record(f"LGBM-Poisson-tuned(it={it1})", lt.predict(S["Xte"]))

    ltw = lgbm("tweedie", tweedie_variance_power=best_pw, n_estimators=2000,
               num_leaves=95, learning_rate=0.03, min_child_samples=60)
    ltw, it2 = fit_es_lgbm(ltw, S)
    record(f"LGBM-Tweedie-tuned(it={it2})", ltw.predict(S["Xte"]))

    xt2 = xgb("count:poisson", n_estimators=2000, max_depth=8, learning_rate=0.03)
    xt2, it3 = fit_es_xgb(xt2, S)
    record(f"XGB-Poisson-tuned(it={it3})", xt2.predict(S["Xte"]))

    # ---- Hurdle / two-stage --------------------------------------------- #
    print("\n[5] hurdle (P(>0) classifier x E[count|>0] regressor)")
    from lightgbm import LGBMClassifier
    clf = LGBMClassifier(n_estimators=600, learning_rate=0.05, num_leaves=63,
                         min_child_samples=80, subsample=0.8, colsample_bytree=0.8,
                         reg_lambda=1.0, n_jobs=-1, random_state=RS, verbose=-1)
    clf.fit(S["Xtr"], (S["ytr"] > 0).astype(int))
    pos = S["ytr"] > 0
    reg = lgbm("poisson", n_estimators=600)
    reg.fit(S["Xtr"][pos], S["ytr"][pos])
    p_pos = clf.predict_proba(S["Xte"])[:, 1]
    e_cond = np.clip(reg.predict(S["Xte"]), 0, None)
    record("Hurdle(LGBM)", p_pos * e_cond)

    # ---- Stacked ensemble (NNLS weights on inner val) ------------------- #
    print("\n[6] stacked ensemble (non-negative LS blend)")
    from scipy.optimize import nnls
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.linear_model import PoissonRegressor
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    base_specs = {
        "glm": lambda: make_pipeline(StandardScaler(),
                                     PoissonRegressor(alpha=1e-3, max_iter=500)),
        "rf": lambda: RandomForestRegressor(n_estimators=120, max_depth=20,
                                            min_samples_leaf=40, max_samples=0.5,
                                            n_jobs=-1, random_state=RS),
        "lgbm_pois": lambda: lgbm("poisson", n_estimators=600),
        "lgbm_tw": lambda: lgbm("tweedie", tweedie_variance_power=best_pw, n_estimators=600),
        "xgb_pois": lambda: xgb("count:poisson", n_estimators=500),
    }
    val_P, test_P, names = [], [], []
    for nm, mk in base_specs.items():
        mfit = mk(); mfit.fit(S["Xfit"], S["yfit"])
        val_P.append(np.clip(mfit.predict(S["Xval"]), 0, None))
        mfull = mk(); mfull.fit(S["Xtr"], S["ytr"])
        test_P.append(np.clip(mfull.predict(S["Xte"]), 0, None))
        names.append(nm)
    val_P = np.column_stack(val_P)
    test_P = np.column_stack(test_P)
    w, _ = nnls(val_P, S["yval"])
    wnorm = w / (w.sum() or 1.0)
    print("    blend weights:", {n: round(float(x), 3) for n, x in zip(names, wnorm)})
    record("Stack(NNLS)", test_P @ w)

    # ---- Summary -------------------------------------------------------- #
    df = pd.DataFrame(results).set_index("model")
    cols = ["RMSE", "MAE", "R2", "PoissonDev", "capture@1%", "capture@5%",
            "capture@10%", "capture@20%"]
    df = df[cols].sort_values(["capture@5%", "RMSE"], ascending=[False, True])
    os.makedirs(os.path.join(ROOT, "experiments"), exist_ok=True)
    df.round(4).to_csv(os.path.join(ROOT, "experiments", "model_search_results.csv"))

    print("\n" + "=" * 78)
    print("MODEL SEARCH — sorted by capture@5% (operational metric), then RMSE")
    print("=" * 78)
    print(df.round(4).to_string())
    base = df.loc["Baseline(hist-mean)"]
    rf = df.loc["RandomForest"]
    best = df.index[0]
    print(f"\nBaseline   : RMSE {base['RMSE']:.4f}  cap@5% {base['capture@5%']:.4f}")
    print(f"Current RF : RMSE {rf['RMSE']:.4f}  cap@5% {rf['capture@5%']:.4f}")
    print(f"NEW BEST   : {best}  RMSE {df.iloc[0]['RMSE']:.4f}  "
          f"cap@5% {df.iloc[0]['capture@5%']:.4f}")
    print("\nsaved -> experiments/model_search_results.csv")


if __name__ == "__main__":
    run()
