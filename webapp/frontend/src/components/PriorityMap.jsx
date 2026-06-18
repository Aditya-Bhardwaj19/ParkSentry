import { useEffect, useMemo, useState } from 'react';
import MapView from './MapView.jsx';
import { getBlocks, getStations, getHotspots } from '../api.js';

export default function PriorityMap() {
  const [blocks, setBlocks] = useState({}); // {idx: label}
  const [stations, setStations] = useState([]);
  const [selBlocks, setSelBlocks] = useState(null); // null = all
  const [selStations, setSelStations] = useState([]);
  const [topN, setTopN] = useState(100);
  const [cells, setCells] = useState([]);
  const [err, setErr] = useState(null);

  useEffect(() => {
    getBlocks()
      .then((b) => {
        setBlocks(b);
        setSelBlocks(Object.values(b)); // default: all blocks
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

  const toggleBlock = (label) => {
    setSelBlocks((prev) => {
      const cur = prev || Object.values(blocks);
      return cur.includes(label) ? cur.filter((x) => x !== label) : [...cur, label];
    });
  };

  return (
    <div>
      <p className="hint">
        Each dot is a ~150 m enforcement cell (a specific road stretch), sized &
        coloured by its Enforcement Priority Index (EPI).
      </p>
      {err && <div className="error-banner">{err}</div>}
      <div className="map-layout">
        <aside className="controls">
          <label className="control">
            Show top-N cells: <strong>{topN}</strong>
            <input
              type="range"
              min="10"
              max="500"
              step="10"
              value={topN}
              onChange={(e) => setTopN(Number(e.target.value))}
            />
          </label>

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
            <div className="control-title">Police station</div>
            <select
              multiple
              size="8"
              value={selStations}
              onChange={(e) =>
                setSelStations(Array.from(e.target.selectedOptions, (o) => o.value))
              }
            >
              {stations.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
            {selStations.length > 0 && (
              <button className="link-btn" onClick={() => setSelStations([])}>
                clear stations
              </button>
            )}
          </div>
        </aside>

        <div className="map-wrap">
          <MapView points={points} height={560} />
        </div>
      </div>
    </div>
  );
}
