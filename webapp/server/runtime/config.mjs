import { existsSync } from 'node:fs';
import { isAbsolute, join, resolve } from 'node:path';
import { nativePythonPath, tablePythonPath } from '../project-paths.mjs';

/** The managed interpreter of this checkout: the SimNIBS runtime, else the Linux table runtime. */
export function managedPython(root) {
  const native = nativePythonPath(root), table = tablePythonPath(root);
  return existsSync(native) ? native : existsSync(table) ? table : null;
}

/** One explicit checkout configuration; default interpreter precedence is preserved. */
export function runtimeConfig({ repositoryRoot, python, queueDirectory, env = process.env } = {}) {
  if (typeof repositoryRoot !== 'string' || !repositoryRoot.trim()) throw new Error('A repository root is required.');
  const root = resolve(repositoryRoot);
  const native = managedPython(root);
  const computePython = python || env.EEG_COMPUTE_PYTHON || native || 'python3';
  const selectedQueue = queueDirectory || env.EEG_QUEUE_DIRECTORY || join(root, 'results/web-service');
  if (!isAbsolute(selectedQueue)) throw new Error('The queue directory must be absolute.');
  return Object.freeze({
    repositoryRoot: root,
    python: computePython,
    // Existing native services select the managed environment when present.
    nativePython: native ?? computePython,
    queueDirectory: resolve(selectedQueue),
  });
}
