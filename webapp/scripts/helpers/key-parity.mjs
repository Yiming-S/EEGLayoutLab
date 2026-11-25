/** The comparisons of check-key-parity-live.mjs, kept apart so that check-key-parity.mjs tests them offline. */
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { isDeepStrictEqual } from 'node:util';

/** The kinds of request key that the comparison must reach, each with at least one key compared on both hosts. */
export const KINDS = ['radius search', 'coordinate evaluation', 'electrode editor', 'signal reception v1', 'signal reception v2'];

/** Record trees whose stored requests are looked up again: tree, the lookup kind, the coverage kind. The radius
 * search's records are the library's cache rows. */
export const STORED_TREES = [
  ['design_evaluation_jobs', 'design-evaluation', 'coordinate evaluation'],
  ['electrode_editor_jobs', 'electrode-editor', 'electrode editor'],
  ['source_reception_jobs', 'source-reception', 'signal reception v1'],
  ['source_reception_v2_jobs', 'source-reception', 'signal reception v2'],
];

const HASH = /^[a-f0-9]{64}$/;
const byText = (a, b) => (a < b ? -1 : a > b ? 1 : 0);

/** What a lookup answer says about identity; a pending task counts as a hit on both hosts. */
export const summary = ({ status, value }) => status === 200
  ? { status, hit: value?.hit === true, ...value?.hit === true ? { key: value.job?.key, request: value.job?.request, job_status: value.job?.status } : {} }
  : { status, error: value?.error, ...value?.code === undefined ? {} : { code: value.code } };

/** Where two answers to one lookup disagree. */
export function differences(a, b) {
  const found = [];
  if (a.status !== b.status) found.push('status');
  else if (a.status === 200) {
    if (a.hit !== b.hit) found.push('hit');
    else if (a.hit) {
      if (a.key !== b.key) found.push('job.key');
      if (!isDeepStrictEqual(a.request, b.request)) found.push('job.request');
      else if (JSON.stringify(a.request) !== JSON.stringify(b.request)) found.push('job.request member order');
    }
  } else if (a.error !== b.error) found.push('error');
  return found;
}

/**
 * The outcome of one lookup on both hosts: `mismatch` (they disagree, or Python's key or request is not the stored
 * record's); `compared` (both hit with the same key and request: the only outcome that shows key equality);
 * `refused` (both refuse with the same message); `not_compared` (both miss: a miss carries no key, so nothing was
 * compared). `stored` names the record the request was read from: Python's hit must carry its key, and its request
 * when given.
 * @param {ReturnType<typeof summary>} python
 * @param {ReturnType<typeof summary>} node
 * @param {{ key: string, request?: unknown }} [stored]
 */
export function outcome(python, node, stored) {
  const found = differences(python, node);
  if (stored && python.status === 200 && python.hit) {
    if ('request' in stored && !isDeepStrictEqual(python.request, stored.request)) found.unshift('python request');
    if (python.key !== stored.key) found.unshift('python key');
  }
  if (found.length) return { outcome: 'mismatch', differences: found };
  if (python.status !== 200) return { outcome: 'refused', differences: [] };
  return { outcome: python.hit ? 'compared' : 'not_compared', differences: [] };
}

/** Compared keys per kind; the kinds with none, which the run could not check. */
export function coverage(results) {
  const counts = Object.fromEntries(KINDS.map(kind => [kind, 0]));
  for (const item of results) if (item.outcome === 'compared') counts[item.coverage]++;
  return { compared: counts, missing: KINDS.filter(kind => !counts[kind]) };
}

/** The coverage kind of a lookup: v2 reception requests name a mode. */
export function coverageKind(kind, body) {
  if (kind === 'local-compute') return 'radius search';
  if (kind === 'design-evaluation') return 'coordinate evaluation';
  if (kind === 'electrode-editor') return 'electrode editor';
  return body?.mode === undefined ? 'signal reception v1' : 'signal reception v2';
}

/**
 * Both hosts serve one root, so their libraries hold the same rows with the same members, Node's per-visitor
 * `visibility` view aside (the service has none, R6). A row whose `compatible` flag differs would leave the
 * cache-row check of one host, so every member is compared.
 */
export function libraryDifferences(pythonRows, nodeRows) {
  const byId = rows => new Map(rows.map(row => [row.id, row]));
  const python = byId(pythonRows), node = byId(nodeRows);
  const plain = ({ visibility: _visibility, ...row }) => row;
  const differing = [];
  for (const [id, row] of python) {
    const other = node.get(id);
    if (!other) continue;
    const a = plain(row), b = plain(other);
    const members = [...new Set([...Object.keys(a), ...Object.keys(b)])]
      .filter(name => !isDeepStrictEqual(a[name], b[name])).sort(byText);
    if (members.length) differing.push({ id, members });
  }
  return {
    only_python: [...python.keys()].filter(id => !node.has(id)).sort(byText),
    only_node: [...node.keys()].filter(id => !python.has(id)).sort(byText),
    differing,
  };
}

/**
 * The stored requests of the root's completed records (`R/results/v2/<tree>/<key>/cache.json` beside
 * `<key>/<job>/request.json`), read only. Each is looked up again: a record of the current identity must hit on both
 * hosts with its own key; one of an older identity misses on both and is not compared.
 * @param {string} root
 * @returns {{ name: string, kind: string, coverage: string, body: unknown, stored: { key: string, request: unknown } }[]}
 */
export function storedRequests(root) {
  const found = [];
  for (const [tree, kind, kindCoverage] of STORED_TREES) {
    const directory = join(root, 'results', 'v2', tree);
    if (!existsSync(directory)) continue;
    for (const key of readdirSync(directory).filter(name => HASH.test(name)).sort(byText)) {
      if (!existsSync(join(directory, key, 'cache.json'))) continue;
      const jobs = readdirSync(join(directory, key), { withFileTypes: true })
        .filter(entry => entry.isDirectory() && existsSync(join(directory, key, entry.name, 'request.json'))).map(entry => entry.name).sort(byText);
      if (!jobs.length) continue;
      let request;
      try { request = JSON.parse(readFileSync(join(directory, key, jobs[0], 'request.json'), 'utf8')).request; } catch { continue; }
      if (request === null || typeof request !== 'object') continue;
      found.push({ name: `stored ${tree} ${key.slice(0, 12)}`, kind, coverage: kindCoverage, body: request, stored: { key, request } });
    }
  }
  return found;
}
