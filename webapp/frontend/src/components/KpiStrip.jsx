import { Icon } from './icons.jsx';

export default function KpiStrip({ summary }) {
  const pct = (x) => `${Math.round((x || 0) * 100)}%`;

  const items = summary
    ? [
        {
          icon: 'alert',
          value: (summary.events_clean || 0).toLocaleString(),
          label: 'Clean violations',
        },
        {
          icon: 'pin',
          value: `${(summary.n_cells || 0).toLocaleString()} / ${(summary.n_zones || 0).toLocaleString()}`,
          label: 'Priority cells / zones',
        },
        {
          icon: 'cpu',
          value: summary.best_model,
          label: 'Best model',
          hint: `RMSE ${summary.best_RMSE} vs baseline ${summary.baseline_RMSE}`,
        },
        {
          icon: 'target',
          value: pct(summary.capture_at_5pct),
          label: 'Top-5% capture',
          hint: 'Share of all violations caught by patrolling the top 5% predicted slots',
        },
        {
          icon: 'target',
          value: pct(summary.capture_at_1pct),
          label: 'Top-1% capture',
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
              <div className="kpi-label">loading…</div>
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
