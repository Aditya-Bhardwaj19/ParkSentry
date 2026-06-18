"""
Mappls (MapmyIndia) map integration for the ViolationProto dashboard.

WHY this module:
    Streamlit cannot drive the Mappls Web JS SDK directly (the SDK is browser
    JavaScript), so we render the interactive map by injecting a self-contained
    HTML+JS block via ``st.components.v1.html``. This module owns everything
    Mappls-specific -- credential resolution, OAuth token minting, and the HTML
    template -- so ``app.py`` stays a thin caller with a graceful fallback to
    pydeck when no Mappls credentials are configured.

CREDENTIALS (read from environment variables):
    MAPPLS_CLIENT_ID      OAuth client id      (from the Mappls console)
    MAPPLS_CLIENT_SECRET  OAuth client secret  (from the Mappls console)
    MAPPLS_MAP_SDK_KEY    static Map SDK / JS key (optional fallback)

    If client_id + client_secret are present we mint a short-lived access token
    (valid ~24h) via the documented OAuth client_credentials grant. Otherwise we
    fall back to the static Map SDK key. Either value is then used as the
    ``<token>`` segment of the vector map_sdk script URL.

Docs used:
    Token  : https://outpost.mappls.com/api/security/oauth/token
    Map SDK: https://apis.mappls.com/advancedmaps/api/<token>/map_sdk?v=3.0&layer=vector
"""
from __future__ import annotations

import json
import os

import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components

OAUTH_URL = "https://outpost.mappls.com/api/security/oauth/token"
MAP_SDK_URL = "https://apis.mappls.com/advancedmaps/api/{token}/map_sdk?v=3.0&layer=vector"


# --------------------------------------------------------------------------- #
# Credential / token resolution
# --------------------------------------------------------------------------- #
def credentials_present() -> bool:
    """True if enough credentials exist to attempt a Mappls render."""
    has_oauth = bool(os.getenv("MAPPLS_CLIENT_ID") and os.getenv("MAPPLS_CLIENT_SECRET"))
    return has_oauth or bool(os.getenv("MAPPLS_MAP_SDK_KEY"))


@st.cache_data(ttl=3600, show_spinner=False)
def _oauth_token(client_id: str, client_secret: str) -> str:
    """Mint an access token via the client_credentials grant (cached ~1h)."""
    resp = requests.post(
        OAUTH_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    resp.raise_for_status()
    token = resp.json().get("access_token")
    if not token:
        raise RuntimeError(f"No access_token in Mappls response: {resp.text[:200]}")
    return token


def resolve_token() -> str | None:
    """Return a usable map token, or None if credentials are missing/invalid.

    Raises nothing for the missing-credential case (returns None so the caller
    can fall back); only the OAuth round-trip can raise, which the caller wraps.
    """
    client_id = os.getenv("MAPPLS_CLIENT_ID")
    client_secret = os.getenv("MAPPLS_CLIENT_SECRET")
    if client_id and client_secret:
        return _oauth_token(client_id, client_secret)
    return os.getenv("MAPPLS_MAP_SDK_KEY") or None


# --------------------------------------------------------------------------- #
# HTML rendering
# --------------------------------------------------------------------------- #
def _epi_color(epi: float) -> str:
    """Yellow (low EPI) -> deep red (high EPI) gradient, as an rgb() string."""
    t = max(0.0, min(1.0, float(epi) / 100.0))
    r = int(230 - 30 * t)          # 230 -> 200
    g = int(200 * (1 - t))         # 200 -> 0
    return f"rgb({r},{g},40)"


def _points_payload(df: pd.DataFrame, lat_col: str, lon_col: str) -> list[dict]:
    """Build the minimal per-point dicts (incl. prebuilt popup HTML) for the JS."""
    pts = []
    for _, row in df.iterrows():
        epi = float(row.get("EPI", 0) or 0)
        rank = row.get("rank", "")
        station = str(row.get("dom_police_station", "") or "")
        junction = str(row.get("dom_junction", "") or "")
        peak = str(row.get("peak_block_label", "") or "")
        pred = row.get("pred_daily_viol", None)
        pred_txt = f"{float(pred):.1f}/day" if pred is not None and pd.notna(pred) else "n/a"
        popup = (
            f"<b>Rank #{rank}</b> &nbsp;EPI {epi:.1f}<br/>"
            f"{station} &mdash; {junction}<br/>"
            f"~{pred_txt} &middot; peak {peak}"
        )
        pts.append({
            "lat": float(row[lat_col]),
            "lon": float(row[lon_col]),
            "epi": epi,
            "color": _epi_color(epi),
            "popup": popup,
        })
    return pts


def render_map(df: pd.DataFrame, token: str, *,
               lat_col: str = "lat", lon_col: str = "lon",
               height: int = 560, zoom: int = 11,
               size_by_epi: bool = True) -> None:
    """Render an interactive Mappls vector map with one marker per row.

    Markers are custom colored dots (color/size encode the Enforcement Priority
    Index) with a click popup. Falls back to a visible error box inside the map
    if the SDK fails to load, so credential/key problems are obvious.
    """
    pts = _points_payload(df, lat_col, lon_col)
    if pts:
        center_lat = sum(p["lat"] for p in pts) / len(pts)
        center_lon = sum(p["lon"] for p in pts) / len(pts)
    else:
        center_lat, center_lon = 12.9716, 77.5946  # Bengaluru fallback

    sdk_url = MAP_SDK_URL.format(token=token)
    data_json = json.dumps(pts)

    html = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8"/>
  <style>
    html, body {{ margin:0; padding:0; height:100%; }}
    #map {{ width:100%; height:{height}px; border-radius:8px; }}
    #maperr {{ font-family:sans-serif; color:#b00; padding:10px; }}
    .epi-dot {{ border-radius:50%; opacity:.78; border:1px solid #7a0000;
                box-shadow:0 0 3px rgba(0,0,0,.4); }}
  </style>
</head>
<body>
  <div id="map"></div>
  <div id="maperr"></div>
  <script src="{sdk_url}" defer async></script>
  <script>
    var POINTS = {data_json};
    var CENTER = [{center_lat}, {center_lon}];
    var ZOOM = {zoom};
    var SIZE_BY_EPI = {str(size_by_epi).lower()};

    function showErr(msg) {{
      document.getElementById('maperr').innerHTML =
        'Mappls map failed to load: ' + msg +
        '<br/>Check the access token / Map SDK key and that the SDK is enabled in the Mappls console.';
    }}

    function initMap() {{
      try {{
        var map = new Mappls.Map('map', {{
          center: CENTER, zoom: ZOOM, zoomControl: true, location: false
        }});
        map.addListener('load', function () {{
          POINTS.forEach(function (p) {{
            var sz = SIZE_BY_EPI ? Math.max(10, Math.round(10 + p.epi * 0.22)) : 14;
            var dot = '<div class="epi-dot" style="width:' + sz + 'px;height:' + sz +
                      'px;background:' + p.color + ';"></div>';
            new Mappls.Marker({{
              map: map,
              position: {{ lat: p.lat, lng: p.lon }},
              fitbounds: false,
              html: dot,
              offset: [0, 0],
              popupHtml: p.popup
            }});
          }});
        }});
      }} catch (e) {{ showErr(e.message || e); }}
    }}

    // The SDK script is async; poll until the Mappls global is ready.
    (function waitForSdk(tries) {{
      if (typeof Mappls !== 'undefined' && Mappls.Map) {{ return initMap(); }}
      if (tries <= 0) {{ return showErr('SDK script did not load (timeout).'); }}
      setTimeout(function () {{ waitForSdk(tries - 1); }}, 150);
    }})(60);
  </script>
</body>
</html>
"""
    components.html(html, height=height + 12)
