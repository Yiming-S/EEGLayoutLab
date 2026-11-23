#!/usr/bin/env node
// Builds the read-only showcase into showcase-dist/ (npm run build:showcase).
//
// The interface is built with EEG_SHOWCASE=1, and the data written by build-showcase-data.mjs
// (showcase/api) is copied to showcase-dist/showcase-api. Pre-compressed .br/.gz sidecars are left out:
// static hosts compress on their own. The site must be served at the root of its domain, because the
// interface links to /design, /data/… and /models/… with absolute paths.
//
// The application's own build in dist/ is set aside during the build and put back afterwards.
import { spawnSync } from 'node:child_process';
import { cp, readdir, rename, rm, stat } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const webapp = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const dist = join(webapp, 'dist'), saved = join(webapp, 'dist.app-build'), out = join(webapp, 'showcase-dist');
const data = join(webapp, 'showcase', 'api');
const exists = (path) => stat(path).then(() => true, () => false);

if (!(await exists(join(data, 'index.json'))))
  throw new Error('showcase/api/index.json is missing; run scripts/build-showcase-data.mjs first');
if (await exists(saved)) throw new Error(`${saved} exists from an interrupted build; move it back to dist/ or remove it`);

const hadApp = await exists(dist);
if (hadApp) await rename(dist, saved);
try {
  const vinext = join(webapp, 'node_modules', '.bin', 'vinext');
  const build = spawnSync(vinext, ['build'], { cwd: webapp, stdio: 'inherit', env: { ...process.env, EEG_SHOWCASE: '1' } });
  if (build.status !== 0) throw new Error(`vinext build failed (${build.status ?? build.signal})`);
  await rm(out, { recursive: true, force: true });
  await cp(join(dist, 'client'), out, { recursive: true, filter: (source) => !/\.(?:br|gz)$/.test(source) });
  await cp(data, join(out, 'showcase-api'), { recursive: true });
} finally {
  await rm(dist, { recursive: true, force: true });
  if (hadApp) await rename(saved, dist);
}

let files = 0, bytes = 0;
const walk = async (dir) => {
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) await walk(path);
    else { files += 1; bytes += (await stat(path)).size; }
  }
};
await walk(out);
console.log(`showcase: ${files} files, ${(bytes / 1048576).toFixed(1)} MiB in ${out}`);
