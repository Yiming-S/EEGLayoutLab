'use client';

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { LANGUAGE_COOKIE, LANGUAGE_STORAGE_KEY, localize, formatDate, startupLocale, type Locale } from '@/lib/i18n/core';
import { SHOWCASE } from '@/lib/showcase';

type LanguageContext = {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  tx: <T>(value: T) => T;
  date: (value: string | number | Date, withTime?: boolean) => string;
};
const Context = createContext<LanguageContext | null>(null);

export function LanguageProvider({ initialLocale, children }: { initialLocale: Locale; children: ReactNode }) {
  const [locale, updateLocale] = useState(initialLocale);
  const setLocale = useCallback((next: Locale) => {
    if (next !== 'en' && next !== 'zh-CN') return;
    updateLocale(next);
    // UI preference only: no URL rewrite, fetch, reload, or compute request.
    document.cookie = `${LANGUAGE_COOKIE}=${next}; Path=/; Max-Age=31536000; SameSite=Lax`;
    try { localStorage.setItem(LANGUAGE_STORAGE_KEY, next); } catch { /* cookies and session state remain usable */ }
  }, []);
  useEffect(() => {
    document.documentElement.lang = locale;
    const description = document.querySelector('meta[name="description"]');
    description?.setAttribute('content', locale === 'en'
      ? 'Explore fixed 64-electrode EEG layouts, compare region size and placement, and evaluate signal retention using local simulations.'
      : '固定64电极，比较区域大小与空间布局，通过仿真评价相对全头64导的性能保留。');
  }, [locale]);
  useEffect(() => {
    const restore = window.setTimeout(() => {
      // The static page is rendered in English; choose the saved language, else the browser's
      // (the showcase stays in English until the visitor chooses).
      const cookie = document.cookie.split(';').map((part) => part.trim())
        .find((part) => part.startsWith(LANGUAGE_COOKIE + '='))?.slice(LANGUAGE_COOKIE.length + 1);
      let saved: string | null = null;
      try { saved = localStorage.getItem(LANGUAGE_STORAGE_KEY); } catch { /* storage is optional */ }
      updateLocale(startupLocale(cookie ?? saved, navigator.languages.join(','), SHOWCASE));
    }, 0);
    const sync = (event: StorageEvent) => {
      if (event.key === LANGUAGE_STORAGE_KEY && (event.newValue === 'en' || event.newValue === 'zh-CN')) setLocale(event.newValue);
    };
    window.addEventListener('storage', sync);
    return () => { window.clearTimeout(restore); window.removeEventListener('storage', sync); };
  }, [setLocale]);
  const value = useMemo<LanguageContext>(() => ({
    locale, setLocale,
    tx: <T,>(value: T) => localize(value, locale),
    date: (value, withTime) => formatDate(value, locale, withTime),
  }), [locale, setLocale]);
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useLanguage() {
  const value = useContext(Context);
  if (!value) throw new Error('LanguageProvider is required');
  return value;
}
