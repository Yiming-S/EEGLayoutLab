'use client';
/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
import { useLanguage } from '@/components/language-provider';
import { resultsViewHref } from '@/lib/results-library';
import type { SavedSummary } from '@/lib/local-library';

export function ResultsNavigation({ view, here, selected }: { view: 'overview' | 'records'; here: string; selected?: SavedSummary | null }) {
  const { tx } = useLanguage();
  const search = new URL(here, 'http://localhost').search;
  return <nav aria-label={tx('结果库视图')} className="mb-5 flex flex-wrap gap-2 rounded-xl border bg-white p-2">
    {([['overview', '实验总览', '查看同协议下的规律与曲线'], ['records', '全部记录', '查找布局、结果与搜索记录']] as const).map(([key, label, description]) =>
      <a key={key} href={resultsViewHref(key, search, selected)} aria-current={view === key ? 'page' : undefined}
        className={'min-w-0 flex-1 rounded-lg px-4 py-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary ' + (view === key ? 'bg-[#102f3a] text-white' : 'text-[#53686e] hover:bg-secondary')}>
        <span className="block text-base font-semibold">{tx(label)}</span><span className="mt-1 block text-sm leading-6">{tx(description)}</span>
      </a>)}
  </nav>;
}
