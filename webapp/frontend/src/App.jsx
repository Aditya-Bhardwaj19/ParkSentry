import { useEffect, useState } from 'react';
import { getSummary } from './api.js';
import KpiStrip from './components/KpiStrip.jsx';
import PriorityMap from './components/PriorityMap.jsx';
import PriorityTable from './components/PriorityTable.jsx';
import Forecaster from './components/Forecaster.jsx';
import ModelEda from './components/ModelEda.jsx';
import LanguageSwitcher from './components/LanguageSwitcher.jsx';
import { Icon } from './components/icons.jsx';
import { useT } from './i18n/index.jsx';

const TABS = [
  { id: 'map', labelKey: 'tabs.map', icon: 'map', el: <PriorityMap /> },
  { id: 'table', labelKey: 'tabs.table', icon: 'list', el: <PriorityTable /> },
  { id: 'forecast', labelKey: 'tabs.forecast', icon: 'bolt', el: <Forecaster /> },
  { id: 'model', labelKey: 'tabs.model', icon: 'chart', el: <ModelEda /> },
];

export default function App() {
  const { t } = useT();
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
        <div className="brand-mark">🚦</div>
        <div className="brand-text">
          <h1>
            Park<span className="accent">Sentry</span>
            <span style={{ WebkitTextFillColor: 'var(--text-2)', fontWeight: 600 }}>
              {' '}
              {t('header.suffix')}
            </span>
          </h1>
          <p className="subtitle">{t('header.subtitle')}</p>
        </div>
        <div className="header-tools">
          <LanguageSwitcher />
        </div>
      </header>

      {err && (
        <div className="error-banner">{t('header.errorBanner', { err })}</div>
      )}

      <KpiStrip summary={summary} />

      <nav className="tabs">
        {TABS.map((tb) => (
          <button
            key={tb.id}
            className={`tab ${tab === tb.id ? 'active' : ''}`}
            onClick={() => setTab(tb.id)}
          >
            <Icon name={tb.icon} /> {t(tb.labelKey)}
          </button>
        ))}
      </nav>

      <main className="tab-body" key={tab}>
        {TABS.find((tb) => tb.id === tab).el}
      </main>

      <footer className="app-footer">
        <span>🚦 {t('footer.text')}</span>
      </footer>
    </div>
  );
}
