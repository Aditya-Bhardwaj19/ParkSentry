import { useEffect, useRef, useState } from 'react';
import { loadMappls, mapplsGlobal } from '../mappls.js';
import { Icon } from './icons.jsx';

// Yellow (low EPI) -> deep red (high EPI).
function epiColor(epi) {
  const t = Math.max(0, Math.min(1, (epi || 0) / 100));
  const r = Math.round(230 - 30 * t);
  const g = Math.round(200 * (1 - t));
  return `rgb(${r},${g},40)`;
}

const avg = (arr, k) => arr.reduce((s, x) => s + x[k], 0) / arr.length;

function EpiLegend() {
  return (
    <div className="epi-legend">
      <div className="legend-title">Enforcement Priority Index</div>
      <div className="epi-bar" />
      <div className="epi-scale">
        <span>Low</span>
        <span>High</span>
      </div>
    </div>
  );
}

/**
 * Renders a Mappls vector map with one custom dot-marker per point.
 * Each point: { lat, lon, epi, popup }. Markers are sized/coloured by EPI and
 * show `popup` (HTML string) on click.
 */
export default function MapView({ points = [], height = 560, zoom = 11 }) {
  const elRef = useRef(null);
  const mapRef = useRef(null);
  const markersRef = useRef([]);
  const [error, setError] = useState(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    loadMappls()
      .then((M) => {
        if (cancelled || !elRef.current) return;
        const center = points.length
          ? [avg(points, 'lat'), avg(points, 'lon')]
          : [12.9716, 77.5946];
        mapRef.current = new M.Map(elRef.current, {
          center,
          zoom,
          zoomControl: true,
          location: false,
        });
        if (mapRef.current.addListener) {
          mapRef.current.addListener('load', () => !cancelled && setReady(true));
        }
        setTimeout(() => !cancelled && setReady(true), 1500);
      })
      .catch((e) => !cancelled && setError(e.message || String(e)));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const M = mapplsGlobal();
    if (!ready || !mapRef.current || !M) return;

    markersRef.current.forEach((mk) => {
      try {
        mk.remove();
      } catch (_) {
        /* best-effort cleanup */
      }
    });
    markersRef.current = [];

    points.forEach((p) => {
      const sz = Math.max(10, Math.round(10 + (p.epi || 0) * 0.22));
      const html =
        `<div style="width:${sz}px;height:${sz}px;border-radius:50%;` +
        `background:${epiColor(p.epi)};opacity:.8;border:1px solid #7a0000;` +
        `box-shadow:0 0 4px rgba(0,0,0,.5)"></div>`;
      try {
        const mk = new M.Marker({
          map: mapRef.current,
          position: { lat: p.lat, lng: p.lon },
          fitbounds: false,
          html,
          popupHtml: p.popup,
        });
        markersRef.current.push(mk);
      } catch (_) {
        /* skip a single bad marker */
      }
    });
  }, [points, ready]);

  // --- Empty / error state (e.g. no Mappls credentials) ---
  if (error) {
    const notConfigured = /credential|not set|not configured|token/i.test(error);
    return (
      <div className="map-state" style={{ height }}>
        <div className="map-state-inner">
          <div className="glyph">
            <Icon name="key" size={28} />
          </div>
          <h3>{notConfigured ? 'Maps need a Mappls key' : 'Map could not load'}</h3>
          <p>
            {notConfigured
              ? 'The data, rankings, forecaster and charts all work without a key — only the interactive map needs Mappls credentials.'
              : error}
          </p>
          <div className="steps">
            1. Create an app at <code>apps.mappls.com</code> and copy the keys.
            <br />
            2. Set <code>MAPPLS_CLIENT_ID</code> + <code>MAPPLS_CLIENT_SECRET</code>{' '}
            (or <code>MAPPLS_MAP_SDK_KEY</code>) in the gateway environment.
            <br />
            3. Ensure the Map SDK is enabled in the console, then reload.
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="map-wrap">
      <div ref={elRef} className="mapview" style={{ height }} />
      {!ready && (
        <div className="map-loading">
          <div className="spinner" />
          Loading map…
        </div>
      )}
      {ready && points.length > 0 && <EpiLegend />}
    </div>
  );
}
