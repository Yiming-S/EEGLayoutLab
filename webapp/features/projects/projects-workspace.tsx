'use client';
/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
import { lazy, Suspense, useEffect, useState } from 'react';
import { SiteHeader } from '@/components/site-header';
import { useLanguage } from '@/components/language-provider';
import { RuntimeMessage } from '@/components/runtime-message';
import { Button } from '@/components/ui/button';
import { apiJson } from '@/client/task-client';
import {
  createProject, forgetProjectAccess, parseProjectAccessFile, projectAccessFile,
  projectAccessFromFragment, projectRequest, projectShareHref, readProjectAccess, saveProjectAccess,
  validateProjectAccess, type ProjectAccess, type ProjectEntry, type ProjectEntryKind,
  type ProjectResponse, type ResearchProject,
} from '@/client/projects';
import { collectProjectRecordChoices, type ProjectRecordChoice } from './project-record-choices';
import { activateProject, readActiveProject } from './active-project';
import { ProjectWorkflowEditor } from './project-workflow-editor';
import { ProjectDeliveryPanel } from './project-delivery-panel';
const ProjectSnapshotViewer = lazy(() => import('./project-snapshot-viewer').then(module => ({ default: module.ProjectSnapshotViewer })));

function download(text: string, filename: string) {
  const href = URL.createObjectURL(new Blob([text], { type: 'application/json' }));
  const link = document.createElement('a'); link.href = href; link.download = filename; link.click();
  setTimeout(() => URL.revokeObjectURL(href), 0);
}
const kindLabel = { layout: '布局评价', editor: '电极编辑副本', source: '信号实验' };

function EntryCard({ entry, owner, busy, inspect, update, remove }: {
  entry: ProjectEntry; owner: boolean; busy: boolean;
  inspect: () => void; update: (title: string, notes: string) => void; remove: () => void;
}) {
  const { tx, date } = useLanguage();
  const [title, setTitle] = useState(entry.title), [notes, setNotes] = useState(entry.notes);
  return <article className="rounded-xl border p-4" aria-label={entry.title}>
    <div className="flex flex-wrap items-start justify-between gap-3"><div>
      <h3 className="font-semibold">{entry.title}</h3>
      <p className="mt-1 text-sm text-muted-foreground">{tx(kindLabel[entry.kind])} · {date(entry.created_at, true)}</p>
      <p className="mt-1 break-all font-mono text-xs text-muted-foreground">{entry.record_id}</p>
    </div><Button variant="outline" disabled={busy} onClick={inspect}>{tx('查看保存的科学数据')}</Button></div>
    {entry.summary && <dl className="mt-3 flex flex-wrap gap-x-6 gap-y-2 text-sm">
      <div><dt className="text-muted-foreground">{tx('评价协议')}</dt><dd>{String(entry.summary.protocol ?? '—')}</dd></div>
      <div><dt className="text-muted-foreground">{tx('电极数量')}</dt><dd>{String(entry.summary.electrode_count ?? '—')}</dd></div>
    </dl>}
    {owner ? <details className="mt-4"><summary className="cursor-pointer text-sm font-medium">{tx('编辑实验说明')}</summary><form className="mt-3 space-y-3" onSubmit={event => { event.preventDefault(); update(title, notes); }}>
      <label className="lab-label">{tx('实验名称')}<input className="lab-select" value={title} maxLength={200} required onChange={event => setTitle(event.target.value)} /></label>
      <label className="lab-label">{tx('实验备注')}<textarea className="lab-select min-h-20" value={notes} maxLength={8000} onChange={event => setNotes(event.target.value)} /></label>
      <div className="flex flex-wrap gap-2"><Button type="submit" variant="outline" disabled={busy}>{tx('保存实验说明')}</Button><Button type="button" variant="outline" disabled={busy} onClick={remove}>{tx('从项目移除')}</Button></div>
    </form></details> : entry.notes && <p className="mt-3 whitespace-pre-wrap text-sm">{entry.notes}</p>}
    <p className="mt-3 break-all text-xs text-muted-foreground">SHA-256: {entry.snapshot_sha256}</p>
  </article>;
}

export default function ProjectsWorkspace() {
  const { tx, date, locale } = useLanguage();
  const [vault, setVault] = useState<ProjectAccess[]>([]), [access, setAccess] = useState<ProjectAccess | null>(null);
  const [project, setProject] = useState<ResearchProject | null>(null), [role, setRole] = useState<'owner' | 'viewer'>('viewer');
  const [title, setTitle] = useState(''), [notes, setNotes] = useState('');
  const [newTitle, setNewTitle] = useState(''), [newOwner, setNewOwner] = useState('');
  const [restoreId, setRestoreId] = useState(''), [restoreKey, setRestoreKey] = useState('');
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState('');
  const [share, setShare] = useState(''), [choices, setChoices] = useState<ProjectRecordChoice[]>([]), [choice, setChoice] = useState('');
  const [choicesLoading, setChoicesLoading] = useState(true), [choicesRetry, setChoicesRetry] = useState(0);
  const [choicesWarnings, setChoicesWarnings] = useState<{ kind: ProjectEntryKind; message: string }[]>([]);
  const [entryTitle, setEntryTitle] = useState(''), [entryNotes, setEntryNotes] = useState('');
  const [snapshot, setSnapshot] = useState<{ entry: ProjectEntry; snapshot: unknown } | null>(null);
  const [initialRecord, setInitialRecord] = useState('');

  const remember = (credential: ProjectAccess) => {
    try { setVault(saveProjectAccess(localStorage, credential)); }
    catch { setNotice('浏览器无法保存访问凭据，请下载项目凭据文件。'); }
  };
  const apply = (value: ProjectResponse, credential: ProjectAccess) => {
    const saved = { ...credential, role: value.role, title: value.project.title };
    setProject(value.project); setRole(value.role); setAccess(saved);
    setTitle(value.project.title); setNotes(value.project.notes);
    setSnapshot(null); remember(saved);
    try { activateProject(saved); }
    catch { setNotice('此标签页无法记住活动项目，可在项目页手动保存已完成结果。'); }
    const url = new URL(window.location.href); url.searchParams.set('project', saved.project_id); url.hash = '';
    window.history.replaceState(null, '', url.pathname + url.search);
  };
  const perform = async (action: () => Promise<void>) => {
    setBusy(true); setError(''); setNotice('');
    try { await action(); } catch (caught) { setError(caught instanceof Error ? caught.message : '项目操作失败'); }
    finally { setBusy(false); }
  };
  const open = (value: ProjectAccess) => perform(async () => {
    const checked = validateProjectAccess(value);
    const result = await projectRequest<ProjectResponse>(checked); apply(result, checked); setShare('');
  });
  useEffect(() => {
    let disposed = false;
    queueMicrotask(() => {
      if (disposed) return;
      let rows: ProjectAccess[] = [];
      try { rows = readProjectAccess(localStorage); }
      catch { setNotice('浏览器无法保存访问凭据，请下载项目凭据文件。'); }
      setVault(rows);
      const url = new URL(window.location.href); setInitialRecord(url.searchParams.get('record') ?? '');
      // Remove the fragment before any API operation or navigation.
      const fragment = url.hash; url.hash = ''; window.history.replaceState(null, '', url.pathname + url.search);
      try {
        const shared = projectAccessFromFragment(fragment);
        let active: ProjectAccess | null = null;
        try { active = readActiveProject(window.sessionStorage); } catch { /* Manual access still works. */ }
        const requested = url.searchParams.get('project');
        const selected = shared ?? rows.find(row => row.project_id === requested) ?? (active && (!requested || active.project_id === requested) ? active : null);
        if (selected) void open(selected);
      } catch (caught) { setError(caught instanceof Error ? caught.message : '项目访问链接无效'); }
    });
    // Initial browser restoration only; later changes use explicit project controls.
    return () => { disposed = true; };
  }, []);
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
      const current = available.find(row => row.kind === 'layout' && row.id === initialRecord);
      if (current) setChoice(current.kind + ':' + current.id);
    });
    return () => controller.abort();
  }, [initialRecord, project?.id, choicesRetry, locale]);
  const mutate = (suffix: string, method: string, body: Record<string, unknown>) => perform(async () => {
    if (!access || !project) return;
    const result = await projectRequest<ProjectResponse>(access, suffix, { method, body: JSON.stringify({ revision: project.revision, ...body }) });
    apply(result, access); setNotice('项目已保存。');
  });
  const attach = (event: { preventDefault(): void }) => {
    event.preventDefault(); const selected = choices.find(row => `${row.kind}:${row.id}` === choice);
    if (!selected) return;
    void mutate('/entries', 'POST', { kind: selected.kind, ...(selected.kind === 'source' ? { receipt_id: selected.id } : { record_id: selected.id }),
      ...(entryTitle ? { title: entryTitle } : {}), notes: entryNotes });
  };
  const owner = role === 'owner';
  return <main className="lab-page">
    <SiteHeader current="projects" />
    <div className="lab-container space-y-5 py-6">
      <header><h1 className="text-2xl font-semibold">{tx('研究项目')}</h1><p className="mt-2 max-w-3xl text-muted-foreground">{tx('保存布局、编辑副本和信号实验，并记录选择理由。项目记录独立于计算队列保留。')}</p></header>
      {error && <p role="alert" className="lab-panel text-red-800">{tx(error)}</p>}
      {notice && <output className="lab-panel block">{tx(notice)}</output>}
      <details key={project ? 'selected-project' : 'no-project'} open={!project} className="rounded-xl border bg-white p-4"><summary className="cursor-pointer font-medium">{tx('新建、恢复或切换项目')}</summary>
      <div className="mt-4 grid gap-5 lg:grid-cols-2">
        <form className="lab-panel space-y-3" onSubmit={event => { event.preventDefault(); void perform(async () => {
          const result = await createProject({ title: newTitle, owner_name: newOwner });
          apply(result, { project_id: result.project.id, access_key: result.access_key });
          setNewTitle(''); setNewOwner(''); setShare(''); setNotice('项目已创建。请下载项目凭据文件，以便在其他浏览器恢复访问。');
        }); }}>
          <h2 className="font-semibold">{tx('新建项目')}</h2>
          <label className="lab-label">{tx('项目名称')}<input className="lab-select" value={newTitle} onChange={event => setNewTitle(event.target.value)} maxLength={200} required /></label>
          <label className="lab-label">{tx('负责人姓名')}<input className="lab-select" value={newOwner} onChange={event => setNewOwner(event.target.value)} maxLength={100} required /></label>
          <Button type="submit" disabled={busy}>{tx('创建项目')}</Button>
        </form>
        <div className="lab-panel space-y-3">
          <h2 className="font-semibold">{tx('恢复项目访问')}</h2>
          <form className="space-y-3" onSubmit={event => { event.preventDefault(); void open({ project_id: restoreId, access_key: restoreKey }); }}>
            <label className="lab-label">{tx('项目编号')}<input className="lab-select" value={restoreId} onChange={event => setRestoreId(event.target.value.trim())} required autoComplete="off" /></label>
            <label className="lab-label">{tx('项目访问凭据')}<input className="lab-select" type="password" value={restoreKey} onChange={event => setRestoreKey(event.target.value.trim())} required autoComplete="off" /></label>
            <Button type="submit" variant="outline" disabled={busy}>{tx('打开项目')}</Button>
          </form>
          <label className="lab-label">{tx('或导入项目凭据文件')}<input type="file" accept="application/json,.json" disabled={busy} className="mt-2 block w-full text-sm" onChange={event => {
            const file = event.target.files?.[0]; if (file) void perform(async () => {
              if (file.size > 8192) throw new Error('项目凭据文件过大');
              const credential = parseProjectAccessFile(await file.text());
              apply(await projectRequest<ProjectResponse>(credential), credential); setShare('');
            }); event.target.value = '';
          }} /></label>
          <p className="text-xs text-muted-foreground">{tx('凭据决定访问权限。请将管理凭据保存到私人位置；给合作者分享时使用单独的只读凭据。')}</p>
        </div>
      </div>
      {vault.length > 0 && <section className="lab-panel"><h2 className="font-semibold">{tx('此浏览器保存的项目')}</h2><div className="mt-3 flex flex-wrap gap-2">{vault.map(row => <Button variant={project?.id === row.project_id ? 'default' : 'outline'} disabled={busy} key={row.project_id} onClick={() => void open(row)}>{row.title || row.project_id.slice(0, 8)}</Button>)}</div></section>}
      </details>
      {project && access && <>
        <section className="lab-panel space-y-4" aria-label={tx('项目详情')}>
          <div className="flex flex-wrap justify-between gap-3"><div><h2 className="text-xl font-semibold">{project.title}</h2><p className="mt-1 text-sm text-muted-foreground">{tx(owner ? '管理权限' : '只读访问')} · {tx('负责人')}：{project.owner_name} · {date(project.updated_at, true)}</p><p className="mt-1 break-all font-mono text-xs">{project.id}</p></div><Button variant="outline" disabled={busy} onClick={() => void open(access)}>{tx('重新读取项目')}</Button></div>
          <details><summary className="cursor-pointer font-medium">{tx('项目说明、凭据与分享')}</summary><div className="mt-4 space-y-4">
          {owner ? <form className="space-y-3" onSubmit={event => { event.preventDefault(); void mutate('', 'PATCH', { title, notes }); }}>
            <label className="lab-label">{tx('项目名称')}<input className="lab-select" value={title} maxLength={200} required onChange={event => setTitle(event.target.value)} /></label>
            <label className="lab-label">{tx('项目备注')}<textarea className="lab-select min-h-24" value={notes} maxLength={8000} onChange={event => setNotes(event.target.value)} /></label>
            <Button type="submit" variant="outline" disabled={busy}>{tx('保存项目说明')}</Button>
          </form> : <p className="whitespace-pre-wrap">{project.notes}</p>}
          <p className="text-xs text-muted-foreground">{tx('名称和备注只改变项目说明，不改变科学数据或重新计算。')}</p>
          <div className="flex flex-wrap gap-2"><Button variant="outline" onClick={() => download(projectAccessFile(access), `eeg-project-${project.id}-access.json`)}>{tx('下载项目凭据')}</Button>
            <Button variant="outline" onClick={() => {
              try { setVault(forgetProjectAccess(localStorage, access.project_id)); activateProject(null); setProject(null); setAccess(null); setShare(''); setNotice('已移除此浏览器的访问记录，服务器项目仍保留。'); }
              catch { setError('浏览器无法更新项目访问记录'); }
            }}>{tx('移除此浏览器的访问记录')}</Button></div>
          {owner && <div className="space-y-3 border-t pt-4"><div className="flex flex-wrap gap-2">
            <Button variant="outline" disabled={busy} onClick={() => void perform(async () => {
              const result = await projectRequest<ProjectResponse & { access_key: string }>(access, '/share', { method: 'POST', body: JSON.stringify({ revision: project.revision }) });
              apply(result, access); setShare(projectShareHref(window.location.origin, { project_id: project.id, access_key: result.access_key }));
            })}>{tx('生成只读分享链接')}</Button>
            <Button variant="outline" disabled={busy} onClick={() => { setShare(''); void mutate('/revoke-share', 'POST', {}); }}>{tx('撤销只读分享')}</Button>
          </div>{share && <label className="lab-label">{tx('只读分享链接')}<input className="lab-select" readOnly value={share} onFocus={event => event.target.select()} /></label>}</div>}
          </div></details>
        </section>
        <ProjectWorkflowEditor key={`${project.id}:${project.revision}`} project={project} owner={owner} busy={busy} save={workflow => void mutate('', 'PATCH', { workflow })} />
        <section className="lab-panel space-y-4" aria-label={tx('项目实验记录')}>
          <h2 className="text-lg font-semibold">{tx('项目实验记录')} · {project.entries.length}</h2>
          {owner && <details open={!project.entries.length} className="rounded-xl border p-4"><summary className="cursor-pointer font-medium">{tx('保存已完成结果到项目')}</summary><form className="mt-3 space-y-3" onSubmit={attach}>
            <h3 className="font-semibold">{tx('保存已完成结果到项目')}</h3>
            <label className="lab-label">{tx('选择已完成记录')}<select aria-label={tx('选择已完成记录')} className="lab-select" required value={choice} onChange={event => setChoice(event.target.value)}><option value="">{tx('选择记录')}</option>{choices.map(row => <option value={`${row.kind}:${row.id}`} key={`${row.kind}:${row.id}`}>{tx(kindLabel[row.kind])} · {row.title}</option>)}</select></label>
            {choicesLoading && <p className="text-sm text-muted-foreground">{tx('正在读取已完成记录…')}</p>}
            {choicesWarnings.map(warning => <p role="alert" className="text-sm text-amber-800" key={warning.kind}>{tx(kindLabel[warning.kind])} · <RuntimeMessage message={warning.message} /></p>)}
            {!choicesLoading && !choices.length && !choicesWarnings.length && <p className="text-sm text-muted-foreground">{tx('当前还没有可保存的已完成记录。')}</p>}
            <Button type="button" variant="outline" disabled={choicesLoading} onClick={() => setChoicesRetry(value => value + 1)}>{tx('重新读取记录目录')}</Button>
            <label className="lab-label">{tx('实验名称')}<input className="lab-select" value={entryTitle} maxLength={200} onChange={event => setEntryTitle(event.target.value)} /></label>
            <label className="lab-label">{tx('实验备注')}<textarea className="lab-select min-h-20" value={entryNotes} maxLength={8000} onChange={event => setEntryNotes(event.target.value)} /></label>
            <Button type="submit" disabled={busy || !choice}>{tx('保存到项目')}</Button>
            <p className="text-xs text-muted-foreground">{tx('保存原始科学结果的独立副本，不启动计算。')}</p>
          </form></details>}
          {!project.entries.length && <p className="text-muted-foreground">{tx('项目中还没有保存的实验。先在结果库选择布局，或完成一次信号仿真。')}</p>}
          {project.entries.map(entry => <EntryCard key={`${entry.id}:${project.revision}`} entry={entry} owner={owner} busy={busy}
            inspect={() => void perform(async () => setSnapshot(await projectRequest(access, `/entries/${entry.id}`)))}
            update={(nextTitle, nextNotes) => void mutate(`/entries/${entry.id}`, 'PATCH', { title: nextTitle, notes: nextNotes })}
            remove={() => void mutate(`/entries/${entry.id}`, 'DELETE', {})} />)}
        </section>
        {snapshot && <section className="lab-panel space-y-3" aria-label={tx('保存的科学数据')}><h2 className="font-semibold">{snapshot.entry.title}</h2><p className="text-sm text-muted-foreground">{tx('此数据来自项目保存时的原始结果。读取和下载不会重新计算。')}</p><Suspense fallback={<p>{tx('正在载入结果视图…')}</p>}><ProjectSnapshotViewer key={snapshot.entry.id} entry={snapshot.entry} snapshot={snapshot.snapshot} /></Suspense><Button variant="outline" onClick={() => download(JSON.stringify(snapshot.snapshot, null, 2) + '\n', `eeg-project-entry-${snapshot.entry.id}.json`)}>{tx('下载保存的科学数据')}</Button><details><summary className="cursor-pointer text-sm text-primary">{tx('展开原始数据')}</summary><pre className="mt-3 max-h-96 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-muted p-3 text-xs">{JSON.stringify(snapshot.snapshot, null, 2)}</pre></details></section>}
        <ProjectDeliveryPanel key={`${project.id}:${project.revision}:${role}`} project={project} access={access} />
      </>}
    </div>
  </main>;
}
