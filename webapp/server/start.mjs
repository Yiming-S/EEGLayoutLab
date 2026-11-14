/** Production entry point: framework adapters and service configuration are separate. */
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';
import { createLocalComputeService } from './local-compute-server.mjs';
import { startProductionHost } from './host/vinext.mjs';
import { hostConfig } from './host/config.mjs';
import { installOperatorSignals } from './host/operator-signals.mjs';
export { attachLocalApi } from './host/vinext.mjs';

export async function startLocalApp(options = {}) {
  const webappRoot = fileURLToPath(new URL('../', import.meta.url));
  const config = hostConfig({ webappRoot, ...options });
  const service = createLocalComputeService(config.repositoryRoot, config);
  try {
    const started = await startProductionHost({ webappRoot, port: config.port, service });
    return { ...started, service };
  } catch (error) { await service.dispose(); throw error; }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const { server, port, service } = await startLocalApp();
  console.log(`EEG Layout Lab: http://127.0.0.1:${port} (PID ${process.pid})`);
  const removeSignals = installOperatorSignals(service);
  let stopping;
  const stop = () => {
    if (stopping) return stopping;
    removeSignals(); server.close(); server.closeAllConnections();
    stopping = Promise.resolve(service.dispose()).catch(() => { process.exitCode = 1; });
    return stopping;
  };
  process.once('SIGINT', stop); process.once('SIGTERM', stop);
}
