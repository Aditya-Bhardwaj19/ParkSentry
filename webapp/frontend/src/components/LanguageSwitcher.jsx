import { useT } from '../i18n/index.jsx';
import { Icon } from './icons.jsx';

// Compact language selector for the header (English / हिन्दी / ಕನ್ನಡ).
export default function LanguageSwitcher() {
  const { lang, setLang, languages, t } = useT();
  return (
    <label className="lang-switcher" title={t('lang.label')}>
      <Icon name="globe" size={15} />
      <select
        aria-label={t('lang.label')}
        value={lang}
        onChange={(e) => setLang(e.target.value)}
      >
        {languages.map((l) => (
          <option key={l.code} value={l.code}>
            {l.name}
          </option>
        ))}
      </select>
    </label>
  );
}
