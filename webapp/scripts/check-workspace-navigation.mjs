import test from 'node:test';
import assert from 'node:assert/strict';
import { WORKSPACES, WORKSPACE_TABS, workspaceGroup, workingPage, routeSelection, selectionHref, workspaceLinks, layoutCapabilities, canCompareRecord } from '../lib/workspace-navigation.ts';
import { documentationHref } from '../lib/documentation.ts';
import { savedLayoutActions } from '../lib/results-library.ts';
import { canSimulateRecord } from '../lib/local-library.ts';
import { parseDecisionThresholds, jointDecisionThresholds } from '../lib/design-decision.ts';

const id = 'a'.repeat(64), secondId = 'b'.repeat(64);
const saved = { id, phase: 'saved' };
const record = { id, dataset_id: 'cache', status: 'completed', region_count: 2, request: { region_count: 2, radius_mm: 35, mode: 'preset', mask_codes: ['AL', 'AR'] }, layout: { xyzMm: Array.from({ length: 64 }, (_, i) => [i, 0, 0]), regionPatchVertexIndices: [[1], [2]] } };
const url = href => new URL(href, 'http://localhost');

void test('all primary and secondary pages have one area', () => {
  assert.deepEqual(WORKSPACES.map(area => area.id), ['workspace', 'layouts', 'analysis', 'findings', 'docs']);
  for (const [group, tabs] of Object.entries(WORKSPACE_TABS)) for (const [page] of tabs) assert.equal(workspaceGroup(page), group);
  for (const [page, group] of [['layout', 'layouts'], ['reception', 'analysis'], ['channels', 'analysis'], ['findings', 'findings'], ['home', 'workspace']]) assert.equal(workspaceGroup(page), group, page);
  for (const [href, page] of [['/coordinates?ar=32', 'coordinates'], ['/?ar=32', 'home'], ['/findings?ar=32', 'findings'], ['/layout?id=' + id, 'layout'],
    ['/pilot-results', 'results']]) assert.equal(workingPage(href), page, href);
});

void test('saved layouts retain their exact identity across eligible tools', () => {
  const links = workspaceLinks('/library?ar=32&record=' + id, 32, record, saved);
  for (const [page, key] of [['electrodes', 'parent'], ['decision', 'a'], ['reception', 'record'], ['layout', 'id']]) {
    assert.equal(url(links[page]).searchParams.get(key), id, page);
    assert.equal(url(links[page]).searchParams.get('ar'), '32');
  }
  assert.deepEqual(layoutCapabilities(record, saved), { design: true, edit: true, compare: true, reception: true });
});

void test('all saved-record and header comparison entries inherit the three shared requirements', () => {
  for (const here of ['/?ar=32', '/library?ar=32', '/design?ar=32', '/electrodes?ar=32', '/reception?ar=32']) {
    const href = workspaceLinks(here, 32, record, saved).decision;
    assert.deepEqual(parseDecisionThresholds(url(href).searchParams), jointDecisionThresholds(32), here);
  }
  assert.deepEqual(parseDecisionThresholds(url(savedLayoutActions(record, 32, '/library?ar=32').compare).searchParams), jointDecisionThresholds(32));
});

void test('independent decision limits survive tool and documentation navigation', () => {
  const here = '/decision?a=' + id + '&ar=68&thresholdMode=custom&sensitivity=30&p90=20';
  const expected = { mode: 'custom', field: 68, sensitivity: 30, localization: null, p90_mm: 20 };
  const first = workspaceLinks(here, 68, record, saved);
  for (const page of ['decision', 'design', 'electrodes', 'reception']) assert.deepEqual(parseDecisionThresholds(url(first[page]).searchParams), expected, page);
  // Coordinate import carries only the AR: it evaluates one layout, not a comparison.
  assert.equal(first.coordinates, '/coordinates?ar=68');
  const fromDesign = workspaceLinks(first.design, 68, record, saved);
  assert.deepEqual(parseDecisionThresholds(url(fromDesign.decision).searchParams), expected);
  const doc = documentationHref('/decision', url(here).search, 'method');
  const next = documentationHref('/method', url(doc).search, 'guide');
  const links = workspaceLinks(next, 68, record, saved);
  assert.equal(links.decision, here);
});

void test('native coordinate evaluations can be compared but are not turned into editable patches', () => {
  const native = { ...record, dataset_id: 'design_evaluation', request: null };
  assert.ok(canCompareRecord(native));
  const cap = layoutCapabilities(native, saved);
  assert.equal(cap.compare, true); assert.equal(cap.edit, false); assert.equal(cap.reception, true);
  for (const bad of [{ ...native, status: 'no_layout' }, { ...native, dataset_id: 'offline_radius' }]) assert.equal(canCompareRecord(bad), false);
  assert.ok(Object.values(layoutCapabilities({ ...record, id: secondId }, saved)).every(v => !v));
});

void test('record actions and workspace links expose simulation only for complete supported protocols', () => {
  for (const dataset_id of ['cache', 'strict_area', 'design_evaluation', 'historical_area', 'offline_radius']) {
    const candidate = { ...record, dataset_id };
    const supported = ['cache', 'strict_area', 'design_evaluation'].includes(dataset_id);
    assert.equal(canSimulateRecord(candidate), supported, dataset_id);
    assert.equal(!!savedLayoutActions(candidate, 32, '/library').reception, supported, dataset_id);
    assert.equal(layoutCapabilities(candidate, saved).reception, supported, dataset_id);
    const link = url(workspaceLinks('/library?record=' + id, 32, candidate, saved).reception);
    assert.equal(link.searchParams.get('record'), supported ? id : null, dataset_id);
  }
  for (const candidate of [null, { ...record, status: 'no_layout' }, { ...record, layout: null },
    { ...record, layout: { ...record.layout, xyzMm: record.layout.xyzMm.slice(0, 63) } }]) {
    assert.equal(canSimulateRecord(candidate), false);
    assert.equal(layoutCapabilities(candidate, saved).reception, false);
    if (candidate) assert.equal(savedLayoutActions(candidate, 32, '/library').reception, null);
  }
});

void test('layouts searched under correlated noise offer neither signal simulation nor electrode editing', () => {
  const noisy = { ...record, request: { ...record.request, noise_model: { kind: 'spatial', rho: 0.5, length_mm: 20 } } };
  assert.equal(canSimulateRecord(noisy), false);
  const cap = layoutCapabilities(noisy, saved);
  assert.equal(cap.edit, false); assert.equal(cap.reception, false); assert.equal(cap.compare, true);
  const actions = savedLayoutActions(noisy, 32, '/library');
  assert.equal(actions.edit, null); assert.equal(actions.reception, null); assert.ok(actions.compare);
  const links = workspaceLinks('/library?record=' + id, 32, noisy, saved);
  assert.equal(url(links.reception).searchParams.has('record'), false);
  assert.equal(url(links.electrodes).searchParams.has('parent'), false);
  const sparse = {
    ...record,
    request: { ...record.request, electrode_count: 24, allocation_mode: 'adaptive' },
    layout: { ...record.layout, xyzMm: record.layout.xyzMm.slice(0, 24), regionElectrodeCounts: [8, 16] },
  };
  assert.equal(canCompareRecord(sparse), true);
  assert.equal(canSimulateRecord(sparse), false);
  assert.deepEqual(layoutCapabilities(sparse, saved), { design: true, edit: false, compare: true, reception: false });
  const sparseActions = savedLayoutActions(sparse, 32, '/library');
  assert.ok(sparseActions.compare);
  assert.ok(sparseActions.design);
  assert.equal(sparseActions.edit, null);
  assert.equal(sparseActions.reception, null);
});

void test('drafts and edited copies never use their parent as a completed evaluation', () => {
  for (const phase of ['draft', 'edited']) {
    const selection = { id, phase, channels: 56, regions: 2 };
    assert.ok(Object.values(layoutCapabilities(record, selection)).every(v => !v));
    const here = selectionHref('/electrodes?parent=' + id + '&ar=32&resume=1', selection);
    const guide = documentationHref(url(here).pathname, url(here).search, 'guide');
    assert.deepEqual(routeSelection(guide), selection);
    const links = workspaceLinks(guide, 32, record, selection);
    assert.equal(links.electrodes, here);
    assert.equal(url(links.reception).searchParams.has('record'), false);
    assert.equal(url(links.decision).searchParams.has('a'), false);
  }
});

void test('explicit no-selection prevents stale source IDs returning through docs', () => {
  for (const path of ['/design?saved=' + id + '&draft=1', '/coordinates?a=' + id]) {
    const here = selectionHref(path, { id: null, phase: 'draft', channels: 64, regions: 3 });
    assert.equal(routeSelection(here).id, null);
    const doc = documentationHref(url(here).pathname, url(here).search, 'method');
    assert.equal(routeSelection(doc).id, null);
    assert.equal(routeSelection(doc).phase, 'draft');
  }
});

void test('both results views retain all filters and current selection after tool excursions', () => {
  const original = '/library?ar=32&domain=whole_scalp_free&area=120&r=2&metric=field_relative&filter=cache&regions=2&kind=editor&electrodes=56&location=AR&q=%E8%80%B3&page=3&sort=newest&record=' + id;
  const first = workspaceLinks(original, 32, record, saved);
  const via = workspaceLinks(first.decision, 46, { ...record, id: secondId }, { id: secondId, phase: 'saved' });
  for (const href of [via.findings, via.library]) {
    const q = url(href).searchParams;
    for (const [key, value] of Object.entries({ ar: '46', domain: 'whole_scalp_free', area: '120', r: '2', metric: 'field_relative', filter: 'cache', regions: '2', kind: 'editor', electrodes: '56', location: 'AR', q: '耳', page: '3', sort: 'newest' })) assert.equal(q.get(key), value, key);
    assert.equal(q.has('layoutRecord'), false); assert.equal(q.has('layoutState'), false);
  }
  // The findings view keeps the selection; the list names no layout record, since
  // the list opens a layout record on its own page and would leave the list.
  assert.equal(url(via.findings).searchParams.get('record'), secondId);
  assert.equal(routeSelection(via.findings).id, secondId);
  assert.equal(url(via.library).searchParams.has('record'), false);
  assert.equal(via.layout, '/layout?id=' + secondId + '&ar=46');
});

void test('the layout list link keeps editor and signal records, whose details stay on the list', () => {
  for (const entry of ['editor:' + 'c'.repeat(64), 'source:' + 'd'.repeat(64)]) {
    const links = workspaceLinks('/library?ar=32&filter=all&record=' + encodeURIComponent(entry), 32, null, { id: null, phase: 'saved' });
    assert.equal(url(links.library).searchParams.get('record'), entry);
  }
  const note = 'e'.repeat(64);
  const annotated = workspaceLinks('/library?ar=32&record=' + id + '&annotation_id=' + note, 32, record, saved);
  assert.equal(url(annotated.library).searchParams.has('record'), false);
  assert.equal(url(annotated.library).searchParams.has('annotation_id'), false);
  assert.equal(url(annotated.layout).searchParams.get('annotation_id'), note);
});

void test('docs preserve full work parameters rather than creating a new configuration', () => {
  for (const work of ['/design?ar=32&draft=1&r=4&radius=35&mode=low_hair', '/reception?ar=32&record=' + id + '&region=frontal&wave=rhythm&seed=91&sourceMode=single_source&source=17', '/coordinates?ar=32&resume=1']) {
    const doc = documentationHref(url(work).pathname, url(work).search, 'method', 'retention-guide');
    const links = workspaceLinks(doc, 32, record, routeSelection(doc));
    assert.equal(links[workingPage(doc)], work);
  }
});

void test('invalid IDs, counts and external returns cannot become active layout references', () => {
  assert.equal(routeSelection('/electrodes?parent=invalid').id, null);
  assert.equal(routeSelection('/electrodes?layoutChannels=200&layoutRegions=-1').channels, undefined);
  assert.equal(routeSelection('/electrodes?layoutChannels=200&layoutRegions=-1').regions, undefined);
  assert.equal(routeSelection('/method?returnTo=' + encodeURIComponent('https://example.com/?record=' + id)).id, null);
  const links = workspaceLinks('/library?ar=32&returnTo=https%3A%2F%2Fexample.com', 32, null, { id: null, phase: 'saved' });
  for (const href of Object.values(links)) assert.equal(url(href).origin, 'http://localhost');
});
