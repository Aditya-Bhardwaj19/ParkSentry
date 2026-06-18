import { useEffect, useState } from 'react';
import { getSummary } from './api.js';
import KpiStrip from './components/KpiStrip.jsx';
import PriorityMap from './components/PriorityMap.jsx';
import PriorityTable from './components/PriorityTable.jsx';
import Forecaster from './components/Forecaster.jsx';
import ModelEda from './components/ModelEda.jsx';

const TABS = [
  { id: 'map', label: '🗺️ Priority Map', el: <PriorityMap /> },
  { id: 'table', label: '📋 Priority List', el: <PriorityTable /> },
  { id: 'forecast', label: '🔮 Live Forecaster', el: <Forecaster /> },
  { id: 'model', label: '📈 Model & EDA', el: <ModelEda /> },
];

export default function App() {
  const [summary, setSummary] = useState(null);
  const [err, setErr] = useState(null);
  const [tab, setTab] = useState('map');

  useEffect(() => {
    getSummary()
      .then(setSummary)
      .catch((e) => setErr(e.message));
  }, []);

  return (
    <div className="app">
      <header className="app-header">
        <h1>🚦 ParkSentry — Parking-Induced Congestion Intelligence</h1>
        <p className="subtitle">
          Theme 1 · Detect illegal-parking hotspots, quantify congestion impact,
          and target enforcement. Data: Bengaluru police parking violations.
        </p>
      </header>

      {err && (
        <div className="error-banner">
          Could not reach the data service: {err}. Is the FastAPI service running
          on :8000 and the gateway on :3000?
        </div>
      )}

      <KpiStrip summary={summary} />

      <nav className="tabs">
        {TABS.map((t) => (
          <button
            key={t.id}
            className={`tab ${tab === t.id ? 'active' : ''}`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </nav>

      <main className="tab-body">{TABS.find((t) => t.id === tab).el}</main>
    </div>
  );
}
