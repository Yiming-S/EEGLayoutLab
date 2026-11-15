'use client';
import { useEffect, useRef, useState } from 'react';
import { parseDesign, type ElectrodeDesign } from '../../lib/design-decision';
import { STUDY_DRAFT_LIMIT } from './robustness-draft';

/** File inputs replace a draft only after validation; superseded reads cannot restore older coordinates. */
export function useStudyDesignDraft(handoff: ElectrodeDesign | null, selectedStudyId?: string) {
  const [fileDraft, setFileDraft] = useState<{ chosen: boolean; design: ElectrodeDesign | null }>({ chosen: false, design: null });
  const [titleOverride, setTitleOverride] = useState<string | null>(null), [error, setError] = useState('');
  const current = useRef<AbortController | null>(null), mounted = useRef(true), [loading, setLoading] = useState(false);
  useEffect(() => { current.current?.abort(); current.current = null; }, [selectedStudyId]);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; current.current?.abort(); current.current = null; }; }, []);
  const readFile = async (file: File) => {
    current.current?.abort(); const controller = new AbortController(); current.current = controller;
    controller.signal.addEventListener('abort', () => { if (current.current === controller && mounted.current) setLoading(false); }, { once: true });
    setFileDraft({ chosen: true, design: null }); setTitleOverride(''); setError(''); setLoading(true);
    try {
      if (!Number.isSafeInteger(file.size) || file.size < 0 || file.size > STUDY_DRAFT_LIMIT) throw new Error('研究坐标草稿超过64 KiB');
      const raw = await file.text(); if (controller.signal.aborted || current.current !== controller) return;
      const imported = parseDesign(raw, file.name); setFileDraft({ chosen: true, design: imported }); setTitleOverride(imported.name);
    } catch (caught) { if (!controller.signal.aborted && current.current === controller) setError(caught instanceof Error ? caught.message : '坐标文件无法读取'); }
    finally { if (current.current === controller) { current.current = null; setLoading(false); } }
  };
  const design = fileDraft.chosen ? fileDraft.design : handoff;
  return { design, title: titleOverride ?? design?.name ?? '', setTitle: setTitleOverride, error, loading, readFile };
}
