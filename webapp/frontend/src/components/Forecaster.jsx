import { useEffect, useMemo, useState } from 'react';
import MapView from './MapView.jsx';
import { Icon } from './icons.jsx';
import { getBlocks, getForecast } from '../api.js';
import { useT } from '../i18n/index.jsx';

export default function Forecaster() {
  const { t, tBlock, tStation } = useT();
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
        `<b>#${i + 1}</b> &nbsp;${tStation(c.police_station || '')}<br/>` +
        `${t('forecast.popup.cell', { cell: c.cell })}<br/>` +
        `${t('forecast.popup.viol', { n: (c.pred_viol || 0).toFixed(2) })} · ${tBlock(result.block_label)}`,
    }));
  }, [result, t, tBlock, tStation]);

  return (
    <div>
      <div className="section-head">
        <h3>{t('forecast.title')}</h3>
      </div>
      <p className="hint">{t('forecast.hint')}</p>

      <div className="panel forecast-controls">
        <label className="field">
          {t('forecast.date')}
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        </label>
        <label className="field">
          {t('forecast.timeBlock')}
          <select value={block} onChange={(e) => setBlock(Number(e.target.value))}>
            {Object.entries(blocks).map(([idx, label]) => (
              <option key={idx} value={idx}>
                {tBlock(label)}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          {t('forecast.topCells')}{' '}
          <span style={{ color: 'var(--brand)', fontSize: 14 }}>{top}</span>
          <input
            type="range"
            min="5"
            max="50"
            value={top}
            onChange={(e) => setTop(Number(e.target.value))}
          />
        </label>
        <button className="primary-btn" onClick={run} disabled={loading}>
          <Icon name="bolt" size={16} />
          {loading ? t('forecast.scoring') : t('forecast.run')}
        </button>
      </div>

      {err && <div className="error-banner">{err}</div>}

      {!result && !err && (
        <div className="empty-hint">{t('forecast.empty')}</div>
      )}

      {result && (
        <div className="forecast-result">
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>{t('forecast.colNum')}</th>
                  <th>{t('forecast.colPred')}</th>
                  <th>{t('forecast.colCell')}</th>
                  <th>{t('forecast.colStation')}</th>
                </tr>
              </thead>
              <tbody>
                {result.cells.map((c, i) => (
                  <tr key={c.cell}>
                    <td>
                      <span className={`rank-badge ${i === 0 ? 'top' : ''}`}>
                        {i + 1}
                      </span>
                    </td>
                    <td>{(c.pred_viol || 0).toFixed(3)}</td>
                    <td className="mono">{c.cell}</td>
                    <td>{tStation(c.police_station)}</td>
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
