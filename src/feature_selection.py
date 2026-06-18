"""
Step 5 -- Feature selection.

REASONING
=========
We engineered 27 features; not all earn their place. Redundant or
uninformative features add variance, slow training and hurt interpretability.
We apply three complementary, well-understood filters and keep a feature if it
survives -- belt-and-braces rather than trusting any single criterion:

  1. Near-zero variance  -- a feature that barely varies cannot discriminate.
  2. Pairwise redundancy  -- among features correlated > 0.95, keep the one
     more correlated with the target and drop the rest (e.g. overlapping
     rolling windows). Removing collinearity stabilises linear baselines and
     importance attribution.
  3. Predictive signal    -- union of (a) |Pearson| with the target and
     (b) mutual information (captures non-linear signal a correlation misses).
     A feature is "informative" if it clears a small threshold on either.

Selection is decided on the TRAIN split only (same anti-leakage discipline),
and we always *report* what was dropped and why rather than silently pruning.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
from sklearn.feature_selection import mutual_info_regression

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402

TARGET = "viol_count"


def select(panel: pd.DataFrame, feature_cols: list[str],
           corr_thresh: float = 0.95, mi_sample: int = 60_000,
           verbose: bool = True) -> tuple[list[str], dict]:
    """Return (selected_features, report)."""
    log = (lambda *a: print("  [select]", *a)) if verbose else (lambda *a: None)
    train = panel[panel["split"] == "train"]
    X = train[feature_cols].astype(float)
    y = train[TARGET].astype(float)

    report: dict = {"dropped": {}, "kept": []}

    # --- 1. near-zero variance ------------------------------------------ #
    variances = X.var()
    near_const = variances[variances < 1e-9].index.tolist()
    for f in near_const:
        report["dropped"][f] = "near-zero variance"
    cols = [c for c in feature_cols if c not in near_const]

    # --- 2. pairwise redundancy ----------------------------------------- #
    corr = X[cols].corr().abs()
    target_corr = X[cols].apply(lambda s: np.corrcoef(s, y)[0, 1]).abs().fillna(0)
    upper = corr.where(np.triu(np.ones(corr.shape), k=1).astype(bool))
    redundant = []
    for col in upper.columns:
        partners = upper.index[upper[col] > corr_thresh].tolist()
        for p in partners:
            # drop whichever of (col, p) is less correlated with the target
            weaker = p if target_corr[p] <= target_corr[col] else col
            if weaker not in redundant:
                redundant.append(weaker)
                report["dropped"][weaker] = f"redundant (|r|>{corr_thresh} with a kept feature)"
    cols = [c for c in cols if c not in redundant]

    # --- 3. predictive signal (Pearson OR mutual information) ----------- #
    samp = train.sample(min(mi_sample, len(train)), random_state=config.RANDOM_STATE)
    mi = mutual_info_regression(
        samp[cols].astype(float), samp[TARGET].astype(float),
        random_state=config.RANDOM_STATE,
    )
    mi = pd.Series(mi, index=cols)
    pear = pd.Series({c: abs(np.corrcoef(X[c], y)[0, 1]) for c in cols}).fillna(0)

    keep, weak = [], []
    for c in cols:
        if mi[c] >= 1e-4 or pear[c] >= 0.01:
            keep.append(c)
        else:
            weak.append(c)
            report["dropped"][c] = f"weak signal (MI={mi[c]:.4f}, |r|={pear[c]:.3f})"

    report["kept"] = keep
    report["mutual_info"] = mi.sort_values(ascending=False).round(4).to_dict()
    report["target_corr"] = pear.sort_values(ascending=False).round(3).to_dict()

    log(f"selected {len(keep)}/{len(feature_cols)} features; "
        f"dropped {len(report['dropped'])}")
    for f, why in report["dropped"].items():
        log(f"  - drop {f}: {why}")
    return keep, report


if __name__ == "__main__":
    from src import ingest, impact, aggregate, features
    d = impact.add_event_impact(ingest.run(cache=True))
    panel, cmeta = aggregate.build_panel(d, verbose=False)
    panel, cols, enc = features.build_features(panel, cmeta, verbose=False)
    keep, rep = select(panel, cols)
    print("\nTop MI:", dict(list(rep["mutual_info"].items())[:8]))
