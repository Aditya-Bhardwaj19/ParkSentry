import { useEffect, useState } from 'react';
import { getSummary } from './api.js';
import KpiStrip from './components/KpiStrip.jsx';
import PriorityMap from './components/PriorityMap.jsx';
import PriorityTable from './components/PriorityTable.jsx';
import Forecaster from './components/Forecaster.jsx';
import ModelEda from './components/ModelEda.jsx';
import { Icon } from './components/icons.jsx';

const TABS = [
  { id: 'map', label: 'Priority Map', icon: 'map', el: <PriorityMap /> },
  { id: 'table', label: 'Priority List', icon: 'list', el: <PriorityTable /> },
  { id: 'forecast', label: 'Live Forecaster', icon: 'bolt', el: <Forecaster /> },
  { id: 'model', label: 'Model & EDA', icon: 'chart', el: <ModelEda /> },
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

  const range = summary?.date_range;
  return (
    <div className="app">
      <header className="app-header">
        <div className="brand-mark">🚦</div>
        <div className="brand-text">
          <h1>
            Park<span className="accent">Sentry</span>
            <span style={{ WebkitTextFillColor: 'var(--text-2)', fontWeight: 600 }}>
              {' '}
              — Parking-Induced Congestion Intelligence
            </span>
          </h1>
          <p className="subtitle">
            Detect illegal-parking hotspots · quantify congestion impact · target
            enforcement. Data: Bengaluru police parking violations.
          </p>
        </div>
        <div className={`status-pill`} title={err ? err : 'Data service connected'}>
          <span className={`status-dot ${err ? 'off' : ''}`} />
          {err
            ? 'Service offline'
            : range
            ? `Live · ${range[0]} → ${range[1]}`
            : 'Connecting…'}
        </div>
      </header>

      {err && (
        <div className="error-banner">
          Could not reach the data service: {err}. Is FastAPI running on :8000 and
          the gateway on :3000?
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
            <Icon name={t.icon} /> {t.label}
          </button>
        ))}
      </nav>

      <main className="tab-body" key={tab}>
        {TABS.find((t) => t.id === tab).el}
      </main>

      <footer className="app-footer">
        <span>
          🚦 ParkSentry · React + Node/Express + FastAPI · Mappls maps
        </span>
      </footer>
    </div>
  );
}
