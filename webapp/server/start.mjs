/** Production UI and local Python API on the same loopback-only HTTP server. */
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';
import { startProdServer } from 'vinext/server/prod-server';
import { createLocalComputeService } from './local-compute-server.mjs';
import { repositoryRootForWebapp } from './project-paths.mjs';

export function attachLocalApi(server, service) {
  const handlers = server.listeners('request');
  if (handlers.length !== 1) throw new Error('Expected one Vinext request handler.');
  server.removeListener('request', handlers[0]);
  server.on('request', (req, res) => {
    void service.middleware(req, res, () => handlers[0].call(server, req, res));
  });
  server.once('close', () => service.dispose());
}

export async function startLocalApp({ port = Number(process.env.PORT || 3000) } = {}) {
  if (!Number.isInteger(port) || port < 0 || port > 65535) throw new Error('Invalid PORT.');
  const webappRoot = fileURLToPath(new URL('../', import.meta.url));
  const service = createLocalComputeService(repositoryRootForWebapp(webappRoot));
  try {
    const started = await startProdServer({ port, host: '127.0.0.1', outDir: resolve(webappRoot, 'dist'), silent: true });
    attachLocalApi(started.server, service);
    return { ...started, service };
  } catch (error) {
    service.dispose();
    throw error;
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const { server, port, service } = await startLocalApp();
  console.log(`EEG Layout Lab: http://127.0.0.1:${port} (local UI and computation)`);
  const stop = () => {
    service.dispose();
    server.close();
    server.closeAllConnections();
  };
  process.once('SIGINT', stop);
  process.once('SIGTERM', stop);
}
