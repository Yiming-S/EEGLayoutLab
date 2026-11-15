import type { ProjectEntry } from '../../client/projects';

const scientificId = (value: unknown): value is string => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
const recordedString = (value: unknown) => typeof value === 'string' && value.trim() ? value : null;
const recordedInteger = (value: unknown) => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? value : null;

/** Associate by the original scientific ID, never by a title, alias, seed or array position. */
export function sourceLayoutAssociation(entry: ProjectEntry, entries: readonly ProjectEntry[]) {
  const parentId = entry.kind === 'source' && scientificId(entry.summary?.parent_id) ? entry.summary.parent_id : null;
  return { parentId, layouts: parentId ? entries.filter(row => row.kind === 'layout' && row.record_id === parentId) : [] };
}

export function projectExperimentAssociations(entries: readonly ProjectEntry[], candidateEntryId?: string | null) {
  const layouts = entries.filter(entry => entry.kind === 'layout');
  const candidate = layouts.find(entry => entry.id === candidateEntryId) ?? null;
  const candidateRecordId = candidate && scientificId(candidate.record_id) ? candidate.record_id : null;
  const signals = entries.filter(entry => entry.kind === 'source');
  const candidateSignals = candidateRecordId ? signals.filter(entry => sourceLayoutAssociation(entry, entries).parentId === candidateRecordId) : [];
  return {
    candidate, candidateRecordId, signals, candidateSignals,
    layoutCopies: layouts.length, distinctLayoutCount: new Set(layouts.filter(entry => scientificId(entry.record_id)).map(entry => entry.record_id)).size,
  };
}

export type ProjectExperimentFilter = 'all' | 'candidate-source';
export function filterProjectExperiments(entries: readonly ProjectEntry[], filter: ProjectExperimentFilter, candidateEntryId?: string | null) {
  return filter === 'candidate-source' ? projectExperimentAssociations(entries, candidateEntryId).candidateSignals : [...entries];
}

/** Missing historical request fields stay missing; mode never supplies defaults. */
export function sourceScenarioSummary(entry: ProjectEntry) {
  const summary = entry.kind === 'source' ? entry.summary : undefined;
  return {
    mode: recordedString(summary?.mode), brainRegion: recordedString(summary?.brain_region),
    brainRegions: Array.isArray(summary?.brain_regions) && summary.brain_regions.length && summary.brain_regions.every(value => recordedString(value)) ? [...summary.brain_regions] : null,
    sourceIndex: recordedInteger(summary?.source_index), seed: recordedInteger(summary?.seed),
  };
}
