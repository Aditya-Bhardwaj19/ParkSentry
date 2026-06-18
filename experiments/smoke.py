"""Fast smoke test of the modified pipeline (no artifact writes)."""
from __future__ import annotations
import os, sys, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import ingest, impact, aggregate, features, feature_selection, model  # noqa

NEW = ["holiday", "nbr_roll7", "nbr_blk_mean", "lag14", "roll14_mean", "ewm7"]

d = impact.add_event_impact(ingest.run(nrows=80000, cache=False))
panel, cmeta = aggregate.build_panel(d, verbose=False)
panel, cols, enc = features.build_features(panel, cmeta, verbose=False)
print("total features:", len(cols))
print("new features present:", [c for c in NEW if c in cols])
print("feature NaNs:", int(panel[cols].isna().sum().sum()))
keep, rep = feature_selection.select(panel, cols, verbose=False)
print("selected count:", len(keep))
print("new features kept:", [c for c in NEW if c in keep])
print("new features dropped:", {c: rep["dropped"].get(c) for c in NEW if c not in keep})
out = model.train_and_evaluate(panel, keep, save=False, verbose=True)
print("BEST:", out["best_name"])
