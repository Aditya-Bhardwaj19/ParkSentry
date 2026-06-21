import { useEffect, useRef, useState } from 'react';
import { loadMappls, mapplsGlobal } from '../mappls.js';
import { Icon } from './icons.jsx';
import { useT } from '../i18n/index.jsx';

// Yellow (low EPI) -> deep red (high EPI).
function epiColor(epi) {
  const t = Math.max(0, Math.min(1, (epi || 0) / 100));
  const r = Math.round(230 - 30 * t);
  const g = Math.round(200 * (1 - t));
  return `rgb(${r},${g},40)`;
}

const avg = (arr, k) => arr.reduce((s, x) => s + x[k], 0) / arr.length;

// Wrap popup HTML in a dark-theme card so the content stays legible over the
// light Mappls basemap (the SDK's default popup inherits no background).
const popupCard = (html) => `<div class="map-popup-card">${html || ''}</div>`;

function EpiLegend() {
  const { t } = useT();
  return (
    <div className="epi-legend">
      <div className="legend-title">{t('mapview.legendTitle')}</div>
      <div className="epi-bar" />
      <div className="epi-scale">
        <span>{t('mapview.low')}</span>
        <span>{t('mapview.high')}</span>
      </div>
    </div>
  );
}

/**
 * Renders a Mappls vector map with one custom dot-marker per point.
 * Each point: { lat, lon, epi, popup }. Markers are sized/coloured by EPI and
 * show `popup` (HTML string) on click.
 */
export default function MapView({ points = [], height = 560, zoom = 11, onSelect = null, route = null }) {
  const elRef = useRef(null);
  const mapIdRef = useRef(`mappls-map-${Math.random().toString(36).slice(2)}`);
  const mapRef = useRef(null);
  const markersRef = useRef([]);
  const routeRef = useRef(null);
  const stationRef = useRef(null);
  const [error, setError] = useState(null);
  const [ready, setReady] = useState(false);
  const { t } = useT();

  // Bridge so a marker's inline onclick (rendered into the SDK's DOM) can reach
  // React. Only the map that passes onSelect (the Priority Map) registers it.
  useEffect(() => {
    if (!onSelect) return undefined;
    window.__psSelectCell = onSelect;
    return () => {
      if (window.__psSelectCell === onSelect) delete window.__psSelectCell;
    };
  }, [onSelect]);

  useEffect(() => {
    let cancelled = false;
    loadMappls()
      .then((M) => {
        if (cancelled || !elRef.current) return;
        const center = points.length
          ? [avg(points, 'lat'), avg(points, 'lon')]
          : [12.9716, 77.5946];
        mapRef.current = new M.Map(mapIdRef.current, {
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
      const click =
        onSelect && p.id != null
          ? `onclick="window.__psSelectCell&&window.__psSelectCell('${String(p.id).replace(/['"\\]/g, '')}')"`
          : '';
      const html =
        `<div ${click} style="width:${sz}px;height:${sz}px;border-radius:50%;` +
        `background:${epiColor(p.epi)};opacity:.8;border:1px solid #7a0000;` +
        `box-shadow:0 0 4px rgba(0,0,0,.5)${onSelect ? ';cursor:pointer' : ''}"></div>`;
      try {
        const mk = new M.Marker({
          map: mapRef.current,
          position: { lat: p.lat, lng: p.lon },
          fitbounds: false,
          html,
          popupHtml: popupCard(p.popup),
        });
        markersRef.current.push(mk);
      } catch (_) {
        /* skip a single bad marker */
      }
    });
  }, [points, ready]);

  // Draw the station→cell road route (polyline) + a station marker.
  useEffect(() => {
    const M = mapplsGlobal();
    if (!ready || !mapRef.current || !M) return;
    try { routeRef.current && routeRef.current.remove(); } catch (_) { /* */ }
    try { stationRef.current && stationRef.current.remove(); } catch (_) { /* */ }
    routeRef.current = null;
    stationRef.current = null;
    if (!route || !route.path || !route.path.length) return;
    try {
      routeRef.current = new M.Polyline({
        map: mapRef.current,
        path: route.path.map(([lat, lng]) => ({ lat, lng })),
        strokeColor: '#2563eb',
        strokeWeight: 5,
        strokeOpacity: 0.85,
        fitbounds: true,
      });
    } catch (_) {
      /* polyline unsupported -> skip the line, still show the station marker */
    }
    if (route.from) {
      try {
        const html =
          '<div style="width:16px;height:16px;border-radius:50%;background:#2563eb;' +
          'border:2px solid #fff;box-shadow:0 0 5px rgba(0,0,0,.6)"></div>';
        stationRef.current = new M.Marker({
          map: mapRef.current,
          position: { lat: route.from.lat, lng: route.from.lon },
          fitbounds: false,
          html,
          popupHtml: popupCard(`🚓 ${route.from.label || 'Station'}`),
        });
      } catch (_) {
        /* skip station marker */
      }
    }
  }, [route, ready]);

  // --- Empty / error state (e.g. no Mappls credentials) ---
  if (error) {
    const notConfigured = /credential|not set|not configured|token/i.test(error);
    return (
      <div className="map-state" style={{ height }}>
        <div className="map-state-inner">
          <div className="glyph">
            <Icon name="key" size={28} />
          </div>
          <h3>{notConfigured ? t('mapview.needKey') : t('mapview.couldNotLoad')}</h3>
          <p>{notConfigured ? t('mapview.needKeyBody') : error}</p>
          <div className="steps">
            1. {t('mapview.step1')}
            <br />
            2. {t('mapview.step2')}
            <br />
            3. {t('mapview.step3')}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="map-wrap">
      <div
        ref={elRef}
        id={mapIdRef.current}
        className="mapview"
        style={{ height }}
      />
      {!ready && (
        <div className="map-loading">
          <div className="spinner" />
          {t('mapview.loading')}
        </div>
      )}
      {ready && points.length > 0 && <EpiLegend />}
    </div>
  );
}
