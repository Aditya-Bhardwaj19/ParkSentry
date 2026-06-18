import { useEffect, useState } from 'react';
import { getHotspots, getZones } from '../api.js';

const COLS = [
  ['rank', 'Rank'],
  ['EPI', 'EPI'],
  ['pred_daily_viol', 'Pred/day'],
  ['actual_daily_viol', 'Actual/day'],
  ['mean_impact_per_viol', 'Impact/viol'],
  ['total_events', 'Events'],
  ['peak_block_label', 'Peak block'],
  ['dom_police_station', 'Police station'],
  ['dom_junction', 'Junction'],
];

const fmt = (v) =>
  typeof v === 'number' ? (Number.isInteger(v) ? v : v.toFixed(2)) : v ?? '';

function toCsv(rows) {
  if (!rows.length) return '';
  const keys = Object.keys(rows[0]);
  const head = keys.join(',');
  const body = rows
    .map((r) => keys.map((k) => JSON.stringify(r[k] ?? '')).join(','))
    .join('\n');
  return `${head}\n${body}`;
}

export default function PriorityTable() {
  const [cells, setCells] = useState([]);
  const [zones, setZones] = useState([]);
  const [showZones, setShowZones] = useState(false);
  const [err, setErr] = useState(null);

  useEffect(() => {
    getHotspots({ top: 500 })
      .then((d) => setCells(d.cells))
      .catch((e) => setErr(e.message));
    getZones()
      .then((d) => setZones(d.zones))
      .catch(() => {});
  }, []);

  const download = () => {
    const blob = new Blob([toCsv(cells)], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'cell_priority_ranked.csv';
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div>
      <h3>Enforcement Priority Index — ranked cells (primary targeting)</h3>
      {err && <div className="error-banner">{err}</div>}
      <button className="primary-btn" onClick={download} disabled={!cells.length}>
        ⬇ Download ranking (CSV)
      </button>
      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              {COLS.map(([, label]) => (
                <th key={label}>{label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {cells.map((c) => (
              <tr key={c.rank}>
                {COLS.map(([k]) => (
                  <td key={k}>{fmt(c[k])}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <button className="link-btn" onClick={() => setShowZones((s) => !s)}>
        {showZones ? '▾' : '▸'} Secondary: DBSCAN density zones (beat-level grouping)
      </button>
      {showZones && (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                {zones[0] &&
                  Object.keys(zones[0]).map((k) => <th key={k}>{k}</th>)}
              </tr>
            </thead>
            <tbody>
              {zones.map((z, i) => (
                <tr key={i}>
                  {Object.values(z).map((v, j) => (
                    <td key={j}>{fmt(v)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
