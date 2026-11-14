'use client';
/* oxlint-disable next/no-html-link-for-pages */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { useLanguage } from '@/components/language-provider';

import { ApiError, followTask, submitTask, cancelTask, readTask, type TaskConnection } from '@/client/task-client';

import { parseAR } from '@/lib/lab-workflow';
import type { SavedSummary } from '@/lib/local-library';
import {
  initialSlots,
  pointMap,
  draftError,
  editHistory,
  slotKey,
  editorLink,
  type Slot,
  type EditorDomain,
  type EditorRequest,
  type EditorJob,
  type EditorResult,
  type EditorRecord,
  type EditHistory,
} from '@/lib/electrode-editor';
export const running = (j: EditorJob | null) =>
  !!j && ['queued', 'running', 'cancelling'].includes(j.status);
const blank: EditHistory = { past: [], present: [], future: [] };
const failure = (key: string) =>
  key === 'count'
    ? '至少保留两个启用电极。'
    : key === 'region'
      ? '点位必须位于其原区域候选列表内。'
      : '操作未应用：启用电极之间需至少4 mm间距。';

export function useElectrodesController() {
  const { tx, locale, date } = useLanguage();
  const [parents, setParents] = useState<SavedSummary[]>([]),
    [parentId, setParentId] = useState('');
  const [domain, setDomain] = useState<EditorDomain | null>(null),
    [digest, setDigest] = useState('');
  const [history, setHistory] = useState<EditHistory>(blank),
    [selection, setSelection] = useState<number[]>([]);
  const [savedDraftKey, setSavedDraftKey] = useState('');
  const [editMode, setEditMode] = useState(false),
    [ar, setAr] = useState(90),
    [candidate, setCandidate] = useState('');
  const [connection, setConnection] = useState<TaskConnection>('connected');
  const [job, setJob] = useState<EditorJob | null>(null),
    [pending, setPending] = useState(false),
    [error, setError] = useState(''),
    [notice, setNotice] = useState('');
  const [lastResult, setLastResult] = useState<EditorResult | null>(null),
    [records, setRecords] = useState<EditorRecord[]>([]);
  const alive = useRef(true),
    controller = useRef<AbortController | null>(null),
    restored = useRef(false);
  const loadingRecord = useRef<EditorRecord | undefined>(undefined);
  const slots = history.present,
    busy = pending || (running(job) && connection !== 'blocked');
  const dirty = !!domain && slotKey(slots) !== savedDraftKey;
  const refreshRecords = useCallback(async () => {
    const r = await fetch('/api/electrode-editor/records', {
      cache: 'no-store',
    });
    if (!r.ok) throw new Error('Editor records are unavailable');
    const body = (await r.json()) as { records: EditorRecord[] };
    if (alive.current) setRecords(body.records);
  }, []);
  useEffect(() => {
    alive.current = true;
    const q = new URLSearchParams(window.location.search);
    void Promise.resolve().then(() => {
      if (alive.current) {
        setAr(parseAR(q.get('ar')));
        setParentId(q.get('parent') ?? '');
      }
    });
    fetch('/api/electrode-editor/parents', { cache: 'no-store' })
      .then((r) => {
        if (!r.ok) throw new Error('Local library is unavailable');
        return r.json() as Promise<{ records: SavedSummary[] }>;
      })
      .then((data) => {
        if (alive.current)
          setParents(
            data.records.filter(
              (r: SavedSummary) =>
                r.status === 'completed' &&
                (r.dataset_id === 'strict_area' || r.dataset_id === 'cache'),
            ),
          );
      })
      .catch((e) => {
        if (alive.current) setError(e.message);
      });
    void refreshRecords().catch((e) => {
      if (alive.current) setError(e.message);
    });
    return () => {
      alive.current = false;
      controller.current?.abort();
    };
  }, [refreshRecords]);
  const follow = useCallback(
    async (initial: EditorJob, signal: AbortSignal) => {
      if (alive.current) { setJob(initial); setConnection('connected'); }
      const current = await followTask({
        service: 'electrode-editor', initial, signal,
        onJob(value) { if (alive.current) setJob(value); },
        onConnection(state, failure) {
          if (!alive.current) return;
          setConnection(state);
          setError(failure?.message ?? '');
        },
      });
      if (current.status !== 'completed' || !current.result)
        throw new Error(current.message);
      return current;
    },
    [],
  );
  const run = useCallback(
    async (
      request: { action: 'prepare'; parent_id: string } | EditorRequest,
    ) => {
      setError('');
      setNotice('');
      setPending(true);
      const abort = new AbortController();
      controller.current = abort;
      try {
        const data = await submitTask<{ job: EditorJob }>('electrode-editor', request, {
          signal: abort.signal, errorMessage: 'Local editor service is unavailable',
        });
        if (alive.current) setPending(false);
        return await follow(data.job, abort.signal);
      } catch (e) {
        if (alive.current && e instanceof ApiError) setConnection('blocked');
        throw e;
      } finally {
        if (alive.current) setPending(false);
      }
    },
    [follow],
  );
  const load = useCallback(
    async (id: string, saved?: EditorRecord, resume = false) => {
      if (!/^[a-f0-9]{64}$/.test(id)) {
        setError('Choose a source layout');
        return;
      }
      loadingRecord.current = saved;
      try {
        const j = await run({ action: 'prepare', parent_id: id });
        if (!alive.current) return;
        const d = j.result as EditorDomain;
        if (saved && saved.request.parent_digest !== j.parent_digest)
          throw new Error('Parent changed; reload the layout before editing');
        let values = saved?.request.slots ?? initialSlots(d);
        if (resume) {
          try {
            const raw = sessionStorage.getItem('eeg-editor-tab-draft:' + id);
            const draft = raw ? JSON.parse(raw) : null;
            if (
              draft?.digest === j.parent_digest &&
              !draftError(draft.slots, d)
            ) {
              values = draft.slots;
              setNotice('已恢复本标签页的电极草稿；尚未重新评价。');
            }
          } catch {
            setNotice('电极草稿无法恢复，已载入所选布局。');
          }
        }
        if (draftError(values, d))
          throw new Error('Saved electrode draft is invalid');
        setDomain(d);
        setDigest(j.parent_digest!);
        setHistory({ past: [], present: values, future: [] });
        setSavedDraftKey(slotKey(values));
        setParentId(id);
        setSelection([]);
        setLastResult(null);
        setEditMode(false);
        const href = new URL(editorLink(id, ar), window.location.origin);
        if (saved) href.searchParams.set('editorRecord', saved.key);
        const origin = new URLSearchParams(window.location.search).get(
          'returnTo',
        );
        if (origin) href.searchParams.set('returnTo', origin);
        if (slotKey(values) !== slotKey(initialSlots(d)))
          href.searchParams.set('resume', '1');
        window.history.replaceState(null, '', href.pathname + href.search);
      } catch (e) {
        if (alive.current)
          setError(e instanceof Error ? e.message : 'Load failed');
      }
    },
    [ar, run],
  );
  useEffect(() => {
    if (restored.current || !parents.length) return;
    restored.current = true;
    const q = new URLSearchParams(window.location.search),
      id = q.get('parent'), savedKey = q.get('editorRecord');
    void (async () => {
      if (savedKey) {
        if (!/^[a-f0-9]{64}$/.test(savedKey)) {
          if (alive.current) setError('编辑记录编号无效，请从记录列表重新选择。');
          return;
        }
        try {
          const response = await fetch('/api/electrode-editor/records', { cache: 'no-store' });
          if (!response.ok) throw new Error('Editor records are unavailable');
          const body = await response.json() as { records: EditorRecord[] };
          const saved = body.records.find(record => record.key === savedKey);
          if (!saved || (id && saved.parent_id !== id)) throw new Error('指定编辑记录无法读取，或与原布局不一致。');
          if (alive.current)
            await load(saved.parent_id, saved, q.get('resume') === '1');
        } catch (e) {
          if (alive.current) setError(e instanceof Error ? e.message : 'Load failed');
        }
      } else if (id && alive.current) await load(id, undefined, q.get('resume') === '1');
    })();
  }, [parents, load]);
  useEffect(() => {
    if (!domain || !digest || draftError(slots, domain)) return;
    try {
      sessionStorage.setItem(
        'eeg-editor-tab-draft:' + domain.parent.id,
        JSON.stringify({ digest, slots }),
      );
    } catch {
      void Promise.resolve().then(() => {
        if (alive.current)
          setNotice('当前标签页无法暂存电极草稿；请手动保存后离开。');
      });
    }
  }, [domain, digest, slots]);
  useEffect(() => {
    if (!dirty) return;
    const warning = (e: BeforeUnloadEvent) => {
      e.preventDefault();
    };
    window.addEventListener('beforeunload', warning);
    return () => window.removeEventListener('beforeunload', warning);
  }, [dirty]);
  const commit = useCallback(
    (next: Slot[]) => {
      if (!domain || busy) return;
      const invalid = draftError(next, domain);
      if (invalid) {
        setNotice(failure(invalid));
        return;
      }
      setHistory((h) => editHistory(h, next));
      setNotice('');
    },
    [domain, busy],
  );
  const select = useCallback((slot: number, multiple: boolean) => {
    setCandidate('');
    setSelection((previous) =>
      multiple
        ? previous.includes(slot)
          ? previous.filter((i) => i !== slot)
          : [...previous, slot]
        : [slot],
    );
  }, []);
  const move = useCallback(
    (slot: number, bank_index: number) =>
      commit(slots.map((s, i) => (i === slot ? { ...s, bank_index } : s))),
    [commit, slots],
  );
  const points = useMemo(
    () => (domain ? pointMap(domain) : new Map()),
    [domain],
  );
  const layout = useMemo(
    () =>
      domain
        ? {
            ...domain.parent.layout!,
            id: 'editor-draft',
            xyzMm: slots.map((s) => points.get(s.bank_index)!),
          }
        : undefined,
    [domain, slots, points],
  );
  const allocation = useMemo(
    () =>
      domain
        ? Array.from(
            { length: domain.parent.region_count },
            (_, r) =>
              slots.filter(
                (s, i) =>
                  s.enabled && domain.parent.layout!.regionIndices[i] === r,
              ).length,
          )
        : [],
    [domain, slots],
  );
  const editor = useMemo(
    () =>
      domain
        ? {
            enabled: editMode && !busy,
            active: slots.map((s) => s.enabled),
            selection,
            candidates: domain.regions,
            onSelect: select,
            onMove: move,
            onInvalid: () =>
              setNotice('操作未应用：启用电极之间需至少4 mm间距。'),
          }
        : undefined,
    [domain, editMode, busy, slots, selection, select, move],
  );
  const result =
    lastResult &&
    lastResult.request.parent_id === domain?.parent.id &&
    slotKey(lastResult.request.slots) === slotKey(slots)
      ? lastResult
      : null;
  const activeCount = slots.filter((s) => s.enabled).length;
  const originalLayout =
    !!domain && slotKey(slots) === slotKey(initialSlots(domain));
  const coords =
    selection.length === 1 ? points.get(slots[selection[0]]?.bank_index) : null;
  const evaluate = async () => {
    if (!domain) return;
    try {
      const j = await run({
        action: 'evaluate',
        parent_id: domain.parent.id,
        parent_digest: digest,
        seed: 2026,
        slots,
      });
      if (!alive.current) return;
      setLastResult(j.result as EditorResult);
      setSavedDraftKey(slotKey((j.result as EditorResult).request.slots));
      await refreshRecords();
    } catch (e) {
      if (alive.current)
        setError(e instanceof Error ? e.message : 'Evaluation failed');
    }
  };
  const cancel = async () => {
    if (!job) return;
    try {
      const id = job.id;
      const data = await cancelTask<{ job: EditorJob }>('electrode-editor', id);
      if (alive.current) setJob(current => current?.id === id ? data.job : current);
    } catch (e) {
      setError(String(e));
    }
  };
  const reconnect = async () => {
    if (!job) return;
    setPending(true);
    setError('');
    const abort = new AbortController();
    controller.current = abort;
    try {
      const current = await readTask<EditorJob>('electrode-editor', job.id, abort.signal);
      const completed = await follow(current, abort.signal);
      if (!alive.current) return;
      if ('parent' in completed.result!) {
        const d = completed.result as EditorDomain,
          saved = loadingRecord.current;
        if (saved && saved.request.parent_digest !== completed.parent_digest)
          throw new Error('Parent changed; reload the layout before editing');
        const values = saved?.request.slots ?? initialSlots(d);
        if (draftError(values, d))
          throw new Error('Saved electrode draft is invalid');
        setDomain(d);
        setDigest(completed.parent_digest!);
        setParentId(d.parent.id);
        setHistory({ past: [], present: values, future: [] });
        setSelection([]);
        setLastResult(null);
        setSavedDraftKey(slotKey(values));
        window.history.replaceState(null, '', editorLink(d.parent.id, ar));
      } else {
        setLastResult(completed.result as EditorResult);
        setSavedDraftKey(
          slotKey((completed.result as EditorResult).request.slots),
        );
        await refreshRecords();
      }
    } catch (e) {
      if (alive.current) {
        setError(String(e));
        if (e instanceof ApiError) setConnection('blocked');
      }
    } finally {
      if (alive.current) setPending(false);
    }
  };
  const saveDraft = () => {
    try {
      localStorage.setItem(
        'eeg-editor-draft:' + domain!.parent.id,
        JSON.stringify({ digest, slots }),
      );
      setSavedDraftKey(slotKey(slots));
      setNotice('草稿已保存在此浏览器；尚未生成新评分。');
    } catch (e) {
      setError(String(e));
    }
  };
  const readDraft = () => {
    try {
      const text = localStorage.getItem(
        'eeg-editor-draft:' + domain!.parent.id,
      );
      if (!text) {
        setNotice('此布局没有已存草稿。');
        return;
      }
      const draft = JSON.parse(text);
      if (draft.digest !== digest) {
        setNotice('草稿来源已变化，请重新载入原布局。');
        return;
      }
      const invalid = draftError(draft.slots, domain!);
      if (invalid) {
        setNotice(failure(invalid));
        return;
      }
      commit(draft.slots);
      setSavedDraftKey(slotKey(draft.slots));
    } catch (e) {
      setError(String(e));
    }
  };
  const switchLayout = (id: string, record?: EditorRecord) => {
    if (dirty && !window.confirm(tx('当前有未保存的编辑，确认切换布局？')))
      return;
    void load(id, record);
  };
  const exportResult = () => {
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' }),
    );
    const a = document.createElement('a');
    a.href = url;
    a.download = 'electrode-edit-evaluation.json';
    a.click();
    URL.revokeObjectURL(url);
  };
  return {
    tx,
    locale,
    date,
    parents,
    parentId,
    setParentId,
    domain,
    history,
    setHistory,
    selection,
    setSelection,
    editMode,
    setEditMode,
    ar,
    setAr,
    candidate,
    setCandidate,
    job,
    pending,
    connection,
    error,
    notice,
    records,
    slots,
    busy,
    commit,
    select,
    move,
    layout,
    allocation,
    editor,
    result,
    activeCount,
    originalLayout,
    coords,
    evaluate,
    cancel,
    reconnect,
    saveDraft,
    readDraft,
    switchLayout,
    exportResult,
  };
}
