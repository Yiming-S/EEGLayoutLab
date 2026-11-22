import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { buildResearchDelivery, MAX_DELIVERY_BYTES } from './research-bundle.mjs';
import { tablePythonPath } from '../project-paths.mjs';
import { managedPython } from '../runtime/config.mjs';

const digest = bytes => createHash('sha256').update(bytes).digest('hex');
const fail = (message, status = 503) => Object.assign(new Error(message), { status, projectSafe: true });
const hostFiles = ['webapp/package.json', 'webapp/package-lock.json', 'webapp/server/projects/store.mjs',
  'webapp/server/projects/service.mjs', 'webapp/server/delivery/research-bundle.mjs', 'webapp/server/delivery/project-delivery.mjs'];

/** The lock of the managed runtime in use: the Linux table runtime has its own; otherwise the macOS lock. */
export const runtimeLockPath = scientificRoot => managedPython(resolve(scientificRoot)) === tablePythonPath(resolve(scientificRoot))
  ? 'configs/runtime/manifest-linux-64.json' : 'configs/runtime/manifest.json';

/** The exporter identifies the current host; each saved payload retains its own calculation identity. */
export async function deliveryVersions(scientificRoot, sourceRoot = resolve(import.meta.dirname, '../../..')) {
  try {
    const [dataBytes, runtimeBytes, ...sourceBytes] = await Promise.all([
      readFile(resolve(scientificRoot, 'data/manifest.json')), readFile(resolve(scientificRoot, runtimeLockPath(scientificRoot))),
      ...hostFiles.map(path => readFile(resolve(sourceRoot, path))),
    ]);
    const data = JSON.parse(dataBytes), runtime = JSON.parse(runtimeBytes), application = JSON.parse(sourceBytes[0]);
    if (data.schema_version !== 'eeglayoutlab-data-bundle/1' || typeof data.bundle_id !== 'string' || !data.bundle_id ||
      runtime.schema !== 'eeglayoutlab-runtime-lock/1' || typeof application.version !== 'string' || !application.version) throw new Error('Missing version identity');
    return { application_version: application.version, data_manifest_sha256: digest(dataBytes), data_bundle_id: data.bundle_id,
      runtime_lock_sha256: digest(runtimeBytes), source_files: hostFiles.map((path, i) => ({ path, sha256: digest(sourceBytes[i]) })) };
  } catch { throw fail('Delivery version information is unavailable. Verify the application, model manifest and runtime lock.'); }
}

export class ProjectDelivery {
  constructor({ store, scientificRoot, versions = () => deliveryVersions(scientificRoot), maximumBytes = MAX_DELIVERY_BYTES } = {}) {
    this.store = store; this.versions = versions; this.maximumBytes = maximumBytes; this.active = false;
  }
  async export(id, key) {
    if (this.active) throw fail('Another research delivery is being prepared. Try again shortly.', 429);
    this.active = true;
    try {
      const saved = await this.store.readSnapshots(id, key, { maxBytes: this.maximumBytes });
      return buildResearchDelivery(saved, await this.versions(), { maxBytes: this.maximumBytes });
    } finally { this.active = false; }
  }
}
