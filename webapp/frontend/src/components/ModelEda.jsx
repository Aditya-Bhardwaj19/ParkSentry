import { useEffect, useState } from 'react';
import { getModelComparison, getPlots, plotUrl } from '../api.js';

const PLOT_CAPTIONS = {
  'model_capture_curve.png': 'Enforcement-efficiency curve',
  'model_feature_importance.png': 'What the model keys on',
  'model_comparison.png': 'Error vs efficiency',
  'hotspot_map.png': 'Density & priority hotspots',
  'eda_temporal.png': 'When violations happen',
  'eda_violation_types.png': 'Violation mix',
  'eda_vehicle_trend.png': 'Vehicles & monthly trend',
  'eda_impact_dist.png': 'Impact score distribution',
};

export default function ModelEda() {
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
      <h3>Model comparison</h3>
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

      <h3>Evidence the forecast can be trusted</h3>
      <div className="plot-grid">
        {plots.map((fn) => (
          <figure key={fn} className="plot">
            <img src={plotUrl(fn)} alt={PLOT_CAPTIONS[fn] || fn} loading="lazy" />
            <figcaption>{PLOT_CAPTIONS[fn] || fn}</figcaption>
          </figure>
        ))}
      </div>
    </div>
  );
}
