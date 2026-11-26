import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { KINDS, coverage, coverageKind, libraryDifferences, outcome, storedRequests, summary } from './helpers/key-parity.mjs';

// The comparisons of check-key-parity-live.mjs (tier C of design 0001 phase 2), offline.
const key = 'a'.repeat(64), other = 'b'.repeat(64);
const request = { region_count: 2, radius_mm: 35, mode: 'whole_surface' };
const hit = (jobKey = key, jobRequest = request) => summary({ status: 200, value: { hit: true, job: { key: jobKey, request: jobRequest, status: 'completed' } } });
const miss = summary({ status: 200, value: { hit: false } });
const refused = message => summary({ status: 400, value: { error: message } });

void test('a lookup that misses on both hosts compares no key', () => {
  // A miss is {hit: false} with no job on both hosts, so nothing about the key can differ: it is not compared.
  assert.deepEqual(miss, { status: 200, hit: false });
  assert.deepEqual(outcome(miss, miss), { outcome: 'not_compared', differences: [] });
  assert.deepEqual(outcome(hit(), hit()), { outcome: 'compared', differences: [] });
  assert.deepEqual(outcome(refused('该头模尚未预计算'), refused('该头模尚未预计算')), { outcome: 'refused', differences: [] });
  // Only compared keys count; a kind with none leaves the run incomplete.
  const results = [{ coverage: 'radius search', ...outcome(hit(), hit()) }, { coverage: 'coordinate evaluation', ...outcome(miss, miss) },
    { coverage: 'signal reception v2', ...outcome(refused('x'), refused('x')) }];
  const { compared, missing } = coverage(results);
  assert.deepEqual(compared, { 'radius search': 1, 'coordinate evaluation': 0, 'electrode editor': 0, 'signal reception v1': 0, 'signal reception v2': 0 });
  assert.deepEqual(missing, KINDS.slice(1));
  assert.deepEqual(coverage(KINDS.map(kind => ({ coverage: kind, outcome: 'compared' }))).missing, []);
  // The live script fails an incomplete run unless told to accept it, and labels a miss on both as not compared.
  const script = readFileSync(new URL('./check-key-parity-live.mjs', import.meta.url), 'utf8');
  assert.match(script, /passed: mismatches === 0 && \(allowIncomplete \|\| !covered\.missing\.length\)/);
  assert.match(script, /not_compared: 'not compared \(miss on both\)'/);
  assert.doesNotMatch(script, /fetch\([^)]*\/jobs/);
});

void test('two hosts agree only in status, hit, key and request, or in the message of a refusal', () => {
  for (const [python, node, found] of [
    [hit(), miss, ['hit']], [miss, hit(), ['hit']], [hit(key), hit(other), ['job.key']],
    [hit(key, request), hit(key, { ...request, radius_mm: 30 }), ['job.request']],
    [hit(key, request), hit(key, { mode: 'whole_surface', region_count: 2, radius_mm: 35 }), ['job.request member order']],
    [refused('a'), refused('b'), ['error']], [refused('a'), miss, ['status']],
  ]) {
    assert.deepEqual(outcome(python, node), { outcome: 'mismatch', differences: found });
  }
  assert.equal(coverageKind('local-compute', request), 'radius search');
  assert.equal(coverageKind('source-reception', { record_id: key }), 'signal reception v1');
  assert.equal(coverageKind('source-reception', { record_id: key, mode: 'single_source' }), 'signal reception v2');
});

void test('a stored record of the current identity must hit with its own key and request', () => {
  const stored = { key, request };
  assert.equal(outcome(hit(), hit(), stored).outcome, 'compared');
  // Both hosts agreeing on another key is still a divergence from what the record was stored under.
  assert.deepEqual(outcome(hit(other), hit(other), stored), { outcome: 'mismatch', differences: ['python key'] });
  assert.deepEqual(outcome(hit(key, { ...request, seed: 1 }), hit(key, { ...request, seed: 1 }), stored), { outcome: 'mismatch', differences: ['python request'] });
  // A cache row names its key only.
  assert.equal(outcome(hit(key, { ...request, seed: 1 }), hit(key, { ...request, seed: 1 }), { key }).outcome, 'compared');
  // An older identity misses on both hosts: nothing compared, nothing wrong.
  assert.equal(outcome(miss, miss, stored).outcome, 'not_compared');
});

void test('both libraries must hold the same rows with the same members', () => {
  const row = { id: key, dataset_id: 'cache', status: 'completed', compatible: true, request };
  assert.deepEqual(libraryDifferences([row], [{ ...row, visibility: { public: false } }]), { only_python: [], only_node: [], differing: [] });
  // A diverging compatible flag would move the row out of one host's cache-row check.
  assert.deepEqual(libraryDifferences([row, { ...row, id: other }], [{ ...row, compatible: false }, { ...row, id: '0'.repeat(64) }]),
    { only_python: [other], only_node: ['0'.repeat(64)], differing: [{ id: key, members: ['compatible'] }] });
  assert.deepEqual(libraryDifferences([{ ...row, label: 'x' }], [row]).differing, [{ id: key, members: ['label'] }]);
});

void test('stored requests are read from the completed records of the root', t => {
  const root = mkdtempSync(join(tmpdir(), 'key-parity-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const record = (tree, id, body, { complete = true } = {}) => {
    const directory = join(root, 'results', 'v2', tree, id);
    mkdirSync(join(directory, 'f3d1c2b4-0000-4000-8000-000000000000'), { recursive: true });
    writeFileSync(join(directory, 'f3d1c2b4-0000-4000-8000-000000000000', 'request.json'), JSON.stringify({ request: body, identity: { schema: 'x' } }));
    if (complete) writeFileSync(join(directory, 'cache.json'), '{}');
  };
  const design = { action: 'evaluate', design: { schema: 'eeg-electrode-design/1' }, seed: 2026 };
  record('design_evaluation_jobs', key, design);
  record('design_evaluation_jobs', other, design, { complete: false });
  record('electrode_editor_jobs', other, { action: 'prepare', parent_id: key });
  record('source_reception_jobs', key, { record_id: key, brain_region: 'frontal' });
  record('source_reception_v2_jobs', key, { record_id: key, mode: 'single_source' });
  record('local_app_jobs', key, request);
  mkdirSync(join(root, 'results', 'v2', 'design_evaluation_jobs', 'not-a-key'));
  assert.deepEqual(storedRequests(root).map(({ kind, coverage: kindCoverage, stored }) => [kind, kindCoverage, stored.key]), [
    ['design-evaluation', 'coordinate evaluation', key],
    ['electrode-editor', 'electrode editor', other],
    ['source-reception', 'signal reception v1', key],
    ['source-reception', 'signal reception v2', key],
  ]);
  assert.deepEqual(storedRequests(root)[0].body, design);
  assert.deepEqual(storedRequests(join(root, 'missing')), []);
});
