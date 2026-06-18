import { useEffect, useMemo, useState } from 'react';
import MapView from './MapView.jsx';
import { Icon } from './icons.jsx';
import { getBlocks, getStations, getHotspots } from '../api.js';

export default function PriorityMap() {
  const [blocks, setBlocks] = useState({}); // {idx: label}
  const [stations, setStations] = useState([]);
  const [selBlocks, setSelBlocks] = useState(null); // null = all
  const [selStations, setSelStations] = useState([]);
  const [stationQuery, setStationQuery] = useState('');
  const [topN, setTopN] = useState(100);
  const [cells, setCells] = useState([]);
  const [err, setErr] = useState(null);

  useEffect(() => {
    getBlocks()
      .then((b) => {
        setBlocks(b);
        setSelBlocks(Object.values(b));
      })
      .catch((e) => setErr(e.message));
    getStations().then(setStations).catch(() => {});
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

  const points = useMemo(
    () =>
      cells.map((c) => ({
        lat: c.lat,
        lon: c.lon,
        epi: c.EPI,
        popup:
          `<b>Rank #${c.rank}</b> &nbsp;EPI ${c.EPI}<br/>` +
          `${c.dom_police_station} — ${c.dom_junction}<br/>` +
          `~${(c.pred_daily_viol || 0).toFixed(1)}/day · peak ${c.peak_block_label}`,
      })),
    [cells]
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
      <p className="hint">
        Each dot is a ~150&nbsp;m enforcement cell (a specific road stretch), sized
        &amp; coloured by its Enforcement Priority Index (EPI). Click a dot for its
        rank, station and predicted volume.
      </p>
      {err && <div className="error-banner">{err}</div>}
      <div className="map-layout">
        <aside className="panel controls">
          <div className="control">
            <div className="control-title">
              Top-N cells <span className="val">{topN}</span>
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
            <div className="control-title">Peak time block</div>
            {Object.values(blocks).map((label) => (
              <label key={label} className="checkbox">
                <input
                  type="checkbox"
                  checked={(selBlocks || []).includes(label)}
                  onChange={() => toggleBlock(label)}
                />
                {label}
              </label>
            ))}
          </div>

          <div className="control">
            <div className="control-title">
              Police station
              {selStations.length > 0 && (
                <span className="val">{selStations.length}</span>
              )}
            </div>
            <input
              className="station-search"
              type="text"
              placeholder="Filter stations…"
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
              <span>{visibleStations.length} stations</span>
              {selStations.length > 0 && (
                <button className="link-btn" onClick={() => setSelStations([])}>
                  clear
                </button>
              )}
            </div>
          </div>

          <div className="control-meta" style={{ marginTop: 4 }}>
            <span>
              <Icon name="pin" size={12} /> {cells.length} cells shown
            </span>
          </div>
        </aside>

        <div className="map-wrap">
          <MapView points={points} height={560} />
        </div>
      </div>
    </div>
  );
}
