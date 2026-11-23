import tailwindcss from '@tailwindcss/postcss';
import vinext from 'vinext';
import { defineConfig, type ProxyOptions } from 'vite';
import { localComputePlugin } from './server/host/development.mjs';
import { serviceOrigin } from './scripts/helpers/service-session.mjs';

// The origin of the Python service, which listens on 127.0.0.1 only (not localhost or [::1]).
const apiTarget = process.env.EEG_API_TARGET
  ? serviceOrigin(process.env.EEG_API_TARGET, { exact: true, name: 'EEG_API_TARGET' })
  : undefined;
// Keep the browser's Host (changeOrigin: false): the service compares Origin with it, and the session cookie
// from the proxied /open is stored for this host.
const forward = (target: string): ProxyOptions => ({ target, changeOrigin: false });

// This checkout runs locally, without a hosted Worker backend. With EEG_API_TARGET set, the Python service
// answers /api and /open instead of the Node API.
export default defineConfig({
  css: { postcss: { plugins: [tailwindcss()] } },
  server: {
    host: '127.0.0.1',
    watch: process.env.EEG_WATCH_POLLING === '1'
      ? { useFsEvents: false, usePolling: true }
      : undefined,
    proxy: apiTarget
      ? { '^/api(?:[/?]|$)': forward(apiTarget), '^/open(?:[/?]|$)': forward(apiTarget) }
      : undefined,
  },
  plugins: [...(apiTarget ? [] : [localComputePlugin()]), vinext()],
});
