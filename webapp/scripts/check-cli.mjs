import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { ERNIE_MNI_MAPPING } from '../lib/ernie-mni.ts';

// Commands that need no model data; evaluate, search and study run natively in examples/run-examples.mjs.
const cli = fileURLToPath(new URL('./eeglayoutlab.mjs', import.meta.url));
const run = (...args) => spawnSync(process.execPath, [cli, ...args], { encoding: 'utf8' });
const names = ERNIE_MNI_MAPPING.golden.standard64.names;

function inTemporary(body) {
  const directory = mkdtempSync(join(tmpdir(), 'eeg-cli-'));
  try { return body(directory); } finally { rmSync(directory, { recursive: true, force: true }); }
}

void test('design builds the same design from a name list, its BIDS export and a search run', () => inTemporary(directory => {
  const labels = join(directory, 'labels.tsv'), design = join(directory, 'design.json');
  writeFileSync(labels, 'name\tregion\n' + names.map((name, index) => `${name}\t${index % 2}`).join('\n') + '\n');
  assert.equal(run('design', labels, '--name', 'standard64', '--out', design).status, 0);
  const base = JSON.parse(readFileSync(design, 'utf8'));
  assert.equal(base.name, 'standard64');
  assert.deepEqual(base.xyz_mm, ERNIE_MNI_MAPPING.golden.standard64.xyz_mm.map((point, index) => base.xyz_mm[index]));
  assert.ok(base.xyz_mm.every((point, index) => Math.hypot(...point.map((value, axis) => value - ERNIE_MNI_MAPPING.golden.standard64.xyz_mm[index][axis])) < 1e-9));

  assert.equal(run('export', design, '--format', 'bids', '--out-dir', join(directory, 'bids')).status, 0);
  const bids = ['electrodes.tsv', 'coordsystem.json', 'electrodes.json'].map(name => join(directory, 'bids', name));
  assert.equal(run('design', ...bids, '--out', join(directory, 'from-bids.json')).status, 0);
  const fromBids = JSON.parse(readFileSync(join(directory, 'from-bids.json'), 'utf8'));
  assert.deepEqual([fromBids.xyz_mm, fromBids.region_indices, fromBids.electrode_names], [base.xyz_mm, base.region_indices, base.electrode_names]);

  const search = join(directory, 'search.result.json');
  writeFileSync(search, JSON.stringify({ schema: 'eeglayoutlab-cli-run/1', service: 'radius-search', request: { region_count: 2, radius_mm: 30, mode: 'whole_surface' },
    result: { status: 'completed', layout: { xyzMm: base.xyz_mm, regionIndices: base.region_indices } } }));
  assert.equal(run('design', search, '--out', join(directory, 'from-search.json')).status, 0);
  const fromSearch = JSON.parse(readFileSync(join(directory, 'from-search.json'), 'utf8'));
  assert.equal(fromSearch.name, 'search 2 regions, 30 mm, whole_surface');
  assert.deepEqual(fromSearch.xyz_mm, base.xyz_mm);
}));

void test('export writes MNE, EEGLAB and SVG files and hides crowded names unless asked', () => inTemporary(directory => {
  const labels = join(directory, 'labels.tsv'), design = join(directory, 'design.json');
  writeFileSync(labels, 'name\tregion\n' + names.map(name => `${name}\t0`).join('\n') + '\n');
  run('design', labels, '--out', design);
  for (const [format, file] of [['mne', 'electrodes.elc'], ['eeglab', 'electrodes.sfp'], ['svg', 'layout.svg']]) {
    assert.equal(run('export', design, '--format', format, '--out-dir', directory).status, 0, format);
    assert.ok(readFileSync(join(directory, file), 'utf8').length > 1000, file);
  }
  assert.match(readFileSync(join(directory, 'layout.svg'), 'utf8'), />Cz<\/text>/, 'standard64 names have room');
  const crowded = JSON.parse(readFileSync(design, 'utf8'));
  crowded.xyz_mm = crowded.xyz_mm.map((_, index) => [-40 + 5 * (index % 8), 20 + 5 * Math.floor(index / 8), 80]);
  writeFileSync(design, JSON.stringify(crowded));
  run('export', design, '--format', 'svg', '--out-dir', directory);
  assert.doesNotMatch(readFileSync(join(directory, 'layout.svg'), 'utf8'), />Cz<\/text>/);
  run('export', design, '--format', 'svg', '--labels', 'yes', '--out-dir', directory);
  assert.match(readFileSync(join(directory, 'layout.svg'), 'utf8'), />Cz<\/text>/);
}));

void test('design reads .elc and .sfp montages and assigns regions on request', () => inTemporary(directory => {
  const labels = join(directory, 'labels.tsv'), design = join(directory, 'design.json');
  writeFileSync(labels, 'name\tregion\n' + names.map(name => `${name}\t0`).join('\n') + '\n');
  run('design', labels, '--out', design);
  run('export', design, '--format', 'mne', '--out-dir', directory);
  run('export', design, '--format', 'eeglab', '--out-dir', directory);
  const base = JSON.parse(readFileSync(design, 'utf8'));
  const elc = join(directory, 'electrodes.elc'), sfp = join(directory, 'electrodes.sfp'), out = join(directory, 'montage.json');
  assert.match(run('design', elc, '--out', out).stderr, /region/);
  assert.match(run('design', sfp, '--regions', '4', '--out', out).stderr, /单位/);
  assert.match(run('design', elc, '--regions', '5', '--out', out).stderr, /--regions must be/);
  for (const args of [[elc, '--regions', '4'], [sfp, '--regions', '4', '--unit', 'mm']]) {
    assert.equal(run('design', ...args, '--out', out).status, 0, args[0]);
    const montage = JSON.parse(readFileSync(out, 'utf8'));
    assert.deepEqual([montage.xyz_mm, montage.electrode_names], [base.xyz_mm, base.electrode_names]);
    assert.deepEqual(montage.source_metadata.region_assignment, { method: 'balanced-spatial/1', region_count: 4 });
    assert.deepEqual([0, 1, 2, 3].map(region => montage.region_indices.filter(value => value === region).length), [16, 16, 16, 16]);
  }
}));

void test('the command line rejects incomplete commands before starting a calculation', () => {
  assert.equal(run('help').status, 0);
  assert.match(run('help').stdout, /evaluate --design/);
  for (const args of [['evaluate', 'request.json'], ['search'], ['study', 'a.json', 'b.json', '--out-dir', 'x'], ['unknown', '--out-dir', 'x'], ['export', 'd.json', '--out-dir', 'x'], ['design', 'x.tsv']]) {
    const result = run(...args);
    assert.equal(result.status, 2, args.join(' '));
    assert.match(result.stderr, /^error: /);
  }
});
