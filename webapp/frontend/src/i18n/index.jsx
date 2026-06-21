// Lightweight, dependency-free i18n: a context provider + a useT() hook.
// English is the default and the fallback; the choice is persisted to
// localStorage and reflected on <html lang>.
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react';
import { LANGUAGES, DEFAULT_LANG, STRINGS, BLOCKS } from './translations.js';
import { STATION_NAMES } from './stationNames.js';

const I18nContext = createContext(null);
const STORAGE_KEY = 'ps_lang';

function interpolate(str, vars) {
  if (!vars) return str;
  return str.replace(/\{(\w+)\}/g, (_, k) => (k in vars ? String(vars[k]) : `{${k}}`));
}

function readSaved() {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    return LANGUAGES.some((l) => l.code === v) ? v : DEFAULT_LANG;
  } catch (_) {
    return DEFAULT_LANG;
  }
}

export function I18nProvider({ children }) {
  const [lang, setLangState] = useState(readSaved);

  const setLang = useCallback((code) => {
    setLangState(LANGUAGES.some((l) => l.code === code) ? code : DEFAULT_LANG);
    try {
      localStorage.setItem(STORAGE_KEY, code);
    } catch (_) {
      /* ignore storage failures (private mode, etc.) */
    }
  }, []);

  useEffect(() => {
    document.documentElement.lang = lang;
    const dict = STRINGS[lang] || STRINGS[DEFAULT_LANG];
    if (dict['app.title']) document.title = dict['app.title'];
  }, [lang]);

  const value = useMemo(() => {
    const dict = STRINGS[lang] || STRINGS[DEFAULT_LANG];
    const t = (key, vars) =>
      interpolate(dict[key] ?? STRINGS[DEFAULT_LANG][key] ?? key, vars);
    // Translate a backend time-block label; falls back to the label itself.
    const tBlock = (label) => (BLOCKS[lang] && BLOCKS[lang][label]) || label;
    // Translate a raw police-station name (data value); English / unmapped
    // names fall back to the raw name unchanged.
    const tStation = (name) => {
      if (!name || lang === DEFAULT_LANG) return name;
      const e = STATION_NAMES[name];
      return (e && e[lang]) || name;
    };
    return { lang, setLang, languages: LANGUAGES, t, tBlock, tStation };
  }, [lang, setLang]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useT() {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error('useT() must be used inside <I18nProvider>');
  return ctx;
}
