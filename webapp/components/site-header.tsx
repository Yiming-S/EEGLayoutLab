'use client';
import { CommunityStatus } from './community-status';
import { SHOWCASE } from '@/lib/showcase';
import { ProjectContext } from '@/features/projects/project-context';
import { recordAnnotationId } from '@/lib/local-library';
/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
import { useEffect, useRef, useState } from 'react';
import { SlidersHorizontal } from 'lucide-react';
import { BrandMark, BrandWordmark } from '@/components/brand-logo';
import { LanguageSwitch } from '@/components/language-switch';
import { useDismissibleDetails } from '@/components/use-dismissible-details';
import { cn } from '@/lib/utils';
import { useLanguage } from '@/components/language-provider';
import { localizedRecordTitle } from '@/lib/i18n/records';
import { PAGES, safeReturnHref, type PageId } from '@/lib/ui-language';
import type { SavedRecord } from '@/lib/local-library';
import { apiFetch } from '@/client/task-client';
import {
  WORKSPACES,
  WORKSPACE_TABS,
  type WorkspaceGroup,
  workspaceGroup,
  workingPage,
  workspaceLinks,
  routeSelection,
  selectionHref,
  navigationAR,
  type WorkspaceSelection,
} from '@/lib/workspace-navigation';

/** Fades the right edge of a horizontally scrolling tab row while more tabs are hidden there, and keeps the current tab in view. */
function useTabOverflow(current: PageId, locale: string) {
  const ref = useRef<HTMLElement>(null);
  const [more, setMore] = useState(false);
  useEffect(() => {
    const row = ref.current;
    if (!row) return;
    const update = () => setMore(row.scrollLeft + row.clientWidth < row.scrollWidth - 2);
    const active = row.querySelector<HTMLElement>('[aria-current="page"]');
    const reveal = () => {
      if (active) {
        const left = row.getBoundingClientRect().left + row.clientLeft;
        const right = left + row.clientWidth;
        const tab = active.getBoundingClientRect();
        if (tab.left < left) row.scrollLeft += tab.left - left;
        else if (tab.right > right) row.scrollLeft += tab.right - right;
      }
      update();
    };
    reveal();
    row.addEventListener('scroll', update, { passive: true });
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(reveal);
    observer?.observe(row);
    if (active) observer?.observe(active);
    return () => { row.removeEventListener('scroll', update); observer?.disconnect(); };
  }, [current, locale]);
  return { ref, more };
}

export function SiteHeader({
  current,
  arPercent,
  returnHref,
  selection: provided,
  offline = false,
}: {
  current: PageId;
  /** A page that reads only local files (a delivery): no task polling or record reads. */
  offline?: boolean;
  arPercent?: number;
  labHref?: string;
  returnHref?: string;
  receptionHref?: string;
  selection?: WorkspaceSelection;
}) {
  const { tx, locale } = useLanguage();
  const settings = useDismissibleDetails();
  const headerRef = useRef<HTMLElement>(null);
  const { ref: areasRef } = useTabOverflow(current, locale);
  const { ref: tabsRef, more: moreTabs } = useTabOverflow(current, locale);
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
    () => returnHref ?? (PAGES.find((p) => p.id === current)?.path ?? '/'),
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
    if (!selection.id || offline) return;
    const id = selection.id,
      controller = new AbortController();
    apiFetch('/api/local-compute/library/' + id + (annotationId ? '?annotation_id=' + annotationId : ''), {
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
  }, [selection.id, annotationId, offline]);
  const record = loaded?.id === selection.id ? loaded.record : null;
  const links = workspaceLinks(here, ar, record, selection);
  links[current] = here;
  const group = workspaceGroup(current);
  const workPage = workingPage(here),
    workGroup = workspaceGroup(workPage);
  const firstTab = (area: WorkspaceGroup) => WORKSPACE_TABS[area][0][0] as PageId;
  const destinations = Object.fromEntries(WORKSPACES.map(({ id: area }) => [area,
    area === group ? (area === 'docs' ? here : links[current])
      : workGroup === area ? links[workPage] : links[firstTab(area)]])) as Record<WorkspaceGroup, string>;
  const areas = WORKSPACES.filter(area => !SHOWCASE || area.id !== 'workspace');
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
    document.title = tx(PAGES.find((p) => p.id === current)?.label ?? '历史批次') + '｜EEG Layout Lab';
  }, [current, tx]);
  return (
    <header
      ref={headerRef}
      className="sticky top-0 z-40 border-b border-border bg-background/92 backdrop-blur-md supports-[backdrop-filter]:bg-background/84"
    >
      <div className="mx-auto flex max-w-[1440px] flex-wrap items-center justify-between gap-x-4 gap-y-2.5 px-4 py-3 sm:px-6 lg:grid lg:grid-cols-[1fr_auto_1fr] lg:px-8">
        <a
          href={SHOWCASE ? links.findings : links.home}
          aria-label={tx(SHOWCASE ? 'EEG Layout Lab · 返回已有结果' : 'EEG Layout Lab · 返回工作区')}
          className="group flex shrink-0 items-center gap-3 justify-self-start rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <BrandMark className="rounded-[9px] shadow-[0_1px_2px_rgba(20,20,19,0.06)] transition-transform duration-150 group-hover:scale-[1.03]" />
          <BrandWordmark subtitle={tx('脑电电极布局仿真')} locale={locale} />
        </a>
        <nav
          ref={areasRef}
          aria-label={tx('主导航')}
          className="order-3 flex w-full items-center gap-1 overflow-x-auto rounded-xl border border-border/85 bg-secondary/65 p-1 [scrollbar-width:none] lg:order-none lg:w-auto lg:justify-self-center"
        >
          {areas.map((p) => (
            <a
              key={p.id}
              href={
                blockedLink(destinations[p.id]) ? undefined : destinations[p.id]
              }
              aria-disabled={blockedLink(destinations[p.id]) || undefined}
              aria-current={group === p.id ? 'page' : undefined}
              className={
                'flex h-8.5 flex-1 items-center justify-center whitespace-nowrap rounded-lg px-4 text-[0.9rem] transition-all lg:flex-none ' +
                (group === p.id
                  ? 'bg-card font-semibold text-foreground shadow-[0_1px_2px_rgba(0,0,0,0.06)] ring-1 ring-inset ring-border/90'
                  : 'font-medium text-ink-soft hover:bg-card/55 hover:text-foreground')
              }
            >
              {tx(p.label)}
            </a>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-2 lg:ml-0 lg:justify-self-end">
          {!SHOWCASE && !offline && <CommunityStatus />}
          <details ref={settings} className="relative">
            <summary
              aria-label={tx('界面设置')}
              className="flex size-9 cursor-pointer list-none items-center justify-center rounded-lg border border-border bg-card text-ink-soft shadow-[0_1px_1px_rgba(0,0,0,0.02)] transition-colors hover:border-foreground/30 hover:text-foreground [&::-webkit-details-marker]:hidden"
            >
              <SlidersHorizontal className="size-4" />
            </summary>
            <div className="absolute right-0 z-50 mt-2 rounded-xl border border-border bg-popover p-3.5 shadow-[0_14px_32px_-10px_rgba(0,0,0,0.16)]">
              <LanguageSwitch />
            </div>
          </details>
        </div>
      </div>
      {(WORKSPACE_TABS[group].length > 0 || selection.id || selection.phase !== 'saved') && (
        <div className="border-t border-border/80 bg-card/80">
          <div className="mx-auto flex max-w-[1440px] items-center justify-between gap-x-4 px-4 sm:flex-wrap sm:gap-y-1 sm:px-6 lg:px-8">
            {WORKSPACE_TABS[group].length > 0 && (
              <nav
                ref={tabsRef}
                aria-label={tx('工作区工具')}
                className={cn(
                  'flex min-w-0 items-center gap-7 overflow-x-auto [scrollbar-width:none] max-sm:flex-1 sm:max-w-full sm:shrink-0',
                  moreTabs && '[mask-image:linear-gradient(to_right,#000_calc(100%-2.5rem),transparent)]',
                )}
              >
                {WORKSPACE_TABS[group].map(([id, label]) => (
                  <a
                    key={id}
                    href={blockedLink(links[id]) ? undefined : links[id]}
                    aria-disabled={blockedLink(links[id]) || undefined}
                    aria-current={current === id ? 'page' : undefined}
                    className={
                      'relative inline-flex h-11 shrink-0 items-center px-0.5 text-[0.9rem] transition-colors ' +
                      (current === id
                        ? 'font-semibold text-foreground after:absolute after:inset-x-0 after:bottom-0 after:h-[2.5px] after:rounded-t-full after:bg-foreground'
                        : 'font-medium text-ink-soft hover:text-foreground')
                    }
                  >
                    {tx(label)}
                  </a>
                ))}
              </nav>
            )}
            {(selection.id || selection.phase !== 'saved') && <div
              aria-label={tx('当前布局')}
              className="flex min-w-0 shrink-0 items-center justify-end gap-x-2.5 gap-y-1 py-1.5 text-[0.8125rem] sm:flex-1"
            >
              <div
                className="hidden min-w-0 items-center gap-2 truncate rounded-lg border border-border bg-background/85 px-3 py-1 sm:inline-flex"
                title={record && selection.phase === 'saved' ? `${localizedRecordTitle(record, locale)} · ${tx(stateLabel)}` : tx(stateLabel)}
              >
                <span
                  aria-hidden
                  className={cn(
                    'size-1.5 shrink-0 rounded-full',
                    selection.phase === 'edited' || selection.phase === 'draft'
                      ? 'bg-warning'
                      : record
                        ? 'bg-success'
                        : 'bg-foreground/45',
                  )}
                />
                <span className="font-medium text-muted-foreground">{tx('当前布局')}</span>
                <span aria-hidden className="text-border">·</span>
                <span className="truncate text-foreground">
                  {record && selection.phase === 'saved'
                    ? current === 'layout' ? localizedRecordTitle(record, locale)
                      : <a className="font-medium underline decoration-border underline-offset-4 hover:decoration-foreground" href={links.layout}>{localizedRecordTitle(record, locale)}</a>
                    : tx(stateLabel)}
                </span>
                {channels != null && (
                  <span className="shrink-0 font-mono text-xs text-muted-foreground tabular-nums">
                    · {channels} {tx('电极')}
                  </span>
                )}
                {selection.phase === 'edited' && (
                  <span className="ml-1 shrink-0 text-xs text-muted-foreground">
                    {tx('编辑结果不进入固定64点信号协议')}
                  </span>
                )}
              </div>
              <div className="shrink-0">
                <a className="lab-link-pill" href={'/library?ar=' + ar}>
                  {tx('更换布局')}
                </a>
              </div>
            </div>}
          </div>
        </div>
      )}
      <ProjectContext currentIsProjects={current === 'projects'} here={here} recordId={selection.phase === 'saved' && record?.status === 'completed' ? record.id : undefined} />
    </header>
  );
}
