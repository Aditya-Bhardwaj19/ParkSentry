"""
Verify the vectorised rank() matches the per-cell _row() loop exactly, and
measure the speedup. Run after pipeline.py.
"""
from __future__ import annotations
import os, sys, time, warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from predict import Forecaster  # noqa: E402

fc = Forecaster()
DATE, BLOCK = "2024-04-10", 2

# Vectorised feature matrix + predictions for ALL cells.
cells, X = fc._feature_matrix(DATE, BLOCK)
pred_vec = np.clip(fc.model.predict(X), 0, None)

# Reference: per-cell _row() loop (the old slow path) for ALL cells.
t0 = time.time()
rows = pd.concat([fc._row(c, DATE, BLOCK) for c in cells], ignore_index=True)
pred_row = np.clip(fc.model.predict(rows), 0, None)
slow_t = time.time() - t0

# Feature-level max diff across all cells.
rows.index = cells
maxdiff = {f: float(np.abs(X[f].to_numpy() - rows[f].to_numpy()).max()) for f in fc.features}
worst = sorted(maxdiff.items(), key=lambda x: -x[1])[:5]
print("top feature diffs (vectorised vs _row):")
for f, v in worst:
    print(f"  {f:16s} {v:.3e}")
print(f"max prediction diff (all {len(cells)} cells): {np.abs(pred_vec - pred_row).max():.3e}")

# Timing: full rank() (vectorised) vs the per-cell loop above.
t1 = time.time(); fc.rank(DATE, BLOCK, top=15); fast_t = time.time() - t1
print(f"\nper-cell _row loop : {slow_t:.2f}s")
print(f"vectorised rank()  : {fast_t:.2f}s  ({slow_t/max(fast_t,1e-9):.1f}x faster)")
print("PASS" if np.abs(pred_vec - pred_row).max() < 1e-4 else "FAIL — predictions diverge")
