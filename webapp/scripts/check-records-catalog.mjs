import test from 'node:test';
import assert from 'node:assert/strict';
import { buildRecordCatalog, parseCatalogView, catalogViewLink, matchesCatalogFilters, savedSourceLink, completedTaskLink, editorRecordLink } from '../lib/records-catalog.ts';
import { sourceKey } from '../lib/source-reception.ts';

const parent = { id: 'a'.repeat(64), dataset_id: 'cache', label: 'AL + AR', region_count: 2, mode: 'preset',
  status: 'completed', request: { region_count: 2, radius_mm: 20, mode: 'preset', mask_codes: ['AL', 'AR'] }, finished_at: '2026-10-01T00:00:00Z' };
const edited = { key: 'b'.repeat(64), parent_id: parent.id, parent_label: parent.label, electrode_count: 63, active_regions: 2,
  finished_at: '2026-10-02T00:00:00Z', protocol: 'electrode-editor/1', request: { parent_id: parent.id, slots: [] } };
const sourceRequest = { record_id: parent.id, mode: 'cross_region', brain_regions: ['frontal', 'occipital'],
  waveform: 'rhythm', artifact_scale: 4, seed: 42, region_definition: 'dk40-six-roi-v1' };
const receipt = { id: 'source-receipt', key: 'c'.repeat(64), kind: 'source-reception', status: 'completed',
  created_at: '2026-10-03T00:00:00Z', finished_at: '2026-10-03T00:01:00Z', request: sourceRequest };

void test('unified catalog keeps actual electrode counts, parent associations and independent schemas', () => {
  const noLayout = { ...parent, id: 'd'.repeat(64), status: 'no_layout' };
  const coordinate = { ...parent, id: 'e'.repeat(64), dataset_id: 'design_evaluation', mode: 'imported_coordinates', request: null };
  const entries = buildRecordCatalog([parent, coordinate, noLayout], [edited], [receipt]);
  assert.deepEqual(entries.map(entry => entry.kind), ['layout', 'coordinates', 'layout', 'editor', 'source']);
  assert.deepEqual(entries.map(entry => entry.electrode_count), [64, 64, null, 63, 64]);
  assert.equal(entries[3].editor, edited); assert.ok(!('summary' in entries[3]));
  assert.equal(entries[3].parent_id, parent.id); assert.deepEqual(entries[4].locations, ['AL', 'AR']);
  const view = parseCatalogView(new URLSearchParams('kind=editor&electrodes=63&location=AR&regions=2'));
  assert.deepEqual(entries.filter(entry => matchesCatalogFilters(entry, view)).map(entry => entry.id), ['editor:' + edited.key]);
  const historical = parseCatalogView(new URLSearchParams('filter=cache'));
  assert.equal(entries.filter(entry => matchesCatalogFilters(entry, historical)).length, 2);
});
void test('repeated saved signal reads produce one row bound to the newest owned receipt', () => {
  const newer = { ...receipt, id: 'newest-receipt', created_at: '2026-10-04T00:00:00Z' };
  const failed = { ...receipt, id: 'failed-read', status: 'failed', created_at: '2026-10-05T00:00:00Z' };
  const entries = buildRecordCatalog([parent], [], [newer, receipt, failed]);
  assert.equal(entries.filter(entry => entry.kind === 'source').length, 1);
  assert.equal(entries.find(entry => entry.kind === 'source').receipt.id, 'newest-receipt');
});
void test('catalog filters round-trip with established selection, search, paging and historical protocol fields', () => {
  const q = new URLSearchParams('filter=offline_radius&history=1&regions=2&q=ear&page=3&kind=layout&electrodes=64&location=AR&sort=oldest');
  const view = parseCatalogView(q), href = catalogViewLink(50, parent.id, view), restored = new URL(href, 'http://localhost');
  assert.deepEqual(parseCatalogView(restored.searchParams), view);
  assert.equal(restored.searchParams.get('record'), parent.id); assert.equal(restored.searchParams.get('history'), '1');
  assert.equal(restored.searchParams.get('ar'), '50');
  assert.equal(parseCatalogView(new URLSearchParams('electrodes=65&kind=unknown&sort=bad')).electrodes, 0);
  assert.equal(parseCatalogView(new URLSearchParams('regions=5')).region, 5);
});
void test('signal result links preserve every current request field and reject older source protocols', () => {
  const requests = [sourceRequest,
    { ...sourceRequest, mode: 'single_source', source_index: 255, brain_regions: undefined },
    { ...sourceRequest, mode: 'multi_source', brain_region: 'temporal_right', brain_regions: undefined }];
  for (const request of requests) {
    const href = savedSourceLink(request, 80, '/library?kind=source&record=source:test'), q = new URL(href, 'http://localhost').searchParams;
    const common = { record_id: q.get('record'), mode: q.get('sourceMode'), waveform: q.get('wave'), artifact_scale: Number(q.get('scale')),
      seed: Number(q.get('seed')), region_definition: 'dk40-six-roi-v1' };
    const restored = request.mode === 'single_source' ? { ...common, source_index: Number(q.get('source')) }
      : request.mode === 'cross_region' ? { ...common, brain_regions: q.get('sources').split(',') } : { ...common, brain_region: q.get('region') };
    assert.equal(sourceKey(restored), sourceKey(request));
    assert.equal(q.get('returnTo'), '/library?kind=source&record=source:test');
  }
  assert.equal(savedSourceLink({ ...sourceRequest, region_definition: undefined }, 90, '/library'), null);
  assert.equal(savedSourceLink({ record_id: parent.id, brain_region: 'frontal', waveform: 'burst', artifact_scale: 1, seed: 2026 }, 90, '/library'), null);
});
void test('completed tasks reopen exact editor records and coordinate evaluations; incomplete tasks and perturbations do not open nominal records', () => {
  const editor = { ...receipt, kind: 'electrode-editor', key: edited.key, request: { action: 'evaluate', parent_id: parent.id } };
  const url = new URL(completedTaskLink(editor), 'http://localhost');
  assert.equal(url.searchParams.get('editorRecord'), edited.key); assert.equal(url.searchParams.get('parent'), parent.id);
  assert.equal(editorRecordLink(edited, 90, '/library'), completedTaskLink(editor));
  assert.equal(completedTaskLink({ ...receipt, kind: 'local-compute' }), `/library?record=${receipt.key}&ar=90`);
  assert.equal(completedTaskLink({ ...receipt, kind: 'design-evaluation', request: { action: 'evaluate' } }), `/library?record=${receipt.key}&ar=90`);
  assert.equal(completedTaskLink({ ...receipt, kind: 'design-evaluation', request: { action: 'perturb' } }), null);
  assert.equal(completedTaskLink({ ...receipt, status: 'failed' }), null);
});
