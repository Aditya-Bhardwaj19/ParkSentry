"""
ViolationProto -- interactive prototype dashboard (Theme 1).

Run:  streamlit run app.py

Consumes the artifacts written by pipeline.py and exposes the solution to a
non-technical enforcement planner:
  * KPI strip            -- the headline forecasting & efficiency numbers
  * Priority map         -- where to send patrols (EPI-ranked hotspots)
  * Priority table       -- the ranked, filterable hotspot list
  * Live forecaster      -- score any cell/date/time-block on demand
  * Model & EDA          -- evidence the forecast can be trusted
"""
from __future__ import annotations

import json
import os

import pandas as pd
import streamlit as st

import config
import mappls_map

st.set_page_config(page_title="ViolationProto - Parking Congestion Intelligence",
                   layout="wide", page_icon="🚦")

OUT, ART = config.OUTPUTS_DIR, config.ARTIFACTS_DIR
PLOTS = os.path.join(OUT, "plots")


@st.cache_data
def load():
    hs = pd.read_csv(os.path.join(OUT, "cell_priority_ranked.csv"))
    zones = pd.read_csv(os.path.join(OUT, "hotspot_zones.csv"))
    cells = pd.read_csv(os.path.join(OUT, "cells_annotated.csv"))
    with open(os.path.join(OUT, "run_summary.json")) as f:
        summary = json.load(f)
    comp = pd.read_csv(os.path.join(ART, "model_comparison.csv"))
    return hs, zones, cells, summary, comp


if not os.path.exists(os.path.join(OUT, "cell_priority_ranked.csv")):
    st.error("No outputs found. Run `python pipeline.py` first to generate artifacts.")
    st.stop()

hs, zones, cells, summary, comp = load()
BLOCK_LABELS = {i: config.TIME_BLOCKS[i][0] for i in range(config.N_TIME_BLOCKS)}


def render_geo(view: pd.DataFrame, *, lat_col: str = "lat", lon_col: str = "lon",
               height: int = 560, size_by_epi: bool = True) -> None:
    """Render a hotspot map: Mappls (if credentials set) → pydeck → st.map.

    A single rendering entry point so both the Priority Map and the Live
    Forecaster get the Mappls map when credentials exist and degrade gracefully
    otherwise. Mappls credentials come from env vars (see mappls_map.py).
    """
    # 1) Mappls — preferred when credentials are configured.
    if mappls_map.credentials_present():
        try:
            token = mappls_map.resolve_token()
            if token:
                mappls_map.render_map(view, token, lat_col=lat_col, lon_col=lon_col,
                                      height=height, size_by_epi=size_by_epi)
                return
        except Exception as e:  # bad/expired key, network, etc. — fall through
            st.warning(f"Mappls map unavailable ({e}); falling back to default map.")

    # 2) pydeck — rich fallback (current behaviour).
    try:
        import pydeck as pdk
        v = view.copy()
        v["radius"] = 30 + v.get("EPI", 0) * 5 if size_by_epi else 60
        layer = pdk.Layer(
            "ScatterplotLayer", data=v,
            get_position=f"[{lon_col}, {lat_col}]", get_radius="radius",
            get_fill_color="[200, 30 + EPI, 30, 160]" if "EPI" in v else "[200, 60, 30, 160]",
            pickable=True,
        )
        tooltip = {"html": "<b>Rank #{rank}</b> (EPI {EPI})<br/>"
                           "{dom_police_station} — {dom_junction}<br/>"
                           "~{pred_daily_viol}/day · peak {peak_block_label}"} \
            if "rank" in v else None
        mid = v[[lat_col, lon_col]].mean()
        st.pydeck_chart(pdk.Deck(
            layers=[layer],
            initial_view_state=pdk.ViewState(latitude=float(mid[lat_col]),
                                             longitude=float(mid[lon_col]),
                                             zoom=11, pitch=0),
            tooltip=tooltip, map_style=None))
        return
    except Exception as e:  # 3) bare st.map fallback
        st.map(view.rename(columns={lat_col: "latitude", lon_col: "longitude"})
               [["latitude", "longitude"]])
        st.caption(f"(pydeck unavailable: {e})")


st.title("🚦 ViolationProto — Parking-Induced Congestion Intelligence")
st.caption("Theme 1 · Detect illegal-parking hotspots, quantify congestion impact, "
           "and target enforcement. Data: Bengaluru police parking violations.")

# ---------------- KPI strip ---------------------------------------------- #
k = st.columns(5)
k[0].metric("Clean violations", f"{summary['events_clean']:,}")
k[1].metric("Priority cells / zones", f"{summary['n_cells']:,} / {summary['n_zones']:,}")
k[2].metric("Best model", summary["best_model"],
            help=f"RMSE {summary['best_RMSE']} vs baseline {summary['baseline_RMSE']}")
k[3].metric("Top-5% capture", f"{summary['capture_at_5pct']*100:.0f}%",
            help="Share of all violations caught by patrolling the top 5% predicted slots")
k[4].metric("Top-1% capture", f"{summary['capture_at_1pct']*100:.0f}%")

tab_map, tab_table, tab_forecast, tab_model = st.tabs(
    ["🗺️ Priority Map", "📋 Priority List", "🔮 Live Forecaster", "📈 Model & EDA"])

# ---------------- Priority map ------------------------------------------- #
with tab_map:
    st.caption("Each dot is a ~150 m enforcement cell (a specific road stretch), "
               "sized & coloured by its Enforcement Priority Index.")
    c1, c2 = st.columns([1, 3])
    with c1:
        top_n = st.slider("Show top-N priority cells", 10, min(500, len(hs)), 100, step=10)
        blocks = st.multiselect("Peak time block",
                                options=list(BLOCK_LABELS.values()),
                                default=list(BLOCK_LABELS.values()))
        stations = st.multiselect("Police station",
                                  options=sorted(hs["dom_police_station"].unique()),
                                  default=[])
    view = hs[hs["peak_block_label"].isin(blocks)]
    if stations:
        view = view[view["dom_police_station"].isin(stations)]
    view = view.head(top_n)

    with c2:
        render_geo(view, height=560, size_by_epi=True)

# ---------------- Priority table ----------------------------------------- #
with tab_table:
    st.subheader("Enforcement Priority Index — ranked cells (primary targeting)")
    cols = ["rank", "EPI", "pred_daily_viol", "actual_daily_viol",
            "mean_impact_per_viol", "total_events", "peak_block_label",
            "dom_police_station", "dom_junction"]
    st.dataframe(hs[cols], use_container_width=True, height=460, hide_index=True)
    st.download_button("⬇ Download full cell ranking (CSV)",
                       hs.to_csv(index=False), "cell_priority_ranked.csv")
    with st.expander("Secondary: DBSCAN density zones (beat-level grouping)"):
        st.caption("In dense contiguous cores DBSCAN merges many cells into one "
                   "zone, so zones inform beat allocation, not pin-point targeting.")
        st.dataframe(zones, use_container_width=True, height=300, hide_index=True)

# ---------------- Live forecaster ---------------------------------------- #
with tab_forecast:
    st.subheader("Forecast parking-violation risk for any zone / time")
    st.caption("Rebuilds the model's features causally and scores on demand.")
    try:
        from predict import Forecaster
        fc = st.cache_resource(lambda: Forecaster())()
        c1, c2, c3 = st.columns(3)
        date = c1.date_input("Date", value=pd.Timestamp("2024-04-10"))
        block = c2.selectbox("Time block", options=list(BLOCK_LABELS.keys()),
                             format_func=lambda b: BLOCK_LABELS[b], index=2)
        topn = c3.slider("Top cells", 5, 50, 15)
        if st.button("Run forecast", type="primary"):
            ranked = fc.rank(str(date), int(block), top=topn)
            st.dataframe(ranked, use_container_width=True, hide_index=True)
            # Adapt the forecaster output to the shared map schema: derive an EPI
            # in [0,100] from the predicted count so markers size/colour sensibly.
            mx = float(ranked["pred_viol"].max()) or 1.0
            view = ranked.assign(
                rank=range(1, len(ranked) + 1),
                EPI=(ranked["pred_viol"] / mx * 100).round(1),
                pred_daily_viol=ranked["pred_viol"],
                dom_police_station=ranked["police_station"],
                dom_junction="",
                peak_block_label=BLOCK_LABELS[int(block)],
            )
            render_geo(view, lat_col="cell_lat", lon_col="cell_lon",
                       height=480, size_by_epi=True)
    except Exception as e:
        st.warning(f"Forecaster unavailable: {e}")

# ---------------- Model & EDA -------------------------------------------- #
with tab_model:
    st.subheader("Model comparison")
    st.dataframe(comp, use_container_width=True, hide_index=True)
    g = st.columns(2)
    figs = [
        ("model_capture_curve.png", "Enforcement-efficiency curve"),
        ("model_feature_importance.png", "What the model keys on"),
        ("model_comparison.png", "Error vs efficiency"),
        ("hotspot_map.png", "Density & priority hotspots"),
        ("eda_temporal.png", "When violations happen"),
        ("eda_violation_types.png", "Violation mix"),
        ("eda_vehicle_trend.png", "Vehicles & monthly trend"),
        ("eda_impact_dist.png", "Impact score distribution"),
    ]
    for i, (fn, cap) in enumerate(figs):
        fp = os.path.join(PLOTS, fn)
        if os.path.exists(fp):
            g[i % 2].image(fp, caption=cap, use_column_width=True)
