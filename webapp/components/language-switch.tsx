'use client';
import { useLanguage } from '@/components/language-provider';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';

export function LanguageSwitch() {
  const { locale, setLocale } = useLanguage();
  return <ToggleGroup multiple={false} value={[locale]} onValueChange={(values) => {
    const next = values[0];
    if (next === 'en' || next === 'zh-CN') setLocale(next);
  }} aria-label={locale === 'en' ? 'Interface language' : '界面语言'}
    className="ml-auto shrink-0 rounded-lg border border-border bg-white p-1 xl:ml-0" spacing={0} size="sm">
    <ToggleGroupItem value="en" lang="en" className="min-h-9 px-3 text-sm data-pressed:bg-brand data-pressed:text-white">English</ToggleGroupItem>
    <ToggleGroupItem value="zh-CN" lang="zh-CN" className="min-h-9 px-3 text-sm data-pressed:bg-brand data-pressed:text-white">简体中文</ToggleGroupItem>
  </ToggleGroup>;
}
