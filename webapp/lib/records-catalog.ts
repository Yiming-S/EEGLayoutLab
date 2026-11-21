import type { EditorRecord, EditorRequest } from './electrode-editor';
import type { SavedSummary } from './local-library';
import type { ComputeRequest } from './local-compute';
import type { SourceRequest, SourceCondition } from './source-reception';
import { canonicalSourceRegions } from './source-regions.ts';
import { libraryViewLink, MASK_NAMES, parseLibraryView } from './ui-language.ts';

export type ExperimentReceipt = {
  id: string; key: string; kind: string; status: string; created_at: string; finished_at?: string | null;
  request: SourceRequest | EditorRequest | ComputeRequest | { action: 'prepare'; parent_id: string } | { action: 'evaluate' | 'perturb'; design: { name: string } };
  catalog?: {
    parent_id?: string; parent_label?: string; region_count?: number; electrode_count?: number;
    protocol?: string; mask_codes?: string[]; location_mode?: string;
    conditions?: { condition: SourceCondition; field_retention: number | null; baseline_explained_energy: number; candidate_explained_energy: number }[];
  } | null;
};
export type RecordKind = 'layout' | 'coordinates' | 'editor' | 'source';
export type CatalogEntry = {
  id: string; kind: RecordKind; finished_at?: string | null; electrode_count: number | null;
  region_count: number | null; locations: string[]; parent_id?: string;
} & ({ kind: 'layout' | 'coordinates'; summary: SavedSummary } | { kind: 'editor'; editor: EditorRecord } | { kind: 'source'; receipt: ExperimentReceipt; request: SourceRequest });
export type CatalogView = ReturnType<typeof parseLibraryView> & { kind: 'all' | RecordKind; electrodes: number; location: string; sort: string };
export const RECORD_KIND_LABELS = { layout: '布局与搜索', coordinates: '坐标评价', editor: '编辑副本', source: '信号实验' };

const locationsFor = (parent?: SavedSummary, codes: string[] = [], mode = '') => {
  const masks = parent?.request?.mask_codes ?? codes;
  return masks.length ? masks : (parent?.mode ?? mode).includes('whole') ? ['whole'] : (parent?.mode ?? mode).includes('low_hair') ? ['low_hair'] : [];
};
export const locationName = (location: string) => MASK_NAMES[location] ?? ({ whole: '全头候选区', low_hair: '少毛发候选区（模型近似）' }[location] ?? location);

/** Independent record types retain their schemas, metric definitions and parent IDs. */
export function buildRecordCatalog(layouts: SavedSummary[], editors: EditorRecord[], receipts: ExperimentReceipt[]): CatalogEntry[] {
  const parents = new Map(layouts.map(record => [record.id, record]));
  const newestSignals = new Map<string, ExperimentReceipt>();
  for (const receipt of receipts) {
    if (receipt.kind !== 'source-reception' || receipt.status !== 'completed') continue;
    const previous = newestSignals.get(receipt.key);
    if (!previous || Date.parse(receipt.created_at) > Date.parse(previous.created_at)) newestSignals.set(receipt.key, receipt);
  }
  return [
    ...layouts.map(summary => ({ id: summary.id, kind: summary.dataset_id === 'design_evaluation' ? 'coordinates' as const : 'layout' as const,
      finished_at: summary.finished_at, electrode_count: summary.status === 'completed' ? 64 : null,
      region_count: summary.region_count, locations: locationsFor(summary), summary })),
    ...editors.map(editor => ({ id: 'editor:' + editor.key, kind: 'editor' as const, finished_at: editor.finished_at,
      electrode_count: editor.electrode_count, region_count: editor.active_regions, parent_id: editor.parent_id,
      locations: locationsFor(parents.get(editor.parent_id)), editor })),
    ...[...newestSignals.values()].map(receipt => {
      const request = receipt.request as SourceRequest, parent = parents.get(request.record_id);
      return { id: 'source:' + receipt.key, kind: 'source' as const, finished_at: receipt.finished_at ?? receipt.created_at,
        electrode_count: receipt.catalog?.electrode_count ?? (parent?.status === 'completed' ? 64 : null),
        region_count: receipt.catalog?.region_count ?? parent?.region_count ?? null, parent_id: request.record_id,
        locations: locationsFor(parent, receipt.catalog?.mask_codes, receipt.catalog?.location_mode), receipt, request };
    }),
  ];
}
export function parseCatalogView(q: URLSearchParams): CatalogView {
  const kind = q.get('kind'), electrodes = Number(q.get('electrodes'));
  const regions = Number(q.get('regions'));
  return { ...parseLibraryView(q), region: Number.isInteger(regions) && regions >= 1 && regions <= 6 ? regions : 0,
    kind: ['layout', 'coordinates', 'editor', 'source'].includes(kind ?? '') ? kind as RecordKind : 'all',
    electrodes: Number.isInteger(electrodes) && electrodes >= 2 && electrodes <= 64 ? electrodes : 0,
    location: q.get('location') ?? '', sort: ['newest', 'oldest', 'name', 'electrodes'].includes(q.get('sort') ?? '') ? q.get('sort')! : 'newest' };
}
export function catalogViewLink(ar: number, id: string, view: CatalogView) {
  const url = new URL(libraryViewLink(ar, id, view), 'http://localhost');
  if (view.kind !== 'all') url.searchParams.set('kind', view.kind);
  if (view.electrodes) url.searchParams.set('electrodes', String(view.electrodes));
  if (view.location) url.searchParams.set('location', view.location);
  url.searchParams.set('sort', view.sort);
  return url.pathname + '?' + url.searchParams.toString();
}
export function matchesCatalogFilters(entry: CatalogEntry, view: CatalogView) {
  const dataset = 'summary' in entry ? entry.summary.dataset_id : '';
  return (view.kind === 'all' || entry.kind === view.kind) &&
    (view.filter === 'all' || (view.filter === 'current' ? ['strict_area', 'cache'].includes(dataset) : dataset === view.filter)) &&
    (!view.region || entry.region_count === view.region) && (!view.electrodes || entry.electrode_count === view.electrodes) &&
    (!view.location || entry.locations.includes(view.location));
}
export function editorRecordLink(record: Pick<EditorRecord, 'parent_id' | 'key'>, ar: number, returnTo: string) {
  const q = new URLSearchParams({ parent: record.parent_id, editorRecord: record.key, ar: String(ar), returnTo });
  return '/electrodes?' + q.toString();
}
/** Only DK40 requests round-trip through the current reception workspace. */
export function savedSourceLink(request: SourceRequest, ar: number, returnTo: string): string | null {
  if (!request.mode || request.region_definition !== 'dk40-six-roi-v1') return null;
  const q = new URLSearchParams({ record: request.record_id, ar: String(ar), returnTo, sourceMode: request.mode,
    wave: request.waveform, scale: String(request.artifact_scale), seed: String(request.seed) });
  if (request.mode === 'single_source') q.set('source', String(request.source_index));
  else if (request.mode === 'cross_region') q.set('sources', canonicalSourceRegions(request.brain_regions).join(','));
  else q.set('region', request.brain_region);
  return '/reception?' + q.toString();
}
/** The page where a queued or running task shows its progress; each page restores its active task. */
export function activeTaskLink(task: ExperimentReceipt, ar = 90, returnTo = '/library'): string | null {
  if (!['queued', 'running'].includes(task.status)) return null;
  const request = task.request as Record<string, unknown>;
  if (task.kind === 'local-compute') {
    const q = new URLSearchParams({ ar: String(ar), draft: '1', r: String(request.region_count), radius: String(request.radius_mm), mode: String(request.mode) });
    if (Array.isArray(request.mask_codes) && request.mask_codes.length) q.set('masks', request.mask_codes.join(','));
    return '/design?' + q.toString();
  }
  if (task.kind === 'design-evaluation') return '/coordinates';
  if (task.kind === 'electrode-editor' && typeof request.parent_id === 'string')
    return '/electrodes?' + new URLSearchParams({ parent: request.parent_id, ar: String(ar), returnTo }).toString();
  return task.kind === 'source-reception' ? savedSourceLink(task.request as SourceRequest, ar, returnTo) : null;
}

export function completedTaskLink(task: ExperimentReceipt, ar = 90, returnTo = '/library'): string | null {
  if (!['completed', 'no_layout'].includes(task.status)) return null;
  if (task.kind === 'local-compute') return `/library?record=${task.key}&ar=${ar}`;
  if (task.kind === 'design-evaluation') return 'action' in task.request && task.request.action === 'evaluate' ? `/library?record=${task.key}&ar=${ar}` : null;
  if (task.kind === 'electrode-editor') return 'parent_id' in task.request && 'action' in task.request && task.request.action === 'evaluate'
    ? editorRecordLink({ parent_id: task.request.parent_id, key: task.key }, ar, returnTo)
    : '/electrodes?' + new URLSearchParams({ parent: (task.request as { parent_id: string }).parent_id, ar: String(ar), returnTo }).toString();
  return task.kind === 'source-reception' ? savedSourceLink(task.request as SourceRequest, ar, returnTo) : null;
}
