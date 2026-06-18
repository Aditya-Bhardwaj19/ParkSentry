"""
Step 8 -- Visualization (EDA, model diagnostics, hotspot map).

REASONING
=========
A decision-support tool earns trust by being legible. We generate three
families of figures, each answering a stakeholder question:

  * EDA            -- "what does the parking-violation problem look like?"
                      (when, what vehicles, what severity, what trend)
  * Model          -- "can I trust the forecast?" (challenger comparison,
                      what the model keys on, and the enforcement-efficiency
                      capture curve that translates the model into patrols)
  * Hotspot map    -- "where do I send the patrol?" (a spatial density map of
                      Bengaluru with the top priority zones marked)

All figures render head-less (Agg backend) and are written to outputs/plots so
the pipeline runs unattended on a server.
"""
from __future__ import annotations

import os
import sys
from collections import Counter

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

try:
    import seaborn as sns
    sns.set_theme(style="whitegrid")
    _HAS_SNS = True
except Exception:
    _HAS_SNS = False

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402

PLOT_DIR = os.path.join(config.OUTPUTS_DIR, "plots")
os.makedirs(PLOT_DIR, exist_ok=True)


def _save(fig, name):
    fp = os.path.join(PLOT_DIR, name)
    fig.tight_layout()
    fig.savefig(fp, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return fp


def eda_plots(events: pd.DataFrame) -> list[str]:
    """Exploratory plots on the cleaned event table."""
    out = []

    # 1. Violation type mix
    c = Counter()
    for toks in events["tokens"]:
        for t in toks:
            c[str(t)] += 1
    top = pd.Series(dict(c.most_common(10))).sort_values()
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.barh(top.index, top.values, color="#c0392b")
    ax.set_title("Top parking-violation types")
    ax.set_xlabel("citations")
    out.append(_save(fig, "eda_violation_types.png"))

    # 2. Time-block + day-of-week activity
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    tb = events["time_block"].map(lambda b: config.TIME_BLOCKS[b][0]).value_counts()
    tb = tb.reindex([config.TIME_BLOCKS[i][0] for i in range(config.N_TIME_BLOCKS)]).fillna(0)
    axes[0].bar(range(len(tb)), tb.values, color="#2980b9")
    axes[0].set_xticks(range(len(tb)))
    axes[0].set_xticklabels([s.split(" (")[0] for s in tb.index], rotation=30, ha="right")
    axes[0].set_title("Violations by time block (local)")
    dow = events["dow"].value_counts().reindex(range(7)).fillna(0)
    axes[1].bar(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"], dow.values, color="#27ae60")
    axes[1].set_title("Violations by day of week")
    out.append(_save(fig, "eda_temporal.png"))

    # 3. Vehicle mix + monthly trend
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    veh = events["vehicle_type_clean"].value_counts().head(8).sort_values()
    axes[0].barh(veh.index, veh.values, color="#8e44ad")
    axes[0].set_title("Top vehicle types")
    mon = events.groupby(events["dt_local"].dt.tz_localize(None).dt.to_period("M").astype(str)).size()
    axes[1].plot(mon.index, mon.values, marker="o", color="#d35400")
    axes[1].set_title("Monthly violation volume")
    axes[1].tick_params(axis="x", rotation=30)
    out.append(_save(fig, "eda_vehicle_trend.png"))

    # 4. Congestion impact distribution
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.hist(events["impact_score"], bins=40, color="#16a085", edgecolor="white")
    ax.set_title("Per-event Congestion Impact Score distribution")
    ax.set_xlabel("impact score")
    out.append(_save(fig, "eda_impact_dist.png"))
    return out


def model_plots(results: pd.DataFrame, importance: pd.Series,
                y_true, y_pred) -> list[str]:
    out = []

    # 1. Model comparison (RMSE + capture@5%)
    fig, ax1 = plt.subplots(figsize=(9, 4.5))
    r = results.sort_values("RMSE")
    x = np.arange(len(r))
    ax1.bar(x - 0.2, r["RMSE"], width=0.4, label="RMSE", color="#34495e")
    ax1.set_ylabel("RMSE (lower better)")
    ax1.set_xticks(x)
    ax1.set_xticklabels(r.index, rotation=25, ha="right")
    ax2 = ax1.twinx()
    ax2.plot(x, r["capture@5%"], "o-", color="#e67e22", label="capture@5%")
    ax2.set_ylabel("capture@5% (higher better)")
    ax1.set_title("Model comparison: error vs enforcement efficiency")
    out.append(_save(fig, "model_comparison.png"))

    # 2. Feature importance
    fig, ax = plt.subplots(figsize=(8, 5))
    imp = importance.head(15).sort_values()
    ax.barh(imp.index, imp.values, color="#2c3e50")
    ax.set_title("Top-15 feature importance (best model)")
    out.append(_save(fig, "model_feature_importance.png"))

    # 3. Enforcement-efficiency capture curve
    yt, yp = np.asarray(y_true, float), np.asarray(y_pred, float)
    order = np.argsort(-yp)
    oracle = np.argsort(-yt)
    frac = np.linspace(0.01, 1.0, 100)
    cum_model, cum_oracle = [], []
    csum_m = np.cumsum(yt[order]); csum_o = np.cumsum(yt[oracle])
    tot = yt.sum() or 1.0          # guard: all-zero test target -> avoid div-by-zero
    n = len(yt)
    for f in frac:
        m = max(1, int(f * n))
        cum_model.append(csum_m[m - 1] / tot)
        cum_oracle.append(csum_o[m - 1] / tot)
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.plot(frac * 100, np.array(cum_model) * 100, label="Model", color="#c0392b", lw=2)
    ax.plot(frac * 100, np.array(cum_oracle) * 100, "--", label="Oracle (upper bound)", color="#7f8c8d")
    ax.plot([0, 100], [0, 100], ":", label="Random", color="#bdc3c7")
    ax.set_xlabel("% of cell-time slots patrolled (by predicted risk)")
    ax.set_ylabel("% of actual violations captured")
    ax.set_title("Enforcement-efficiency curve")
    ax.legend()
    out.append(_save(fig, "model_capture_curve.png"))
    return out


def hotspot_map(cells: pd.DataFrame, hotspots: pd.DataFrame, top_k: int = 30) -> list[str]:
    """Static spatial map: cell density + top-K priority hotspots marked."""
    out = []
    fig, ax = plt.subplots(figsize=(8.5, 8))
    sc = ax.scatter(cells["cell_lon"], cells["cell_lat"],
                    c=np.log1p(cells["total_events"]), s=12,
                    cmap="YlOrRd", alpha=0.7)
    plt.colorbar(sc, ax=ax, label="log(1 + violations) per cell")
    top = hotspots.head(top_k)
    ax.scatter(top["lon"], top["lat"], s=80, facecolors="none",
               edgecolors="#2c3e50", linewidths=1.5, label=f"Top-{top_k} priority cells")
    for _, r in top.head(8).iterrows():
        ax.annotate(f"#{int(r['rank'])}", (r["lon"], r["lat"]),
                    fontsize=8, fontweight="bold")
    ax.set_xlabel("longitude"); ax.set_ylabel("latitude")
    ax.set_title("Bengaluru illegal-parking density & priority hotspots")
    ax.legend(loc="upper right")
    out.append(_save(fig, "hotspot_map.png"))
    return out


def make_all(events, results, importance, y_true, y_pred, cells, hotspots) -> list[str]:
    paths = []
    paths += eda_plots(events)
    paths += model_plots(results, importance, y_true, y_pred)
    paths += hotspot_map(cells, hotspots)
    print(f"  [viz] wrote {len(paths)} figures to {PLOT_DIR}")
    return paths
