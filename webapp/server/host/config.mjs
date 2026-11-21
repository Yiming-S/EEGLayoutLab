import { existsSync } from 'node:fs';
import { isAbsolute, resolve } from 'node:path';
import { repositoryRootForWebapp } from '../project-paths.mjs';
import { createAccessPolicy } from '../http/access-policy.mjs';
import { operationsConfig } from '../operations/config.mjs';
import { libraryConfig } from '../library/record-visibility.mjs';

export function hostConfig({ webappRoot, env = process.env, ...options }) {
  const port = options.port ?? Number(env.PORT || 3000);
  if (!Number.isInteger(port) || port < 0 || port > 65535) throw new Error('Invalid PORT.');
  const selectedRoot = options.repositoryRoot || env.EEG_REPOSITORY_ROOT;
  if (selectedRoot && !isAbsolute(selectedRoot)) throw new Error('EEG_REPOSITORY_ROOT must be absolute.');
  const root = resolve(selectedRoot || repositoryRootForWebapp(webappRoot));
  if (!existsSync(root)) throw new Error('The scientific repository root does not exist.');
  if (env.EEG_MAINTENANCE !== undefined && !['0', '1'].includes(env.EEG_MAINTENANCE)) throw new Error('EEG_MAINTENANCE must be 0 or 1.');
  const initialMaintenance = options.initialMaintenance ?? env.EEG_MAINTENANCE === '1';
  if (typeof initialMaintenance !== 'boolean') throw new Error('initialMaintenance must be boolean.');
  const policy = createAccessPolicy({ publicOrigin: options.publicOrigin ?? env.EEG_PUBLIC_ORIGIN,
    trustedProxyAddresses: options.trustedProxyAddresses ?? (env.EEG_TRUSTED_PROXIES || '').split(',').map(ip => ip.trim()).filter(Boolean) });
  return { port, repositoryRoot: root, queueDirectory: options.queueDirectory ?? env.EEG_QUEUE_DIRECTORY,
    python: options.python ?? env.EEG_COMPUTE_PYTHON, initialMaintenance, policy, operations: options.operations ?? operationsConfig(env),
    library: options.library ?? libraryConfig(env) };
}
