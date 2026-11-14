import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtemp, mkdir, writeFile, readFile, lstat, utimes, symlink, unlink, rename, rm, access, chmod } from 'node:fs/promises';
import { constants } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createRuntimeIdentityCache } from '../server/runtime/identity-cache.mjs';

const hash = text => createHash('sha256').update(text).digest('hex');
async function observation(paths) {
  const entries = [];
  for (const path of paths) {
    const info = await lstat(path, { bigint: true });
    entries.push([path, true, [info.dev, info.ino, info.mode, info.size, info.mtimeNs, info.ctimeNs].join(':')]);
  }
  return { schema: 'reception-runtime-watch/1', entries };
}

async function fixture(t, options = {}) {
  const root = await mkdtemp(join(tmpdir(), 'eeg-runtime-watch-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  const folder = join(root, 'package'); await mkdir(folder);
  const file = join(folder, 'numerical.py'); await writeFile(file, 'version1');
  let calls = 0, failure, afterSnapshot;
  const inspect = async ({ env }) => {
    calls++;
    if (failure) throw failure;
    const value = hash((await readFile(file, 'utf8')) + (env.CHOICE || ''));
    const watch = await observation([folder, file]);
    await afterSnapshot?.();
    return { schema: 'reception-runtime-digest/1', sha256: value, watch };
  };
  const read = createRuntimeIdentityCache({ inspect, ...options });
  const args = { root, python: process.execPath, env: {} };
  return { root, folder, file, args, read, get calls() { return calls; },
    fail(value) { failure = value; }, afterSnapshot(value) { afterSnapshot = value; } };
}

void test('warm runtime checks preserve digest with no new inspector and isolate returned values', async t => {
  const f = await fixture(t);
  const first = await f.read(f.args); const expected = structuredClone(first);
  first.sha256 = '0'.repeat(64);
  assert.deepEqual(await f.read(f.args), expected);
  assert.equal(f.calls, 1);
});

void test('same-size writes invalidate even when mtime is restored', async t => {
  const f = await fixture(t); const before = await f.read(f.args);
  const info = await lstat(f.file); await writeFile(f.file, 'version2'); await utimes(f.file, info.atime, info.mtime);
  assert.notEqual((await f.read(f.args)).sha256, before.sha256); assert.equal(f.calls, 2);
});

for (const mutation of ['add', 'delete', 'replace']) {
  void test(`numerical discovery ${mutation} invalidates the cached inspection`, async t => {
    const f = await fixture(t);
    const sibling = join(f.folder, 'other.py'); await writeFile(sibling, 'other');
    const expected = await f.read(f.args);
    if (mutation === 'add') await writeFile(join(f.folder, 'added.py'), 'new numerical module');
    if (mutation === 'delete') await unlink(sibling);
    if (mutation === 'replace') { await rename(f.folder, f.folder + '-old'); await mkdir(f.folder); await writeFile(f.file, 'version1'); }
    assert.deepEqual(await f.read(f.args), expected); assert.equal(f.calls, 2);
  });
}

void test('missing dependencies fail closed and repaired inputs retry', async t => {
  const f = await fixture(t); const first = await f.read(f.args);
  await unlink(f.file); await assert.rejects(f.read(f.args), { code: 'ENOENT' });
  await writeFile(f.file, 'version1'); assert.deepEqual(await f.read(f.args), first); assert.equal(f.calls, 3);
});

void test('simultaneous cold and warm queries share a single inspection/check', async t => {
  const f = await fixture(t);
  const cold = await Promise.all(Array.from({ length: 12 }, () => f.read(f.args)));
  assert.ok(cold.every(result => result.sha256 === cold[0].sha256)); assert.equal(f.calls, 1);
  await Promise.all(Array.from({ length: 12 }, () => f.read(f.args))); assert.equal(f.calls, 1);
  await writeFile(f.file, 'version2'); await Promise.all(Array.from({ length: 12 }, () => f.read(f.args))); assert.equal(f.calls, 2);
});

void test('failed inspection is not reused and observations changed during inspection are rejected', async t => {
  const f = await fixture(t); f.fail(new Error('incomplete runtime'));
  await assert.rejects(f.read(f.args), /incomplete runtime/); f.fail(null);
  f.afterSnapshot(() => writeFile(f.file, 'version2'));
  await assert.rejects(f.read(f.args), /检查期间/);
  f.afterSnapshot(null); assert.equal((await f.read(f.args)).sha256, hash('version2')); assert.equal(f.calls, 3);
});

void test('environment keys and bounded least-recently-used entries stay independent', async t => {
  const f = await fixture(t, { maxEntries: 2 });
  const a = { ...f.args, env: { CHOICE: 'a' } }, b = { ...f.args, env: { CHOICE: 'b' } }, c = { ...f.args, env: { CHOICE: 'c' } };
  const first = await f.read(a); assert.notEqual((await f.read(b)).sha256, first.sha256);
  assert.deepEqual(await f.read(a), first); await f.read(c); assert.equal(f.calls, 3);
  await f.read(a); assert.equal(f.calls, 3); await f.read(b); assert.equal(f.calls, 4);
});

void test('launcher symlink and an earlier PATH executable invalidate the current digest', async t => {
  const f = await fixture(t);
  const first = join(f.root, 'first'), second = join(f.root, 'second'); await mkdir(first); await mkdir(second);
  const one = join(second, 'python'); await symlink(process.execPath, one);
  const args = { ...f.args, python: 'python', env: { PATH: `${first}:${second}` } };
  await f.read(args); await f.read(args); assert.equal(f.calls, 1);
  await symlink(process.execPath, join(first, 'python')); await f.read(args); assert.equal(f.calls, 2);
  await unlink(join(first, 'python')); await writeFile(join(first, 'python'), 'different executable'); await f.read(args); assert.equal(f.calls, 3);
});

for (const change of ['missing target', 'nonexecutable target', 'intermediate link']) {
  void test(`an earlier PATH symlink becoming executable via ${change} invalidates the digest`, async t => {
    const f = await fixture(t), first = join(f.root, 'first'), second = join(f.root, 'second'), external = join(f.root, 'external');
    await Promise.all([mkdir(first), mkdir(second), mkdir(external)]);
    const preferred = join(first, 'python'), fallback = join(second, 'python'), target = join(external, 'preferred-python');
    await writeFile(fallback, 'fallback runtime', { mode: 0o755 });
    if (change === 'intermediate link') {
      await symlink('preferred-python', join(external, 'intermediate'));
      await symlink('../external/intermediate', preferred);
    } else await symlink(target, preferred);
    if (change === 'nonexecutable target') await writeFile(target, 'preferred runtime', { mode: 0o644 });
    let inspections = 0;
    const read = createRuntimeIdentityCache({ inspect: async () => {
      inspections++;
      let executable = fallback;
      try { await access(preferred, constants.X_OK); executable = preferred; } catch { /* Search proceeds to the fallback. */ }
      return { schema: 'reception-runtime-digest/1', sha256: hash(await readFile(executable)), watch: await observation([executable]) };
    } });
    const args = { ...f.args, python: 'python', env: { PATH: `${first}:${second}` } };
    const initial = await read(args); assert.equal(initial.sha256, hash('fallback runtime'));
    assert.deepEqual(await read(args), initial); assert.equal(inspections, 1);
    if (change === 'nonexecutable target') await chmod(target, 0o755);
    else await writeFile(target, 'preferred runtime', { mode: 0o755 });
    const updated = await read(args); assert.equal(updated.sha256, hash('preferred runtime')); assert.equal(inspections, 2);
    assert.deepEqual(await read(args), updated); assert.equal(inspections, 2);
  });
}

for (const invocation of ['PATH entry', 'absolute executable', 'relative executable']) {
  void test(`symlink/../ traversal in ${invocation} retains operating-system path semantics`, async t => {
    const f = await fixture(t), physical = join(f.root, 'physical'), branch = join(f.root, 'branch');
    await mkdir(join(physical, 'nested'), { recursive: true }); await mkdir(join(physical, 'bin')); await mkdir(branch);
    await symlink(join(physical, 'nested'), join(branch, 'link'));
    const actual = join(physical, 'bin/python'), fallback = join(f.root, 'fallback'); await mkdir(fallback);
    await writeFile(join(fallback, 'python'), 'fallback runtime', { mode: 0o755 });
    const lexical = `${branch}/link/../bin/python`;
    const args = invocation === 'PATH entry'
      ? { ...f.args, python: 'python', env: { PATH: `${branch}/link/../bin:${fallback}` } }
      : { ...f.args, python: invocation === 'absolute executable' ? lexical : 'branch/link/../bin/python' };
    if (invocation !== 'PATH entry') await writeFile(actual, 'version1', { mode: 0o755 });
    let inspections = 0;
    const read = createRuntimeIdentityCache({ inspect: async () => {
      inspections++; let executable = lexical;
      try { await access(executable, constants.X_OK); } catch { executable = join(fallback, 'python'); }
      return { schema: 'reception-runtime-digest/1', sha256: hash(await readFile(executable)), watch: await observation([f.file]) };
    } });
    const initial = await read(args); assert.deepEqual(await read(args), initial); assert.equal(inspections, 1);
    await writeFile(actual, 'version2', { mode: 0o755 });
    assert.equal((await read(args)).sha256, hash('version2')); assert.equal(inspections, 2);
  });
}

void test('legacy digest-only inspectors are accepted but not cached', async t => {
  const f = await fixture(t); let calls = 0;
  const read = createRuntimeIdentityCache({ inspect: async () => { calls++; return { schema: 'reception-runtime-digest/1', sha256: hash('legacy') }; } });
  await read(f.args); await read(f.args); assert.equal(calls, 2);
});

void test('an implicit platform executable search path is inspected each time', async t => {
  const f = await fixture(t);
  const args = { ...f.args, python: 'python3', env: {} };
  await f.read(args); await f.read(args); assert.equal(f.calls, 2);
});

void test('zero entry budget disables retention; malformed runtime output fails', async t => {
  const f = await fixture(t, { maxEntries: 0 }); await f.read(f.args); await f.read(f.args); assert.equal(f.calls, 2);
  for (const result of [{ schema: 'wrong', sha256: hash('x') }, { schema: 'reception-runtime-digest/1', sha256: 'bad' }, { schema: 'reception-runtime-digest/1', sha256: hash('x'), watch: {} }]) {
    const read = createRuntimeIdentityCache({ inspect: async () => result }); await assert.rejects(read(f.args));
  }
});
