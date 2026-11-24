'use client';
/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
import { useEffect, useMemo, useState } from 'react';
import { FlaskConical, FolderKanban, Grid3x3, Import, PencilRuler, Search } from 'lucide-react';
import { useLanguage } from '@/components/language-provider';
import { RuntimeMessage } from '@/components/runtime-message';
import { SiteHeader } from '@/components/site-header';
import { TaskList, useTaskStatus } from '@/components/community-status';
import { apiJson } from '@/client/task-client';
import { listRobustnessStudies } from '@/client/robustness';
import { localizedRecordTitle } from '@/lib/i18n/records';
import { protocolName, metricPercent, recordConditionLabels } from '@/lib/ui-language';
import { parseAR } from '@/lib/lab-workflow';
import { SHOWCASE } from '@/lib/showcase';
import { layoutHref } from '@/lib/layout-page';
import type { LocalLibrary, SavedSummary } from '@/lib/local-library';
import type { StudyDirectoryEntry } from '@/contracts/robustness-study';

/** Old overview addresses carried these; they now open the findings page. */
export const OVERVIEW_PARAMETERS = ['domain', 'area', 'r', 'metric'] as const;

const RECENT = 6;
const STUDY_STATUS: Record<string, string> = { draft: '草稿', running: '进行中', paused: '已暂停', completed: '已完成', cancelled: '已取消' };

function NewLayout({ ar }: { ar: number }) {
  const { tx } = useLanguage();
  const sources = [
    { href: '/design?ar=' + ar, icon: Search, title: '按区域搜索', text: '选择部位、区域数和每区半径，搜索64电极布局。' },
    { href: '/coordinates?ar=' + ar, icon: Import, title: '坐标导入', text: '读取已有电极坐标文件，在当前条件下评价。' },
    { href: '/library?ar=' + ar, icon: PencilRuler, title: '复制并编辑', text: '从布局列表打开一个布局，移动或停用电极。' },
  ];
  return <section aria-labelledby="new-layout" className="lab-panel">
    <h2 id="new-layout" className="text-lg font-semibold">{tx('新建布局')}</h2>
    <div className="mt-3 grid gap-3 sm:grid-cols-3">
      {sources.map(({ href, icon: Icon, title, text }) => <a key={title} href={href} className="group flex gap-3 rounded-lg border bg-card p-3 hover:border-primary/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary">
        <Icon aria-hidden className="mt-0.5 size-5 shrink-0 text-primary" />
        <span><span className="block font-medium group-hover:text-primary">{tx(title)}</span><span className="mt-1 block text-sm leading-6 text-muted-foreground">{tx(text)}</span></span>
      </a>)}
    </div>
  </section>;
}

function RecentLayouts({ records, ar, error }: { records: SavedSummary[] | null; ar: number; error: string }) {
  const { tx, locale, date } = useLanguage();
  const recent = useMemo(() => (records ?? []).filter(record => record.status === 'completed' && record.finished_at)
    .sort((a, b) => Date.parse(b.finished_at!) - Date.parse(a.finished_at!)).slice(0, RECENT), [records]);
  return <section aria-labelledby="recent-layouts" className="lab-panel">
    <div className="flex flex-wrap items-baseline justify-between gap-2">
      <h2 id="recent-layouts" className="text-lg font-semibold">{tx('最近的布局')}</h2>
      <a href={'/library?ar=' + ar} className="text-sm text-primary underline underline-offset-4">{tx('全部布局')}</a>
    </div>
    {error ? <p role="alert" className="mt-3 text-sm text-danger"><RuntimeMessage message={error} /></p>
      : !records ? <p className="mt-3 text-sm text-muted-foreground">{tx('读取方案目录…')}</p>
      : !recent.length ? <p className="mt-3 text-sm text-muted-foreground">{tx('还没有保存的布局。')}</p>
      : <ul className="mt-3 divide-y">
        {recent.map(record => {
          const conditions = recordConditionLabels(record);
          return <li key={record.id} className="py-2.5">
            <a href={layoutHref({ id: record.id }, ar)} className="font-medium text-primary underline-offset-4 hover:underline">{localizedRecordTitle(record, locale)}</a>
            <span className="mt-0.5 block text-xs text-muted-foreground">
              {tx(protocolName(record.dataset_id))}{conditions.map(label => <span key={label}> · {tx(label)}</span>)} · {date(record.finished_at!)}
              {record.metrics?.field_relative != null && <> · {tx('场重建保留率')} {metricPercent(record.metrics.field_relative)}</>}
            </span>
          </li>;
        })}
      </ul>}
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
  return <section aria-labelledby="recent-studies" className="lab-panel">
    <div className="flex flex-wrap items-baseline justify-between gap-2">
      <h2 id="recent-studies" className="flex items-center gap-2 text-lg font-semibold"><FlaskConical aria-hidden className="size-4 text-primary" />{tx('稳健性研究')}</h2>
      <a href={'/robustness?ar=' + ar} className="text-sm text-primary underline underline-offset-4">{tx('全部研究')}</a>
    </div>
    {error ? <p className="mt-3 text-sm text-muted-foreground"><RuntimeMessage message={error} /></p>
      : !studies ? <p className="mt-3 text-sm text-muted-foreground">{tx('读取研究目录…')}</p>
      : !recent.length ? <p className="mt-3 text-sm text-muted-foreground">{tx('还没有稳健性研究。')}</p>
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
  const tasks = useTaskStatus();
  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    // Saved links to the old overview keep working: it moved to /findings with the same parameters.
    // The read-only showcase has no workspace; its front page is the findings.
    if (SHOWCASE || OVERVIEW_PARAMETERS.some(key => q.has(key))) { window.location.replace('/findings' + window.location.search + window.location.hash); return; }
    const restore = () => setAR(parseAR(new URLSearchParams(window.location.search).get('ar')));
    restore();
    const controller = new AbortController();
    apiJson<LocalLibrary>('/api/local-compute/library', { signal: controller.signal, errorMessage: '数据服务暂不可用，请稍后重新读取。' })
      .then(value => setLibrary(value.records)).catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '数据服务暂不可用，请稍后重新读取。'); });
    return () => controller.abort();
  }, []);
  return <main className="lab-page">
    <SiteHeader current="home" arPercent={ar} />
    <div className="lab-container space-y-5 pb-10">
      <header className="pt-6">
        <h1 className="text-2xl font-semibold">{tx('工作区')}</h1>
        <p className="mt-2 text-base text-muted-foreground">{tx('最近的布局、计算任务、研究和项目。新布局从这里开始；已发表的研究结果在“研究结果”中。')}</p>
      </header>
      <NewLayout ar={ar} />
      <div className="grid items-start gap-5 lg:grid-cols-2">
        <RecentLayouts records={library} ar={ar} error={error} />
        <section id="tasks" aria-labelledby="tasks-title" className="lab-panel scroll-mt-32">
          <h2 id="tasks-title" className="text-lg font-semibold">{tx('计算任务')}</h2>
          <div className="text-sm"><TaskList {...tasks} /></div>
        </section>
        <Studies ar={ar} />
        <section aria-labelledby="projects-title" className="lab-panel">
          <h2 id="projects-title" className="flex items-center gap-2 text-lg font-semibold"><FolderKanban aria-hidden className="size-4 text-primary" />{tx('研究项目')}</h2>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">{tx('项目把多个布局、对比和交付包放在一起，便于导出和交给合作者。')}</p>
          <div className="mt-3 flex flex-wrap gap-3 text-sm">
            <a href="/projects" className="text-primary underline underline-offset-4">{tx('打开研究项目')}</a>
            <a href="/deliveries" className="text-primary underline underline-offset-4">{tx('读取交付包')}</a>
          </div>
        </section>
      </div>
      <section aria-labelledby="findings-title" className="lab-panel">
        <h2 id="findings-title" className="flex items-center gap-2 text-lg font-semibold"><Grid3x3 aria-hidden className="size-4 text-primary" />{tx('研究结果')}</h2>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">{tx('总面积研究：相同面积上限下，1–6个区域各保留多少信号。历史批次保留最初的半径实验和两区域原型。')}</p>
        <div className="mt-3 flex flex-wrap gap-3 text-sm">
          <a href={'/findings?ar=' + ar} className="text-primary underline underline-offset-4">{tx('打开总面积研究')}</a>
          <a href={'/results?ar=' + ar} className="text-primary underline underline-offset-4">{tx('历史批次')}</a>
        </div>
      </section>
    </div>
  </main>;
}
