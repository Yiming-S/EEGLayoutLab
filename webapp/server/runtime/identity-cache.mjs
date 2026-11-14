import { createHash } from 'node:crypto';
import { execFile } from 'node:child_process';
import { lstat, access, readlink } from 'node:fs/promises';
import { constants } from 'node:fs';
import { isAbsolute, join, resolve, delimiter, dirname } from 'node:path';
import { promisify } from 'node:util';

const exec = promisify(execFile);
const digestSchema = 'reception-runtime-digest/1';
const watchSchema = 'reception-runtime-watch/1';

async function stamp(path, full) {
  try {
    const info = await lstat(path, { bigint: true });
    const values = [info.dev, info.ino, info.mode];
    if (full) values.push(info.size, info.mtimeNs, info.ctimeNs);
    return values.join(':');
  } catch (error) {
    if (['ENOENT', 'ENOTDIR'].includes(error.code)) return null;
    throw error;
  }
}

function validWatch(watch) {
  if (!watch || watch.schema !== watchSchema || !Array.isArray(watch.entries) ||
      !watch.entries.length || watch.entries.length > 100000) return false;
  const paths = new Set();
  for (const item of watch.entries) {
    if (!Array.isArray(item) || item.length !== 3 || typeof item[0] !== 'string' || !isAbsolute(item[0]) ||
        paths.has(item[0]) || typeof item[1] !== 'boolean' ||
        !(item[2] === null || (typeof item[2] === 'string' && /^\d+(?::\d+){2}(?::\d+:-?\d+:-?\d+)?$/.test(item[2])))) return false;
    paths.add(item[0]);
  }
  return true;
}

async function unchanged(watch) {
  return (await Promise.all(watch.entries.map(async ([path, full, expected]) =>
    await stamp(path, full) === expected))).every(Boolean);
}

async function launcherWatch(python, root, env) {
  // execFile uses a platform default search path when PATH is omitted. Keep
  // those uncommon invocations uncached rather than assume that search path.
  if (!isAbsolute(python) && !python.includes('/') && typeof env.PATH !== 'string') return null;
  const absolute = path => isAbsolute(path) ? path : `${root}/${path}`;
  const candidates = isAbsolute(python) || python.includes('/')
    ? [absolute(python)]
    : env.PATH.split(delimiter).map(directory => `${absolute(directory || '.')}/${python}`);
  const paths = new Map(), expanded = new Set(), pending = candidates.map(path => [path, true]);
  while (pending.length) {
    const [path, full] = pending.pop();
    paths.set(path, Boolean(paths.get(path) || full));
    if (expanded.has(path)) continue;
    if (expanded.size > 10000) throw new Error('Python launcher link chain is too large');
    expanded.add(path);
    try {
      if ((await lstat(path)).isSymbolicLink()) {
        paths.set(path, true);
        const target = await readlink(path);
        // Do not normalize ../ before traversing directory symlinks: it would
        // observe a different path than the operating system executes.
        pending.push([isAbsolute(target) ? target : `${dirname(path)}/${target}`, true]);
      }
    } catch (error) { if (!['ENOENT', 'ENOTDIR'].includes(error.code)) throw error; }
    if (dirname(path) !== path) pending.push([dirname(path), false]);
  }
  // Watch each PATH candidate, not whole PATH directories: unrelated commands
  // must not invalidate a numerical runtime; a new earlier Python must do so.
  return { schema: watchSchema, entries: await Promise.all([...paths].map(async ([path, full]) =>
    [path, full, await stamp(path, full)])) };
}

async function runInspector({ python, root, env }) {
  let script = join(root, 'scripts/inspect_reception_runtime_snapshot.py');
  try { await access(script, constants.R_OK); }
  catch (error) {
    if (error.code !== 'ENOENT') throw error;
    script = join(root, 'scripts/inspect_reception_runtime.py');
  }
  const { stdout } = await exec(python, [script], { cwd: root, env, timeout: 15000, maxBuffer: 8 * 1024 * 1024 });
  return JSON.parse(stdout);
}

/** Revalidate file observations on every call; no time-based validity window. */
export function createRuntimeIdentityCache({ inspect = runInspector, maxEntries = 4 } = {}) {
  if (!Number.isInteger(maxEntries) || maxEntries < 0) throw new Error('Invalid runtime cache limit');
  const cache = new Map(), pending = new Map();
  return async function runtimeIdentity({ python, root, env = process.env }) {
    root = resolve(root);
    env = { ...env, PYTHONDONTWRITEBYTECODE: '1', OMP_NUM_THREADS: '1', OPENBLAS_NUM_THREADS: '1', MKL_NUM_THREADS: '1', VECLIB_MAXIMUM_THREADS: '1' };
    const key = createHash('sha256').update(JSON.stringify([python, root, Object.entries(env).sort(([a], [b]) => a.localeCompare(b))])).digest('hex');
    if (pending.has(key)) return { ...await pending.get(key) };
    const operation = (async () => {
      const saved = cache.get(key);
      if (saved && await unchanged(saved.watch) && await unchanged(saved.launcher)) {
        cache.delete(key); cache.set(key, saved);
        return { ...saved.digest };
      }
      cache.delete(key);
      const launcher = await launcherWatch(python, root, env);
      const result = await inspect({ python, root, env });
      if (result?.schema !== digestSchema || !/^[a-f0-9]{64}$/.test(result.sha256)) throw new Error('接收数值环境身份无效');
      const digest = { schema: result.schema, sha256: result.sha256 };
      // Older scientific snapshots remain readable, but are inspected on every call.
      if (result.watch !== undefined) {
        if (!validWatch(result.watch) || !await unchanged(result.watch) || (launcher && !await unchanged(launcher))) throw new Error('数值运行环境在检查期间发生变化');
        if (maxEntries && launcher) {
          cache.set(key, { digest, watch: result.watch, launcher });
          while (cache.size > maxEntries) cache.delete(cache.keys().next().value);
        }
      }
      return digest;
    })();
    pending.set(key, operation);
    try { return { ...await operation }; }
    catch (error) { cache.delete(key); throw error; }
    finally { pending.delete(key); }
  };
}
