import { useEffect, useRef, useState } from 'react';
import { loadMappls, mapplsGlobal } from '../mappls.js';

// Yellow (low EPI) -> deep red (high EPI).
function epiColor(epi) {
  const t = Math.max(0, Math.min(1, (epi || 0) / 100));
  const r = Math.round(230 - 30 * t);
  const g = Math.round(200 * (1 - t));
  return `rgb(${r},${g},40)`;
}

const avg = (arr, k) => arr.reduce((s, x) => s + x[k], 0) / arr.length;

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

  // Initialise the map once.
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
        // Fallback in case the 'load' event doesn't fire on this build.
        setTimeout(() => !cancelled && setReady(true), 1500);
      })
      .catch((e) => !cancelled && setError(e.message || String(e)));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // (Re)draw markers when the points change or the map becomes ready.
  useEffect(() => {
    const M = mapplsGlobal();
    if (!ready || !mapRef.current || !M) return;

    markersRef.current.forEach((mk) => {
      try {
        mk.remove();
      } catch (_) {
        /* some builds expose removeLayer instead; best-effort cleanup */
      }
    });
    markersRef.current = [];

    points.forEach((p) => {
      const sz = Math.max(10, Math.round(10 + (p.epi || 0) * 0.22));
      const html =
        `<div style="width:${sz}px;height:${sz}px;border-radius:50%;` +
        `background:${epiColor(p.epi)};opacity:.78;border:1px solid #7a0000;` +
        `box-shadow:0 0 3px rgba(0,0,0,.4)"></div>`;
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
        /* skip a single bad marker rather than break the whole map */
      }
    });
  }, [points, ready]);

  if (error) {
    return (
      <div className="map-error">
        <strong>Map unavailable.</strong> {error}
        <div className="map-error-hint">
          Set <code>MAPPLS_CLIENT_ID</code> + <code>MAPPLS_CLIENT_SECRET</code>{' '}
          (or <code>MAPPLS_MAP_SDK_KEY</code>) in the gateway environment, ensure
          the Map SDK is enabled in the Mappls console, then reload.
        </div>
      </div>
    );
  }
  return <div ref={elRef} className="mapview" style={{ height }} />;
}
