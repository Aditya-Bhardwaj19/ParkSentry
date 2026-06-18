export default function KpiStrip({ summary }) {
  if (!summary) return null;
  const pct = (x) => `${Math.round((x || 0) * 100)}%`;
  const items = [
    { label: 'Clean violations', value: (summary.events_clean || 0).toLocaleString() },
    {
      label: 'Priority cells / zones',
      value: `${(summary.n_cells || 0).toLocaleString()} / ${(summary.n_zones || 0).toLocaleString()}`,
    },
    {
      label: 'Best model',
      value: summary.best_model,
      hint: `RMSE ${summary.best_RMSE} vs baseline ${summary.baseline_RMSE}`,
    },
    {
      label: 'Top-5% capture',
      value: pct(summary.capture_at_5pct),
      hint: 'Share of all violations caught by patrolling the top 5% predicted slots',
    },
    { label: 'Top-1% capture', value: pct(summary.capture_at_1pct) },
  ];
  return (
    <div className="kpi-strip">
      {items.map((it) => (
        <div className="kpi" key={it.label} title={it.hint || ''}>
          <div className="kpi-value">{it.value}</div>
          <div className="kpi-label">{it.label}</div>
        </div>
      ))}
    </div>
  );
}
