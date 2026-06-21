import { useCallback, useEffect, useMemo, useState } from 'react';
import MapView from './MapView.jsx';
import { Icon } from './icons.jsx';
import { getBlocks, getStations, getHotspots, getStationGeo, getRoute } from '../api.js';
import { useT } from '../i18n/index.jsx';

export default function PriorityMap() {
  const { t, tBlock } = useT();
  const [blocks, setBlocks] = useState({}); // {idx: label}
  const [stations, setStations] = useState([]);
  const [selBlocks, setSelBlocks] = useState(null); // null = all
  const [selStations, setSelStations] = useState([]);
  const [stationQuery, setStationQuery] = useState('');
  const [topN, setTopN] = useState(100);
  const [cells, setCells] = useState([]);
  const [err, setErr] = useState(null);

  // --- station assignment + routing ---
  const [stationGeo, setStationGeo] = useState([]); // [{station, lat, lon, cells}]
  const [selCell, setSelCell] = useState(null); // selected cell id
  const [assignTo, setAssignTo] = useState(''); // chosen station name
  const [route, setRoute] = useState(null); // {path, from, distance, duration}
  const [routing, setRouting] = useState(false);
  const [routeErr, setRouteErr] = useState(null);

  useEffect(() => {
    getBlocks()
      .then((b) => {
        setBlocks(b);
        setSelBlocks(Object.values(b));
      })
      .catch((e) => setErr(e.message));
    getStations().then(setStations).catch(() => {});
    getStationGeo().then((d) => setStationGeo(d.stations)).catch(() => {});
  }, []);

  const stationMap = useMemo(() => {
    const m = {};
    stationGeo.forEach((s) => { m[s.station] = s; });
    return m;
  }, [stationGeo]);

  const selectedCell = useMemo(
    () => cells.find((c) => String(c.cell) === String(selCell)) || null,
    [cells, selCell]
  );

  // A dot was clicked: select its cell, default the assignment to its station.
  const onSelect = useCallback(
    (cellId) => {
      const c = cells.find((x) => String(x.cell) === String(cellId));
      if (!c) return;
      setSelCell(c.cell);
      setAssignTo(c.dom_police_station || '');
      setRoute(null);
      setRouteErr(null);
    },
    [cells]
  );

  const showRoute = () => {
    const c = selectedCell;
    const from = stationMap[assignTo];
    if (!c || !from) return;
    setRouting(true);
    setRouteErr(null);
    getRoute({ lat: from.lat, lon: from.lon }, { lat: c.lat, lon: c.lon })
      .then((r) => {
        if (!r.path || !r.path.length) throw new Error('no path');
        setRoute({
          path: r.path,
          from: { lat: from.lat, lon: from.lon, label: assignTo },
          distance: r.distance,
          duration: r.duration,
        });
      })
      .catch(() => setRouteErr(t('map.routeErr')))
      .finally(() => setRouting(false));
  };

  const clearSel = () => {
    setSelCell(null);
    setRoute(null);
    setRouteErr(null);
  };

  // Drop the selection/route if the selected cell leaves the filtered set.
  useEffect(() => {
    if (selCell && !cells.some((c) => String(c.cell) === String(selCell))) {
      clearSel();
    }
  }, [cells, selCell]);

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

  const points = useMemo(
    () =>
      cells.map((c) => ({
        id: c.cell,
        lat: c.lat,
        lon: c.lon,
        epi: c.EPI,
        popup:
          `<b>${t('map.popup.rank', { rank: c.rank })}</b> &nbsp;EPI ${c.EPI}<br/>` +
          `${c.dom_police_station} — ${c.dom_junction}<br/>` +
          `${t('map.popup.perDay', { n: (c.pred_daily_viol || 0).toFixed(1) })} · ${tBlock(c.peak_block_label)}`,
      })),
    [cells, t, tBlock]
  );

  const visibleStations = useMemo(
    () =>
      stations.filter((s) =>
        s.toLowerCase().includes(stationQuery.trim().toLowerCase())
      ),
    [stations, stationQuery]
  );

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
          {selectedCell && (
            <div className="control assign-card">
              <div className="control-title">
                {t('map.assignTitle')}
                <button className="link-btn" onClick={clearSel} title={t('map.clearRoute')}>
                  ✕
                </button>
              </div>
              <div className="assign-cell">
                <b>{t('map.popup.rank', { rank: selectedCell.rank })}</b> · EPI{' '}
                {selectedCell.EPI}
                <div className="muted">{selectedCell.dom_junction}</div>
              </div>
              <label className="assign-label">{t('map.assignTo')}</label>
              <select
                className="assign-select"
                value={assignTo}
                onChange={(e) => {
                  setAssignTo(e.target.value);
                  setRoute(null);
                }}
              >
                {stationGeo.map((s) => (
                  <option key={s.station} value={s.station}>
                    {s.station}
                  </option>
                ))}
              </select>
              <button
                className="primary-btn route-btn"
                onClick={showRoute}
                disabled={routing || !assignTo}
              >
                <Icon name="pin" size={14} />{' '}
                {routing ? t('map.routing') : t('map.showRoute')}
              </button>
              {route && (
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
              )}
              {routeErr && <div className="route-err">{routeErr}</div>}
            </div>
          )}

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
                  {s}
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

          <div className="control-meta" style={{ marginTop: 4 }}>
            <span>
              <Icon name="pin" size={12} /> {t('map.cellsShown', { count: cells.length })}
            </span>
          </div>
        </aside>

        <div className="map-wrap">
          <MapView points={points} height={560} onSelect={onSelect} route={route} />
        </div>
      </div>
    </div>
  );
}
