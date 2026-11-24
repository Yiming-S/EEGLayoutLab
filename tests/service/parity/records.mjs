// Node reference for tests/service/test_storage.py: Node's own RecordStore and atomicJson
// (webapp/server/storage/records.mjs) on synthetic roots. For each case it runs the operations in order and records
// each one's value or error and the fs/promises calls it made (realpath, mkdir, open, rename, link, unlink, with
// their arguments). Writes only under the case roots and <out.json>.
// Usage: node tests/service/parity/records.mjs <spec.json> <out.json>
//   spec: {cases: [{id, root, ops: [op]}]}, op one of
//     {op: 'createBatch', kind, key, id}   {op: 'write', path, value, cycle?}   {op: 'atomicJson', path, value, cycle?}
//     {op: 'read', path}   {op: 'keys', kind}   {op: 'path', kind, key, parts}   {op: 'directory', kind}
//     {op: 'publish', kind, key, value, cycle?}: Node's write of the cache, store.write(store.path(kind, key,
//     'cache.json'), value), which Python's publish_cache replaces
//   A path is relative to the case root (path.join(root, path)); `value` is JSON text in which
//   {"$number": "NaN" | "Infinity" | "-Infinity" | "-0"} stands for that number; `cycle` {at: [...], to: [...]}
//   replaces the member at the path `at` with the value at the path `to`, which contains it.
//   out: {node, platform, cases: [{id, results: [{ok, value? | error: {name, code, message}, calls}]}]};
//   a read's value is its JSON.stringify text.
import { readFileSync, writeFileSync } from 'node:fs';
import { createRequire, syncBuiltinESMExports } from 'node:module';
import { join } from 'node:path';

const [specPath, outPath] = process.argv.slice(2);
if (!specPath || !outPath) throw new Error('usage: records.mjs <spec.json> <out.json>');

// Record the calls before records.mjs binds its imports: syncBuiltinESMExports carries the replaced functions to
// the named exports of node:fs/promises.
const require = createRequire(import.meta.url);
const fsp = require('node:fs/promises');
let calls = [];
for (const name of ['realpath', 'mkdir', 'open', 'rename', 'link', 'unlink']) {
  const original = fsp[name];
  fsp[name] = (...args) => { calls.push([name, ...args.map(String)]); return original(...args); };
}
syncBuiltinESMExports();
const records = new URL('../../../webapp/server/storage/records.mjs', import.meta.url);
const { RecordStore, atomicJson } = await import(records);

const SPECIAL = { NaN: NaN, Infinity: Infinity, '-Infinity': -Infinity, '-0': -0 };
const revive = (key, value) => (value && typeof value === 'object' && !Array.isArray(value)
  && Object.keys(value).length === 1 && typeof value.$number === 'string' ? SPECIAL[value.$number] : value);
function build(op) {
  // A reviver walks the value recursively; the deeply nested values have no stand-ins.
  const value = op.value.includes('"$number"') ? JSON.parse(op.value, revive) : JSON.parse(op.value);
  if (op.cycle) {
    const at = op.cycle.at, target = op.cycle.to.reduce((node, step) => node[step], value);
    at.slice(0, -1).reduce((node, step) => node[step], value)[at[at.length - 1]] = target;
  }
  return value;
}

async function run(store, root, op) {
  switch (op.op) {
    case 'createBatch': return store.createBatch(op.kind, op.key, op.id);
    case 'write': return store.write(join(root, op.path), build(op));
    case 'atomicJson': return atomicJson(join(root, op.path), build(op));
    case 'publish': return store.write(store.path(op.kind, op.key, 'cache.json'), build(op));
    case 'read': return JSON.stringify(await store.read(join(root, op.path)));
    case 'keys': return store.keys(op.kind);
    case 'path': return store.path(op.kind, op.key, ...op.parts);
    case 'directory': return store.directory(op.kind);
    default: throw new Error(`unknown op ${op.op}`);
  }
}

const { cases } = JSON.parse(readFileSync(specPath, 'utf8'));
const out = [];
for (const { id, root, ops } of cases) {
  const store = new RecordStore(root), results = [];
  for (const op of ops) {
    calls = [];
    let result;
    try {
      const value = await run(store, root, op);
      result = value === undefined ? { ok: true } : { ok: true, value };
    } catch (error) {
      const { name = null, code = null, message } = error ?? {};
      result = { ok: false, error: { name, code, message: String(message ?? error) } };
    }
    result.calls = calls;
    results.push(result);
  }
  out.push({ id, results });
}
writeFileSync(outPath, JSON.stringify({ node: process.version, platform: process.platform, cases: out }));
