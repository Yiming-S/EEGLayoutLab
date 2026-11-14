import { existsSync } from 'node:fs';
import { isAbsolute, join, resolve } from 'node:path';
import { nativePythonPath } from '../project-paths.mjs';

/** One explicit checkout configuration; default interpreter precedence is preserved. */
export function runtimeConfig({ repositoryRoot, python, queueDirectory, env = process.env } = {}) {
  if (typeof repositoryRoot !== 'string' || !repositoryRoot.trim()) throw new Error('A repository root is required.');
  const root = resolve(repositoryRoot);
  const native = nativePythonPath(root);
  const computePython = python || env.EEG_COMPUTE_PYTHON || (existsSync(native) ? native : 'python3');
  const selectedQueue = queueDirectory || env.EEG_QUEUE_DIRECTORY || join(root, 'results/web-service');
  if (!isAbsolute(selectedQueue)) throw new Error('The queue directory must be absolute.');
  return Object.freeze({
    repositoryRoot: root,
    python: computePython,
    // Existing native services select the managed environment when present.
    nativePython: existsSync(native) ? native : computePython,
    queueDirectory: resolve(selectedQueue),
  });
}
