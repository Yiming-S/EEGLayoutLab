import { randomUUID } from 'node:crypto';
import { mkdir, open, readFile, readdir, realpath, rename, unlink } from 'node:fs/promises';
import { dirname, isAbsolute, join, relative, resolve, sep } from 'node:path';

export const RECORD_DIRECTORIES = Object.freeze({
  radius: 'results/v2/local_app_jobs',
  design: 'results/v2/design_evaluation_jobs',
  editor: 'results/v2/electrode_editor_jobs',
  source: 'results/v2/source_reception_jobs',
  sourceV2: 'results/v2/source_reception_v2_jobs',
});

/** Atomic JSON replacement; a failed write never replaces the last valid file. */
export async function atomicJson(path, value) {
  const temporary = `${path}.${randomUUID()}.tmp`;
  try {
    const bytes = JSON.stringify(value);
    const file = await open(temporary, 'wx', 0o600);
    try { await file.writeFile(bytes); await file.sync(); } finally { await file.close(); }
    await rename(temporary, path);
    const directory = await open(dirname(path), 'r');
    try { await directory.sync(); } finally { await directory.close(); }
  } finally {
    await unlink(temporary).catch(error => { if (error.code !== 'ENOENT') throw error; });
  }
}

/** Wrap the existing record layout. Scientific validation stays in each workflow. */
export class RecordStore {
  constructor(repositoryRoot) { this.root = resolve(repositoryRoot); }

  directory(kind) {
    const path = RECORD_DIRECTORIES[kind];
    if (!path) throw new Error(`Unknown record kind: ${kind}`);
    return join(this.root, path);
  }

  path(kind, key, ...parts) {
    if (!/^[a-f0-9]{64}$/.test(key)) throw new Error('Invalid scientific record key.');
    const base = join(this.directory(kind), key), path = join(base, ...parts);
    const suffix = relative(base, path);
    if (isAbsolute(suffix) || suffix === '..' || suffix.startsWith('..' + sep)) throw new Error('Record path leaves its directory.');
    return path;
  }

  async contained(path) {
    const root = await realpath(this.root), target = await realpath(path);
    if (!target.startsWith(root + sep)) throw new Error('Record path leaves the repository.');
    return target;
  }

  async read(path) { return JSON.parse(await readFile(await this.contained(path), 'utf8')); }

  async write(path, value) {
    const root = await realpath(this.root), parent = await realpath(dirname(path));
    if (!parent.startsWith(root + sep)) throw new Error('Record path leaves the repository.');
    await atomicJson(path, value);
  }

  async createBatch(kind, key, id) {
    if (!/^[a-f0-9-]{36}$/.test(id)) throw new Error('Invalid batch identifier.');
    const path = this.path(kind, key, id);
    // Verify each existing ancestor before creating a directory through it.
    const root = await realpath(this.root);
    let cursor = this.root;
    for (const part of relative(this.root, path).split(sep)) {
      cursor = join(cursor, part);
      await mkdir(cursor).catch(error => { if (error.code !== 'EEXIST') throw error; });
      const actual = await realpath(cursor);
      if (!actual.startsWith(root + sep)) throw new Error('Record directory leaves the repository.');
    }
    return path;
  }

  async keys(kind) {
    const directory = this.directory(kind);
    try {
      const path = await this.contained(directory);
      return (await readdir(path, { withFileTypes: true }))
        .filter(entry => entry.isDirectory() && /^[a-f0-9]{64}$/.test(entry.name)).map(entry => entry.name);
    } catch (error) { if (error.code === 'ENOENT') return []; throw error; }
  }
}
