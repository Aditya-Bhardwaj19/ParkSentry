"""
Train/serve skew check.

The Forecaster (predict.py) rebuilds features by hand from saved artifacts. This
script confirms those reconstructed features MATCH the training panel's features
for the same (cell, date, time_block) rows — i.e. no train/serve skew that would
make live forecasts diverge from the trained model. Run after pipeline.py.
"""
from __future__ import annotations
import os, sys, warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src import ingest, impact, aggregate, features  # noqa: E402
from predict import Forecaster  # noqa: E402

# Rebuild the panel exactly as training did.
d = impact.add_event_impact(ingest.run(cache=True))
panel, cmeta = aggregate.build_panel(d, verbose=False)
panel, cols, enc = features.build_features(panel, cmeta, verbose=False)

fc = Forecaster()
feats = fc.features
test = panel[panel["split"] == "test"]
sample = test.sample(60, random_state=7)

maxdiff = {f: 0.0 for f in feats}
pred_diffs = []
for _, r in sample.iterrows():
    row = fc._row(r["cell"], pd.Timestamp(r["date"]), int(r["time_block"]))
    for col in feats:
        maxdiff[col] = max(maxdiff[col], abs(float(row[col].iloc[0]) - float(r[col])))

print("max abs diff per feature (Forecaster reconstruction vs training panel):")
for col, v in sorted(maxdiff.items(), key=lambda x: -x[1]):
    flag = "  <-- check" if v > 1e-3 else ""
    print(f"  {col:16s} {v:.3e}{flag}")
print(f"\nOVERALL max abs diff: {max(maxdiff.values()):.3e}")
print("PASS" if max(maxdiff.values()) < 1e-2 else "FAIL — investigate skew")
