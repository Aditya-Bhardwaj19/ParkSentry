// Thin client over the gateway's /api surface. The browser only ever calls the
// gateway (proxied by Vite in dev); the gateway mints the Mappls token and
// forwards data/forecast calls to the Python FastAPI service.

async function getJSON(url) {
  const r = await fetch(url);
  if (!r.ok) {
    let detail = `${r.status}`;
    try {
      const body = await r.json();
      detail = body.detail || body.error || detail;
    } catch (_) {
      /* non-JSON error body */
    }
    throw new Error(`${url} → ${detail}`);
  }
  return r.json();
}

const qs = (params) => new URLSearchParams(params).toString();

export const getSummary = () => getJSON('/api/summary');
export const getBlocks = () => getJSON('/api/blocks');
export const getStations = () => getJSON('/api/stations');
export const getHotspots = (params) => getJSON('/api/hotspots?' + qs(params));
export const getZones = () => getJSON('/api/zones');
export const getModelComparison = () => getJSON('/api/model-comparison');
export const getForecast = (params) => getJSON('/api/forecast?' + qs(params));
export const getPlots = () => getJSON('/api/plots');
export const plotUrl = (name) => `/api/plots/${name}`;
export const getStationGeo = () => getJSON('/api/station-geo');
export const getRoute = (from, to) =>
  getJSON(`/api/route?slat=${from.lat}&slng=${from.lon}&dlat=${to.lat}&dlng=${to.lon}`);

export const getAssignments = () => getJSON('/api/assignments');
export const saveAssignment = (cell, station) =>
  fetch('/api/assignments', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ cell, station }),
  }).then((r) => {
    if (!r.ok) throw new Error('save failed');
    return r.json();
  });
export const resetAssignments = () =>
  fetch('/api/assignments', { method: 'DELETE' }).then((r) => {
    if (!r.ok) throw new Error('reset failed');
    return r.json();
  });
export const assignmentsExportUrl = '/api/assignments/export';
