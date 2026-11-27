'use client';
/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { ArrowUpRight, BookOpen, FlaskConical, FolderKanban, Grid3x3, Import, PencilRuler, Search } from 'lucide-react';
import { DataReadinessNotice } from '@/components/data-readiness-notice';
import { useLanguage } from '@/components/language-provider';
import { RuntimeMessage } from '@/components/runtime-message';
import { SiteHeader } from '@/components/site-header';
import { TaskList, useTaskStatus } from '@/components/community-status';
import { TermHint } from '@/components/term-hint';
import { Button } from '@/components/ui/button';
import { apiJson } from '@/client/task-client';
import { listRobustnessStudies } from '@/client/robustness';
import { localizedRecordTitle } from '@/lib/i18n/records';
import { protocolName, metricPercent } from '@/lib/ui-language';
import { methodLink, parseAR } from '@/lib/lab-workflow';
import { documentationHref } from '@/lib/documentation';
import { SHOWCASE } from '@/lib/showcase';
import { exampleLayout, layoutHref, recentLayouts } from '@/lib/layout-page';
import type { LocalLibrary, SavedSummary } from '@/lib/local-library';
import type { StudyDirectoryEntry } from '@/contracts/robustness-study';
import { cn } from '@/lib/utils';

/** Old overview addresses carried these; they now open the findings page. */
export const OVERVIEW_PARAMETERS = ['domain', 'area', 'r', 'metric'] as const;
/** Set once the reader closes the start panel; the panel reopens from the page header. */
export const START_DISMISSED_KEY = 'eeg-layout-lab/start-dismissed';

const RECENT = 6;
const STUDY_STATUS: Record<string, string> = { draft: '草稿', running: '进行中', paused: '已暂停', completed: '已完成', cancelled: '已取消' };

/** Hairline-divided 3-column architectural matrix for primary entry paths. */
function ArchitecturalMatrix({
  items,
  framed = false,
}: {
  items: { href: string; icon: typeof Search; title: string; text: string }[];
  framed?: boolean;
}) {
  const { tx } = useLanguage();
  return (
    <div
      className={cn(
        'grid divide-y divide-border sm:grid-cols-3 sm:divide-x sm:divide-y-0',
        framed ? 'overflow-hidden rounded-lg border border-border bg-card' : 'border-y border-border bg-card',
      )}
    >
      {items.map(({ href, icon: Icon, title, text }, index) => (
        <a
          key={title}
          href={href}
          className="group relative flex flex-col justify-between gap-5 p-5 transition-colors hover:bg-secondary/45 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring sm:p-6"
        >
          <span className="flex items-center justify-between gap-3">
            <span className="inline-flex items-center gap-2 font-mono text-[11px] font-medium tracking-widest text-muted-foreground">
              <span>{String(index + 1).padStart(2, '0')}</span>
              <span aria-hidden className="h-px w-3 bg-border" />
              <Icon aria-hidden className="size-3.5 text-foreground/75" />
            </span>
            <ArrowUpRight
              aria-hidden
              className="size-4 text-muted-foreground/50 transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5 group-hover:text-foreground"
            />
          </span>
          <span>
            <span className="block text-[0.9375rem] font-semibold tracking-[-0.015em] text-foreground">
              {tx(title)}
            </span>
            <span className="mt-1.5 block text-[0.8125rem] leading-6 text-muted-foreground">
              {tx(text)}
            </span>
          </span>
        </a>
      ))}
    </div>
  );
}

/** What the application answers, three ways in by goal, and how to read a score. */
function StartHere({ ar, example, onClose }: { ar: number; example: string | null; onClose: () => void }) {
  const { tx } = useLanguage();
  const goals = [
    { href: '/findings?ar=' + ar, icon: BookOpen, title: '先看现成结论', text: '浏览总面积研究：1–6个区域在不同面积上限下各保留多少信号。只读，不需要计算。' },
    { href: '/coordinates?ar=' + ar, icon: Import, title: '评价我已有的电极位置', text: '导入CSV、JSON、BIDS、.elc或.sfp坐标文件，或按10-05电极名称导入，得到三项保留率。' },
    { href: '/design?ar=' + ar, icon: Search, title: '设计一个新布局', text: '选择头部部位、区域数、电极总数（8–64导）和每区大小，搜索布局并评价。' },
  ];
  const rules = [
    '保留率 = 布局的得分 ÷ 标准64导全头布置的得分；100%表示与全头64导相同。',
    '三项保留率分别回答：标准64导记录到的头皮电场能重建多少（场重建）；损失最多的10%脑源还能记录到多大的电位差（幅度）；源定位与标准64导相比如何（定位效用）。',
    '最低保留要求是你设定的合格线：三项保留率都达到它才算合格。调整它只重新判断，不重新计算。',
  ] as const;
  const here = '/?ar=' + ar;
  return (
    <section aria-labelledby="start-here" className="lab-hero">
      <div className="bg-card/85 p-5 sm:px-7 sm:py-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="max-w-3xl">
            <span className="font-mono text-[11px] font-medium tracking-[0.12em] text-muted-foreground uppercase">
              8–64 CH · ERNIE FEM
            </span>
            <h2 id="start-here" className="mt-1.5 text-lg font-semibold tracking-[-0.02em] text-foreground sm:text-xl">
              {tx('从这里开始')}
            </h2>
            <p className="mt-2 max-w-2xl text-sm leading-6.5 text-ink-soft">
              {tx('把电极集中放在头上少数几个区域（默认64导，支持8–64导探索），相比标准64导全头布置还能保留多少信号？本应用用头模仿真回答这个问题，并帮你设计、评价和比较这样的布局。')}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {example && (
              <a href={layoutHref({ key: example }, ar)} className="lab-link-pill h-7.5 px-2.5">
                {tx('打开示例布局')}
                <ArrowUpRight aria-hidden className="size-3.5" />
              </a>
            )}
            <Button size="sm" variant="outline" onClick={onClose}>
              {tx('我已了解，收起')}
            </Button>
          </div>
        </div>
        {example && (
          <p className="mt-2.5 text-xs text-muted-foreground">
            {tx('一个已在多种条件下评价过的布局，可以先看看完整的结果页面。')}
          </p>
        )}
      </div>

      <ArchitecturalMatrix items={goals} />

      <div className="bg-secondary/35 px-5 py-4 sm:px-7 sm:py-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-xs font-semibold tracking-wide text-foreground/90 uppercase">
            {tx('怎么读分数')}
          </h3>
          <div className="flex flex-wrap gap-2">
            <a href={methodLink(here, ar, '#retention-guide')} className="lab-link-pill">
              {tx('三项指标如何计算')}
            </a>
            <a href={documentationHref('/', '?ar=' + ar, 'guide')} className="lab-link-pill">
              {tx('使用指南')}
            </a>
          </div>
        </div>
        <ul className="mt-3.5 grid gap-4 md:grid-cols-3">
          {rules.map((rule, index) => (
            <li key={index} className="flex gap-2.5 text-xs leading-5.5 text-muted-foreground">
              <span aria-hidden className="font-mono text-[11px] font-medium text-foreground/45 select-none">
                0{index + 1}
              </span>
              <span>{tx(rule)}</span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

function NewLayout({ ar }: { ar: number }) {
  const { tx } = useLanguage();
  return (
    <section aria-labelledby="new-layout" className="space-y-3">
      <div className="flex items-center justify-between">
        <h2 id="new-layout" className="text-sm font-semibold tracking-tight text-foreground">
          {tx('新建布局')}
        </h2>
      </div>
      <ArchitecturalMatrix
        framed
        items={[
          { href: '/design?ar=' + ar, icon: Search, title: '按区域搜索', text: '选择部位、区域数、电极总数（默认64导）和每区半径，搜索最优布局。' },
          { href: '/coordinates?ar=' + ar, icon: Import, title: '坐标导入', text: '读取已有电极坐标文件，在当前条件下评价。' },
          { href: '/library?ar=' + ar, icon: PencilRuler, title: '复制并编辑', text: '从布局列表打开一个布局，移动或停用电极。' },
        ]}
      />
    </section>
  );
}

/** A panel with nothing to show is one line: its name, why it is empty, and where to go. */
function EmptyLine({ id, title, icon, note, children }: { id: string; title: string; icon?: ReactNode; note: string; children?: ReactNode }) {
  const { tx } = useLanguage();
  return <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2.5">
    <div className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-1">
      <h2 id={id} className="flex items-center gap-2 text-sm font-semibold text-foreground">{icon}{tx(title)}</h2>
      <span className="text-[0.8125rem] text-muted-foreground">{tx(note)}</span>
    </div>
    {children}
  </div>;
}

function RecentLayouts({ records, ar, error }: { records: SavedSummary[] | null; ar: number; error: string }) {
  const { tx, locale, date } = useLanguage();
  const recent = useMemo(() => recentLayouts(records ?? [], RECENT), [records]);
  return <section aria-labelledby="recent-layouts" className="lab-panel">
    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border pb-3.5">
      <h2 id="recent-layouts" className="text-base font-semibold tracking-tight">{tx('最近的布局')}</h2>
      <a href={'/library?ar=' + ar} className="lab-link-pill">{tx('全部布局')}</a>
    </div>
    {error ? <p role="alert" className="mt-3 text-sm text-danger"><RuntimeMessage message={error} /></p>
      : !records ? <p className="mt-3 text-sm text-muted-foreground">{tx('读取方案目录…')}</p>
      : !recent.length ? <p className="mt-3 text-sm text-muted-foreground">{tx('还没有保存的布局。')}</p>
      : <>
        <ul className="divide-y divide-border/80">
          {recent.map(group => {
            const record = group[0], latest = group.map(row => row.finished_at!).sort().at(-1)!;
            return <li key={record.layout_key ?? record.id} className="-mx-2 rounded-lg px-2 py-3 transition-colors hover:bg-secondary/45">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <a href={layoutHref(record.layout_key ? { key: record.layout_key } : { id: record.id }, ar)} className="text-sm font-medium text-foreground underline-offset-4 hover:underline">{localizedRecordTitle({ ...record, evaluation_condition: undefined }, locale)}</a>
                {record.metrics?.field_relative != null && (
                  <span className="rounded border border-border bg-secondary/70 px-2 py-0.5 font-mono text-[11px] font-medium text-foreground tabular-nums">
                    {tx('场重建保留率')} {metricPercent(record.metrics.field_relative)}
                  </span>
                )}
              </div>
              <span className="mt-1 block font-mono text-[11px] text-muted-foreground">
                {tx(protocolName(record.dataset_id))}{group.length > 1 && <> · {tx(`共${group.length}种条件`)}</>} · {date(latest)}
              </span>
            </li>;
          })}
        </ul>
        <TermHint term="retention" ar={ar} className="mt-3.5 border-t border-border/70 pt-3" />
      </>}
  </section>;
}

function Tasks() {
  const { tx } = useLanguage();
  const tasks = useTaskStatus(), { status, offline, failure } = tasks;
  // Idle while the first status is read, or when the workspace has no task; a service that has ended is not idle.
  const idle = !failure && (status ? !status.jobs.length && !status.recovery_blocked && status.available !== false : offline === 'loading');
  return <section id="tasks" aria-labelledby="tasks-title" className={cn('lab-panel scroll-mt-32', idle && 'py-4')}>
    {idle ? <EmptyLine id="tasks-title" title="计算任务" note="此工作区暂无计算任务" />
      : <><h2 id="tasks-title" className="text-base font-semibold">{tx('计算任务')}</h2><div className="text-sm"><TaskList {...tasks} /></div></>}
  </section>;
}

function Studies({ ar }: { ar: number }) {
  const { tx, date } = useLanguage();
  const [studies, setStudies] = useState<StudyDirectoryEntry[] | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    listRobustnessStudies(controller.signal).then(value => setStudies(value.studies))
      .catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '研究目录无法读取'); });
    return () => controller.abort();
  }, []);
  const recent = (studies ?? []).slice().sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at)).slice(0, RECENT);
  const icon = <span aria-hidden className="grid size-5.5 place-items-center rounded border border-border bg-secondary/70 text-foreground/80"><FlaskConical className="size-3" /></span>;
  const all = <a href={'/robustness?ar=' + ar} className="lab-link-pill">{tx('全部研究')}</a>;
  if (studies && !recent.length && !error) return <section aria-labelledby="recent-studies" className="lab-panel py-4">
    <EmptyLine id="recent-studies" title="稳健性研究" icon={icon} note="还没有稳健性研究。">
      <a href={'/robustness?ar=' + ar} className="lab-link-pill">{tx('新建研究')}</a>
    </EmptyLine>
  </section>;
  return <section aria-labelledby="recent-studies" className="lab-panel">
    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border pb-3">
      <h2 id="recent-studies" className="flex items-center gap-2 text-base font-semibold">{icon}{tx('稳健性研究')}</h2>
      {all}
    </div>
    {error ? <p className="mt-3 text-sm text-muted-foreground"><RuntimeMessage message={error} /></p>
      : !studies ? <p className="mt-3 text-sm text-muted-foreground">{tx('读取研究目录…')}</p>
      : <ul className="divide-y divide-border/80">{recent.map(study => <li key={study.id} className="-mx-2 rounded-lg px-2 py-2.5 transition-colors hover:bg-secondary/45">
        <a href={'/robustness?study=' + study.id} className="text-sm font-medium text-foreground underline-offset-4 hover:underline">{study.title}</a>
        <span className="mt-0.5 block font-mono text-[11px] text-muted-foreground">{tx(STUDY_STATUS[study.status] ?? study.status)} · {tx(`${study.completed_cases}/${study.case_count}个案例`)} · {date(study.updated_at)}</span>
      </li>)}</ul>}
  </section>;
}

export default function HomeWorkspace() {
  const { tx } = useLanguage();
  const [ar, setAR] = useState(90);
  const [library, setLibrary] = useState<SavedSummary[] | null>(null);
  const [error, setError] = useState('');
  const [start, setStart] = useState<boolean | null>(null);
  const example = useMemo(() => exampleLayout(library ?? []), [library]);
  const layoutCount = useMemo(() => (library ? recentLayouts(library, 9999).length : null), [library]);
  const showStart = (open: boolean) => {
    setStart(open);
    try { if (open) localStorage.removeItem(START_DISMISSED_KEY); else localStorage.setItem(START_DISMISSED_KEY, '1'); } catch { /* storage is optional */ }
  };
  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    if (SHOWCASE || OVERVIEW_PARAMETERS.some(key => q.has(key))) { window.location.replace('/findings' + window.location.search + window.location.hash); return; }
    const restore = () => {
      setAR(parseAR(new URLSearchParams(window.location.search).get('ar')));
      let dismissed = false;
      try { dismissed = localStorage.getItem(START_DISMISSED_KEY) === '1'; } catch { /* storage is optional */ }
      setStart(!dismissed);
    };
    restore();
    const controller = new AbortController();
    apiJson<LocalLibrary>('/api/local-compute/library', { signal: controller.signal, errorMessage: '数据服务暂不可用，请稍后重新读取。' })
      .then(value => setLibrary(value.records)).catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '数据服务暂不可用，请稍后重新读取。'); });
    return () => controller.abort();
  }, []);
  return <main className="lab-page">
    <SiteHeader current="home" arPercent={ar} />
    <div className="lab-container space-y-6 pb-12">
      <header className="flex flex-wrap items-end justify-between gap-4 border-b border-border pt-7 pb-5">
        <div>
          <h1 className="text-2xl font-semibold tracking-[-0.028em] text-foreground sm:text-[1.65rem]">{tx('工作区')}</h1>
          <p className="mt-1 text-sm text-muted-foreground">{tx('你的布局、计算任务、研究和项目。')}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2.5">
          <span className="inline-flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-1.5 font-mono text-xs text-muted-foreground tabular-nums">
            <span>AR τ = {ar}%</span>
            {layoutCount != null && (
              <>
                <span aria-hidden className="text-border">|</span>
                <span>{layoutCount} {tx('全部布局')}</span>
              </>
            )}
          </span>
          {start === false && <Button size="sm" variant="outline" onClick={() => showStart(true)}>{tx('新手入门')}</Button>}
        </div>
      </header>
      <DataReadinessNotice scope="home" />
      {start ? <StartHere ar={ar} example={example} onClose={() => showStart(false)} /> : start === false && <NewLayout ar={ar} />}
      <div className="grid items-start gap-5 lg:grid-cols-2">
        <RecentLayouts records={library} ar={ar} error={error} />
        <div className="space-y-3.5">
          <Tasks />
          <Studies ar={ar} />
          <section aria-labelledby="projects-title" className="lab-panel py-4">
            <EmptyLine id="projects-title" title="研究项目" icon={<span aria-hidden className="grid size-5.5 place-items-center rounded border border-border bg-secondary/70 text-foreground/80"><FolderKanban className="size-3" /></span>} note="项目把多个布局、对比和交付包放在一起，便于导出和交给合作者。">
              <span className="flex flex-wrap gap-2">
                <a href="/projects" className="lab-link-pill">{tx('打开研究项目')}</a>
                <a href="/deliveries" className="lab-link-pill">{tx('读取交付包')}</a>
              </span>
            </EmptyLine>
          </section>
          <section aria-labelledby="findings-title" className="lab-panel py-4">
            <EmptyLine id="findings-title" title="研究结果" icon={<span aria-hidden className="grid size-5.5 place-items-center rounded border border-border bg-secondary/70 text-foreground/80"><Grid3x3 className="size-3" /></span>} note="已发表的总面积研究和历史批次。">
              <span className="flex flex-wrap gap-2">
                <a href={'/findings?ar=' + ar} className="lab-link-pill">{tx('打开总面积研究')}</a>
                <a href={'/results?ar=' + ar} className="lab-link-pill">{tx('历史批次')}</a>
              </span>
            </EmptyLine>
          </section>
        </div>
      </div>
    </div>
  </main>;
}
