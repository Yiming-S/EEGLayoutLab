import type { ProjectEntryKind } from '../../client/projects';
import type { SavedSummary } from '../../lib/local-library';
import { localizedRecordTitle } from '../../lib/i18n/records.ts';
import type { Locale } from '../../lib/i18n/core';

export type ProjectRecordChoice = { kind: ProjectEntryKind; id: string; title: string; annotation_id?: string };
export const projectChoiceId = (choice: ProjectRecordChoice) => `${choice.kind}:${choice.id}${choice.annotation_id ? ':' + choice.annotation_id : ''}`;
const kinds: ProjectEntryKind[] = ['layout', 'editor', 'source'];
const hash = /^[a-f0-9]{64}$/;
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;
const object = (value: unknown): value is Record<string, unknown> => Boolean(value && typeof value === 'object' && !Array.isArray(value));

export function projectRecordChoices(kind: ProjectEntryKind, value: unknown, locale: Locale): ProjectRecordChoice[] {
  if (!object(value) || !Array.isArray(value.records)) throw new Error('记录目录格式无效');
  const rows = value.records.filter(object);
  return rows.flatMap<ProjectRecordChoice>(row => {
    if (kind === 'layout') {
      if (row.status !== 'completed' || typeof row.id !== 'string' || !hash.test(row.id)) return [];
      if (typeof row.label !== 'string') return [];
      const base = { kind, id: row.id, title: localizedRecordTitle(row as unknown as SavedSummary, locale) };
      const annotations = Array.isArray(value.electrode_annotations) ? value.electrode_annotations.filter(object).filter(annotation => annotation.record_id === row.id && typeof annotation.id === 'string' && hash.test(annotation.id) && Array.isArray(annotation.electrode_names) && annotation.electrode_names.every(name => typeof name === 'string')) : [];
      return [base, ...annotations.map(annotation => ({ ...base, annotation_id: annotation.id as string,
        title: `${base.title} · ${(annotation.electrode_names as string[])[0] ?? ''} · ${(annotation.id as string).slice(0, 8)}` }))];
    }
    if (kind === 'editor') {
      if (typeof row.key !== 'string' || !hash.test(row.key)) return [];
      return [{ kind, id: row.key, title: `${row.key.slice(0, 8)} · ${typeof row.electrode_count === 'number' ? row.electrode_count : '—'} ${locale === 'en' ? 'electrodes' : '电极'}` }];
    }
    if (row.kind !== 'source-reception' || row.status !== 'completed' || typeof row.id !== 'string' || !uuid.test(row.id)) return [];
    return [{ kind, id: row.id, title: typeof row.key === 'string' ? row.key.slice(0, 12) : row.id.slice(0, 12) }];
  });
}

/** Keep available record types usable when one independent directory fails. */
export function collectProjectRecordChoices(results: PromiseSettledResult<unknown>[], locale: Locale) {
  const choices: ProjectRecordChoice[] = [], warnings: { kind: ProjectEntryKind; message: string }[] = [];
  for (const [index, kind] of kinds.entries()) {
    const result = results[index];
    try {
      if (!result || result.status === 'rejected') throw result?.status === 'rejected' ? result.reason : new Error('记录目录未返回');
      choices.push(...projectRecordChoices(kind, result.value, locale));
    } catch (caught) {
      warnings.push({ kind, message: caught instanceof Error ? caught.message : '记录目录未载入' });
    }
  }
  return { choices, warnings };
}
