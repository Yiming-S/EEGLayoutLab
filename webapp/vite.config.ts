import tailwindcss from '@tailwindcss/postcss';
import vinext from 'vinext';
import { defineConfig } from 'vite';
import { localComputePlugin } from './server/host/development.mjs';

// This checkout runs locally, without a hosted Worker backend.
export default defineConfig({
  css: { postcss: { plugins: [tailwindcss()] } },
  server: {
    host: '127.0.0.1',
    watch: process.env.EEG_WATCH_POLLING === '1'
      ? { useFsEvents: false, usePolling: true }
      : undefined,
  },
  plugins: [localComputePlugin(), vinext()],
});
