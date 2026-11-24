import type { SavedRecord, SavedSummary } from './local-library';
import { canSimulateRecord } from './local-library.ts';
import { assessment, parseAR, radiusDesignLink } from './lab-workflow.ts';
import { safeReturnHref } from './ui-language.ts';
import { decisionHref, jointDecisionThresholds } from './design-decision.ts';

const overviewKeys = ['domain', 'area', 'r', 'metric'];
const recordsKeys = [
  'record',
  'filter',
  'regions',
  'q',
  'page',
  'sort',
  'history',
  'kind',
  'electrodes',
  'location',
];

// Each route owns its controls; carry only the other view's state through it.
export function preserveResultsContext(
  destination: string,
  previousSearch: string,
) {
  const url = new URL(destination, 'http://localhost');
  const previous = new URLSearchParams(previousSearch);
  for (const key of url.pathname === '/library' ? overviewKeys : recordsKeys) {
    const value = previous.get(key);
    if (value !== null && !url.searchParams.has(key))
      url.searchParams.set(key, value);
  }
  return url.pathname + '?' + url.searchParams.toString() + url.hash;
}

export function resultsViewHref(
  view: 'overview' | 'records',
  search: string,
  selected?: SavedSummary | null,
) {
  const q = new URLSearchParams(search);
  q.set('ar', String(parseAR(q.get('ar'))));
  if (view === 'records' && !q.has('record') && selected)
    q.set('record', selected.id);
  if (
    view === 'overview' &&
    !q.has('domain') &&
    selected?.dataset_id === 'strict_area'
  ) {
    q.set('domain', selected.mode);
    q.set('area', String(selected.area_cap_cm2));
    q.set('r', String(selected.region_count));
  }
  return (view === 'overview' ? '/findings' : '/library') + '?' + q.toString();
}

export function resultQualification(record: SavedSummary, ar: number) {
  if (record.status !== 'completed') return '无法判断';
  const state = assessment(record.metrics, ar).state;
  return state === 'pass'
    ? '达到要求'
    : state === 'fail'
      ? '未达到要求'
      : '无法判断';
}

export function savedLayoutActions(
  record: SavedRecord,
  ar: number,
  back: string,
) {
  const complete =
    record.status === 'completed' && record.layout?.xyzMm.length === 64;
  const current = ['strict_area', 'cache', 'design_evaluation'].includes(
    record.dataset_id,
  );
  const withReturn = (href: string | null) =>
    href
      ? href +
        '&returnTo=' +
        encodeURIComponent(safeReturnHref(back, '/library?ar=' + ar))
      : null;
  return {
    design: withReturn(radiusDesignLink(record, ar)),
    edit:
      complete &&
      ['strict_area', 'cache'].includes(record.dataset_id) &&
      record.layout?.regionPatchVertexIndices?.length &&
      !record.request?.noise_model && !record.request?.data_prior
        ? withReturn(`/electrodes?parent=${record.id}&ar=${ar}`)
        : null,
    compare:
      complete && current
        ? withReturn(decisionHref([record.id], jointDecisionThresholds(ar)))
        : null,
    reception:
      canSimulateRecord(record)
        ? `/reception?record=${record.id}&ar=${ar}&returnTo=${encodeURIComponent(back)}`
        : null,
  };
}
