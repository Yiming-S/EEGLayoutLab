import { readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import tailwindcss from '@tailwindcss/postcss';
import vinext from 'vinext';
import { defineConfig, type Plugin, type ProxyOptions } from 'vite';
import { checkedRuntime, serviceOrigin } from './scripts/helpers/service-session.mjs';

// The development server forwards /api and /open to the Python service (eeglayoutlab serve), which listens on
// 127.0.0.1 only (not localhost or [::1]). EEG_API_TARGET names its origin; otherwise EEG_WORKSPACE names the
// workspace it serves, whose .eeglayoutlab/runtime.json gives its port. That file is read again for each request,
// so a restarted service (a new port) is followed; its new launch token still has to be opened once at
// /open?token=... on this server. EEG_NODE_API=1 mounts the legacy Node API instead (kept until phase 4).
const NODE_API = process.env.EEG_NODE_API === '1';
const HINT = 'Start the service with `eeglayoutlab serve <workspace> --no-browser` and set EEG_WORKSPACE=<workspace> '
  + '(or EEG_API_TARGET=http://127.0.0.1:<port>); EEG_NODE_API=1 mounts the legacy Node API instead.';

function serviceTarget(): string {
  if (process.env.EEG_API_TARGET) return serviceOrigin(process.env.EEG_API_TARGET, { exact: true, name: 'EEG_API_TARGET' });
  if (!process.env.EEG_WORKSPACE) throw new Error(`No Python service for /api and /open. ${HINT}`);
  const path = join(resolve(process.env.EEG_WORKSPACE), '.eeglayoutlab', 'runtime.json');
  let text;
  try { text = readFileSync(path, 'utf8'); }
  catch { throw new Error(`The Python service is not running on ${resolve(process.env.EEG_WORKSPACE)}: ${path} is missing. ${HINT}`); }
  let value: unknown;
  try { value = JSON.parse(text); } catch { value = undefined; }
  return `http://127.0.0.1:${checkedRuntime(value, path).port}`;
}

// One proxy per path prefix. Its target is set again before each request (http-proxy reads the options object
// that `configure` receives on every call); a missing service answers 503 with the hint.
function serviceProxy(): ProxyOptions {
  let live: ProxyOptions | undefined;
  return {
    // Keep the browser's Host (changeOrigin: false): the service compares Origin with it, and the session cookie
    // from the proxied /open is stored for this host.
    changeOrigin: false,
    configure(_proxy, options) { live = options; },
    bypass(request, response) {
      try {
        if (live) live.target = serviceTarget();
        return undefined;
      } catch (error) {
        response?.writeHead(503, { 'Content-Type': 'text/plain; charset=utf-8', 'Cache-Control': 'no-store' })
          .end((error as Error).message + '\n');
        // Vite stops here: the response is ended.
        return request.url ?? '/';
      }
    },
  };
}

// Names the service at start; a missing one is reported then and on each request until it runs.
function serviceNotice(): Plugin {
  return { name: 'eeg-python-service', apply: 'serve',
    configureServer(server) {
      try { server.config.logger.info(`  /api and /open → Python service at ${serviceTarget()}`); }
      catch (error) { server.config.logger.warn(`  ${(error as Error).message}`); }
    } };
}

export default defineConfig(async ({ command }) => {
  const serving = command === 'serve';
  if (serving && !NODE_API && !process.env.EEG_API_TARGET && !process.env.EEG_WORKSPACE) {
    throw new Error(`The development server needs the Python service for /api and /open. ${HINT}`);
  }
  // A malformed EEG_API_TARGET is refused at start; a workspace whose service is not running yet only warns.
  if (serving && !NODE_API && process.env.EEG_API_TARGET) serviceTarget();
  // The Node host's modules load only when its API is mounted.
  const nodePlugins = serving && NODE_API ? [(await import('./server/host/development.mjs')).localComputePlugin()] : [];
  return {
    css: { postcss: { plugins: [tailwindcss()] } },
    build: {
      chunkSizeWarningLimit: 700,
      rolldownOptions: {
        output: {
          codeSplitting: {
            groups: [
              { name: 'three-vendor', test: /[\\/]node_modules[\\/]three[\\/]/, priority: 20 },
              { name: 'charts-vendor', test: /[\\/]node_modules[\\/](?:recharts|d3-|victory-vendor)[\\/]/, priority: 15 },
            ],
          },
        },
      },
    },
    server: {
      host: '127.0.0.1',
      watch: process.env.EEG_WATCH_POLLING === '1'
        ? { useFsEvents: false, usePolling: true }
        : undefined,
      proxy: NODE_API ? undefined : { '^/api(?:[/?]|$)': serviceProxy(), '^/open(?:[/?]|$)': serviceProxy() },
    },
    plugins: [...nodePlugins, ...(NODE_API ? [] : [serviceNotice()]), vinext()],
  };
});
