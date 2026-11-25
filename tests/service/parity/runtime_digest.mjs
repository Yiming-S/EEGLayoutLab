// Node reference for tests/service/test_runtime_digest.py: createRuntimeIdentityCache of
// webapp/server/runtime/identity-cache.mjs with its own inspector runner (execFile of the root's inspector script),
// on case directories runtime_digest_support.py lays out. Writes only inside the case directories and <out.json>.
// Usage: node tests/service/parity/runtime_digest.mjs <spec.json> <out.json>
//
// spec: {python, inspectTimeoutMs?, cases: [{id, dir, maxEntries?, steps}]}. In every string of a step, '<case>' is
// the case directory and '<python>' the interpreter. A fresh cache per case (`maxEntries` passed when given); its
// steps run in order:
// - ['read', {python?, root?, env?, parallel?}]: `parallel` (default 1) simultaneous reads with python (default
//   spec.python) and root (default <case>/R); env is left out (process.env) or {base: 'process' | 'empty', set?,
//   unset?}. Recorded: {outcomes, runs}, each outcome {ok: true, value} or {ok: false, error}, and runs the lines of
//   <case>/inspections.log (the stub inspector's count) after the read;
// - ['write', path, text, mode?], ['symlink', target, path], ['unlink', path], ['chmod', path, mode],
//   ['mkdir', path] (recursive), ['rename', from, to]; a relative path is under <case>.
// Errors are {name: 'SyntaxError'} or {name, message, code, signal, killed} with the case directory as '<case>'.
// With inspectTimeoutMs, execFile's 15 s timer runs for that long instead (`scaled` counts the timers changed).
import { createRequire } from 'node:module';
import { readFileSync, writeFileSync } from 'node:fs';
import { chmod, mkdir, rename, symlink, unlink, writeFile } from 'node:fs/promises';

const [specPath, outPath] = process.argv.slice(2);
if (!specPath || !outPath) throw new Error('usage: runtime_digest.mjs <spec.json> <out.json>');
const spec = JSON.parse(readFileSync(specPath, 'utf8'));
let scaled = 0;
if (spec.inspectTimeoutMs) {
  // execFile reads setTimeout from the timers module when it is called.
  const timers = createRequire(import.meta.url)('timers');
  const original = timers.setTimeout;
  timers.setTimeout = (callback, ms, ...rest) => {
    if (ms === 15000) { scaled++; ms = spec.inspectTimeoutMs; }
    return original(callback, ms, ...rest);
  };
}
const { createRuntimeIdentityCache } = await import('../../../webapp/server/runtime/identity-cache.mjs');

const map = (value, text) => typeof value === 'string' ? text(value)
  : Array.isArray(value) ? value.map(item => map(item, text))
  : value && typeof value === 'object'
    ? Object.fromEntries(Object.entries(value).map(([key, item]) => [key, map(item, text)]))
  : value;
const fill = (value, dir) => map(value, text => text.replaceAll('<case>', dir).replaceAll('<python>', spec.python));
const plain = (value, dir) => map(value, text => text.replaceAll(dir, '<case>'));
const describe = (error, dir) => error instanceof SyntaxError ? { name: 'SyntaxError' } : {
  name: error?.name ?? null, message: plain(String(error?.message), dir), code: error?.code ?? null,
  signal: error?.signal ?? null, killed: error?.killed ?? null,
};
const runs = dir => {
  try { return readFileSync(`${dir}/inspections.log`, 'utf8').split('\n').filter(Boolean).length; }
  catch { return 0; }
};
const environment = env => {
  if (!env) return undefined;
  const value = env.base === 'empty' ? {} : { ...process.env };
  for (const name of env.unset ?? []) delete value[name];
  return Object.assign(value, env.set ?? {});
};
const at = (dir, path) => path.startsWith('/') ? path : `${dir}/${path}`;
const ops = {
  write: (dir, path, text, mode) => writeFile(at(dir, path), text, mode === undefined ? undefined : { mode }),
  symlink: (dir, target, path) => symlink(target, at(dir, path)),
  unlink: (dir, path) => unlink(at(dir, path)),
  chmod: (dir, path, mode) => chmod(at(dir, path), mode),
  mkdir: (dir, path) => mkdir(at(dir, path), { recursive: true }),
  rename: (dir, from, to) => rename(at(dir, from), at(dir, to)),
};

const results = [];
for (const c of spec.cases) {
  const { dir } = c, out = { id: c.id, steps: [] };
  let read;
  try { read = createRuntimeIdentityCache(c.maxEntries === undefined ? {} : { maxEntries: c.maxEntries }); }
  catch (error) { out.create = describe(error, dir); results.push(out); continue; }
  for (const step of c.steps) {
    const [op, ...args] = fill(step, dir);
    if (op !== 'read') { await ops[op](dir, ...args); continue; }
    const { python = spec.python, root = `${dir}/R`, env, parallel = 1 } = args[0] ?? {};
    const call = async () => {
      try { return { ok: true, value: await read({ python, root, env: environment(env) }) }; }
      catch (error) { return { ok: false, error: describe(error, dir) }; }
    };
    const outcomes = await Promise.all(Array.from({ length: parallel }, call));
    out.steps.push({ outcomes: plain(outcomes, dir), runs: runs(dir) });
  }
  results.push(out);
}
writeFileSync(outPath, JSON.stringify({ node: process.version, platform: process.platform, scaled, cases: results }));
