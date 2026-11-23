#!/usr/bin/env node
/**
 * Runs the three examples through the command line and compares their scores with expected.json.
 *
 *   node examples/run-examples.mjs [--root DIR] [--out-dir DIR] [--skip-cross-head] [--update-expected]
 *
 * Example 3 needs the cross-head packages under results/v2/heads/. Without them the run fails and names the
 * missing packages; --skip-cross-head runs examples 1 and 2 only and says that example 3 was not compared.
 */
import { spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url)), repository = resolve(here, '..');
const cli = join(repository, 'webapp/scripts/eeglayoutlab.mjs');
const args = process.argv.slice(2), option = name => { const at = args.indexOf(name); return at < 0 ? undefined : args[at + 1]; };
const update = args.includes('--update-expected'), skipCrossHead = args.includes('--skip-cross-head');
const root = resolve(option('--root') ?? process.env.EEG_REPOSITORY_ROOT ?? repository);
const out = resolve(option('--out-dir') ?? join(here, 'outputs'));
const TOLERANCE = 1e-6;

const readJson = path => JSON.parse(readFileSync(path, 'utf8'));
function run(...parameters) {
  const command = parameters[0] === 'design' || parameters[0] === 'export' ? parameters : [...parameters, '--root', root];
  console.log(`$ node webapp/scripts/eeglayoutlab.mjs ${command.join(' ')}`);
  const result = spawnSync(process.execPath, [cli, ...command], { stdio: ['ignore', 'inherit', 'inherit'] });
  if (result.status !== 0) throw new Error(`command failed: ${command[0]}`);
}
const pick = (value, keys) => Object.fromEntries(keys.map(key => [key, value[key]]));
const evaluationScores = path => pick(readJson(path).result.nominal, ['field_relative', 'sensitivity_tail', 'localization_relative', 'median_mm', 'p90_mm']);

const scores = {}, ex = name => join(out, name);

// 1. The standard 64-electrode reference from its 10-05 names: files for other tools and its own scores.
run('design', join(here, '01-standard64/standard64-labels.tsv'), '--name', 'standard64', '--out', join(ex('01-standard64'), 'design.json'));
for (const format of ['bids', 'mne', 'eeglab', 'svg']) run('export', join(ex('01-standard64'), 'design.json'), '--format', format, '--out-dir', join(ex('01-standard64'), 'files'));
run('evaluate', '--design', join(ex('01-standard64'), 'design.json'), '--radius', '6', '--seed', '42', '--out-dir', ex('01-standard64'));
scores['01-standard64'] = evaluationScores(join(ex('01-standard64'), 'request.result.json'));

// 2. A compact two-region layout from a radius search, then evaluated as fixed coordinates.
run('search', join(here, '02-compact-search/search.json'), '--out-dir', ex('02-compact-search'));
const search = readJson(join(ex('02-compact-search'), 'search.result.json')).result;
run('design', join(ex('02-compact-search'), 'search.result.json'), '--name', 'compact 2 regions 30 mm', '--out', join(ex('02-compact-search'), 'design.json'));
run('export', join(ex('02-compact-search'), 'design.json'), '--format', 'svg', '--out-dir', join(ex('02-compact-search'), 'files'));
run('evaluate', '--design', join(ex('02-compact-search'), 'design.json'), '--radius', '6', '--seed', '42', '--out-dir', ex('02-compact-search'));
scores['02-compact-search'] = {
  search: { ...pick(search.metrics, ['field_relative', 'sensitivity_tail', 'localization_relative', 'conditional_global']),
    union_area_cm2: search.geometry.union_area_cm2 },
  evaluation: evaluationScores(join(ex('02-compact-search'), 'request.result.json')),
};

// 3. The same compact layout on eleven heads (one shared noise seed).
const heads = readJson(join(here, '03-cross-head/heads.json'));
const missing = heads.cases.map(entry => entry.head_id).filter(id => !existsSync(join(root, 'results/v2/heads', id, 'table.json')));
const notRun = {};
if (skipCrossHead) notRun['03-cross-head'] = 'skipped with --skip-cross-head';
else if (missing.length) notRun['03-cross-head'] = `head packages without a published table: ${missing.join(', ')}`;
if (notRun['03-cross-head']) console.log(`\nExample 3 not run: ${notRun['03-cross-head']}`);
else {
  const studyFile = join(ex('03-cross-head'), 'study-input.json');
  mkdirSync(ex('03-cross-head'), { recursive: true });
  writeFileSync(studyFile, JSON.stringify({ ...heads, design: readJson(join(ex('02-compact-search'), 'design.json')) }, null, 2) + '\n');
  run('study', studyFile, '--out-dir', ex('03-cross-head'));
  const aggregation = readJson(join(ex('03-cross-head'), 'study.json')).aggregation, group = aggregation.groups[0];
  scores['03-cross-head'] = { completed_cases: aggregation.completed_cases,
    field_relative: group.nominal.field_relative, localization_relative: group.nominal.localization_relative };
}

const expectedPath = join(here, 'expected.json');
if (update && Object.keys(notRun).length) {
  console.error(`\n--update-expected needs every example; not run: ${Object.keys(notRun).join(', ')}`);
  process.exitCode = 1;
} else if (update) {
  writeFileSync(expectedPath, JSON.stringify({ schema: 'eeglayoutlab-examples-expected/1', tolerance: TOLERANCE, scores }, null, 2) + '\n');
  console.log(`\nwrote ${expectedPath}`);
} else {
  const expected = readJson(expectedPath).scores, differences = [];
  const compare = (want, got, path) => {
    if (typeof want === 'number') { if (typeof got !== 'number' || Math.abs(want - got) > TOLERANCE) differences.push(`${path}: expected ${want}, got ${got}`); }
    else if (want && typeof want === 'object') for (const key of Object.keys(want)) compare(want[key], got?.[key], `${path}.${key}`);
  };
  const skipped = [];
  for (const name of Object.keys(expected)) {
    if (scores[name]) compare(expected[name], scores[name], name);
    else if (name in notRun && skipCrossHead) skipped.push(name);
    else differences.push(`${name}: not run (${notRun[name] ?? 'no scores'})`);
  }
  const compared = Object.keys(expected).length - skipped.length;
  console.log(differences.length ? `\n${differences.length} differences:\n${differences.join('\n')}`
    : `\nAll scores of ${compared} of ${Object.keys(expected).length} examples match expected.json within ${TOLERANCE}.` +
      (skipped.length ? ` Not compared: ${skipped.join(', ')}.` : ''));
  process.exitCode = differences.length ? 1 : 0;
}
