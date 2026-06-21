import { useEffect, useState } from 'react';
import { Icon } from './icons.jsx';
import { getHotspots, getZones } from '../api.js';
import { useT } from '../i18n/index.jsx';

const COLS = [
  ['rank', 'table.col.rank'],
  ['EPI', 'table.col.epi'],
  ['pred_daily_viol', 'table.col.predDay'],
  ['actual_daily_viol', 'table.col.actualDay'],
  ['mean_impact_per_viol', 'table.col.impactViol'],
  ['total_events', 'table.col.events'],
  ['peak_block_label', 'table.col.peakBlock'],
  ['dom_police_station', 'table.col.policeStation'],
  ['dom_junction', 'table.col.junction'],
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
  const { t, tBlock, tStation } = useT();
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
      <div className="section-head">
        <h3>{t('table.title')}</h3>
        <button className="primary-btn" onClick={download} disabled={!cells.length}>
          <Icon name="download" size={16} /> {t('table.downloadCsv')}
        </button>
      </div>
      <p className="hint">{t('table.hint', { count: cells.length })}</p>
      {err && <div className="error-banner">{err}</div>}
      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              {COLS.map(([k, labelKey]) => (
                <th key={k}>{t(labelKey)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {cells.map((c) => (
              <tr key={c.rank}>
                <td>
                  <span className={`rank-badge ${c.rank <= 3 ? 'top' : ''}`}>
                    {c.rank}
                  </span>
                </td>
                {COLS.slice(1).map(([k]) => (
                  <td key={k}>
                    {fmt(
                      k === 'peak_block_label'
                        ? tBlock(c[k])
                        : k === 'dom_police_station'
                        ? tStation(c[k])
                        : c[k]
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <button className="link-btn" onClick={() => setShowZones((s) => !s)}>
        {showZones ? '▾' : '▸'} {t('table.zonesToggle')}
      </button>
      {showZones && (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                {zones[0] && Object.keys(zones[0]).map((k) => <th key={k}>{k}</th>)}
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
