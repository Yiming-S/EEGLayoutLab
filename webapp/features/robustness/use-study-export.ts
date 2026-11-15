'use client';
import { useEffect, useRef, useState } from 'react';

/** A download remains attached to the study selected when it was requested. */
export function useStudyExport(id: string | undefined, exportText: (signal?: AbortSignal) => Promise<string>, save: (id: string, text: string) => void) {
  const [state, setState] = useState({ id, busy: false, error: '' });
  const current = useRef<AbortController | null>(null);
  if (state.id !== id) setState({ id, busy: false, error: '' });
  useEffect(() => { current.current?.abort(); current.current = null; }, [id]);
  useEffect(() => () => { current.current?.abort(); current.current = null; }, []);
  const run = async () => {
    if (!id || current.current) return;
    const request = new AbortController(); current.current = request; setState({ id, error: '', busy: true });
    try { const raw = await exportText(request.signal); if (!request.signal.aborted && current.current === request) save(id, raw); }
    catch (caught) { if (!request.signal.aborted && current.current === request) setState({ id, busy: true, error: caught instanceof Error ? caught.message : '研究导出失败' }); }
    finally { if (current.current === request) { current.current = null; setState(value => ({ ...value, busy: false })); } }
  };
  return { busy: state.id === id && state.busy, error: state.id === id ? state.error : '', run };
}
