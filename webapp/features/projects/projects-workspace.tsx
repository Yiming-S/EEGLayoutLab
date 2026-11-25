'use client';
/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
import { lazy, Suspense, useEffect, useState } from 'react';
import { ChevronDown, FolderKanban, RefreshCcw } from 'lucide-react';
import { SiteHeader } from '@/components/site-header';
import { useLanguage } from '@/components/language-provider';
import { RuntimeMessage } from '@/components/runtime-message';
import { Button } from '@/components/ui/button';
import { apiJson } from '@/client/task-client';
import {
  createProject, isProjectId, listProjects, projectRequest, projectSummary,
  type ProjectEntry, type ProjectEntryKind, type ProjectResponse, type ProjectSummary, type ResearchProject,
} from '@/client/projects';
import { collectProjectRecordChoices, projectChoiceId, type ProjectRecordChoice } from './project-record-choices';
import { activateProject, readActiveProject } from './active-project';
import { ProjectWorkflowEditor } from './project-workflow-editor';
import { ProjectDeliveryPanel } from './project-delivery-panel';
import { filterProjectExperiments, projectExperimentAssociations, sourceLayoutAssociation, sourceScenarioSummary, type ProjectExperimentFilter } from './project-experiment-associations';
import { useConfirmDialog } from '@/components/ui/confirm-dialog';
const ProjectSnapshotViewer = lazy(() => import('./project-snapshot-viewer').then(module => ({ default: module.ProjectSnapshotViewer })));

function download(text: string, filename: string) {
  const href = URL.createObjectURL(new Blob([text], { type: 'application/json' }));
  const link = document.createElement('a'); link.href = href; link.download = filename; link.click();
  setTimeout(() => URL.revokeObjectURL(href), 0);
}
const kindLabel = { layout: '布局评价', editor: '电极编辑副本', source: '信号实验' };

function EntryCard({ entry, entries, busy, inspect, update, remove }: {
  entry: ProjectEntry; entries: ProjectEntry[]; busy: boolean;
  inspect: () => void; update: (title: string, notes: string) => void; remove: () => void;
}) {
  const { tx, date } = useLanguage();
  const { confirm, dialog } = useConfirmDialog();
  const [title, setTitle] = useState(entry.title), [notes, setNotes] = useState(entry.notes);
  // Unsaved edits survive saves of other entries; a new saved text for this entry replaces them.
  const [saved, setSaved] = useState({ title: entry.title, notes: entry.notes });
  if (saved.title !== entry.title || saved.notes !== entry.notes) {
    setSaved({ title: entry.title, notes: entry.notes }); setTitle(entry.title); setNotes(entry.notes);
  }
  return <article className="rounded-2xl border border-border/80 bg-card/95 p-4.5 shadow-2xs transition-colors hover:border-primary/30" aria-label={entry.title} data-project-entry-id={entry.id} data-entry-kind={entry.kind}>
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded-md bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary ring-1 ring-inset ring-primary/18">{tx(kindLabel[entry.kind])}</span>
          <span className="text-xs text-muted-foreground">{date(entry.created_at, true)}</span>
        </div>
        <h3 className="mt-1.5 text-base font-semibold text-foreground">{entry.title}</h3>
        <p className="mt-1.5 max-w-md truncate rounded-md bg-muted/65 px-2 py-0.5 font-mono text-[11px] text-muted-foreground" title={entry.record_id}>{entry.record_id}</p>
      </div>
      <Button variant="outline" size="sm" disabled={busy} onClick={inspect}>{tx('查看保存的科学数据')}</Button>
    </div>
    {entry.summary && <dl className="mt-3 grid gap-2.5 text-xs sm:grid-cols-2 md:max-w-md">
      <div className="lab-subpanel py-2"><dt className="text-muted-foreground">{tx('评价协议')}</dt><dd className="mt-0.5 font-mono font-medium">{String(entry.summary.protocol ?? '—')}</dd></div>
      <div className="lab-subpanel py-2"><dt className="text-muted-foreground">{tx('电极数量')}</dt><dd className="mt-0.5 font-mono font-medium tabular-nums">{String(entry.summary.electrode_count ?? '—')}</dd></div>
    </dl>}
    {entry.kind === 'source' && <SourceExperimentDetails entry={entry} entries={entries} />}
    <details className="group/edit mt-3.5 rounded-xl border border-border/65 bg-muted/25 px-3.5 py-2.5">
      <summary className="flex cursor-pointer list-none items-center justify-between text-xs font-semibold text-ink-soft select-none [&::-webkit-details-marker]:hidden">
        <span>{tx('编辑实验说明')}</span>
        <ChevronDown aria-hidden className="size-4 text-muted-foreground transition-transform group-open/edit:rotate-180" />
      </summary>
      <form className="mt-3 space-y-3" onSubmit={event => { event.preventDefault(); update(title, notes); }}>
        <label className="lab-label">{tx('实验名称')}<input className="lab-select" value={title} maxLength={200} required onChange={event => setTitle(event.target.value)} /></label>
        <label className="lab-label">{tx('实验备注')}<textarea className="lab-input min-h-20" value={notes} maxLength={8000} onChange={event => setNotes(event.target.value)} /></label>
        <div className="flex flex-wrap gap-2"><Button type="submit" size="sm" variant="outline" disabled={busy}>{tx('保存实验说明')}</Button><Button type="button" size="sm" variant="destructive" disabled={busy} onClick={() => void confirm({ title: '从项目移除', message: '从项目移除此实验记录？项目保存的副本会被删除，原始结果不受影响。', confirmLabel: '从项目移除', destructive: true }).then(ok => { if (ok) remove(); })}>{tx('从项目移除')}</Button>{dialog}</div>
      </form>
    </details>
    <p className="mt-3 max-w-full truncate font-mono text-[11px] text-muted-foreground" title={`SHA-256: ${entry.snapshot_sha256}`}>SHA-256: {entry.snapshot_sha256}</p>
  </article>;
}

function SourceExperimentDetails({ entry, entries }: { entry: ProjectEntry; entries: ProjectEntry[] }) {
  const { tx } = useLanguage(), association = sourceLayoutAssociation(entry, entries), scenario = sourceScenarioSummary(entry);
  const absent = tx('未记录');
  return <section className="mt-3.5 space-y-2.5 border-t border-border/65 pt-3" aria-label={tx('信号实验关联与条件')}>
    <dl className="grid gap-2 text-xs sm:grid-cols-2">
      <div className="lab-subpanel py-2"><dt className="text-muted-foreground">{tx('父布局')}</dt><dd className="mt-0.5 font-medium">{association.layouts.length ? association.layouts.map(layout => layout.title).join(' / ') : association.parentId ? tx('项目中未保存此布局') : absent}</dd></div>
      <div className="lab-subpanel py-2"><dt className="text-muted-foreground">{tx('父布局科学编号')}</dt><dd className="mt-0.5 truncate font-mono text-[11px]" title={association.parentId ?? undefined}>{association.parentId ?? absent}</dd></div>
      <div className="lab-subpanel py-2"><dt className="text-muted-foreground">{tx('场景模式')}</dt><dd className="mt-0.5 font-mono">{scenario.mode ?? absent}</dd></div>
      <div className="lab-subpanel py-2"><dt className="text-muted-foreground">{tx('随机种子')}</dt><dd className="mt-0.5 font-mono tabular-nums">{scenario.seed ?? absent}</dd></div>
    </dl>
    {association.layouts.length > 1 && <p className="text-xs text-muted-foreground">{tx('这些名称副本共用同一份科学布局记录。')}</p>}
    <details className="group/src text-xs">
      <summary className="inline-flex cursor-pointer list-none items-center gap-1 font-medium text-primary select-none [&::-webkit-details-marker]:hidden">
        <span>{tx('已保存的脑源请求条件')}</span>
        <ChevronDown aria-hidden className="size-3.5 transition-transform group-open/src:rotate-180" />
      </summary>
      <dl className="mt-2.5 grid gap-2.5 rounded-xl border border-border/65 bg-muted/30 p-3 sm:grid-cols-3">
        <div><dt className="text-muted-foreground">{tx('请求的源编号')}</dt><dd className="mt-0.5 font-mono">{scenario.sourceIndex ?? absent}</dd></div>
        <div><dt className="text-muted-foreground">{tx('请求的脑区')}</dt><dd className="mt-0.5 font-mono">{scenario.brainRegion ?? absent}</dd></div>
        <div><dt className="text-muted-foreground">{tx('请求的跨区脑源区域')}</dt><dd className="mt-0.5 font-mono">{scenario.brainRegions ? scenario.brainRegions.join(', ') : absent}</dd></div>
      </dl>
      <p className="mt-2 text-xs text-muted-foreground">{tx('缺失字段显示为“未记录”。')}</p>
    </details>
  </section>;
}

/** Most recently updated first, as the service lists them. */
const byUpdate = (a: ProjectSummary, b: ProjectSummary) => b.updated_at.localeCompare(a.updated_at) || a.id.localeCompare(b.id);

export default function ProjectsWorkspace() {
  const { tx, date, locale } = useLanguage();
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null), [listError, setListError] = useState(''), [listRetry, setListRetry] = useState(0);
  const [project, setProject] = useState<ResearchProject | null>(null);
  const [title, setTitle] = useState(''), [notes, setNotes] = useState('');
  const [newTitle, setNewTitle] = useState(''), [newOwner, setNewOwner] = useState('');
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState('');
  const [choices, setChoices] = useState<ProjectRecordChoice[]>([]), [choice, setChoice] = useState('');
  const [choicesLoading, setChoicesLoading] = useState(true), [choicesRetry, setChoicesRetry] = useState(0);
  const [choicesWarnings, setChoicesWarnings] = useState<{ kind: ProjectEntryKind; message: string }[]>([]);
  const [entryTitle, setEntryTitle] = useState(''), [entryNotes, setEntryNotes] = useState('');
  const [snapshot, setSnapshot] = useState<{ entry: ProjectEntry; snapshot: unknown } | null>(null);
  const [initialRecord, setInitialRecord] = useState('');
  const [initialAnnotation, setInitialAnnotation] = useState('');
  const [entryView, setEntryView] = useState<{ projectId: string; filter: ProjectExperimentFilter }>({ projectId: '', filter: 'all' });

  // The title and note fields follow the saved project, but an unsaved edit survives a save
  // of another part of the same project.
  const [synced, setSynced] = useState<{ id: string; title: string; notes: string } | null>(null);
  if (project && (synced?.id !== project.id || synced.title !== project.title || synced.notes !== project.notes)) {
    const same = synced?.id === project.id;
    setSynced({ id: project.id, title: project.title, notes: project.notes });
    if (!same || title === synced.title) setTitle(project.title);
    if (!same || notes === synced.notes) setNotes(project.notes);
  }
  const apply = (value: ProjectResponse) => {
    const saved = value.project;
    setProject(saved); setSnapshot(null);
    setProjects(rows => rows && [projectSummary(saved), ...rows.filter(row => row.id !== saved.id)].sort(byUpdate));
    try { activateProject({ project_id: saved.id, title: saved.title }); }
    catch { setNotice('此标签页无法记住活动项目，可在项目页手动保存已完成结果。'); }
    const url = new URL(window.location.href); url.searchParams.set('project', saved.id);
    window.history.replaceState(null, '', url.pathname + url.search);
  };
  const perform = async (action: () => Promise<void>) => {
    setBusy(true); setError(''); setNotice('');
    try { await action(); } catch (caught) { setError(caught instanceof Error ? caught.message : '项目操作失败'); }
    finally { setBusy(false); }
  };
  const open = (id: string) => perform(async () => { apply(await projectRequest<ProjectResponse>(id)); });
  useEffect(() => {
    let disposed = false;
    queueMicrotask(() => {
      if (disposed) return;
      const url = new URL(window.location.href); setInitialRecord(url.searchParams.get('record') ?? ''); setInitialAnnotation(url.searchParams.get('annotation_id') ?? '');
      let active: string | undefined;
      try { active = readActiveProject(window.sessionStorage)?.project_id; } catch { /* The list still opens any project. */ }
      const requested = url.searchParams.get('project')?.toLowerCase();
      if (requested !== undefined && !isProjectId(requested)) { setError('项目编号无效'); return; }
      const selected = requested ?? active;
      if (selected) void open(selected);
    });
    // Initial restoration only; later changes use explicit project controls.
    return () => { disposed = true; };
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    void listProjects(controller.signal).then(rows => {
      if (!controller.signal.aborted) { setProjects(rows); setListError(''); }
    }, (caught: unknown) => {
      if (!controller.signal.aborted) setListError(caught instanceof Error ? caught.message : '项目目录未载入，请重新读取。');
    });
    return () => controller.abort();
  }, [listRetry]);
  useEffect(() => {
    const controller = new AbortController();
    queueMicrotask(() => { if (!controller.signal.aborted) setChoicesLoading(true); });
    void Promise.allSettled([
      apiJson('/api/local-compute/library', { signal: controller.signal }),
      apiJson('/api/electrode-editor/records', { signal: controller.signal }),
      apiJson('/api/community/records', { signal: controller.signal }),
    ]).then(results => {
      if (controller.signal.aborted) return;
      const { choices: available, warnings } = collectProjectRecordChoices(results, locale);
      setChoices(available); setChoicesWarnings(warnings); setChoicesLoading(false);
      const current = available.find(row => row.kind === 'layout' && row.id === initialRecord && (row.annotation_id ?? '') === initialAnnotation);
      if (current) setChoice(projectChoiceId(current));
    });
    return () => controller.abort();
  }, [initialRecord, initialAnnotation, project?.id, choicesRetry, locale]);
  const mutate = (suffix: string, method: string, body: Record<string, unknown>) => perform(async () => {
    if (!project) return;
    const result = await projectRequest<ProjectResponse>(project.id, suffix, { method, body: JSON.stringify({ revision: project.revision, ...body }) });
    apply(result); setNotice('项目已保存。');
  });
  const attach = (event: { preventDefault(): void }) => {
    event.preventDefault(); const selected = choices.find(row => projectChoiceId(row) === choice);
    if (!selected) return;
    void mutate('/entries', 'POST', { kind: selected.kind, ...(selected.kind === 'source' ? { receipt_id: selected.id } : { record_id: selected.id }),
      ...(selected.annotation_id ? { annotation_id: selected.annotation_id } : {}),
      ...(entryTitle ? { title: entryTitle } : {}), notes: entryNotes });
  };
  const entryFilter = project && entryView.projectId === project.id ? entryView.filter : 'all';
  const associations = project ? projectExperimentAssociations(project.entries, project.workflow?.candidate_entry_id) : null;
  const visibleEntries = project ? filterProjectExperiments(project.entries, entryFilter, project.workflow?.candidate_entry_id) : [];
  const filterEntries = (filter: ProjectExperimentFilter) => { if (project) setEntryView({ projectId: project.id, filter }); };
  return <main className="lab-page">
    <SiteHeader current="projects" />
    <div className="lab-container space-y-5 pb-10">
      <header className="flex flex-wrap items-end justify-between gap-4 border-b border-border pt-7 pb-5">
        <div>
          <h1 className="text-2xl font-semibold tracking-[-0.028em] sm:text-[1.65rem]">{tx('研究项目')}</h1>
          <p className="mt-1.5 max-w-3xl text-sm text-muted-foreground">{tx('保存布局、编辑副本和信号实验，并记录选择理由。项目记录独立于计算队列保留。')}</p>
        </div>
        <a className="lab-link-pill" href="/deliveries">{tx('打开本地交付包')}</a>
      </header>
      {error && <p role="alert" className="lab-panel border-danger/35 bg-danger-surface/65 text-sm text-danger">{tx(error)}</p>}
      {notice && <output className="lab-panel block border-border bg-secondary/45 text-sm">{tx(notice)}</output>}
      <details key={project ? 'selected-project' : 'no-project'} open={!project} className="group/switcher lab-panel">
        <summary className="flex cursor-pointer list-none items-center justify-between gap-2 text-sm font-semibold select-none [&::-webkit-details-marker]:hidden">
          <span className="flex items-center gap-2">
            <span aria-hidden className="grid size-6 place-items-center rounded border border-border bg-secondary/75 text-foreground/80"><FolderKanban className="size-3.5" /></span>
            <span>{tx('新建或打开项目')}</span>
          </span>
          <ChevronDown aria-hidden className="size-4 text-muted-foreground transition-transform group-open/switcher:rotate-180" />
        </summary>
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <form className="rounded-xl border border-border/75 bg-muted/30 p-4 space-y-3" onSubmit={event => { event.preventDefault(); void perform(async () => {
            apply(await createProject({ title: newTitle, owner_name: newOwner }));
            setNewTitle(''); setNewOwner(''); setNotice('项目已创建。');
          }); }}>
            <h2 className="text-base font-semibold">{tx('新建项目')}</h2>
            <label className="lab-label">{tx('项目名称')}<input className="lab-select" value={newTitle} onChange={event => setNewTitle(event.target.value)} maxLength={200} required /></label>
            <label className="lab-label">{tx('负责人姓名')}<input className="lab-select" value={newOwner} onChange={event => setNewOwner(event.target.value)} maxLength={100} required /></label>
            <Button type="submit" disabled={busy}>{tx('创建项目')}</Button>
          </form>
          <section className="rounded-xl border border-border/75 bg-muted/30 p-4 space-y-3" aria-label={tx('此工作区的项目')}>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-base font-semibold">{tx('此工作区的项目')}</h2>
              <Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => setListRetry(value => value + 1)}><RefreshCcw className="size-3.5" />{tx('刷新项目列表')}</Button>
            </div>
            {listError && listError !== error && <p role="alert" className="text-sm text-warning"><RuntimeMessage message={listError} /></p>}
            {!projects && !listError && <p className="text-sm text-muted-foreground">{tx('正在读取项目目录…')}</p>}
            {projects && !projects.length && <p className="text-sm text-muted-foreground">{tx('此工作区还没有项目。')}</p>}
            {projects && projects.length > 0 && <ul className="space-y-2">{projects.map(row => <li key={row.id} className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <Button size="sm" className="max-w-full truncate" variant={project?.id === row.id ? 'default' : 'outline'} aria-current={project?.id === row.id ? 'true' : undefined} disabled={busy} onClick={() => void open(row.id)}>{row.title}</Button>
              <span className="text-xs text-muted-foreground">{row.owner_name} · {date(row.updated_at, true)} · {tx(`${row.entry_count}条实验记录`)}</span>
            </li>)}</ul>}
            <p className="text-xs leading-5 text-muted-foreground">{tx('项目保存在当前工作区目录中，不随浏览器数据清除。')}</p>
          </section>
        </div>
      </details>
      {project && <>
        <section className="lab-panel space-y-4" aria-label={tx('项目详情')}>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="text-xs text-muted-foreground">{tx('负责人')}：{project.owner_name} · {date(project.updated_at, true)}</p>
              <h2 className="mt-1.5 text-xl font-semibold">{project.title}</h2>
              <p className="mt-1.5 inline-block max-w-full truncate rounded-md bg-muted/65 px-2 py-0.5 font-mono text-xs text-muted-foreground" title={project.id}>{project.id}</p>
            </div>
            <Button variant="outline" size="sm" disabled={busy} onClick={() => void open(project.id)}>{tx('重新读取项目')}</Button>
          </div>
          <details className="group/meta rounded-xl border border-border/70 bg-muted/25 p-3.5">
            <summary className="flex cursor-pointer list-none items-center justify-between text-sm font-medium select-none [&::-webkit-details-marker]:hidden">
              <span>{tx('编辑项目说明')}</span>
              <ChevronDown aria-hidden className="size-4 text-muted-foreground transition-transform group-open/meta:rotate-180" />
            </summary>
            <div className="mt-4 space-y-4">
              <form className="space-y-3" onSubmit={event => { event.preventDefault(); void mutate('', 'PATCH', { title, notes }); }}>
                <label className="lab-label">{tx('项目名称')}<input className="lab-select" value={title} maxLength={200} required onChange={event => setTitle(event.target.value)} /></label>
                <label className="lab-label">{tx('项目备注')}<textarea className="lab-input min-h-24" value={notes} maxLength={8000} onChange={event => setNotes(event.target.value)} /></label>
                <Button type="submit" variant="outline" size="sm" disabled={busy}>{tx('保存项目说明')}</Button>
              </form>
              <p className="text-xs text-muted-foreground">{tx('名称和备注只改变项目说明，不改变科学数据或重新计算。')}</p>
            </div>
          </details>
        </section>
        <ProjectWorkflowEditor key={`${project.id}:${project.revision}`} project={project} busy={busy} save={workflow => void mutate('', 'PATCH', { workflow })} showCandidateSignals={() => { filterEntries('candidate-source'); document.getElementById('project-experiments')?.scrollIntoView({ block: 'start' }); }} />
        <section id="project-experiments" className="lab-panel space-y-4" aria-label={tx('项目实验记录')}>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-lg font-semibold">{tx('项目实验记录')} · {project.entries.length}</h2>
            <fieldset className="flex flex-wrap gap-1 rounded-xl border border-border/75 bg-muted/55 p-1" aria-label={tx('项目实验筛选')}>
              <Button type="button" size="sm" variant={entryFilter === 'all' ? 'default' : 'ghost'} aria-pressed={entryFilter === 'all'} onClick={() => filterEntries('all')}>{tx('全部实验记录')}</Button>
              <Button type="button" size="sm" variant={entryFilter === 'candidate-source' ? 'default' : 'ghost'} aria-pressed={entryFilter === 'candidate-source'} disabled={!associations?.candidateRecordId} onClick={() => filterEntries('candidate-source')}>{tx('只看当前候选的信号记录')}</Button>
            </fieldset>
          </div>
          {entryFilter === 'candidate-source' && <p className="text-sm text-muted-foreground" aria-live="polite">{associations?.candidate ? <>{tx('当前候选布局')}：{associations.candidate.title} · <span className="break-all font-mono text-xs">{associations.candidateRecordId}</span></> : tx('尚未选择项目候选布局。')}{' · '}{tx('显示记录数')}：{visibleEntries.length}</p>}
          <details open={!project.entries.length} className="group/attach rounded-xl border border-border/75 bg-muted/30 p-4">
            <summary className="flex cursor-pointer list-none items-center justify-between text-sm font-semibold select-none [&::-webkit-details-marker]:hidden">
              <span>{tx('保存已完成结果到项目')}</span>
              <ChevronDown aria-hidden className="size-4 text-muted-foreground transition-transform group-open/attach:rotate-180" />
            </summary>
            <form className="mt-3.5 space-y-3" onSubmit={attach}>
              <h3 className="text-sm font-semibold">{tx('保存已完成结果到项目')}</h3>
              <label className="lab-label">{tx('选择已完成记录')}<select aria-label={tx('选择已完成记录')} className="lab-select" required value={choice} onChange={event => setChoice(event.target.value)}><option value="">{tx('选择记录')}</option>{choices.map(row => <option value={projectChoiceId(row)} key={projectChoiceId(row)}>{tx(kindLabel[row.kind])} · {row.title}</option>)}</select></label>
              {choicesLoading && <p className="text-sm text-muted-foreground">{tx('正在读取已完成记录…')}</p>}
              {choicesWarnings.map(warning => <p role="alert" className="text-sm text-warning" key={warning.kind}>{tx(kindLabel[warning.kind])} · <RuntimeMessage message={warning.message} /></p>)}
              {!choicesLoading && !choices.length && !choicesWarnings.length && <p className="text-sm text-muted-foreground">{tx('当前还没有可保存的已完成记录。')}</p>}
              <Button type="button" size="sm" variant="outline" disabled={choicesLoading} onClick={() => setChoicesRetry(value => value + 1)}>{tx('重新读取记录目录')}</Button>
              <label className="lab-label">{tx('实验名称')}<input className="lab-select" value={entryTitle} maxLength={200} onChange={event => setEntryTitle(event.target.value)} /></label>
              <label className="lab-label">{tx('实验备注')}<textarea className="lab-input min-h-20" value={entryNotes} maxLength={8000} onChange={event => setEntryNotes(event.target.value)} /></label>
              <Button type="submit" disabled={busy || !choice}>{tx('保存到项目')}</Button>
              <p className="text-xs text-muted-foreground">{tx('保存原始科学结果的独立副本，不启动计算。')}</p>
            </form>
          </details>
          {!project.entries.length && <p className="text-sm text-muted-foreground">{tx('项目中还没有保存的实验。先在结果库选择布局，或完成一次信号仿真。')}</p>}
          {project.entries.length > 0 && entryFilter === 'candidate-source' && !visibleEntries.length && <p className="text-sm text-muted-foreground">{tx('当前候选布局尚无已关联的信号记录。')}</p>}
          <div className="space-y-3.5">
            {visibleEntries.map(entry => <EntryCard key={entry.id} entry={entry} entries={project.entries} busy={busy}
              inspect={() => void perform(async () => setSnapshot(await projectRequest(project.id, `/entries/${entry.id}`)))}
              update={(nextTitle, nextNotes) => void mutate(`/entries/${entry.id}`, 'PATCH', { title: nextTitle, notes: nextNotes })}
              remove={() => void mutate(`/entries/${entry.id}`, 'DELETE', {})} />)}
          </div>
        </section>
        {snapshot && <section className="lab-panel space-y-3.5" aria-label={tx('保存的科学数据')}><h2 className="text-lg font-semibold">{snapshot.entry.title}</h2><p className="text-sm text-muted-foreground">{tx('此数据来自项目保存时的原始结果。读取和下载不会重新计算。')}</p><Suspense fallback={<p>{tx('正在载入结果视图…')}</p>}><ProjectSnapshotViewer key={snapshot.entry.id} entry={snapshot.entry} snapshot={snapshot.snapshot} /></Suspense><Button variant="outline" size="sm" onClick={() => download(JSON.stringify(snapshot.snapshot, null, 2) + '\n', `eeg-project-entry-${snapshot.entry.id}.json`)}>{tx('下载保存的科学数据')}</Button><details className="group/raw"><summary className="inline-flex cursor-pointer list-none items-center gap-1 text-xs font-medium text-primary select-none [&::-webkit-details-marker]:hidden"><span>{tx('展开原始数据')}</span><ChevronDown aria-hidden className="size-3.5 transition-transform group-open/raw:rotate-180" /></summary><pre className="mt-2.5 max-h-96 overflow-auto whitespace-pre-wrap break-all rounded-xl border border-border/70 bg-muted/45 p-3.5 font-mono text-xs">{JSON.stringify(snapshot.snapshot, null, 2)}</pre></details></section>}
        {/* Its key differs from the workflow editor's: equal sibling keys leave stale editors behind. */}
        <ProjectDeliveryPanel key={`delivery:${project.id}:${project.revision}`} project={project} />
      </>}
    </div>
  </main>;
}
