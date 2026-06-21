import { useEffect, useMemo, useRef, useState } from 'react';
import MapView from './MapView.jsx';
import { Icon } from './icons.jsx';
import {
  getBlocks,
  getStations,
  getHotspots,
  getStationGeo,
  getRoute,
  getAssignments,
  saveAssignment,
  resetAssignments,
  assignmentsExportUrl,
} from '../api.js';
import { useT } from '../i18n/index.jsx';

const escapeHtml = (s) =>
  String(s).replace(
    /[&<>"']/g,
    (m) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m])
  );

export default function PriorityMap() {
  const { t, tBlock, tStation } = useT();
  const [blocks, setBlocks] = useState({}); // {idx: label}
  const [stations, setStations] = useState([]);
  const [selBlocks, setSelBlocks] = useState(null); // null = all
  const [selStations, setSelStations] = useState([]);
  const [stationQuery, setStationQuery] = useState('');
  const [topN, setTopN] = useState(100);
  const [cells, setCells] = useState([]);
  const [err, setErr] = useState(null);

  // Station assignment + routing. The controls live INSIDE each dot's popup;
  // the chosen route is drawn on the map.
  const [stationGeo, setStationGeo] = useState([]); // [{station, lat, lon, cells}]
  const [route, setRoute] = useState(null); // {path, from, distance, duration}
  const [assignments, setAssignments] = useState({}); // {cell: station} (persisted)

  useEffect(() => {
    getBlocks()
      .then((b) => {
        setBlocks(b);
        setSelBlocks(Object.values(b));
      })
      .catch((e) => setErr(e.message));
    getStations().then(setStations).catch(() => {});
    getStationGeo().then((d) => setStationGeo(d.stations)).catch(() => {});
    getAssignments().then((d) => setAssignments(d.assignments || {})).catch(() => {});
  }, []);

  useEffect(() => {
    if (selBlocks === null) return;
    const allBlocks = Object.values(blocks);
    const params = { top: topN };
    if (allBlocks.length && selBlocks.length < allBlocks.length) {
      params.blocks = selBlocks.join(',');
    }
    if (selStations.length) params.stations = selStations.join(',');
    getHotspots(params)
      .then((d) => setCells(d.cells))
      .catch((e) => setErr(e.message));
  }, [topN, selBlocks, selStations, blocks]);

  const stationMap = useMemo(() => {
    const m = {};
    stationGeo.forEach((s) => { m[s.station] = s; });
    return m;
  }, [stationGeo]);

  // Live refs so the (once-attached) popup click handler always sees fresh data.
  const cellsRef = useRef([]);
  const stationMapRef = useRef({});
  useEffect(() => { cellsRef.current = cells; }, [cells]);
  useEffect(() => { stationMapRef.current = stationMap; }, [stationMap]);

  // Compute + draw the road route for a cell, reading the chosen station from
  // that cell's popup <select>, and writing the result back into the popup.
  const doRoute = (cellId) => {
    const cell = cellsRef.current.find((x) => String(x.cell) === String(cellId));
    const sel = document.getElementById('psA-' + cellId);
    const station = (sel && sel.value) || (cell && cell.dom_police_station);
    const from = stationMapRef.current[station];
    const out = document.getElementById('psR-' + cellId);
    if (!cell || !from) {
      if (out) out.textContent = t('map.routeErr');
      return;
    }
    if (out) out.textContent = t('map.routing');
    getRoute({ lat: from.lat, lon: from.lon }, { lat: cell.lat, lon: cell.lon })
      .then((r) => {
        if (!r.path || !r.path.length) throw new Error('no path');
        setRoute({
          path: r.path,
          from: { lat: from.lat, lon: from.lon, label: tStation(station) },
          distance: r.distance,
          duration: r.duration,
        });
        const el = document.getElementById('psR-' + cellId);
        if (el) {
          el.textContent = t('map.routeInfo', {
            km: (r.distance / 1000).toFixed(1),
            min: Math.round(r.duration / 60),
          });
        }
      })
      .catch(() => {
        const el = document.getElementById('psR-' + cellId);
        if (el) el.textContent = t('map.routeErr');
      });
  };
  const doRouteRef = useRef(doRoute);
  doRouteRef.current = doRoute;

  // Persist the assignment (server-side) when the popup dropdown changes.
  const onAssign = (cellId, station) => {
    setAssignments((prev) => ({ ...prev, [cellId]: station }));
    setRoute(null); // station changed -> drop any stale route
    const out = document.getElementById('psS-' + cellId);
    if (out) out.textContent = ' …';
    saveAssignment(cellId, station)
      .then(() => {
        const el = document.getElementById('psS-' + cellId);
        if (el) el.textContent = ' ' + t('map.saved');
      })
      .catch(() => {
        const el = document.getElementById('psR-' + cellId);
        if (el) el.textContent = t('map.saveErr');
      });
  };
  const onAssignRef = useRef(onAssign);
  onAssignRef.current = onAssign;

  // Clear ALL saved assignments (with a confirm).
  const doReset = () => {
    if (!window.confirm(t('map.resetConfirm'))) return;
    resetAssignments()
      .then(() => {
        setAssignments({});
        setRoute(null);
      })
      .catch(() => {});
  };

  // Delegated listeners catch "Show route" clicks and dropdown changes in any
  // popup, regardless of how the Mappls SDK renders the popup DOM.
  useEffect(() => {
    const onClick = (e) => {
      const btn = e.target && e.target.closest && e.target.closest('[data-psroute]');
      if (btn) {
        e.preventDefault();
        doRouteRef.current(btn.getAttribute('data-psroute'));
      }
    };
    const onChange = (e) => {
      const sel = e.target && e.target.closest && e.target.closest('[data-psassign]');
      if (sel) onAssignRef.current(sel.getAttribute('data-psassign'), sel.value);
    };
    document.addEventListener('click', onClick);
    document.addEventListener('change', onChange);
    return () => {
      document.removeEventListener('click', onClick);
      document.removeEventListener('change', onChange);
    };
  }, []);

  const stationOptions = (selected) =>
    stationGeo
      .map((s) => {
        const v = escapeHtml(s.station); // raw value -> drives assignment/route
        const label = escapeHtml(tStation(s.station)); // localized display only
        return `<option value="${v}"${s.station === selected ? ' selected' : ''}>${label}</option>`;
      })
      .join('');

  const points = useMemo(
    () =>
      cells.map((c) => {
        const info =
          `<b>${t('map.popup.rank', { rank: c.rank })}</b> &nbsp;EPI ${c.EPI}<br/>` +
          `${escapeHtml(tStation(c.dom_police_station || ''))} — ${escapeHtml(c.dom_junction || '')}<br/>` +
          `${t('map.popup.perDay', { n: (c.pred_daily_viol || 0).toFixed(1) })} · ${tBlock(c.peak_block_label)}`;
        const assigned = assignments[c.cell]; // saved choice, if any
        const dflt = assigned || c.dom_police_station;
        const assign = stationGeo.length
          ? '<div class="ps-assign">' +
            `<label>${escapeHtml(t('map.assignTo'))}` +
            `<span class="ps-saved" id="psS-${c.cell}">${assigned ? ' ✓' : ''}</span></label>` +
            `<select id="psA-${c.cell}" data-psassign="${c.cell}">${stationOptions(dflt)}</select>` +
            `<button class="ps-route-btn" data-psroute="${c.cell}">${escapeHtml(t('map.showRoute'))}</button>` +
            `<div class="ps-route-out" id="psR-${c.cell}"></div>` +
            '</div>'
          : '';
        return { id: c.cell, lat: c.lat, lon: c.lon, epi: c.EPI, popup: info + assign };
      }),
    [cells, stationGeo, assignments, t, tBlock, tStation]
  );

  const visibleStations = useMemo(() => {
    const q = stationQuery.trim().toLowerCase();
    if (!q) return stations;
    // Match the raw English name OR its localized form, so the filter works
    // whichever script the user types in.
    return stations.filter(
      (s) =>
        s.toLowerCase().includes(q) || tStation(s).toLowerCase().includes(q)
    );
  }, [stations, stationQuery, tStation]);

  const toggleBlock = (label) => {
    setSelBlocks((prev) => {
      const cur = prev || Object.values(blocks);
      return cur.includes(label) ? cur.filter((x) => x !== label) : [...cur, label];
    });
  };

  return (
    <div>
      <p className="hint">{t('map.hint')}</p>
      {err && <div className="error-banner">{err}</div>}
      <div className="map-layout">
        <aside className="panel controls">
          <div className="control">
            <div className="control-title">
              {t('map.topN')} <span className="val">{topN}</span>
            </div>
            <input
              type="range"
              min="10"
              max="500"
              step="10"
              value={topN}
              onChange={(e) => setTopN(Number(e.target.value))}
            />
          </div>

          <div className="control">
            <div className="control-title">{t('map.peakBlock')}</div>
            {Object.values(blocks).map((label) => (
              <label key={label} className="checkbox">
                <input
                  type="checkbox"
                  checked={(selBlocks || []).includes(label)}
                  onChange={() => toggleBlock(label)}
                />
                {tBlock(label)}
              </label>
            ))}
          </div>

          <div className="control">
            <div className="control-title">
              {t('map.policeStation')}
              {selStations.length > 0 && (
                <span className="val">{selStations.length}</span>
              )}
            </div>
            <input
              className="station-search"
              type="text"
              placeholder={t('map.filterStations')}
              value={stationQuery}
              onChange={(e) => setStationQuery(e.target.value)}
            />
            <select
              multiple
              size="7"
              value={selStations}
              onChange={(e) =>
                setSelStations(Array.from(e.target.selectedOptions, (o) => o.value))
              }
            >
              {visibleStations.map((s) => (
                <option key={s} value={s}>
                  {tStation(s)}
                </option>
              ))}
            </select>
            <div className="control-meta">
              <span>{t('map.stations', { count: visibleStations.length })}</span>
              {selStations.length > 0 && (
                <button className="link-btn" onClick={() => setSelStations([])}>
                  {t('map.clear')}
                </button>
              )}
            </div>
          </div>

          {route && (
            <div className="control assign-card">
              <div className="control-title">{t('map.assignTitle')}</div>
              <div className="route-info">
                <span>
                  {t('map.routeInfo', {
                    km: (route.distance / 1000).toFixed(1),
                    min: Math.round(route.duration / 60),
                  })}
                </span>
                <button className="link-btn" onClick={() => setRoute(null)}>
                  {t('map.clearRoute')}
                </button>
              </div>
            </div>
          )}

          {Object.keys(assignments).length > 0 && (
            <div className="control assign-card">
              <div className="control-title">{t('map.assignmentsTitle')}</div>
              <div className="route-info">
                <span>
                  {t('map.assignmentsCount', { count: Object.keys(assignments).length })}
                </span>
                <span className="assign-actions">
                  <a className="link-btn" href={assignmentsExportUrl} download>
                    {t('map.exportCsv')}
                  </a>
                  <button className="link-btn danger" onClick={doReset}>
                    {t('map.reset')}
                  </button>
                </span>
              </div>
            </div>
          )}

          <div className="control-meta" style={{ marginTop: 4 }}>
            <span>
              <Icon name="pin" size={12} /> {t('map.cellsShown', { count: cells.length })}
            </span>
          </div>
        </aside>

        <div className="map-wrap">
          <MapView points={points} height={560} route={route} />
        </div>
      </div>
    </div>
  );
}
