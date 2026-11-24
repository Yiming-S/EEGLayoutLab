'use client';
/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { BookOpen, FlaskConical, FolderKanban, Grid3x3, Import, PencilRuler, Search } from 'lucide-react';
import { useLanguage } from '@/components/language-provider';
import { RuntimeMessage } from '@/components/runtime-message';
import { SiteHeader } from '@/components/site-header';
import { TaskList, VisitorNotice, useTaskStatus } from '@/components/community-status';
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
const cardClass = 'group flex gap-3 rounded-lg border bg-card p-3 hover:border-primary/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary';

function Cards({ items }: { items: { href: string; icon: typeof Search; title: string; text: string }[] }) {
  const { tx } = useLanguage();
  return <div className="mt-3 grid gap-3 sm:grid-cols-3">
    {items.map(({ href, icon: Icon, title, text }) => <a key={title} href={href} className={cardClass}>
      <Icon aria-hidden className="mt-0.5 size-5 shrink-0 text-primary" />
      <span><span className="block font-medium group-hover:text-primary">{tx(title)}</span><span className="mt-1 block text-sm leading-6 text-muted-foreground">{tx(text)}</span></span>
    </a>)}
  </div>;
}

/** What the application answers, three ways in by goal, and how to read a score. */
function StartHere({ ar, example, onClose }: { ar: number; example: string | null; onClose: () => void }) {
  const { tx } = useLanguage();
  const goals = [
    { href: '/findings?ar=' + ar, icon: BookOpen, title: '先看现成结论', text: '浏览总面积研究：1–6个区域在不同面积上限下各保留多少信号。只读，不需要计算。' },
    { href: '/coordinates?ar=' + ar, icon: Import, title: '评价我已有的电极位置', text: '导入CSV、JSON、BIDS、.elc或.sfp坐标文件，或按10-05电极名称导入，得到三项保留率。' },
    { href: '/design?ar=' + ar, icon: Search, title: '设计一个新布局', text: '选择头部部位、区域数和每区大小，搜索64电极布局并评价。' },
  ];
  const here = '/?ar=' + ar;
  return <section aria-labelledby="start-here" className="lab-panel border-primary/40">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="max-w-3xl">
        <h2 id="start-here" className="text-lg font-semibold">{tx('从这里开始')}</h2>
        <p className="mt-1 text-sm leading-6">{tx('把64个电极集中放在头上少数几个区域，相比标准64导全头布置还能保留多少信号？本应用用头模仿真回答这个问题，并帮你设计、评价和比较这样的布局。')}</p>
      </div>
      <Button size="sm" variant="outline" onClick={onClose}>{tx('我已了解，收起')}</Button>
    </div>
    <Cards items={goals} />
    {example && <p className="mt-3 text-sm">
      <a href={layoutHref({ key: example }, ar)} className="font-medium text-primary underline underline-offset-4">{tx('打开示例布局')}</a>
      <span className="text-muted-foreground"> · {tx('一个已在多种条件下评价过的布局，可以先看看完整的结果页面。')}</span>
    </p>}
    <div className="mt-4 border-t pt-3">
      <h3 className="text-sm font-semibold">{tx('怎么读分数')}</h3>
      <ul className="mt-2 list-disc space-y-1 pl-5 text-sm leading-6 text-muted-foreground">
        <li>{tx('保留率 = 布局的得分 ÷ 标准64导全头布置的得分；100%表示与全头64导相同。')}</li>
        <li>{tx('三项保留率分别回答：标准64导记录到的头皮电场能重建多少（场重建）；损失最多的10%脑源还能记录到多大的电位差（幅度）；源定位与标准64导相比如何（定位效用）。')}</li>
        <li>{tx('最低保留要求是你设定的合格线：三项保留率都达到它才算合格。调整它只重新判断，不重新计算。')}</li>
      </ul>
      <p className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm">
        <a href={methodLink(here, ar, '#retention-guide')} className="text-primary underline underline-offset-4">{tx('三项指标如何计算')}</a>
        <a href={documentationHref('/', '?ar=' + ar, 'guide')} className="text-primary underline underline-offset-4">{tx('使用指南')}</a>
      </p>
    </div>
  </section>;
}

function NewLayout({ ar }: { ar: number }) {
  const { tx } = useLanguage();
  return <section aria-labelledby="new-layout" className="lab-panel">
    <h2 id="new-layout" className="text-lg font-semibold">{tx('新建布局')}</h2>
    <Cards items={[
      { href: '/design?ar=' + ar, icon: Search, title: '按区域搜索', text: '选择部位、区域数和每区半径，搜索64电极布局。' },
      { href: '/coordinates?ar=' + ar, icon: Import, title: '坐标导入', text: '读取已有电极坐标文件，在当前条件下评价。' },
      { href: '/library?ar=' + ar, icon: PencilRuler, title: '复制并编辑', text: '从布局列表打开一个布局，移动或停用电极。' },
    ]} />
  </section>;
}

/** A panel with nothing to show is one line: its name, why it is empty, and where to go. */
function EmptyLine({ id, title, icon, note, children }: { id: string; title: string; icon?: ReactNode; note: string; children?: ReactNode }) {
  const { tx } = useLanguage();
  return <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
    <h2 id={id} className="flex items-center gap-2 text-base font-semibold">{icon}{tx(title)}</h2>
    <span className="text-sm text-muted-foreground">{tx(note)}</span>
    {children}
  </div>;
}

function RecentLayouts({ records, ar, error }: { records: SavedSummary[] | null; ar: number; error: string }) {
  const { tx, locale, date } = useLanguage();
  // One row per layout: a layout evaluated on several heads or noise models is one entry.
  const recent = useMemo(() => recentLayouts(records ?? [], RECENT), [records]);
  return <section aria-labelledby="recent-layouts" className="lab-panel">
    <div className="flex flex-wrap items-baseline justify-between gap-2">
      <h2 id="recent-layouts" className="text-lg font-semibold">{tx('最近的布局')}</h2>
      <a href={'/library?ar=' + ar} className="text-sm text-primary underline underline-offset-4">{tx('全部布局')}</a>
    </div>
    {error ? <p role="alert" className="mt-3 text-sm text-danger"><RuntimeMessage message={error} /></p>
      : !records ? <p className="mt-3 text-sm text-muted-foreground">{tx('读取方案目录…')}</p>
      : !recent.length ? <p className="mt-3 text-sm text-muted-foreground">{tx('还没有保存的布局。')}</p>
      : <>
        <ul className="mt-3 divide-y">
          {recent.map(group => {
            const record = group[0], latest = group.map(row => row.finished_at!).sort().at(-1)!;
            return <li key={record.layout_key ?? record.id} className="py-2.5">
              <a href={layoutHref(record.layout_key ? { key: record.layout_key } : { id: record.id }, ar)} className="font-medium text-primary underline-offset-4 hover:underline">{localizedRecordTitle({ ...record, evaluation_condition: undefined }, locale)}</a>
              <span className="mt-0.5 block text-xs text-muted-foreground">
                {tx(protocolName(record.dataset_id))}{group.length > 1 && <> · {tx(`共${group.length}种条件`)}</>} · {date(latest)}
                {record.metrics?.field_relative != null && <> · {tx('场重建保留率')} {metricPercent(record.metrics.field_relative)}</>}
              </span>
            </li>;
          })}
        </ul>
        <TermHint term="retention" ar={ar} className="mt-2" />
      </>}
  </section>;
}

function Tasks() {
  const { tx } = useLanguage();
  const tasks = useTaskStatus(), { status, failure } = tasks;
  const idle = !status?.jobs.length && !failure && !status?.recovery_blocked && status?.available !== false;
  return <section id="tasks" aria-labelledby="tasks-title" className={cn('lab-panel scroll-mt-32', idle && 'py-3')}>
    {idle ? <EmptyLine id="tasks-title" title="计算任务" note="当前浏览器暂无计算任务"><VisitorNotice status={status} className="basis-full" /></EmptyLine>
      : <><h2 id="tasks-title" className="text-lg font-semibold">{tx('计算任务')}</h2><div className="text-sm"><TaskList {...tasks} /></div></>}
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
  const icon = <FlaskConical aria-hidden className="size-4 text-primary" />;
  const all = <a href={'/robustness?ar=' + ar} className="text-sm text-primary underline underline-offset-4">{tx('全部研究')}</a>;
  if (studies && !recent.length && !error) return <section aria-labelledby="recent-studies" className="lab-panel py-3">
    <EmptyLine id="recent-studies" title="稳健性研究" icon={icon} note="还没有稳健性研究。">
      <a href={'/robustness?ar=' + ar} className="text-sm text-primary underline underline-offset-4">{tx('新建研究')}</a>
    </EmptyLine>
  </section>;
  return <section aria-labelledby="recent-studies" className="lab-panel">
    <div className="flex flex-wrap items-baseline justify-between gap-2">
      <h2 id="recent-studies" className="flex items-center gap-2 text-lg font-semibold">{icon}{tx('稳健性研究')}</h2>
      {all}
    </div>
    {error ? <p className="mt-3 text-sm text-muted-foreground"><RuntimeMessage message={error} /></p>
      : !studies ? <p className="mt-3 text-sm text-muted-foreground">{tx('读取研究目录…')}</p>
      : <ul className="mt-3 divide-y">{recent.map(study => <li key={study.id} className="py-2.5">
        <a href={'/robustness?study=' + study.id} className="font-medium text-primary underline-offset-4 hover:underline">{study.title}</a>
        <span className="mt-0.5 block text-xs text-muted-foreground">{tx(STUDY_STATUS[study.status] ?? study.status)} · {tx(`${study.completed_cases}/${study.case_count}个案例`)} · {date(study.updated_at)}</span>
      </li>)}</ul>}
  </section>;
}

export default function HomeWorkspace() {
  const { tx } = useLanguage();
  const [ar, setAR] = useState(90);
  const [library, setLibrary] = useState<SavedSummary[] | null>(null);
  const [error, setError] = useState('');
  // Shown until the reader closes it, so the first page a newcomer sees says where to begin.
  // Unknown until the browser's choice is read, so a returning reader never sees it flash.
  const [start, setStart] = useState<boolean | null>(null);
  const example = useMemo(() => exampleLayout(library ?? []), [library]);
  const showStart = (open: boolean) => {
    setStart(open);
    try { if (open) localStorage.removeItem(START_DISMISSED_KEY); else localStorage.setItem(START_DISMISSED_KEY, '1'); } catch { /* storage is optional */ }
  };
  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    // Saved links to the old overview keep working: it moved to /findings with the same parameters.
    // The read-only showcase has no workspace; its front page is the findings.
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
    <div className="lab-container space-y-5 pb-10">
      <header className="flex flex-wrap items-end justify-between gap-3 pt-6">
        <div>
          <h1 className="text-2xl font-semibold">{tx('工作区')}</h1>
          <p className="mt-2 text-base text-muted-foreground">{tx('你的布局、计算任务、研究和项目。')}</p>
        </div>
        {start === false && <Button size="sm" variant="outline" onClick={() => showStart(true)}>{tx('新手入门')}</Button>}
      </header>
      {start ? <StartHere ar={ar} example={example} onClose={() => showStart(false)} /> : start === false && <NewLayout ar={ar} />}
      <div className="grid items-start gap-5 lg:grid-cols-2">
        <RecentLayouts records={library} ar={ar} error={error} />
        <div className="space-y-5">
          <Tasks />
          <Studies ar={ar} />
          <section aria-labelledby="projects-title" className="lab-panel py-3">
            <EmptyLine id="projects-title" title="研究项目" icon={<FolderKanban aria-hidden className="size-4 text-primary" />} note="项目把多个布局、对比和交付包放在一起，便于导出和交给合作者。">
              <span className="flex flex-wrap gap-3 text-sm">
                <a href="/projects" className="text-primary underline underline-offset-4">{tx('打开研究项目')}</a>
                <a href="/deliveries" className="text-primary underline underline-offset-4">{tx('读取交付包')}</a>
              </span>
            </EmptyLine>
          </section>
          <section aria-labelledby="findings-title" className="lab-panel py-3">
            <EmptyLine id="findings-title" title="研究结果" icon={<Grid3x3 aria-hidden className="size-4 text-primary" />} note="已发表的总面积研究和历史批次。">
              <span className="flex flex-wrap gap-3 text-sm">
                <a href={'/findings?ar=' + ar} className="text-primary underline underline-offset-4">{tx('打开总面积研究')}</a>
                <a href={'/results?ar=' + ar} className="text-primary underline underline-offset-4">{tx('历史批次')}</a>
              </span>
            </EmptyLine>
          </section>
        </div>
      </div>
    </div>
  </main>;
}
