'use client';
import { useLanguage } from '@/components/language-provider';
/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
export function LabNavigation({ current, compareHref = '/', designHref = '/design' }: { current: 'compare' | 'design'; compareHref?: string; designHref?: string }) {
  const { tx } = useLanguage();
  return <nav aria-label={tx("布局页面")} className="flex gap-5 border-b text-sm font-medium">
    <a href={compareHref} aria-current={current === 'compare' ? 'page' : undefined} className={`border-b-2 px-1 py-3 ${current === 'compare' ? 'border-primary text-primary' : 'border-transparent text-muted-foreground'}`}>{tx("已有结果")}</a>
    <a href={designHref} aria-current={current === 'design' ? 'page' : undefined} className={`border-b-2 px-1 py-3 ${current === 'design' ? 'border-primary text-primary' : 'border-transparent text-muted-foreground'}`}>{tx("布局设计")}</a>
  </nav>;
}
