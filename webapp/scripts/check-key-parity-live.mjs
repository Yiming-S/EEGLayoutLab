/** Lookup-only key parity of the legacy Node host and the Python service on one root; never submits a job. */
import assert from 'node:assert/strict';
import { readFileSync, realpathSync } from 'node:fs';
import { writeFile } from 'node:fs/promises';
import { isAbsolute, resolve } from 'node:path';
import { exportDesign } from '../lib/design-decision.ts';
import { assertCacheOnly, scriptServer } from './helpers/service-session.mjs';
import { coverage, coverageKind, libraryDifferences, outcome, storedRequests, summary } from './helpers/key-parity.mjs';

// Both hosts serve the same root R and run cache-only, so a lookup can never become a calculation:
// - the Python service (eeglayoutlab serve <W> --root R --cache-only): EEG_SERVICE_RUNTIME (its
//   <W>/.eeglayoutlab/runtime.json), or EEG_SERVICE_TOKEN with EEG_TEST_URL;
// - the legacy Node host (EEG_REPOSITORY_ROOT=R EEG_QUEUE_DIRECTORY=<a temporary directory> EEG_MAINTENANCE=1
//   node server/start.mjs): --node <url> or EEG_NODE_URL.
// R is --root, else EEG_REPOSITORY_ROOT, else the root in the service's runtime.json; the script only reads it.
// Three sets of lookups go to both hosts; their status, hit, job.key and job.request must agree (a refusal: its
// message):
// - a fixed set (radius search, coordinate evaluation with each scientific option, editor preparation, signal
//   reception v1 and v2), which mostly checks refusals alike: a miss carries no key, so a lookup that misses on
//   both hosts compares nothing and is reported as not compared;
// - the stored request of every completed coordinate evaluation, electrode edit and signal simulation under
//   R/results/v2: a record of the current identity hits on both with its own key and request, one of an older
//   identity misses on both (not compared);
// - every radius-search cache row of the library that the current code can reuse (compatible): it must hit with its
//   own id on both; a row of an older identity is only reported.
// Both libraries must hold the same rows with the same members. Each kind of request key (radius search,
// coordinate evaluation, electrode editor, signal reception v1 and v2) must have at least one key compared, or the
// run fails as incomplete; compute one request of a missing kind on R, or pass --allow-incomplete to accept a
// partial comparison.
// The report is printed, and written to EEG_QA_OUTPUT (an absolute file path) when set. Exit 1 on any mismatch, or
// when incomplete.
const args = process.argv.slice(2);
let nodeUrl = process.env.EEG_NODE_URL, rootOption, allowIncomplete = false;
for (let index = 0; index < args.length; index++) {
  const [flag, value] = args[index].split(/=(.*)/s, 2);
  if (flag === '--allow-incomplete' && value === undefined) { allowIncomplete = true; continue; }
  if (flag !== '--node' && flag !== '--root') throw new Error(`Unknown argument ${JSON.stringify(args[index])}; use --node <url>, --root <R> or --allow-incomplete.`);
  if (flag === '--node') nodeUrl = value ?? args[++index];
  else rootOption = value ?? args[++index];
}
const output = process.env.EEG_QA_OUTPUT;
if (output !== undefined && !isAbsolute(output)) throw new Error('EEG_QA_OUTPUT must be an absolute file path.');
let node;
try { node = new URL(nodeUrl ?? ''); } catch { node = undefined; }
if (!node || node.protocol !== 'http:' || !['127.0.0.1', 'localhost'].includes(node.hostname) || node.username || node.password
  || node.pathname !== '/' || node.search || node.hash) {
  throw new Error(`Name the legacy Node host with --node or EEG_NODE_URL as http://127.0.0.1:<port>, not ${JSON.stringify(nodeUrl)}.`);
}
const { service } = await scriptServer({ node: false });
assert.notEqual(node.origin, service.base, 'The Node host and the Python service must be two servers.');
let served;
try { served = JSON.parse(readFileSync(process.env.EEG_SERVICE_RUNTIME ?? '', 'utf8')).root; } catch { served = undefined; }
const rootPath = rootOption ?? process.env.EEG_REPOSITORY_ROOT ?? served;
if (!rootPath) throw new Error('Name the root both hosts serve with --root or EEG_REPOSITORY_ROOT.');
const root = realpathSync(resolve(rootPath));
if (typeof served === 'string' && realpathSync(served) !== root) throw new Error(`The service serves ${served}, not ${root}.`);

// One client per host. Node knows a browser by the visitor cookie it issues and allows a visitor 20 lookups and an
// address 100 a minute, so its client starts a new visitor every 15 and waits out a 429 once; the Python service
// knows its session cookie.
function client(base, session) {
  let visitor = '', token = session?.csrf, used = 0;
  async function call(path, body) {
    const headers = new Headers(body === undefined ? {} : { 'Content-Type': 'application/json' });
    const cookie = [session?.cookie, visitor].filter(Boolean).join('; ');
    if (cookie) headers.set('Cookie', cookie);
    if (body !== undefined) headers.set('X-EEG-Compute-Token', token);
    const response = await fetch(base + path, { method: body === undefined ? 'GET' : 'POST', headers,
      body: body === undefined ? undefined : JSON.stringify(body) });
    const issued = response.headers.getSetCookie().map(line => line.split(';', 1)[0]).find(pair => pair.startsWith('eeg_visitor='));
    if (issued) visitor = issued;
    const text = await response.text();
    let value;
    try { value = JSON.parse(text); } catch { value = { error: text.slice(0, 200) }; }
    return { status: response.status, value };
  }
  return {
    base,
    async get(path) {
      const { status, value } = await call(path);
      assert.equal(status, 200, `GET ${base}${path}: ${status} ${value?.error ?? ''}`);
      return value;
    },
    async health() {
      const value = await this.get('/api/local-compute/health');
      if (!session) token = value.token;
      return value;
    },
    async lookup(kind, body) {
      if (session) return call(`/api/${kind}/lookup`, body);
      if (++used > 15) { visitor = ''; used = 1; await this.health(); }
      const answer = await call(`/api/${kind}/lookup`, body);
      if (answer.status !== 429) return answer;
      await new Promise(resolve => setTimeout(resolve, 61000));
      visitor = ''; used = 1; await this.health();
      return call(`/api/${kind}/lookup`, body);
    },
  };
}
const python = client(service.base, service), legacy = client(node.origin, null);
for (const { name, host } of [{ name: 'Python service', host: python }, { name: 'Node host', host: legacy }]) {
  try { assertCacheOnly(await host.health()); }
  catch (error) { throw new Error(`${name} at ${host.base}: ${error.message} (Node: EEG_MAINTENANCE=1)`); }
}

// Both hosts list the same library: they serve one root.
const [library, nodeLibrary] = [await python.get('/api/local-compute/library'), await legacy.get('/api/local-compute/library')];
const libraryDifference = libraryDifferences(library.records, nodeLibrary.records);
for (const { id, members } of libraryDifference.differing) console.log(`MISMATCH  library row ${id} (${members.join(', ')})`);

const HASH = /^[a-f0-9]{64}$/;
const layouts = library.records.filter(row => row.status === 'completed' && HASH.test(row.id));
assert.ok(layouts.length, 'The Python library lists no completed layout.');
// The coordinate evaluations use the live script's saved strict-area layout when the root has it, else the first
// completed layout whose record carries one; the signal experiments use the reception script's 32+32 layout.
const designRow = layouts.find(row => row.dataset_id === 'strict_area' && row.area_cap_cm2 === 60 && row.region_count === 2
  && String(row.mode).includes('whole')) ?? layouts[0];
let design;
for (const row of [designRow, ...layouts.filter(other => other !== designRow)]) {
  const { record } = await python.get('/api/local-compute/library/' + row.id);
  try {
    // A plain evaluation names no electrodes; a library record without its annotation carries none.
    const { electrode_names: _names, source_metadata: _source, ...plain } = exportDesign(record);
    design = { row: row.id, value: plain }; break;
  } catch { /* the next layout */ }
}
assert.ok(design, 'No library layout exports a coordinate design.');
const signalRow = layouts.find(row => row.dataset_id === 'cache' && row.request?.region_count === 2 && row.request.radius_mm === 35
  && JSON.stringify(row.request.mask_codes) === JSON.stringify(['AL', 'AR'])) ?? designRow;
const { heads = [] } = await python.get('/api/design-evaluation/heads');
const { records: parents = [] } = await python.get('/api/electrode-editor/parents');

const evaluation = { action: 'evaluate', design: design.value, radius_mm: 6, seed: 42 };
const signal = { record_id: signalRow.id, waveform: 'burst', artifact_scale: 1, seed: 2026 };
/** @type {[name: string, kind: string, body: object][]} */
const cases = [
  ['radius search, free regions', 'local-compute', { region_count: 2, radius_mm: 35, mode: 'whole_surface' }],
  ['radius search, preset masks', 'local-compute', { region_count: 2, radius_mm: 35, mode: 'preset', mask_codes: ['AL', 'AR'] }],
  ['coordinate evaluation', 'design-evaluation', evaluation],
  ['coordinate evaluation, iid noise', 'design-evaluation', { ...evaluation, noise_model: { kind: 'iid' } }],
  ['coordinate evaluation, spatial noise', 'design-evaluation', { ...evaluation, noise_model: { kind: 'spatial', rho: 0.5, length_mm: 20 } }],
  ['coordinate evaluation, brain background', 'design-evaluation', { ...evaluation, noise_model: { kind: 'brain_background', fraction: 0.5 } }],
  ['coordinate evaluation, skull x0.5', 'design-evaluation', { ...evaluation, conductivity_scenario: 'skull_x0.5' }],
  ['coordinate evaluation, skull x2', 'design-evaluation', { ...evaluation, conductivity_scenario: 'skull_x2' }],
  // Without an installed head both hosts must refuse it alike.
  ['coordinate evaluation, other head', 'design-evaluation', { ...evaluation, head_id: heads[0]?.head_id ?? 'qa-missing-head' }],
  ['coordinate evaluation, robustness', 'design-evaluation', { ...evaluation, robustness: 'standard/1' }],
  ['coordinate evaluation, data prior', 'design-evaluation', { ...evaluation, data_prior: { region_gain: [1.5, 1, 1, 1, 1, 1, 1], rho: 0.3, length_mm: 20 } }],
  ['coordinate perturbation', 'design-evaluation', { ...evaluation, action: 'perturb' }],
  ['coordinate perturbation, spatial noise', 'design-evaluation', { ...evaluation, action: 'perturb', noise_model: { kind: 'spatial', rho: 0.5, length_mm: 20 } }],
  ...parents.length ? [['electrode editor preparation', 'electrode-editor', { action: 'prepare', parent_id: parents[0].id }]] : [],
  ['signal reception v1', 'source-reception', { ...signal, brain_region: 'frontal' }],
  ['signal reception v2, single source', 'source-reception', { ...signal, mode: 'single_source', source_index: 2 }],
  ['signal reception v2, multiple sources', 'source-reception', { ...signal, mode: 'multi_source', brain_region: 'frontal' }],
  ['signal reception v2, cross region', 'source-reception', { ...signal, mode: 'cross_region', brain_regions: ['frontal', 'occipital'] }],
];

// The fixed lookups, then the root's stored requests.
const lookups = [], storedLookups = [];
const label = { compared: 'same', refused: 'refused alike', not_compared: 'not compared (miss on both)', mismatch: 'MISMATCH' };
async function compareLookup(list, name, kind, body, kindCoverage, stored) {
  const answers = { python: summary(await python.lookup(kind, body)), node: summary(await legacy.lookup(kind, body)) };
  const result = outcome(answers.python, answers.node, stored);
  list.push({ name, kind, coverage: kindCoverage, ...result, ...answers, body });
  console.log(`${label[result.outcome]}  ${name}: ${answers.python.status} ${answers.python.hit ?? answers.python.error}`
    + (result.differences.length ? `  (${result.differences.join(', ')})` : answers.python.hit ? `  ${answers.python.key}` : ''));
}
for (const [name, kind, body] of cases) await compareLookup(lookups, name, kind, body, coverageKind(kind, body));
const stored = storedRequests(root);
for (const item of stored) await compareLookup(storedLookups, item.name, item.kind, item.body, item.coverage, item.stored);

// Every reusable stored radius search is found again by its own request, under the key the library names it by,
// and Node finds the same; a row the current code cannot reuse (compatible: false) misses by design.
const cacheRows = [];
for (const row of library.records.filter(item => item.dataset_id === 'cache' && item.request && HASH.test(item.id))) {
  const answer = summary(await python.lookup('local-compute', row.request));
  if (row.compatible !== true) { cacheRows.push({ id: row.id, status: row.status, coverage: 'radius search', outcome: 'incompatible', python: answer }); continue; }
  const nodeAnswer = summary(await legacy.lookup('local-compute', row.request));
  const result = outcome(answer, nodeAnswer, { key: row.id });
  // A compatible row must hit: a miss on both is a mismatch here, not a lookup left uncompared.
  if (result.outcome !== 'compared') { result.outcome = 'mismatch'; if (!result.differences.length) result.differences.push('python key'); }
  cacheRows.push({ id: row.id, status: row.status, coverage: 'radius search', ...result, ...result.outcome === 'mismatch' ? { python: answer, node: nodeAnswer } : {} });
  if (result.outcome === 'mismatch') console.log(`MISMATCH  library cache row ${row.id} (${result.differences.join(', ')}): ${JSON.stringify({ python: answer, node: nodeAnswer })}`);
}
const checkedRows = cacheRows.filter(item => item.outcome !== 'incompatible');
const covered = coverage([...lookups, ...storedLookups, ...checkedRows]);
for (const kind of covered.missing) console.log(`NOT COMPARED  ${kind}: no lookup hit on both hosts; compute one such request on ${root} and run again`);

const mismatches = [...lookups, ...storedLookups, ...checkedRows].filter(item => item.outcome === 'mismatch').length
  + libraryDifference.only_python.length + libraryDifference.only_node.length + libraryDifference.differing.length;
const count = (list, value) => list.filter(item => item.outcome === value).length;
const report = {
  passed: mismatches === 0 && (allowIncomplete || !covered.missing.length), complete: !covered.missing.length,
  finished_at: new Date().toISOString(), python: service.base, node: node.origin, root,
  totals: { lookups: lookups.length, lookups_compared: count(lookups, 'compared'), lookups_refused_alike: count(lookups, 'refused'),
    lookups_not_compared: count(lookups, 'not_compared'), lookup_mismatches: count(lookups, 'mismatch'),
    stored_requests: storedLookups.length, stored_compared: count(storedLookups, 'compared'), stored_refused_alike: count(storedLookups, 'refused'),
    stored_not_compared: count(storedLookups, 'not_compared'), stored_mismatches: count(storedLookups, 'mismatch'),
    cache_rows: checkedRows.length, cache_row_mismatches: count(checkedRows, 'mismatch'), incompatible_cache_rows: cacheRows.length - checkedRows.length },
  keys_compared: covered.compared, not_compared_kinds: covered.missing,
  inputs: { design_record: design.row, signal_record: signalRow.id, head: heads[0]?.head_id ?? null, editor_parent: parents[0]?.id ?? null },
  library: { python_rows: library.records.length, node_rows: nodeLibrary.records.length, ...libraryDifference },
  lookups, stored_lookups: storedLookups, cache_rows: cacheRows,
  scope: 'Lookups only (POST /api/<kind>/lookup) on two cache-only hosts; no job was submitted. Only a lookup that hits on both hosts compares a key.',
};
if (output) await writeFile(output, JSON.stringify(report, null, 2) + '\n', { mode: 0o600 });
console.log(JSON.stringify({ passed: report.passed, complete: report.complete, mismatches, ...report.totals, keys_compared: covered.compared,
  library: libraryDifference.only_python.length + libraryDifference.only_node.length + libraryDifference.differing.length ? libraryDifference : 'same',
  ...output ? { output } : {} }));
if (!report.passed) process.exitCode = 1;
