#!/usr/bin/env node
/** Native-shell JSON-lines protocol and offline local-server supervisor. */
import { spawn } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { createWriteStream } from 'node:fs';
import { lstat, mkdir, readFile, rename, rm, writeFile } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import {
  SCHEMA, atomicJson, cleanEnvironment, inside, installWorkspace, loopbackHealthy,
  managedDirectory, pidAlive, readManifest, userDataDirectory,
} from './bootstrap-support.mjs';

const SELF = fileURLToPath(import.meta.url);
const delay = (ms) => new Promise((accept) => setTimeout(accept, ms));
const send = (value) => process.stdout.write(`${JSON.stringify(value)}\n`);

function killGroup(pid, signal) {
  if (!Number.isSafeInteger(pid) || pid <= 1) return;
  try { process.kill(-pid, signal); } catch (error) { if (error.code !== 'ESRCH') throw error; }
}

async function serve() {
  if (!process.send || !process.connected) throw new Error('The desktop server must be launched by its supervisor.');
  const workspace = process.env.EEG_DESKTOP_WORKSPACE;
  const userData = process.env.EEG_DESKTOP_USER_DATA;
  if (!workspace || !userData || !inside(join(userData, 'workspaces'), workspace)) throw new Error('Invalid desktop workspace.');
  let server, service, stopping = false;
  const stop = () => {
    if (stopping) return;
    stopping = true;
    try { service?.dispose(); } catch (error) { console.error('Service disposal:', error); }
    server?.close();
    server?.closeAllConnections();
    // If the supervisor was terminated abruptly, this child still owns its whole group.
    // The signal also reaches Python and any meshing workers that inherited the group.
    killGroup(process.pid, 'SIGTERM');
    setTimeout(() => killGroup(process.pid, 'SIGKILL'), 2500).unref();
    if (process.connected) process.disconnect();
  };
  process.on('SIGTERM', stop);
  process.on('SIGINT', stop);
  process.once('disconnect', stop);
  process.on('message', (message) => { if (message?.type === 'stop') stop(); });
  const { startLocalApp } = await import(pathToFileURL(join(workspace, 'webapp/server/start.mjs')).href);
  const remembered = Number(process.env.EEG_DESKTOP_PREFERRED_PORT || 0);
  const preferredPort = Number.isInteger(remembered) && remembered > 0 && remembered <= 65535 ? remembered : 0;
  let started;
  try { started = await startLocalApp({ port: preferredPort }); }
  catch (error) {
    if (!preferredPort || error.code !== 'EADDRINUSE') throw error;
    console.error(`Remembered loopback port ${preferredPort} is occupied; allocating a new local port.`);
    started = await startLocalApp({ port: 0 });
  }
  ({ server, service } = started);
  if (stopping) { service?.dispose(); server.close(); server.closeAllConnections(); return; }
  const address = server.address();
  if (!address || typeof address === 'string' || address.address !== '127.0.0.1') throw new Error('The desktop server did not bind exclusively to IPv4 loopback.');
  const handlers = server.listeners('request');
  server.removeAllListeners('request');
  server.on('request', (request, response) => {
    if (request.url === '/api/desktop/health') {
      const host = `127.0.0.1:${address.port}`;
      if (request.method !== 'GET' || request.socket.remoteAddress !== '127.0.0.1' || request.headers.host !== host ||
          (request.headers.origin && request.headers.origin !== `http://${host}`)) {
        response.writeHead(403); response.end(); return;
      }
      response.writeHead(200, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' });
      response.end(JSON.stringify({ desktop: SCHEMA }));
      return;
    }
    for (const handler of handlers) handler.call(server, request, response);
  });
  const url = `http://127.0.0.1:${address.port}/`;
  if (!await loopbackHealthy(url)) throw new Error('The local compute service did not pass its startup health check.');
  if (process.connected && !stopping) process.send({ type: 'ready', url });
}

async function main() {
  const controller = new AbortController();
  const originalParent = process.ppid;
  let child, log, logPath, lock, statePath, stopping = false, parentWatch, release, shutdownPromise;
  const record = (message) => { if (log) log.write(`${new Date().toISOString()} ${message}\n`); };
  const shutdown = (code = 0) => {
    if (shutdownPromise) return shutdownPromise;
    stopping = true;
    controller.abort(new Error('Desktop startup was cancelled.'));
    shutdownPromise = (async () => {
      clearInterval(parentWatch);
      record('Stopping desktop server and workers.');
      if (child?.pid) {
        if (child.connected) child.send({ type: 'stop' }, () => {});
        killGroup(child.pid, 'SIGTERM');
        for (let index = 0; index < 20; index++) {
          try { process.kill(-child.pid, 0); } catch { break; }
          await delay(100);
        }
        killGroup(child.pid, 'SIGKILL');
      }
      if (statePath && release) await rm(statePath, { force: true }).catch(() => {});
      if (release) await release();
      if (log) await new Promise((accept) => log.end(accept));
      process.exitCode = code;
    })();
    return shutdownPromise;
  };
  const requestStop = () => {
    stopping = true;
    controller.abort(new Error('Desktop startup was cancelled.'));
    // Installation must unwind before releasing its lock, or a second launch could
    // start writing while this process is still extracting into staging.
    if (child) void shutdown();
  };
  process.once('SIGINT', requestStop);
  process.once('SIGTERM', requestStop);
  // Swift is the owning process; parent disappearance must also close computation.
  parentWatch = setInterval(() => {
    if (process.ppid !== originalParent || !pidAlive(originalParent)) requestStop();
  }, 1000);
  try {
    const userData = await userDataDirectory();
    const logs = await managedDirectory(userData, 'logs');
    logPath = join(logs, `desktop-${new Date().toISOString().replace(/[:.]/g, '-')}-${process.pid}.log`);
    log = createWriteStream(logPath, { flags: 'wx', mode: 0o600 });
    await new Promise((accept, reject) => { log.once('open', accept); log.once('error', reject); });
    record('Starting EEG Layout Lab desktop bootstrap.');
    const resources = resolve(process.env.EEG_DESKTOP_RESOURCES || join(dirname(SELF), '..'));
    const manifest = await readManifest(resources);
    const runtime = await managedDirectory(userData, 'run');
    const preferredPortPath = join(runtime, 'preferred-port.json');
    lock = join(runtime, 'desktop.lock');
    statePath = join(runtime, 'server.json');
    const token = randomUUID();
    const deadline = Date.now() + 30 * 60 * 1000;
    let waitingMessage = false;
    while (!release) {
      controller.signal.throwIfAborted();
      try {
        await mkdir(lock, { mode: 0o700 });
        await writeFile(join(lock, 'owner.json'), JSON.stringify({ schema: SCHEMA, pid: process.pid, token }), { flag: 'wx', mode: 0o600 });
        release = async () => {
          try {
            const owner = JSON.parse(await readFile(join(lock, 'owner.json'), 'utf8'));
            if (owner.token === token) await rm(lock, { recursive: true });
          } catch (error) { if (error.code !== 'ENOENT') record(`Lock release: ${error.message}`); }
        };
      } catch (error) {
        if (error.code !== 'EEXIST') throw error;
        if (!(await lstat(lock)).isDirectory()) throw new Error('Desktop lock is not a regular directory.');
        let owner;
        try { owner = JSON.parse(await readFile(join(lock, 'owner.json'), 'utf8')); } catch { /* A new owner can be between mkdir and write. */ }
        if (owner && pidAlive(owner.pid)) {
          let existing;
          try { existing = JSON.parse(await readFile(statePath, 'utf8')); } catch { /* Installation is still underway. */ }
          if (existing?.ownerToken === owner.token && existing.payloadSha256 === manifest.payload.sha256 && await loopbackHealthy(existing.url, { desktop: true })) {
            record(`Reusing active desktop server ${existing.url}`);
            send({ type: 'ready', url: existing.url, reused: true, sharedServer: true });
            clearInterval(parentWatch);
            await new Promise((accept) => log.end(accept));
            return;
          }
        } else if (owner || Date.now() - (await lstat(lock)).mtimeMs > 5000) {
          // An exclusive reclaim file prevents simultaneous launches from moving a
          // newly acquired lock after both observed the same dead previous owner.
          const reclaim = join(runtime, 'reclaim.json');
          let claimed = false;
          try {
            await writeFile(reclaim, JSON.stringify({ pid: process.pid }), { flag: 'wx', mode: 0o600 });
            claimed = true;
            let latest;
            try { latest = JSON.parse(await readFile(join(lock, 'owner.json'), 'utf8')); } catch { /* Check an incomplete owner's age below. */ }
            const staleOwner = latest ? !pidAlive(latest.pid) : Date.now() - (await lstat(lock)).mtimeMs > 5000;
            if (staleOwner) {
              const stale = join(runtime, `.stale-lock-${randomUUID()}`);
              try { await rename(lock, stale); await rm(stale, { recursive: true }); } catch (failure) { if (failure.code !== 'ENOENT') throw failure; }
            }
          } catch (failure) {
            if (failure.code !== 'EEXIST' && failure.code !== 'ENOENT') throw failure;
            if (failure.code === 'EEXIST') {
              try {
                const reclaimer = JSON.parse(await readFile(reclaim, 'utf8'));
                if (!pidAlive(reclaimer.pid) && Date.now() - (await lstat(reclaim)).mtimeMs > 5000) await rm(reclaim);
              } catch { /* Another contender is completing reclamation. */ }
            }
          } finally { if (claimed) await rm(reclaim, { force: true }); }
          await delay(50);
          continue;
        }
        if (Date.now() > deadline) throw new Error('Another desktop instance is still preparing its workspace. Quit that instance and open EEG Layout Lab again.');
        if (!waitingMessage) { send({ type: 'progress', message: 'Waiting for the existing application to finish preparation', fraction: 0.02 }); waitingMessage = true; }
        await delay(250);
      }
    }
    await rm(statePath, { force: true });
    const progress = (message, fraction) => {
      if (!stopping) send({ type: 'progress', message, fraction });
      record(`${Math.round(fraction * 100)}% ${message}`);
    };
    const { workspace, reused } = await installWorkspace({ userData, manifest, progress, signal: controller.signal });
    controller.signal.throwIfAborted();
    await managedDirectory(userData, 'cache');
    await managedDirectory(userData, 'cache/matplotlib');
    progress('Starting the local application', 0.88);
    const environment = cleanEnvironment(process.env, workspace, userData, process.execPath);
    try {
      const preferred = JSON.parse(await readFile(preferredPortPath, 'utf8'));
      if (Number.isInteger(preferred.port) && preferred.port > 0 && preferred.port <= 65535) environment.EEG_DESKTOP_PREFERRED_PORT = String(preferred.port);
    } catch { /* The first launch allocates an ephemeral loopback port. */ }
    child = spawn(process.execPath, [SELF, '--serve'], {
      cwd: workspace, env: environment,
      detached: true, stdio: ['ignore', 'pipe', 'pipe', 'ipc'],
    });
    child.stdout.on('data', (chunk) => log.write(chunk));
    child.stderr.on('data', (chunk) => log.write(chunk));
    const ready = await new Promise((accept, reject) => {
      const timer = setTimeout(() => reject(new Error('The local application did not become ready within 120 seconds.')), 120_000);
      const finish = (error, result) => { clearTimeout(timer); error ? reject(error) : accept(result); };
      child.once('error', (error) => finish(error));
      child.once('exit', (code, signal) => finish(new Error(`Local application exited during startup (${signal || code}). See ${logPath}`)));
      child.on('message', (message) => {
        if (message?.type === 'ready') finish(null, message);
        if (message?.type === 'error') finish(new Error(message.message));
      });
    });
    controller.signal.throwIfAborted();
    if (!await loopbackHealthy(ready.url, { desktop: true })) throw new Error('The application failed its loopback readiness check.');
    controller.signal.throwIfAborted();
    await atomicJson(preferredPortPath, { port: Number(new URL(ready.url).port) });
    await atomicJson(statePath, { schema: SCHEMA, ownerToken: token, pid: process.pid, serverPid: child.pid, payloadSha256: manifest.payload.sha256, url: ready.url });
    if (controller.signal.aborted) {
      await rm(statePath, { force: true });
      controller.signal.throwIfAborted();
    }
    record(`Ready ${ready.url} (${reused ? 'reused' : 'new'} workspace ${workspace})`);
    send({ type: 'progress', message: 'Application ready', fraction: 1 });
    send({ type: 'ready', url: ready.url, workspace, logPath, reused });
    child.once('exit', (code, signal) => {
      if (!stopping) {
        const message = `The local application stopped unexpectedly (${signal || code}).`;
        record(message); send({ type: 'error', message, logPath });
        void shutdown(1);
      }
    });
  } catch (error) {
    if (!stopping) {
      record(error.stack || error.message);
      send({ type: 'error', message: error.message, ...(logPath ? { logPath } : {}) });
    }
    await shutdown(stopping ? 0 : 1);
  }
}

if (process.argv[2] === '--serve') {
  serve().catch((error) => {
    console.error(error.stack || error.message);
    if (process.connected) process.send({ type: 'error', message: error.message });
    process.exitCode = 1;
    // Terminate descendants even when initialization fails after workers were created.
    killGroup(process.pid, 'SIGTERM');
  });
} else {
  await main();
}
