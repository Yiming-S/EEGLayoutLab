'use client';
import { CommunityStatus } from './community-status';
import { ProjectContext } from '@/features/projects/project-context';
import { recordAnnotationId } from '@/lib/local-library';
/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
import { useEffect, useRef, useState } from 'react';
import { Activity, Settings2 } from 'lucide-react';
import { LanguageSwitch } from '@/components/language-switch';
import { useLanguage } from '@/components/language-provider';
import { localizedRecordTitle } from '@/lib/i18n/records';
import { PAGES, safeReturnHref, type PageId } from '@/lib/ui-language';
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
        : current === 'projects'
          ? '/projects'
        : current === 'robustness'
          ? '/robustness'
        : current === 'coordinates'
          ? '/coordinates'
          : (PAGES.find((p) => p.id === current)?.path ?? '/')),
  );
  useEffect(() => {
    const restore = () =>
      setBrowserHref(safeReturnHref(
        window.location.pathname +
          window.location.search +
          window.location.hash, '/'));
    restore();
    window.addEventListener('popstate', restore);
    return () => window.removeEventListener('popstate', restore);
  }, []);
  const original = new URL(browserHref, 'http://localhost');
  const currentUrl = new URL(safeReturnHref(returnHref ?? browserHref, '/'), 'http://localhost');
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
  const annotationId = recordAnnotationId(here, selection.id);
  useEffect(() => {
    if (!selection.id) return;
    const id = selection.id,
      controller = new AbortController();
    fetch('/api/local-compute/library/' + id + (annotationId ? '?annotation_id=' + annotationId : ''), {
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
  }, [selection.id, annotationId]);
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
  const channels =
    selection.channels ??
    (selection.phase === 'saved' ? record?.layout?.xyzMm.length : undefined);
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
          : current === 'projects'
            ? '研究项目'
          : current === 'robustness'
            ? '稳健性研究'
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
      <div className="mx-auto flex max-w-[1500px] flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2 sm:px-6 lg:px-8">
        <a
          href={links.compare}
          aria-label={tx('EEG Layout Lab · 返回已有结果')}
          className="flex shrink-0 items-center gap-3 rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
        >
          <span className="grid size-8 place-items-center rounded-xl bg-[#102f3a] text-[#78dfcc] sm:size-9">
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
          className="order-3 flex w-full gap-1 overflow-x-auto rounded-lg bg-white/85 p-1 min-[1000px]:order-none min-[1000px]:ml-auto min-[1000px]:w-auto"
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
                'flex min-h-9 flex-1 items-center justify-center whitespace-nowrap rounded-lg px-3 text-sm font-medium min-[1000px]:flex-none ' +
                (group === p.id
                  ? 'bg-[#102f3a] text-white'
                  : 'text-[#53686e] hover:bg-[#eef4f1]')
              }
            >
              {tx(p.label)}
            </a>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-1 min-[1000px]:ml-0">
          <CommunityStatus />
          <details className="relative">
            <summary aria-label={tx('界面设置')} className="flex size-9 cursor-pointer list-none items-center justify-center rounded-lg border bg-white text-muted-foreground hover:text-foreground [&::-webkit-details-marker]:hidden">
              <Settings2 className="size-4" />
            </summary>
            <div className="absolute right-0 z-50 mt-2 rounded-xl border bg-white p-3 shadow-lg">
              <LanguageSwitch />
            </div>
          </details>
        </div>
      </div>
      <div className="mx-auto flex max-w-[1500px] flex-wrap items-center justify-between gap-x-3 gap-y-1 px-4 pb-2 sm:px-6 lg:px-8">
        {WORKSPACE_TABS[group].length > 0 && (
          <nav
            aria-label={tx('工作区工具')}
            className="flex max-w-full shrink-0 gap-1 overflow-x-auto"
          >
            {WORKSPACE_TABS[group].map(([id, label]) => (
              <a
                key={id}
                href={blockedLink(links[id]) ? undefined : links[id]}
                aria-disabled={blockedLink(links[id]) || undefined}
                aria-current={current === id ? 'page' : undefined}
                className={
                  'shrink-0 rounded-lg px-3 py-1.5 text-sm font-medium ' +
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
          className="flex min-w-0 flex-1 items-center justify-end gap-x-3 gap-y-1 text-sm"
        >
          <div className="hidden min-w-0 truncate sm:block" title={record && selection.phase === 'saved' ? `${localizedRecordTitle(record, locale)} · ${tx(stateLabel)}` : tx(stateLabel)}>
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
            {selection.phase === 'edited' && (
              <span className="ml-2 text-muted-foreground">
                {tx('编辑结果不进入固定64点信号协议')}
              </span>
            )}
          </div>
          <div className="shrink-0">
            <a className="text-primary underline" href={'/library?ar=' + ar}>
              {tx('更换布局')}
            </a>
          </div>
        </div>
      </div>
      <ProjectContext currentIsProjects={current === 'projects'} here={here} recordId={selection.phase === 'saved' && record?.status === 'completed' ? record.id : undefined} />
    </header>
  );
}
