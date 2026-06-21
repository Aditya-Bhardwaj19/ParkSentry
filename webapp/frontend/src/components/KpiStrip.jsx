import { Icon } from './icons.jsx';
import { useT } from '../i18n/index.jsx';

export default function KpiStrip({ summary }) {
  const { t } = useT();
  const pct = (x) => `${Math.round((x || 0) * 100)}%`;

  const items = summary
    ? [
        {
          icon: 'alert',
          value: (summary.events_clean || 0).toLocaleString(),
          label: t('kpi.cleanViolations'),
        },
        {
          icon: 'pin',
          value: `${(summary.n_cells || 0).toLocaleString()} / ${(summary.n_zones || 0).toLocaleString()}`,
          label: t('kpi.priorityCellsZones'),
        },
        {
          icon: 'cpu',
          value: summary.best_model,
          label: t('kpi.bestModel'),
          hint: t('kpi.bestModelHint', {
            rmse: summary.best_RMSE,
            baseline: summary.baseline_RMSE,
          }),
        },
        {
          icon: 'target',
          value: pct(summary.capture_at_5pct),
          label: t('kpi.capture5'),
          hint: t('kpi.capture5Hint'),
        },
        {
          icon: 'target',
          value: pct(summary.capture_at_1pct),
          label: t('kpi.capture1'),
        },
      ]
    : null;

  if (!items) {
    // Loading skeleton (5 placeholder cards)
    return (
      <div className="kpi-strip">
        {Array.from({ length: 5 }).map((_, i) => (
          <div className="kpi skeleton" key={i}>
            <div className="kpi-icon" />
            <div className="kpi-body">
              <div className="kpi-value">000,000</div>
              <div className="kpi-label">{t('kpi.loading')}</div>
            </div>
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="kpi-strip">
      {items.map((it, i) => (
        <div className="kpi" key={i} title={it.hint || ''}>
          <div className="kpi-icon">
            <Icon name={it.icon} size={20} />
          </div>
          <div className="kpi-body">
            <div className="kpi-value">{it.value}</div>
            <div className="kpi-label">{it.label}</div>
          </div>
        </div>
      ))}
    </div>
  );
}
