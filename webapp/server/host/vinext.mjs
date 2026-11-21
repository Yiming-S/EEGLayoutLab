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
  // Request bodies are at most 64 KB; a client that trickles one ties up a socket.
  // Node's defaults (300 s per request, 60 s for headers) are far longer than any API needs.
  started.server.requestTimeout = 30000;
  started.server.headersTimeout = 15000;
  started.server.keepAliveTimeout = 5000;
  attachLocalApi(started.server, service);
  return started;
}
