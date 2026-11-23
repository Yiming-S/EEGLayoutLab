#!/usr/bin/env node
// Writes the data of the read-only showcase (showcase/api) from a running host.
//
//   node scripts/build-showcase-data.mjs --from http://127.0.0.1:3331 [--out showcase/api]
//
// The host is the maintainer's installation (the Node host, or the Python service with a session).
// Only GET requests are sent. The records published are listed in showcase/curation.json: whole
// datasets plus single records, and, per record, whether its experiment bundle is included. The
// catalogs that list layouts (editor parents, reception layouts) are filtered to the same records,
// so every entry the showcase lists can be opened. Paths under a home directory are written as
// '~/…', and the script fails if any other local path remains.
import { mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { parseArgs } from 'node:util';

export const SHOWCASE_DATA_SCHEMA = 'eeglayoutlab-showcase-data/1';
const webapp = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const HOME_PATH = /(?:\/Users|\/home)\/[^/"\s]+(?=\/)/g;
const LOCAL_PATH = /\/Users\/|\/home\/|\/private\/var\/|\/var\/folders\//;

/** Replaces home-directory prefixes in every string; returns the value and the number replaced. */
export function redactHomePaths(value) {
  let count = 0;
  const walk = (item) => {
    if (typeof item === 'string') return item.replace(HOME_PATH, () => { count += 1; return '~'; });
    if (Array.isArray(item)) return item.map(walk);
    if (item && typeof item === 'object') return Object.fromEntries(Object.entries(item).map(([key, entry]) => [key, walk(entry)]));
    return item;
  };
  return { value: walk(value), count };
}

/** A host's health with its session token removed and computation marked unavailable. */
export function showcaseHealth(health) {
  return { ...health, available: false, showcase: true, token: 'showcase-read-only', active_job: null, max_concurrent_jobs: 0, maintenance: false, drained: false };
}

/** The library list restricted to the curated records, without per-visitor fields. */
export function curateLibrary(library, curation) {
  const datasets = new Set(curation.library.datasets);
  const singles = new Map(curation.library.records.map((entry) => [entry.id, entry]));
  const records = library.records
    .filter((record) => datasets.has(record.dataset_id) || singles.has(record.id))
    .map(({ visibility: _visibility, ...record }) => record);
  for (const entry of singles.values()) {
    const record = records.find((row) => row.id === entry.id);
    if (!record) throw new Error(`Curated record ${entry.id} (${entry.label}) is not in the host's library`);
    if (entry.label && record.label !== entry.label) throw new Error(`Curated record ${entry.id} is labelled "${record.label}", not "${entry.label}"`);
  }
  const counts = new Map();
  for (const record of records) counts.set(record.dataset_id, (counts.get(record.dataset_id) ?? 0) + 1);
  const { library_scope: _scope, ...rest } = library;
  return {
    ...rest,
    records,
    warnings: [],
    electrode_annotations: [],
    datasets: (library.datasets ?? []).filter((dataset) => counts.has(dataset.id)).map((dataset) => ({ ...dataset, count: counts.get(dataset.id) })),
  };
}

async function main() {
  const { values } = parseArgs({ options: { from: { type: 'string' }, out: { type: 'string', default: 'showcase/api' }, curation: { type: 'string', default: 'showcase/curation.json' } } });
  if (!values.from) throw new Error('--from <origin of a running host> is required');
  const origin = new URL(values.from).origin;
  const out = resolve(webapp, values.out);
  const curation = JSON.parse(await readFile(resolve(webapp, values.curation), 'utf8'));
  if (curation.schema !== 'eeglayoutlab-showcase-curation/1') throw new Error('Unknown curation schema');

  const get = async (path) => {
    const response = await fetch(origin + path, { headers: { Accept: 'application/json' } });
    if (!response.ok) throw new Error(`GET ${path}: ${response.status} ${await response.text()}`);
    return response.json();
  };
  const files = new Map();
  let redacted = 0;
  const put = (path, body) => {
    const { value, count } = redactHomePaths(body);
    const text = JSON.stringify(value);
    if (LOCAL_PATH.test(text)) throw new Error(`${path} still contains a local path after redaction`);
    redacted += count;
    files.set(path, text);
  };

  const library = curateLibrary(await get('/api/local-compute/library'), curation);
  const published = new Set(library.records.map((record) => record.id));
  put('/api/local-compute/library', library);
  for (const record of library.records) {
    put(`/api/local-compute/library/${record.id}`, await get(`/api/local-compute/library/${record.id}`));
    if (curation.library.records.some((entry) => entry.id === record.id && entry.bundle))
      put(`/api/local-compute/library/${record.id}/bundle`, await get(`/api/local-compute/library/${record.id}/bundle`));
  }
  const onlyPublished = (body) => ({ ...body, records: body.records.filter((record) => published.has(record.id)) });
  put('/api/electrode-editor/parents', onlyPublished(await get('/api/electrode-editor/parents')));
  put('/api/electrode-editor/records', { records: [] });
  put('/api/source-reception/layouts', onlyPublished(await get('/api/source-reception/layouts')));
  put('/api/source-reception/catalog', await get('/api/source-reception/catalog'));
  put('/api/design-evaluation/heads', { heads: [] });
  // Health answers as a service that cannot compute: pages stay browsable, and a calculation request
  // reaches the showcase's refusal instead of a connection error.
  for (const kind of ['local-compute', 'design-evaluation', 'electrode-editor', 'source-reception'])
    put(`/api/${kind}/health`, showcaseHealth(await get(`/api/${kind}/health`)));
  put('/api/community/records', { schema: 'browser-experiment-records/1', scope: 'current_browser', receipt_limit: 0, records: [] });
  put('/api/robustness-studies', { studies: [] });

  await rm(out, { recursive: true, force: true });
  for (const [path, text] of files) {
    const file = join(out, path.slice('/api/'.length) + '.json');
    await mkdir(dirname(file), { recursive: true });
    await writeFile(file, text + '\n');
  }
  const paths = [...files.keys()].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
  await writeFile(join(out, 'index.json'), JSON.stringify({ schema: SHOWCASE_DATA_SCHEMA, records: library.records.length, paths }, null, 2) + '\n');
  const bytes = [...files.values()].reduce((sum, text) => sum + Buffer.byteLength(text), 0);
  console.log(`showcase data: ${paths.length} files, ${library.records.length} records, ${(bytes / 1024).toFixed(0)} KiB, ${redacted} home path(s) written as ~`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((error) => { console.error(error.message); process.exitCode = 1; });
}
