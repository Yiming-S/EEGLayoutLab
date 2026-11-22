import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { comparisonGroup, dominates, paretoAnalysis, paretoRanks, summaryObjectives } from '../lib/pareto.ts';
import { robustnessSummary } from '../contracts/scientific-options.mjs';
import { robustnessBlock } from './helpers/robustness-fixture.mjs';

void test('non-dominated sorting ranks fronts and treats ties as equal', () => {
  const points = [[1, 1], [2, 0], [0, 2], [.5, .5], [1, 1], [0, 0], [.4, .4]];
  const { rank, dominatedBy } = paretoRanks(points, ['max', 'max']);
  assert.deepEqual(rank, [1, 1, 1, 2, 1, 4, 3]);
  assert.deepEqual(dominatedBy, [0, 0, 0, 2, 0, 6, 3]);
  assert.equal(dominates([1, 1], [1, 1 - 1e-13], ['max', 'max']), false, 'differences within 1e-12 are ties');
  // Minimized objectives reverse the order.
  assert.deepEqual(paretoRanks([[1, 10], [1, 5], [2, 5]], ['max', 'min']).rank, [3, 2, 1]);
});

void test('analysis excludes records missing a chosen objective and sorts the front first', () => {
  const items = [{ item: 'a', values: { field: .9, p90: 10 } }, { item: 'b', values: { field: .8, p90: 8 } },
    { item: 'c', values: { field: .7, p90: 12 } }, { item: 'd', values: { field: .95, p90: null } }];
  const analysis = paretoAnalysis(items, ['field', 'p90']);
  assert.deepEqual(analysis.rows.map(row => [row.item, row.rank]), [['a', 1], ['b', 1], ['c', 2]]);
  assert.deepEqual(analysis.excluded, ['d']);
  assert.deepEqual(paretoAnalysis(items, ['field']).rows.map(row => row.item), ['d', 'a', 'b', 'c']);
  assert.throws(() => paretoAnalysis(items, []), /目标/);
  assert.throws(() => paretoAnalysis(items, ['field', 'field']), /目标/);
});

void test('library records give their objectives and only same-condition current records are grouped', () => {
  const metrics = { field_relative: .9, sensitivity_tail: .8, localization_relative: .7, p90_mm: 11 };
  const values = summaryObjectives({ metrics, geometry: { union_area_cm2: 30 }, robustness: robustnessSummary(robustnessBlock()) });
  assert.deepEqual(values, { field: .9, sensitivity: .8, localization: .7, p90: 11, area: 30, dropout: .998, impedance: .997, replacement: .99 });
  assert.equal(summaryObjectives({ metrics, geometry: null }).replacement, null);
  assert.equal(summaryObjectives({ metrics, geometry: null, robustness: robustnessSummary(robustnessBlock({ table: false })) }).replacement, null);
  const base = { status: 'completed', compatible: true, request: null };
  assert.equal(comparisonGroup({ ...base, dataset_id: 'offline_radius' }), null);
  assert.equal(comparisonGroup({ ...base, dataset_id: 'cache', compatible: false }), null);
  assert.equal(comparisonGroup({ ...base, dataset_id: 'design_evaluation', status: 'no_layout' }), null);
  assert.equal(comparisonGroup({ ...base, dataset_id: 'design_evaluation' }), comparisonGroup({ ...base, dataset_id: 'strict_area' }));
  assert.notEqual(comparisonGroup({ ...base, dataset_id: 'design_evaluation', evaluation_condition: { head_id: 'ixi002' } }), comparisonGroup({ ...base, dataset_id: 'design_evaluation' }));
});

void test('the pareto command ranks result files of one condition', () => {
  const directory = mkdtempSync(join(tmpdir(), 'eeg-pareto-'));
  try {
    const cli = fileURLToPath(new URL('./eeglayoutlab.mjs', import.meta.url));
    const run = (...args) => spawnSync(process.execPath, [cli, ...args], { encoding: 'utf8' });
    const design = name => ({ schema: 'eeg-electrode-design/1', coordinate_system: 'ernie_native_mm', unit: 'mm', name, xyz_mm: [], region_indices: [] });
    const evaluation = (name, field, localization, extra = {}) => ({ schema: 'eeglayoutlab-cli-run/1', service: 'design-evaluation',
      request: { action: 'evaluate', design: design(name), radius_mm: 6, seed: 42, ...extra },
      result: { nominal: { field_relative: field, sensitivity_tail: .8, localization_relative: localization, p90_mm: 10 } } });
    const files = Object.entries({ a: evaluation('a', .9, .5), b: evaluation('b', .8, .7), c: evaluation('c', .7, .4),
      search: { schema: 'eeglayoutlab-cli-run/1', service: 'radius-search', request: { region_count: 2, radius_mm: 30, mode: 'whole_surface' },
        result: { status: 'completed', metrics: { field_relative: .95, sensitivity_tail: .5, localization_relative: .6, p90_mm: 9 }, geometry: { union_area_cm2: 40 } } },
      spatial: evaluation('s', .99, .99, { noise_model: { kind: 'spatial', rho: .5, length_mm: 20 } }) })
      .map(([name, value]) => { const path = join(directory, name + '.json'); writeFileSync(path, JSON.stringify(value)); return path; });
    const out = join(directory, 'pareto.json');
    const ranked = run('pareto', ...files.slice(0, 4), '--objectives', 'field,localization', '--out', out);
    assert.equal(ranked.status, 0, ranked.stderr);
    const report = JSON.parse(readFileSync(out, 'utf8'));
    assert.equal(report.schema, 'eeglayoutlab-cli-pareto/1');
    assert.deepEqual(report.rows.map(row => [row.name, row.rank]), [['search 2 regions, 30 mm, whole_surface', 1], ['b', 1], ['a', 2], ['c', 3]]);
    assert.equal(run('pareto', ...files.slice(0, 4), '--objectives', 'field,area', '--out', out).status, 0);
    assert.deepEqual(JSON.parse(readFileSync(out, 'utf8')).excluded.map(item => item.missing), [['area'], ['area'], ['area']]);
    assert.match(run('pareto', files[0], files[4], '--out', out).stderr, /one condition/);
    assert.match(run('pareto', files[0], files[1], '--objectives', 'speed', '--out', out).stderr, /unknown objective/);
    assert.match(run('pareto', files[0], '--out', out).stderr, /at least two/);
  } finally { rmSync(directory, { recursive: true, force: true }); }
});
