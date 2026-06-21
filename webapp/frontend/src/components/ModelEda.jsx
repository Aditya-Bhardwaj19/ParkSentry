import { useEffect, useState } from 'react';
import { getModelComparison, getPlots, plotUrl } from '../api.js';
import { useT } from '../i18n/index.jsx';

export default function ModelEda() {
  const { t } = useT();
  // Translated plot caption, falling back to the filename for unknown plots.
  const caption = (fn) => {
    const k = `plot.${fn}`;
    const v = t(k);
    return v === k ? fn : v;
  };
  const [models, setModels] = useState([]);
  const [plots, setPlots] = useState([]);
  const [err, setErr] = useState(null);

  useEffect(() => {
    getModelComparison()
      .then((d) => setModels(d.models))
      .catch((e) => setErr(e.message));
    getPlots()
      .then((d) => setPlots(d.plots))
      .catch(() => {});
  }, []);

  const cols = models[0] ? Object.keys(models[0]) : [];
  const fmt = (v) =>
    typeof v === 'number' ? (Number.isInteger(v) ? v : v.toFixed(4)) : v ?? '';

  return (
    <div>
      <div className="section-head">
        <h3>{t('model.comparisonTitle')}</h3>
      </div>
      <p className="hint">{t('model.comparisonHint')}</p>
      {err && <div className="error-banner">{err}</div>}
      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              {cols.map((c) => (
                <th key={c}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {models.map((m, i) => (
              <tr key={i}>
                {cols.map((c) => (
                  <td key={c}>{fmt(m[c])}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="section-head" style={{ marginTop: 22 }}>
        <h3>{t('model.evidenceTitle')}</h3>
      </div>
      <div className="plot-grid">
        {plots.map((fn) => (
          <figure key={fn} className="plot">
            <img src={plotUrl(fn)} alt={caption(fn)} loading="lazy" />
            <figcaption>{caption(fn)}</figcaption>
          </figure>
        ))}
      </div>
    </div>
  );
}
