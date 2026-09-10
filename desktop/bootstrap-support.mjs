/** Offline, user-owned installation support. No writes to the application bundle. */
import { createHash, randomUUID } from 'node:crypto';
import { createReadStream } from 'node:fs';
import { access, chmod, link, lstat, mkdir, open, readFile, readdir, realpath, rename, rm, statfs, symlink, writeFile } from 'node:fs/promises';
import { constants } from 'node:fs';
import { homedir } from 'node:os';
import { basename, dirname, isAbsolute, join, relative, resolve, sep } from 'node:path';
import { createGunzip } from 'node:zlib';

export const SCHEMA = 'eeglayoutlab-desktop/1';
export const READY_MARKER = '.desktop-ready.json';
const SHA256 = /^[a-f0-9]{64}$/;
const STAGE_NAME = /^\.install-[a-f0-9]{64}-[a-f0-9-]{36}$/;

export function inside(root, candidate) {
  const rel = relative(resolve(root), resolve(candidate));
  return rel !== '' && rel !== '..' && !rel.startsWith(`..${sep}`) && !isAbsolute(rel);
}

export function archivePath(value) {
  if (typeof value !== 'string' || value.includes('\0') || value.includes('\\') || isAbsolute(value) || /^[A-Za-z]:/.test(value)) {
    throw new Error(`Unsafe archive path: ${JSON.stringify(value)}`);
  }
  const parts = value.split('/').filter((part) => part && part !== '.');
  if (parts.includes('..')) throw new Error(`Unsafe archive path: ${JSON.stringify(value)}`);
  return parts.join('/');
}

export async function sha256(file) {
  const digest = createHash('sha256');
  for await (const chunk of createReadStream(file)) digest.update(chunk);
  return digest.digest('hex');
}

export async function userDataDirectory(override = process.env.EEG_DESKTOP_USER_DATA) {
  const target = override || join(homedir(), 'Library', 'Application Support', 'EEG Layout Lab');
  if (!isAbsolute(target) || resolve(target) === sep || resolve(target) === resolve(homedir())) {
    throw new Error('EEG_DESKTOP_USER_DATA must name a dedicated absolute application directory.');
  }
  await mkdir(target, { recursive: true, mode: 0o700 });
  if (!(await lstat(target)).isDirectory()) throw new Error('Application data directory must be a real directory, not a symbolic link.');
  return realpath(target);
}

export async function managedDirectory(root, name) {
  root = await realpath(root);
  const clean = archivePath(name);
  if (!clean) throw new Error('Invalid managed directory.');
  let target = root;
  for (const part of clean.split('/')) {
    target = join(target, part);
    try { await mkdir(target, { mode: 0o700 }); } catch (error) { if (error.code !== 'EEXIST') throw error; }
    // Check each component before creating its children, including cache subfolders.
    if (!(await lstat(target)).isDirectory() || !inside(root, await realpath(target))) {
      throw new Error(`Managed directory must stay inside application data: ${name}`);
    }
  }
  return target;
}

async function bundleFile(resources, file) {
  resources = await realpath(resources);
  const clean = archivePath(file);
  if (!clean) throw new Error('Missing bundled asset filename.');
  const target = join(resources, clean);
  if (!inside(resources, await realpath(target)) || !(await lstat(target)).isFile()) {
    throw new Error(`Bundled asset is not a regular contained file: ${file}`);
  }
  return target;
}

export async function readManifest(resources) {
  const manifest = JSON.parse(await readFile(await bundleFile(resources, 'desktop-manifest.json'), 'utf8'));
  if (manifest.schema !== SCHEMA || typeof manifest.version !== 'string' || !manifest.version ||
      !manifest.payload || !SHA256.test(manifest.payload.sha256) ||
      !Number.isSafeInteger(manifest.payload.unpackedBytes) || manifest.payload.unpackedBytes <= 0) {
    throw new Error('The desktop manifest is invalid. Reinstall EEG Layout Lab from a complete application bundle.');
  }
  manifest.payloadPath = await bundleFile(resources, manifest.payload.file);
  if (manifest.assets !== undefined && !Array.isArray(manifest.assets)) throw new Error('Invalid desktop asset manifest.');
  for (const asset of manifest.assets || []) {
    if (!SHA256.test(asset.sha256)) throw new Error('Invalid desktop asset digest.');
    const file = await bundleFile(resources, asset.file);
    if (await sha256(file) !== asset.sha256) throw new Error(`Bundled asset failed SHA-256 verification: ${asset.file}`);
  }
  return manifest;
}

function tarNumber(bytes) {
  if (bytes[0] & 0x80) throw new Error('Unsupported binary tar size.');
  const value = bytes.toString('utf8').replace(/\0.*$/, '').trim();
  if (value && !/^[0-7]+$/.test(value)) throw new Error('Invalid tar number.');
  const number = parseInt(value || '0', 8);
  if (!Number.isSafeInteger(number)) throw new Error('Tar entry is too large.');
  return number;
}

function tarString(bytes) { return bytes.toString('utf8').replace(/\0.*$/, ''); }

function paxValues(bytes) {
  const values = {};
  for (let offset = 0; offset < bytes.length;) {
    const space = bytes.indexOf(32, offset);
    const size = Number(bytes.subarray(offset, space).toString());
    if (space < offset || !Number.isSafeInteger(size) || size < 4 || offset + size > bytes.length) throw new Error('Invalid PAX tar metadata.');
    const record = bytes.subarray(space + 1, offset + size - 1).toString('utf8');
    const equal = record.indexOf('=');
    if (equal < 1) throw new Error('Invalid PAX tar key.');
    values[record.slice(0, equal)] = record.slice(equal + 1);
    offset += size;
  }
  if (Object.keys(values).some((key) => key.includes('sparse') || key === 'SCHILY.filetype')) {
    throw new Error('Sparse and special tar entries are not supported.');
  }
  return values;
}

/** Stream gzip/tar directly into staging; links are created only after regular files. */
export async function extractPayload(archive, destination, { maximumBytes, progress = () => {}, signal } = {}) {
  destination = await realpath(destination);
  const input = createReadStream(archive);
  const gzip = createGunzip();
  input.on('error', (error) => gzip.destroy(error));
  input.pipe(gzip);
  const iterator = gzip[Symbol.asyncIterator]();
  let buffer = Buffer.alloc(0), complete = false;
  const take = async (count, consume) => {
    let remaining = count;
    while (remaining) {
      signal?.throwIfAborted();
      if (!buffer.length) {
        const next = await iterator.next();
        if (next.done) throw new Error('The bundled payload is truncated.');
        buffer = next.value;
      }
      const part = buffer.subarray(0, Math.min(remaining, buffer.length));
      if (consume) await consume(part);
      buffer = buffer.subarray(part.length);
      remaining -= part.length;
    }
  };
  const collect = async (size) => {
    const chunks = [];
    await take(size, (part) => { chunks.push(part); });
    return Buffer.concat(chunks, size);
  };
  const links = [], destinations = new Set();
  let globalPax = {}, nextPax = {}, longName, longLink, total = 0, lastProgress = 0;
  try {
    while (true) {
      const header = await collect(512);
      if (header.every((byte) => byte === 0)) { complete = true; break; }
      const checksum = tarNumber(header.subarray(148, 156));
      const actual = header.reduce((sum, byte, index) => sum + (index >= 148 && index < 156 ? 32 : byte), 0);
      if (checksum !== actual) throw new Error('The bundled tar header checksum is invalid.');
      const type = tarString(header.subarray(156, 157)) || '0';
      let size = tarNumber(header.subarray(124, 136));
      if (['x', 'g', 'L', 'K'].includes(type)) {
        if (size > 1024 * 1024) throw new Error('Tar metadata exceeds the supported size.');
        const body = await collect(size);
        if (type === 'x') nextPax = paxValues(body);
        if (type === 'g') globalPax = { ...globalPax, ...paxValues(body) };
        if (type === 'L') longName = tarString(body);
        if (type === 'K') longLink = tarString(body);
      } else {
        const pax = { ...globalPax, ...nextPax };
        const prefix = tarString(header.subarray(345, 500));
        const name = archivePath(pax.path || longName || `${prefix ? prefix + '/' : ''}${tarString(header.subarray(0, 100))}`);
        const target = join(destination, name);
        if (pax.size !== undefined) {
          size = Number(pax.size);
          if (!Number.isSafeInteger(size) || size < 0) throw new Error('Invalid PAX file size.');
        }
        if (!['0', '5', '1', '2'].includes(type)) throw new Error(`Unsupported tar entry type ${type}: ${name}`);
        if (!name && type !== '5') throw new Error('Empty archive filename.');
        if (name === READY_MARKER || name === '.desktop-install.json') throw new Error('Archive contains a reserved installation marker.');
        if (type !== '5' && destinations.has(name)) throw new Error(`Duplicate archive entry: ${name}`);
        destinations.add(name);
        if (type === '5') {
          await mkdir(target, { recursive: true, mode: 0o755 });
          if (size) throw new Error('Tar directory contains data.');
        } else {
          await mkdir(dirname(target), { recursive: true, mode: 0o755 });
          if (type === '0') {
            total += size;
            if (maximumBytes && total > maximumBytes) throw new Error('Payload exceeds the unpacked size in its manifest.');
            const mode = tarNumber(header.subarray(100, 108));
            const output = await open(target, 'wx', (mode & 0o777) | 0o600);
            try { await take(size, async (part) => { await output.writeFile(part); }); } finally { await output.close(); }
          } else {
            if (size) throw new Error('Tar link contains data.');
            const value = pax.linkpath || longLink || tarString(header.subarray(157, 257));
            if (!value || value.includes('\0') || value.includes('\\') || isAbsolute(value)) throw new Error(`Unsafe link target: ${name}`);
            const resolved = type === '1' ? join(destination, archivePath(value)) : resolve(dirname(target), value);
            if (!inside(destination, resolved)) throw new Error(`Archive link escapes its workspace: ${name}`);
            links.push({ target, value, resolved, type });
          }
        }
        nextPax = {}; longName = undefined; longLink = undefined;
        if (Date.now() - lastProgress >= 250) { progress(total); lastProgress = Date.now(); }
      }
      await take((512 - size % 512) % 512);
    }
    // Drain the gzip trailer as well, so CRC errors cannot produce a completed install.
    for await (const _chunk of { [Symbol.asyncIterator]: () => iterator }) { signal?.throwIfAborted(); }
    for (const item of links.filter((item) => item.type === '1')) {
      if (!(await lstat(item.resolved)).isFile()) throw new Error('Archive hardlink must point to a regular bundled file.');
      await link(item.resolved, item.target);
    }
    for (const item of links.filter((item) => item.type === '2')) await symlink(item.value, item.target);
    for (const item of links) {
      if (!inside(destination, await realpath(item.target))) throw new Error('Archive link resolves outside its workspace.');
    }
    progress(total);
    return total;
  } finally {
    input.destroy(); gzip.destroy();
    if (!complete) await iterator.return?.().catch(() => {});
  }
}

export async function installedWorkspace(workspaces, manifest) {
  const target = join(workspaces, manifest.payload.sha256);
  try {
    if (!(await lstat(target)).isDirectory()) return null;
    const marker = JSON.parse(await readFile(join(target, READY_MARKER), 'utf8'));
    if (marker.schema !== SCHEMA || marker.payloadSha256 !== manifest.payload.sha256) return null;
    await access(join(target, 'webapp/server/start.mjs'), constants.R_OK);
    await access(join(target, '.runtime/simnibs-4.6.0/bin/python'), constants.X_OK);
    return target;
  } catch (error) {
    if (['EACCES', 'EPERM'].includes(error.code)) throw error;
    return null;
  }
}

export async function installWorkspace({ userData, manifest, progress = () => {}, signal }) {
  userData = await realpath(userData);
  const workspaces = await managedDirectory(userData, 'workspaces');
  const existing = await installedWorkspace(workspaces, manifest);
  if (existing) { progress('Opening the installed workspace', 0.8); return { workspace: existing, reused: true }; }
  progress('Verifying the bundled scientific workspace', 0.08);
  if (await sha256(manifest.payloadPath) !== manifest.payload.sha256) {
    throw new Error('The bundled payload failed SHA-256 verification. Reinstall EEG Layout Lab from a complete application bundle.');
  }
  signal?.throwIfAborted();
  const space = await statfs(workspaces);
  // Small Python/Node files occupy whole filesystem blocks; logical tar bytes
  // alone undercount installation space. Include metadata and allocation slack.
  const required = manifest.payload.unpackedBytes + 512 * 1024 * 1024;
  if (space.bavail * space.bsize < required) throw new Error(`Insufficient disk space. At least ${(required / 1024 ** 3).toFixed(1)} GB is required for the first launch.`);
  const hash = manifest.payload.sha256;
  // Only unexposed staging folders carrying our own installation record are disposable.
  for (const name of await readdir(workspaces)) {
    if (!STAGE_NAME.test(name) || !name.startsWith(`.install-${hash}-`)) continue;
    const stale = join(workspaces, name);
    if (!(await lstat(stale)).isDirectory()) continue;
    let record;
    try { record = JSON.parse(await readFile(join(stale, '.desktop-install.json'), 'utf8')); } catch { continue; }
    if (record.schema === SCHEMA && record.payloadSha256 === hash) await rm(stale, { recursive: true });
  }
  const destination = join(workspaces, hash);
  try {
    await lstat(destination);
    const recovered = await managedDirectory(userData, 'recovered');
    await rename(destination, join(recovered, `${hash}-${Date.now()}-${randomUUID()}`));
    progress('Preserved an incomplete workspace in the recovered folder', 0.16);
  } catch (error) { if (error.code !== 'ENOENT') throw error; }
  const staging = join(workspaces, `.install-${hash}-${randomUUID()}`);
  await mkdir(staging, { mode: 0o700 });
  await writeFile(join(staging, '.desktop-install.json'), JSON.stringify({ schema: SCHEMA, payloadSha256: hash }), { flag: 'wx' });
  try {
    progress('Preparing the offline Python runtime and scientific data', 0.18);
    const bytes = await extractPayload(manifest.payloadPath, staging, {
      maximumBytes: manifest.payload.unpackedBytes + 32 * 1024 * 1024,
      signal,
      progress: (unpacked) => progress('Preparing the offline Python runtime and scientific data', Math.min(0.76, 0.18 + 0.58 * unpacked / manifest.payload.unpackedBytes)),
    });
    await access(join(staging, 'webapp/server/start.mjs'), constants.R_OK);
    await access(join(staging, '.runtime/simnibs-4.6.0/bin/python'), constants.X_OK);
    await mkdir(join(staging, 'results'), { recursive: true, mode: 0o755 });
    await chmod(join(staging, 'results'), 0o755);
    await writeFile(join(staging, READY_MARKER), JSON.stringify({ schema: SCHEMA, payloadSha256: hash, version: manifest.version, unpackedBytes: bytes, installedAt: new Date().toISOString() }), { flag: 'wx' });
    signal?.throwIfAborted();
    await rename(staging, destination);
    progress('Scientific workspace is ready', 0.8);
    return { workspace: destination, reused: false };
  } catch (error) {
    await rm(staging, { recursive: true, force: true }).catch(() => {});
    throw error;
  }
}

export function cleanEnvironment(source, workspace, userData, nodePath) {
  const result = {};
  for (const name of ['HOME', 'TMPDIR', 'LANG', 'LC_ALL', 'LC_CTYPE', 'TZ', 'USER', 'LOGNAME', 'SHELL']) {
    if (source[name] !== undefined) result[name] = source[name];
  }
  const runtime = join(workspace, '.runtime/simnibs-4.6.0');
  Object.assign(result, {
    PATH: [join(runtime, 'bin'), dirname(nodePath), '/usr/bin', '/bin', '/usr/sbin', '/sbin'].join(':'),
    EEG_COMPUTE_PYTHON: join(runtime, 'bin/python'),
    PYTHONNOUSERSITE: '1', PYTHONDONTWRITEBYTECODE: '1', PYTHONUNBUFFERED: '1',
    NODE_ENV: 'production', PORT: '0', HOST: '127.0.0.1',
    OMP_NUM_THREADS: '2', OPENBLAS_NUM_THREADS: '2', MKL_NUM_THREADS: '2',
    NUMEXPR_NUM_THREADS: '2', VECLIB_MAXIMUM_THREADS: '2',
    MPLCONFIGDIR: join(userData, 'cache', 'matplotlib'), XDG_CACHE_HOME: join(userData, 'cache'),
    EEG_DESKTOP_WORKSPACE: workspace, EEG_DESKTOP_USER_DATA: userData,
  });
  return result;
}

export async function atomicJson(file, value) {
  const temporary = join(dirname(file), `.${basename(file)}-${randomUUID()}.tmp`);
  await writeFile(temporary, JSON.stringify(value), { flag: 'wx', mode: 0o600 });
  await rename(temporary, file);
}

export function pidAlive(pid) {
  if (!Number.isSafeInteger(pid) || pid <= 1) return false;
  try { process.kill(pid, 0); return true; } catch (error) { return error.code === 'EPERM'; }
}

export async function loopbackHealthy(url, { desktop = false } = {}) {
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== 'http:' || parsed.hostname !== '127.0.0.1' || !parsed.port || parsed.pathname !== '/' || parsed.username || parsed.password || parsed.search || parsed.hash) return false;
    const response = await fetch(new URL(desktop ? '/api/desktop/health' : '/api/local-compute/health', url), { signal: AbortSignal.timeout(1500), redirect: 'error' });
    if (!response.ok) return false;
    const body = await response.json();
    return desktop ? body.desktop === SCHEMA : body.local_only === true && body.available === true;
  } catch { return false; }
}
