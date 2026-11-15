/** Read-only cache inspection. Invoked under the Python CLI's offline locks. */
import { constants } from 'node:fs';
import { lstat, open, readdir, readFile } from 'node:fs/promises';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { LocalComputeQueue, normalizeRequest } from '../webapp/server/local-compute-server.mjs';
import { SourceReceptionService } from '../webapp/server/source-reception-server.mjs';
import { DesignEvaluationService } from '../webapp/server/design-evaluation-server.mjs';
import { ElectrodeEditorService } from '../webapp/server/electrode-editor-server.mjs';
import { communityAdapters } from '../webapp/server/community-adapters.mjs';
import { receiptCatalog } from '../webapp/server/community-queue.mjs';
import { buildReconciliation, eligibleReceipt, jsonHash, textHash, validateQueue } from '../webapp/server/operations/reconciliation.mjs';

const SAME = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const LIMIT = 64 * 1024 * 1024;
export async function readStrictCache(root, path) {
  root = resolve(root); path = resolve(path);
  const suffix = relative(root, path);
  if (!suffix || suffix.startsWith('..') || suffix.startsWith('/')) throw new Error('Cache path leaves scientific root.');
  let current = root;
  for (const part of suffix.split('/')) {
    current = join(current, part);
    const info = await lstat(current);
    if (info.isSymbolicLink() || (current !== path && !info.isDirectory())) throw new Error('Cache path contains a link or invalid directory.');
  }
  const file = await open(path, constants.O_RDONLY | constants.O_NOFOLLOW);
  try {
    const before = await file.stat({ bigint: true });
    if (!before.isFile() || before.nlink !== 1n || before.size > BigInt(LIMIT)) throw new Error('Invalid cache file.');
    const bytes = await file.readFile();
    const after = await file.stat({ bigint: true });
    if (bytes.length > LIMIT || ['dev', 'ino', 'size', 'mtimeNs', 'ctimeNs'].some(key => before[key] !== after[key])) throw new Error('Cache changed while reading.');
    return { value: JSON.parse(bytes.toString('utf8')), sha256: textHash(bytes), bytes: bytes.length };
  } finally { await file.close(); }
}

export async function inspectReceipt(task, { adapters, cacheFile, sourceService, root }) {
  const adapter = adapters[task.kind];
  try {
    const prepared = await adapter.prepare(task.request);
    if (!SAME(prepared.request, task.request) || prepared.key !== task.key ||
        jsonHash({ request: prepared.request, identity: prepared.ctx.identity }) !== task.key) return { id: task.id, verdict: 'retained', reason: 'current_identity_or_request_changed' };
    const path = cacheFile(task, prepared), first = await readStrictCache(root, path), cache = first.value;
    if (cache.key !== task.key || cache.result_sha256 !== jsonHash(cache.result) ||
        (cache.identity !== undefined && !SAME(cache.identity, prepared.ctx.identity)) ||
        (cache.request !== undefined && !SAME(cache.request, prepared.request))) throw new Error('Cache request, identity or result checksum mismatch.');
    const found = await adapter.lookup(prepared);
    if (!found.hit || found.job.key !== task.key || !['completed', 'no_layout'].includes(found.job.status) ||
        !SAME(found.job.result, cache.result) || found.job.status !== cache.result.status || !Number.isFinite(Date.parse(cache.finished_at))) throw new Error('Full production cache validation did not confirm completion.');
    if (task.kind === 'source-reception' && !SAME(await sourceService.savedResult(task.key, prepared.request), cache.result)) throw new Error('Saved signal result does not reproduce its cache.');
    const latest = await adapter.prepare(task.request), second = await readStrictCache(root, path);
    if (latest.key !== prepared.key || !SAME(latest.request, prepared.request) || !SAME(latest.ctx.identity, prepared.ctx.identity) || second.sha256 !== first.sha256) throw new Error('Scientific identity or cache changed during inspection.');
    return { id: task.id, key: task.key, kind: task.kind, verdict: 'verified', request_sha256: jsonHash(prepared.request),
      identity_sha256: jsonHash(prepared.ctx.identity), cache_path: relative(root, path), cache_sha256: first.sha256,
      identity_evidence: cache.identity === undefined ? 'original_key_definition_and_production_validation' : 'stored_identity_and_original_key_definition',
      status: cache.result.status, finished_at: cache.finished_at, catalog: receiptCatalog(task.kind, prepared, cache.result) };
  } catch (error) {
    return { id: task.id, verdict: 'retained', reason: 'cache_missing_invalid_or_identity_changed', detail: String(error.message).slice(0, 600) };
  }
}

export async function sourceFingerprint(sourceRoot) {
  const files = [fileURLToPath(import.meta.url)];
  async function walk(directory) {
    for (const entry of await readdir(directory, { withFileTypes: true })) {
      const path = join(directory, entry.name);
      if (entry.isDirectory()) await walk(path);
      else if (entry.isFile() && entry.name.endsWith('.mjs')) files.push(path);
    }
  }
  await walk(join(sourceRoot, 'webapp/server'));
  await walk(join(sourceRoot, 'webapp/contracts'));
  const values = [];
  for (const path of files.sort((a, b) => a.localeCompare(b))) values.push([relative(sourceRoot, path), textHash(await readFile(path))]);
  return jsonHash(values);
}

export async function readInspectionInput(stream, limit = LIMIT) {
  const chunks = []; let size = 0;
  for await (const chunk of stream) {
    const bytes = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    size += bytes.length;
    if (size > limit) throw new Error('Queue inspection input is too large.');
    chunks.push(bytes);
  }
  return JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(Buffer.concat(chunks, size)));
}

export async function inspectService({ root, queue_directory, python, queue_json }) {
  const sourceRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
  const sourceBefore = await sourceFingerprint(sourceRoot);
  const state = validateQueue(JSON.parse(queue_json));
  let launches = 0;
  const forbidden = () => { launches++; throw new Error('Offline inspection cannot launch or submit scientific work.'); };
  const queue = new LocalComputeQueue({ repositoryRoot: root, queueDirectory: queue_directory, python, spawnProcess: forbidden });
  queue.sources = new SourceReceptionService(queue, { spawnProcess: forbidden });
  queue.designTests = new DesignEvaluationService(queue, { spawnProcess: forbidden });
  queue.editor = new ElectrodeEditorService(queue, { spawnProcess: forbidden });
  queue.executionSlot.pause();
  for (const service of [queue, queue.sources, queue.designTests, queue.editor]) service.submit = forbidden;
  const adapters = communityAdapters(queue, normalizeRequest);
  for (const adapter of Object.values(adapters)) adapter.start = forbidden;
  const cacheFile = task => queue.store.path(task.kind === 'local-compute' ? 'radius' : task.kind === 'source-reception'
    ? task.request.mode ? 'sourceV2' : 'source' : task.kind === 'design-evaluation' ? 'design' : 'editor', task.key, 'cache.json');
  const observations = [];
  for (const task of state.tasks) {
    if (eligibleReceipt(task) && adapters[task.kind]) observations.push(await inspectReceipt(task, { adapters, cacheFile, sourceService: queue.sources, root: queue.root }));
  }
  const reconciliation = buildReconciliation(state, observations);
  const sourceAfter = await sourceFingerprint(sourceRoot);
  if (sourceAfter !== sourceBefore || launches) throw new Error('Inspector source changed or a scientific launch was attempted.');
  const proposed = JSON.stringify(reconciliation.proposed_queue);
  return { inspector_schema: 'eeglayoutlab-offline-inspection/1', source_files_sha256: sourceBefore,
    runtime: { root: queue.root, queue_directory: queue.runtime.queueDirectory, python: queue.python, native_python: queue.runtime.nativePython },
    observations, changes: reconciliation.changes, retained: reconciliation.retained,
    proposed_queue_json: proposed, proposed_queue_sha256: textHash(proposed), scientific_worker_launches: launches,
    runtime_inspection_note: 'Source-v2 context may invoke the existing read-only Python runtime-identity inspector; scientific workers and FEM are forbidden.' };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    console.log(JSON.stringify(await inspectService(await readInspectionInput(process.stdin))));
  } catch (error) { console.error(String(error.message)); process.exitCode = 1; }
}
