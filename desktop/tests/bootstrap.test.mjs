import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { chmod, lstat, mkdir, mkdtemp, readFile, readdir, realpath, rm, symlink, writeFile } from 'node:fs/promises';
import http from 'node:http';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { gzipSync } from 'node:zlib';
import { archivePath, cleanEnvironment, extractPayload, installWorkspace, loopbackHealthy, managedDirectory, readManifest, SCHEMA, userDataDirectory } from '../bootstrap-support.mjs';

const BOOTSTRAP = fileURLToPath(new URL('../bootstrap.mjs', import.meta.url));
const pause = (ms) => new Promise((accept) => setTimeout(accept, ms));

function tar(entries) {
  const chunks = [];
  for (const entry of entries) {
    const body = Buffer.from(entry.body || '');
    const header = Buffer.alloc(512);
    header.write(entry.name, 0, 100);
    header.write((entry.mode || 0o644).toString(8).padStart(7, '0') + '\0', 100, 8);
    header.write('0000000\0', 108, 8); header.write('0000000\0', 116, 8);
    header.write(body.length.toString(8).padStart(11, '0') + '\0', 124, 12);
    header.write('00000000000\0', 136, 12);
    header.fill(32, 148, 156);
    header.write(entry.type || '0', 156, 1);
    if (entry.link) header.write(entry.link, 157, 100);
    header.write('ustar\0', 257, 6); header.write('00', 263, 2);
    const checksum = header.reduce((sum, byte) => sum + byte, 0);
    header.write(checksum.toString(8).padStart(6, '0') + '\0 ', 148, 8);
    chunks.push(header, body, Buffer.alloc((512 - body.length % 512) % 512));
  }
  chunks.push(Buffer.alloc(1024));
  return gzipSync(Buffer.concat(chunks));
}

const fakeServer = `
import http from 'node:http';
import {spawn} from 'node:child_process';
import {writeFileSync} from 'node:fs';
export async function startLocalApp({port}) {
  const worker=spawn(process.execPath,['-e',"process.on('SIGTERM',()=>{});setInterval(()=>{},1000)"], {stdio:'ignore'});
  writeFileSync('results/worker.pid',String(worker.pid));
  const server=http.createServer((req,res)=>{
    res.setHeader('Content-Type','application/json');
    res.end(JSON.stringify({available:true,local_only:true}));
  });
  try { await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(port,'127.0.0.1',resolve);}); }
  catch(error){worker.kill('SIGKILL');throw error;}
  console.log('Fixture server console output belongs in logs.');
  return {server,port:server.address().port,service:{dispose(){
    writeFileSync('results/disposed','yes');worker.kill('SIGTERM');
  }}};
}
`;

async function fixture(t, extras = []) {
  const root = await realpath(await mkdtemp(join(tmpdir(), 'eeg-desktop-test-')));
  const resources = join(root, 'Read Only.app', 'Contents', 'Resources');
  t.after(async () => { await chmod(resources, 0o755).catch(() => {}); await rm(root, { recursive: true, force: true }); });
  const userData = join(root, 'user data');
  await mkdir(resources, { recursive: true });
  await mkdir(userData);
  const entries = [
    { name: 'webapp/server/start.mjs', body: fakeServer },
    { name: '.runtime/simnibs-4.6.0/bin/python3.11', body: '#!/bin/sh\nexit 0\n', mode: 0o755 },
    { name: '.runtime/simnibs-4.6.0/bin/python', type: '2', link: 'python3.11' },
    { name: 'results/frozen.txt', body: 'frozen data' },
    ...extras,
  ];
  const payload = tar(entries);
  const manifest = { schema: SCHEMA, version: '0.1.0', payload: {
    file: 'payload.tar.gz', sha256: createHash('sha256').update(payload).digest('hex'),
    unpackedBytes: entries.reduce((sum, entry) => sum + Buffer.byteLength(entry.body || ''), 0),
  } };
  const payloadPath = join(resources, manifest.payload.file);
  await writeFile(payloadPath, payload);
  await writeFile(join(resources, 'desktop-manifest.json'), JSON.stringify(manifest));
  return { root, resources, userData, payloadPath, manifest: { ...manifest, payloadPath } };
}

function launch(fixture) {
  const child = spawn(process.execPath, [BOOTSTRAP], {
    env: { ...process.env, EEG_DESKTOP_USER_DATA: fixture.userData, EEG_DESKTOP_RESOURCES: fixture.resources },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  const records = []; let output = '', stderr = '';
  child.stdout.on('data', (chunk) => {
    output += chunk;
    const lines = output.split('\n'); output = lines.pop();
    for (const line of lines) if (line) records.push(JSON.parse(line));
  });
  child.stderr.on('data', (chunk) => { stderr += chunk; });
  const exited = new Promise((accept) => child.once('exit', (code, signal) => accept({ code, signal })));
  return {
    child, records, exited,
    async until(type, timeout = 15_000) {
      const deadline = Date.now() + timeout;
      while (Date.now() < deadline) {
        const found = records.find((record) => record.type === type);
        if (found) return found;
        if (records.find((record) => record.type === 'error')) throw new Error(JSON.stringify(records));
        if (child.exitCode !== null) throw new Error(`Bootstrap exited: ${stderr} ${JSON.stringify(records)}`);
        await pause(20);
      }
      throw new Error(`Bootstrap timed out: ${stderr} ${JSON.stringify(records)}`);
    },
    async stop() {
      if (child.exitCode === null && child.signalCode === null) child.kill('SIGTERM');
      let timer;
      try { return await Promise.race([exited, new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('Bootstrap did not stop.')), 8000); })]); }
      finally { clearTimeout(timer); }
    },
  };
}

test('manifest verifies bundled assets and reports missing or corrupt payloads', async (t) => {
  const f = await fixture(t);
  assert.equal((await readManifest(f.resources)).payload.sha256, f.manifest.payload.sha256);
  const asset = Buffer.from('bootstrap fixture asset');
  await writeFile(join(f.resources, 'bootstrap.mjs'), asset);
  await writeFile(join(f.resources, 'desktop-manifest.json'), JSON.stringify({ ...f.manifest, assets: [
    { file: 'bootstrap.mjs', sha256: createHash('sha256').update(asset).digest('hex') },
  ] }));
  assert.equal((await readManifest(f.resources)).assets.length, 1);
  await writeFile(join(f.resources, 'bootstrap.mjs'), 'tampered');
  await assert.rejects(readManifest(f.resources), /Bundled asset failed SHA-256/);
  await writeFile(join(f.resources, 'bootstrap.mjs'), asset);
  await writeFile(f.payloadPath, 'corrupt');
  await assert.rejects(installWorkspace(f), /SHA-256/);
  assert.equal((await readdir(join(f.userData, 'workspaces'))).length, 0);
  await rm(f.payloadPath);
  await assert.rejects(readManifest(f.resources), /ENOENT/);
});

test('streaming extractor preserves large files, PAX long names, and contained hardlinks', async (t) => {
  const f = await fixture(t);
  const longName = `long/${'segment-'.repeat(18)}/fixture.txt`;
  const value = `path=${longName}\n`;
  let length = Buffer.byteLength(value) + 2;
  while (length !== Buffer.byteLength(`${length} ${value}`)) length = Buffer.byteLength(`${length} ${value}`);
  const body = '0123456789abcdef'.repeat(16384);
  const payload = tar([
    { name: 'PaxHeader', type: 'x', body: `${length} ${value}` },
    { name: 'short-name', body },
    { name: 'copy.txt', type: '1', link: 'small.txt' },
    { name: 'small.txt', body: 'hardlink data' },
  ]);
  const archive = join(f.root, 'pax.tar.gz');
  const destination = join(f.root, 'pax-output');
  await writeFile(archive, payload);
  await mkdir(destination);
  await extractPayload(archive, destination, { maximumBytes: body.length + 1024 });
  assert.equal(await readFile(join(destination, longName), 'utf8'), body);
  assert.equal(await readFile(join(destination, 'copy.txt'), 'utf8'), 'hardlink data');
  assert.equal((await lstat(join(destination, 'copy.txt'))).ino, (await lstat(join(destination, 'small.txt'))).ino);
});

test('dedicated user directories and archive names reject containment escapes', async () => {
  for (const value of ['../../outside', '/etc/passwd', 'safe/../outside', 'C:/outside', 'a\\b']) {
    assert.throws(() => archivePath(value), /Unsafe/);
  }
  assert.equal(archivePath('./safe/file.txt'), 'safe/file.txt');
  await assert.rejects(userDataDirectory('/'), /dedicated/);
  await assert.rejects(userDataDirectory('relative-path'), /dedicated/);
});

test('managed cache directory does not follow a symlink before creating children', async (t) => {
  const f = await fixture(t);
  const outside = join(f.root, 'outside');
  await mkdir(outside);
  await symlink(outside, join(f.userData, 'cache'));
  await assert.rejects(managedDirectory(f.userData, 'cache/matplotlib'), /inside application data/);
  assert.deepEqual(await readdir(outside), []);
});

test('archive traversal, external links, and bad gzip never create a ready workspace', async (t) => {
  for (const entry of [
    { name: '../outside.txt', body: 'escape' },
    { name: 'external', type: '2', link: '/tmp' },
    { name: 'deep/link', type: '2', link: '../../outside' },
    { name: '.desktop-ready.json', body: '{}' },
  ]) {
    const f = await fixture(t, [entry]);
    await assert.rejects(installWorkspace(f), /Unsafe|escapes|reserved/);
    assert.deepEqual(await readdir(join(f.userData, 'workspaces')), []);
  }
  const f = await fixture(t);
  const bytes = await readFile(f.payloadPath);
  bytes[bytes.length - 5] ^= 1;
  await writeFile(f.payloadPath, bytes);
  const destination = join(f.root, 'broken-gzip');
  await mkdir(destination);
  await assert.rejects(extractPayload(f.payloadPath, destination), /check|data|length/);
});

test('first launch installs; later launch reuses writable results without decompressing', async (t) => {
  const f = await fixture(t);
  await chmod(f.resources, 0o555);
  const first = await installWorkspace(f);
  assert.equal(first.reused, false);
  assert.equal(await readFile(join(first.workspace, 'results/frozen.txt'), 'utf8'), 'frozen data');
  assert.equal((await lstat(join(first.workspace, '.runtime/simnibs-4.6.0/bin/python'))).isSymbolicLink(), true);
  await writeFile(join(first.workspace, 'results/user-result.txt'), 'user result');
  const marker = await readFile(join(first.workspace, '.desktop-ready.json'), 'utf8');
  await writeFile(f.payloadPath, 'not a tar, so reuse must not decompress');
  const second = await installWorkspace(f);
  assert.deepEqual(second, { workspace: first.workspace, reused: true });
  assert.equal(await readFile(join(second.workspace, 'results/user-result.txt'), 'utf8'), 'user result');
  assert.equal(await readFile(join(second.workspace, '.desktop-ready.json'), 'utf8'), marker);
});

test('interrupted staging recovers, incomplete user workspace is preserved', async (t) => {
  const f = await fixture(t);
  const workspaces = join(f.userData, 'workspaces');
  const incomplete = join(workspaces, f.manifest.payload.sha256);
  await mkdir(join(incomplete, 'results'), { recursive: true });
  await writeFile(join(incomplete, 'results/valuable.txt'), 'keep');
  const staging = join(workspaces, `.install-${f.manifest.payload.sha256}-12345678-1234-1234-1234-123456789abc`);
  await mkdir(staging);
  await writeFile(join(staging, '.desktop-install.json'), JSON.stringify({ schema: SCHEMA, payloadSha256: f.manifest.payload.sha256 }));
  const installed = await installWorkspace(f);
  assert.equal(installed.reused, false);
  assert.deepEqual(await readdir(workspaces), [f.manifest.payload.sha256]);
  const recovered = await readdir(join(f.userData, 'recovered'));
  assert.equal(recovered.length, 1);
  assert.equal(await readFile(join(f.userData, 'recovered', recovered[0], 'results/valuable.txt'), 'utf8'), 'keep');
});

test('worker environment strips injected paths and fixes native compute runtime and caches', () => {
  const env = cleanEnvironment({ HOME: '/Users/test', NODE_OPTIONS: '--require bad', NODE_PATH: '/bad', PYTHONPATH: '/bad', PYTHONHOME: '/bad', DYLD_LIBRARY_PATH: '/bad', PATH: '/bad', OMP_NUM_THREADS: '64' }, '/data/workspaces/hash', '/data', '/bundle/node/bin/node');
  for (const field of ['NODE_OPTIONS', 'NODE_PATH', 'PYTHONPATH', 'PYTHONHOME', 'DYLD_LIBRARY_PATH']) assert.equal(env[field], undefined);
  assert.equal(env.EEG_COMPUTE_PYTHON, '/data/workspaces/hash/.runtime/simnibs-4.6.0/bin/python');
  assert.equal(env.OMP_NUM_THREADS, '2');
  assert.equal(env.MPLCONFIGDIR, '/data/cache/matplotlib');
  assert.equal(env.PORT, '0');
  assert.equal(env.HOST, '127.0.0.1');
});

test('bootstrap starts loopback, logs server output, shares one active server, and kills workers on quit', async (t) => {
  const f = await fixture(t);
  const app = launch(f);
  t.after(() => app.stop());
  const ready = await app.until('ready');
  assert.equal(ready.sharedServer, undefined);
  assert.match(ready.url, /^http:\/\/127\.0\.0\.1:\d+\/$/);
  assert.equal(await loopbackHealthy(ready.url, { desktop: true }), true);
  assert.match(await readFile(ready.logPath, 'utf8'), /Fixture server console/);
  const worker = Number(await readFile(join(ready.workspace, 'results/worker.pid'), 'utf8'));
  const second = launch(f);
  t.after(() => second.stop());
  const shared = await second.until('ready');
  assert.equal(shared.url, ready.url);
  assert.equal(shared.reused, true);
  assert.equal(shared.sharedServer, true);
  assert.equal((await second.exited).code, 0);
  assert.equal(await loopbackHealthy(ready.url), true);
  assert.equal((await app.stop()).code, 0);
  assert.equal(await loopbackHealthy(ready.url), false);
  assert.equal(await readFile(join(ready.workspace, 'results/disposed'), 'utf8'), 'yes');
  assert.throws(() => process.kill(worker, 0), /ESRCH/);
  assert.deepEqual(await readdir(join(f.userData, 'run')), ['preferred-port.json']);
  assert.match(await readFile(ready.logPath, 'utf8'), /Stopping desktop server/);
  assert.equal(app.records.filter((record) => record.type === 'error').length, 0);
  const reopened = launch(f);
  t.after(() => reopened.stop());
  const reopenedReady = await reopened.until('ready');
  assert.equal(reopenedReady.url, ready.url);
  assert.equal(reopenedReady.reused, true);
  assert.equal(reopenedReady.sharedServer, undefined);
  await reopened.stop();
  const collision = http.createServer((_request, response) => response.end('other application'));
  await new Promise((accept) => collision.listen(Number(new URL(ready.url).port), '127.0.0.1', accept));
  t.after(() => new Promise((accept) => collision.close(accept)));
  const fallback = launch(f);
  t.after(() => fallback.stop());
  const fallbackReady = await fallback.until('ready');
  assert.notEqual(fallbackReady.url, ready.url);
  assert.equal(await loopbackHealthy(fallbackReady.url, { desktop: true }), true);
  await fallback.stop();
});

test('bootstrap emits a structured error for missing application resources', async (t) => {
  const f = await fixture(t);
  await rm(f.payloadPath);
  const app = launch(f);
  t.after(() => app.stop());
  const error = await app.until('error');
  assert.match(error.message, /ENOENT/);
  assert.ok(error.logPath);
  assert.equal((await app.exited).code, 1);
});

test('abrupt supervisor termination closes the server group and a stale lock recovers', async (t) => {
  const f = await fixture(t);
  const app = launch(f);
  t.after(() => app.stop());
  const ready = await app.until('ready');
  const worker = Number(await readFile(join(ready.workspace, 'results/worker.pid'), 'utf8'));
  app.child.kill('SIGKILL');
  assert.equal((await app.exited).signal, 'SIGKILL');
  const deadline = Date.now() + 5000;
  let alive = true;
  while (Date.now() < deadline) {
    try { process.kill(worker, 0); } catch { alive = false; break; }
    await pause(50);
  }
  assert.equal(alive, false, 'Worker must stop after its supervisor loses IPC.');
  assert.equal(await loopbackHealthy(ready.url), false);
  const reopened = launch(f);
  t.after(() => reopened.stop());
  const reopenedReady = await reopened.until('ready');
  assert.equal(reopenedReady.url, ready.url);
  assert.equal(reopenedReady.reused, true);
  await reopened.stop();
});
