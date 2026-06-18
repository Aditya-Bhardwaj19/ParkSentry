import { useEffect, useMemo, useState } from 'react';
import MapView from './MapView.jsx';
import { getBlocks, getForecast } from '../api.js';

export default function Forecaster() {
  const [blocks, setBlocks] = useState({});
  const [date, setDate] = useState('2024-04-10');
  const [block, setBlock] = useState(2);
  const [top, setTop] = useState(15);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState(null);

  useEffect(() => {
    getBlocks().then(setBlocks).catch((e) => setErr(e.message));
  }, []);

  const run = () => {
    setLoading(true);
    setErr(null);
    getForecast({ date, block, top })
      .then(setResult)
      .catch((e) => setErr(e.message))
      .finally(() => setLoading(false));
  };

  const points = useMemo(() => {
    if (!result) return [];
    const mx = Math.max(...result.cells.map((c) => c.pred_viol), 1);
    return result.cells.map((c, i) => ({
      lat: c.cell_lat,
      lon: c.cell_lon,
      epi: (c.pred_viol / mx) * 100,
      popup:
        `<b>#${i + 1}</b> &nbsp;${c.police_station || ''}<br/>` +
        `cell ${c.cell}<br/>~${(c.pred_viol || 0).toFixed(2)} viol · ${result.block_label}`,
    }));
  }, [result]);

  return (
    <div>
      <h3>Forecast parking-violation risk for any zone / time</h3>
      <p className="hint">
        Rebuilds the model's features causally and scores every known cell on
        demand (Python FastAPI + the deployable Forecaster).
      </p>

      <div className="forecast-controls">
        <label>
          Date
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        </label>
        <label>
          Time block
          <select value={block} onChange={(e) => setBlock(Number(e.target.value))}>
            {Object.entries(blocks).map(([idx, label]) => (
              <option key={idx} value={idx}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Top cells: <strong>{top}</strong>
          <input
            type="range"
            min="5"
            max="50"
            value={top}
            onChange={(e) => setTop(Number(e.target.value))}
          />
        </label>
        <button className="primary-btn" onClick={run} disabled={loading}>
          {loading ? 'Scoring…' : 'Run forecast'}
        </button>
      </div>

      {err && <div className="error-banner">{err}</div>}

      {result && (
        <div className="forecast-result">
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Pred viol</th>
                  <th>Cell</th>
                  <th>Police station</th>
                </tr>
              </thead>
              <tbody>
                {result.cells.map((c, i) => (
                  <tr key={c.cell}>
                    <td>{i + 1}</td>
                    <td>{(c.pred_viol || 0).toFixed(3)}</td>
                    <td>{c.cell}</td>
                    <td>{c.police_station}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="map-wrap">
            <MapView points={points} height={480} />
          </div>
        </div>
      )}
    </div>
  );
}
