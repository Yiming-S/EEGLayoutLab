'use client';
/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
import { useEffect, useRef, useState } from 'react';
import { Activity } from 'lucide-react';
import { LanguageSwitch } from '@/components/language-switch';
import { useLanguage } from '@/components/language-provider';
import { localizedRecordTitle } from '@/lib/i18n/records';
import { PAGES, type PageId } from '@/lib/ui-language';
import type { SavedRecord } from '@/lib/local-library';
import {
  WORKSPACES,
  WORKSPACE_TABS,
  workspaceGroup,
  workingPage,
  workspaceLinks,
  routeSelection,
  selectionHref,
  navigationAR,
  layoutCapabilities,
  type WorkspaceSelection,
} from '@/lib/workspace-navigation';

export function SiteHeader({
  current,
  arPercent,
  returnHref,
  selection: provided,
}: {
  current: PageId;
  arPercent?: number;
  labHref?: string;
  returnHref?: string;
  receptionHref?: string;
  selection?: WorkspaceSelection;
}) {
  const { tx, locale } = useLanguage();
  const headerRef = useRef<HTMLElement>(null);
  useEffect(() => {
    if (!headerRef.current || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry)
        document.documentElement.style.setProperty(
          '--workspace-header-height',
          entry.target.getBoundingClientRect().height + 'px',
        );
    });
    observer.observe(headerRef.current);
    return () => {
      observer.disconnect();
      document.documentElement.style.removeProperty(
        '--workspace-header-height',
      );
    };
  }, []);
  const [browserHref, setBrowserHref] = useState(
    () =>
      returnHref ??
      (current === 'library'
        ? '/library'
        : current === 'coordinates'
          ? '/coordinates'
          : (PAGES.find((p) => p.id === current)?.path ?? '/')),
  );
  useEffect(() => {
    const restore = () =>
      setBrowserHref(
        window.location.pathname +
          window.location.search +
          window.location.hash,
      );
    restore();
    window.addEventListener('popstate', restore);
    return () => window.removeEventListener('popstate', restore);
  }, []);
  const original = new URL(browserHref, 'http://localhost');
  const currentUrl = new URL(returnHref ?? browserHref, 'http://localhost');
  // Page props contain the latest replaceState parameters. Retain the original
  // return target without reintroducing stale layout parameters.
  if (
    !currentUrl.searchParams.has('returnTo') &&
    original.searchParams.has('returnTo')
  )
    currentUrl.searchParams.set(
      'returnTo',
      original.searchParams.get('returnTo')!,
    );
  const selection =
    provided ?? routeSelection(currentUrl.pathname + currentUrl.search);
  const ar = arPercent ?? navigationAR(browserHref);
  currentUrl.searchParams.set('ar', String(ar));
  const baseHref = currentUrl.pathname + currentUrl.search + currentUrl.hash;
  const here =
    provided && !['guide', 'method'].includes(current)
      ? selectionHref(baseHref, selection)
      : baseHref;
  const [loaded, setLoaded] = useState<{
    id: string;
    record: SavedRecord | null;
    error: boolean;
  } | null>(null);
  useEffect(() => {
    if (!selection.id) return;
    const id = selection.id,
      controller = new AbortController();
    fetch('/api/local-compute/library/' + id, {
      signal: controller.signal,
      cache: 'no-store',
    })
      .then(async (r) => {
        if (!r.ok) throw new Error('record');
        const value = (await r.json()) as { record: SavedRecord };
        if (value.record?.id !== id) throw new Error('identity');
        if (!controller.signal.aborted)
          setLoaded({ id, record: value.record, error: false });
      })
      .catch(() => {
        if (!controller.signal.aborted)
          setLoaded({ id, record: null, error: true });
      });
    return () => controller.abort();
  }, [selection.id]);
  const record = loaded?.id === selection.id ? loaded.record : null;
  const links = workspaceLinks(here, ar, record, selection);
  // Stay on the current working URL, including its draft and thresholds.
  links[current] = here;
  const group = workspaceGroup(current);
  const workPage = workingPage(here),
    workGroup = workspaceGroup(workPage);
  const destinations = {
    results: workGroup === 'results' ? links[workPage] : links.compare,
    design: workGroup === 'design' ? links[workPage] : links.design,
    reception: links.reception,
    docs: group === 'docs' ? here : links.guide,
  };
  const capabilities = layoutCapabilities(record, selection);
  const channels =
    selection.channels ??
    (selection.phase === 'saved' ? record?.layout?.xyzMm.length : undefined);
  const regions =
    selection.regions ??
    (selection.phase === 'saved' ? record?.region_count : undefined);
  const needsRecord = selection.phase === 'saved' && !!selection.id && !record;
  const blockedLink = (href: string) =>
    needsRecord &&
    href !== here &&
    [
      '/design',
      '/electrodes',
      '/decision',
      '/coordinates',
      '/reception',
    ].includes(new URL(href, currentUrl).pathname);
  const stateLabel =
    selection.phase === 'edited'
      ? '电极编辑副本 · 与原布局分开评价'
      : selection.phase === 'draft'
        ? '当前草稿 · 尚无匹配的布局评价'
        : record?.status === 'no_layout'
          ? '本轮未找到完整布局'
          : record
            ? '已保存的布局评价'
            : selection.id
              ? loaded?.id === selection.id && loaded.error
                ? '当前记录无法读取'
                : '正在读取当前布局'
              : '尚未选择布局';
  useEffect(() => {
    document.title =
      tx(
        current === 'coordinates'
          ? '坐标导入'
          : current === 'library'
            ? '布局记录'
            : (PAGES.find((p) => p.id === current)?.label ?? '历史实验'),
      ) + '｜EEG Layout Lab';
  }, [current, tx]);
  return (
    <header
      ref={headerRef}
      className="sticky top-0 z-40 border-b border-[#d6e1df] bg-[#f7faf8]/95 backdrop-blur-xl"
    >
      <div className="mx-auto flex max-w-[1500px] flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3 sm:px-6 lg:px-8">
        <a
          href={links.compare}
          aria-label={tx('EEG Layout Lab · 返回已有结果')}
          className="flex shrink-0 items-center gap-3 rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
        >
          <span className="grid size-9 place-items-center rounded-xl bg-[#102f3a] text-[#78dfcc]">
            <Activity className="size-5" />
          </span>
          <span>
            <span className="block text-base font-semibold text-[#102a34]">
              EEG Layout Lab
            </span>
            <span className="block text-xs text-[#607379]">
              {tx('脑电电极布局仿真')}
            </span>
          </span>
        </a>
        <nav
          aria-label={tx('主导航')}
          className="order-3 flex w-full gap-1 overflow-x-auto rounded-xl border border-[#dbe4e1] bg-white/85 p-1 lg:order-none lg:ml-auto lg:w-auto"
        >
          {WORKSPACES.map((p) => (
            <a
              key={p.id}
              href={
                blockedLink(destinations[p.id]) ? undefined : destinations[p.id]
              }
              aria-disabled={blockedLink(destinations[p.id]) || undefined}
              aria-current={group === p.id ? 'page' : undefined}
              className={
                'flex min-h-10 shrink-0 items-center whitespace-nowrap rounded-lg px-4 text-sm font-medium ' +
                (group === p.id
                  ? 'bg-[#102f3a] text-white'
                  : 'text-[#53686e] hover:bg-[#eef4f1]')
              }
            >
              {tx(p.label)}
            </a>
          ))}
        </nav>
        <LanguageSwitch />
      </div>
      <div className="mx-auto max-w-[1500px] px-4 pb-3 sm:px-6 lg:px-8">
        {WORKSPACE_TABS[group].length > 0 && (
          <nav
            aria-label={tx('工作区工具')}
            className="mb-2 flex gap-1 overflow-x-auto border-t border-[#dbe4e1] pt-2"
          >
            {WORKSPACE_TABS[group].map(([id, label]) => (
              <a
                key={id}
                href={blockedLink(links[id]) ? undefined : links[id]}
                aria-disabled={blockedLink(links[id]) || undefined}
                aria-current={current === id ? 'page' : undefined}
                className={
                  'shrink-0 rounded-lg px-4 py-2 text-sm font-medium ' +
                  (current === id
                    ? 'bg-primary/10 text-primary'
                    : 'text-muted-foreground hover:bg-white')
                }
              >
                {tx(label)}
              </a>
            ))}
          </nav>
        )}
        <div
          aria-label={tx('当前布局')}
          className="flex flex-wrap items-center justify-between gap-x-5 gap-y-2 rounded-lg border bg-white px-3 py-2 text-sm"
        >
          <div className="min-w-0">
            <span className="font-semibold">{tx('当前布局')} · </span>
            {record && selection.phase === 'saved'
              ? localizedRecordTitle(record, locale)
              : tx(stateLabel)}
            {channels != null && (
              <span>
                {' '}
                · {channels} {tx('电极')}
              </span>
            )}
            {regions != null && (
              <span>
                {' '}
                · {regions} {tx('区域')}
              </span>
            )}
            {record && selection.phase === 'saved' && (
              <span className="ml-2 text-muted-foreground">
                {tx(stateLabel)}
              </span>
            )}
            {selection.phase === 'edited' && (
              <span className="ml-2 text-muted-foreground">
                {tx('编辑结果不进入固定64点信号协议')}
              </span>
            )}
          </div>
          <div className="flex flex-wrap gap-x-4 gap-y-2">
            <a className="text-primary underline" href={'/library?ar=' + ar}>
              {tx('更换布局')}
            </a>
            {selection.id && (
              <a
                className="text-primary underline"
                href={'/library?record=' + selection.id + '&ar=' + ar}
              >
                {tx('查看来源')}
              </a>
            )}
            {capabilities.edit && current !== 'electrodes' && (
              <a className="text-primary underline" href={links.electrodes}>
                {tx('编辑当前布局')}
              </a>
            )}
            {capabilities.compare && current !== 'decision' && (
              <a className="text-primary underline" href={links.decision}>
                {tx('对比当前布局')}
              </a>
            )}
            {capabilities.reception && current !== 'reception' && (
              <a className="text-primary underline" href={links.reception}>
                {tx('仿真当前布局')}
              </a>
            )}
          </div>
        </div>
      </div>
    </header>
  );
}
