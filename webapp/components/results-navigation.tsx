'use client';
/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
import { useLanguage } from '@/components/language-provider';
import { resultsViewHref } from '@/lib/results-library';
import type { SavedSummary } from '@/lib/local-library';

export function ResultsNavigation({ view, here, selected }: { view: 'overview' | 'records'; here: string; selected?: SavedSummary | null }) {
  const { tx } = useLanguage();
  const search = new URL(here, 'http://localhost').search;
  return (
    <nav aria-label={tx('结果库视图')} className="mb-5 grid gap-1.5 rounded-xl border border-border bg-secondary/60 p-1.5 sm:grid-cols-2">
      {([['overview', '实验总览', '查看同协议下的规律与曲线'], ['records', '全部记录', '查找布局、结果与搜索记录']] as const).map(([key, label, description]) => (
        <a
          key={key}
          href={resultsViewHref(key, search, selected)}
          aria-current={view === key ? 'page' : undefined}
          className={
            'min-w-0 rounded-lg px-4 py-3 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ' +
            (view === key
              ? 'bg-card text-foreground shadow-[0_1px_2px_rgba(0,0,0,0.06)] ring-1 ring-inset ring-border'
              : 'text-muted-foreground hover:bg-card/55 hover:text-foreground')
          }
        >
          <span className="block text-sm font-semibold">{tx(label)}</span>
          <span className="mt-0.5 block text-xs leading-5 text-muted-foreground">{tx(description)}</span>
        </a>
      ))}
    </nav>
  );
}
