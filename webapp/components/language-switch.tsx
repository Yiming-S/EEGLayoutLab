'use client';
import { useCallback, useEffect, useState } from 'react';
import { Monitor, Moon, Sun } from 'lucide-react';
import { useLanguage } from '@/components/language-provider';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';

export const THEME_STORAGE_KEY = 'eeg-layout-lab/theme';
type ThemeChoice = 'light' | 'dark' | 'system';

function readStoredTheme(): ThemeChoice {
  try {
    const raw = localStorage.getItem(THEME_STORAGE_KEY);
    if (raw === 'light' || raw === 'dark' || raw === 'system') return raw;
  } catch {
    /* storage is optional */
  }
  return 'system';
}

function applyThemeClass(choice: ThemeChoice) {
  if (typeof document === 'undefined') return;
  const prefersDark =
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-color-scheme: dark)').matches;
  const isDark = choice === 'dark' || (choice === 'system' && prefersDark);
  document.documentElement.classList.toggle('dark', isDark);
}

export function LanguageSwitch() {
  const { locale, setLocale, tx } = useLanguage();
  const [theme, setThemeState] = useState<ThemeChoice>('system');

  const setTheme = useCallback((next: ThemeChoice) => {
    setThemeState(next);
    applyThemeClass(next);
    try {
      localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      /* storage is optional */
    }
  }, []);

  useEffect(() => {
    const restore = window.setTimeout(() => {
      const saved = readStoredTheme();
      setThemeState(saved);
      applyThemeClass(saved);
    }, 0);

    const media =
      typeof window.matchMedia === 'function'
        ? window.matchMedia('(prefers-color-scheme: dark)')
        : null;
    const onMediaChange = () => {
      if (readStoredTheme() === 'system') applyThemeClass('system');
    };
    const onStorage = (event: StorageEvent) => {
      if (
        event.key === THEME_STORAGE_KEY &&
        (event.newValue === 'light' ||
          event.newValue === 'dark' ||
          event.newValue === 'system')
      ) {
        setThemeState(event.newValue);
        applyThemeClass(event.newValue);
      }
    };
    media?.addEventListener('change', onMediaChange);
    window.addEventListener('storage', onStorage);
    return () => {
      window.clearTimeout(restore);
      media?.removeEventListener('change', onMediaChange);
      window.removeEventListener('storage', onStorage);
    };
  }, []);

  return (
    <div className="min-w-[216px] space-y-3">
      <div className="space-y-1.5">
        <p className="px-0.5 text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">
          {tx('界面语言')}
        </p>
        <ToggleGroup
          multiple={false}
          value={[locale]}
          onValueChange={(values) => {
            const next = values[0];
            if (next === 'en' || next === 'zh-CN') setLocale(next);
          }}
          aria-label={tx('界面语言')}
          className="w-full rounded-xl border border-border/75 bg-muted/65 p-1"
          spacing={0}
          size="sm"
        >
          <ToggleGroupItem
            value="en"
            lang="en"
            className="min-h-8 flex-1 rounded-lg px-3 text-xs font-medium data-pressed:bg-brand data-pressed:text-white data-pressed:shadow-xs"
          >
            English
          </ToggleGroupItem>
          <ToggleGroupItem
            value="zh-CN"
            lang="zh-CN"
            className="min-h-8 flex-1 rounded-lg px-3 text-xs font-medium data-pressed:bg-brand data-pressed:text-white data-pressed:shadow-xs"
          >
            简体中文
          </ToggleGroupItem>
        </ToggleGroup>
      </div>
      <div className="space-y-1.5 border-t border-border/65 pt-2.5">
        <p className="px-0.5 text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">
          {tx('外观主题')}
        </p>
        <ToggleGroup
          multiple={false}
          value={[theme]}
          onValueChange={(values) => {
            const next = values[0];
            if (next === 'light' || next === 'dark' || next === 'system')
              setTheme(next);
          }}
          aria-label={tx('外观主题')}
          className="w-full rounded-xl border border-border/75 bg-muted/65 p-1"
          spacing={0}
          size="sm"
        >
          <ToggleGroupItem
            value="light"
            className="min-h-8 flex-1 gap-1 rounded-lg px-2 text-xs font-medium data-pressed:bg-brand data-pressed:text-white data-pressed:shadow-xs"
          >
            <Sun aria-hidden className="size-3.5" />
            {tx('浅色')}
          </ToggleGroupItem>
          <ToggleGroupItem
            value="dark"
            className="min-h-8 flex-1 gap-1 rounded-lg px-2 text-xs font-medium data-pressed:bg-brand data-pressed:text-white data-pressed:shadow-xs"
          >
            <Moon aria-hidden className="size-3.5" />
            {tx('深色')}
          </ToggleGroupItem>
          <ToggleGroupItem
            value="system"
            className="min-h-8 flex-1 gap-1 rounded-lg px-2 text-xs font-medium data-pressed:bg-brand data-pressed:text-white data-pressed:shadow-xs"
          >
            <Monitor aria-hidden className="size-3.5" />
            {tx('跟随系统')}
          </ToggleGroupItem>
        </ToggleGroup>
      </div>
    </div>
  );
}
