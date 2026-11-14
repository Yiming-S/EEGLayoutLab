import { resolve } from 'node:path';
import { startProdServer } from 'vinext/server/prod-server';

export function attachLocalApi(server, service) {
  const handlers = server.listeners('request');
  if (handlers.length !== 1) throw new Error('Expected one Vinext request handler.');
  server.removeListener('request', handlers[0]);
  server.on('request', (req, res) => {
    void service.middleware(req, res, () => handlers[0].call(server, req, res));
  });
  server.once('close', () => service.dispose());
}

export async function startProductionHost({ webappRoot, port, service }) {
  const started = await startProdServer({ port, host: '127.0.0.1', outDir: resolve(webappRoot, 'dist'), silent: true });
  attachLocalApi(started.server, service);
  return started;
}
