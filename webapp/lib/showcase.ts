/**
 * Whether this page belongs to the read-only showcase (see showcase-api.ts for what it answers).
 *
 * `npm run build:showcase` builds with EEG_SHOWCASE=1. The root layout, rendered at build time, writes it
 * into <html data-showcase>, and the browser reads that attribute, so the build's render and the browser's
 * agree. Outside a browser (the build's render, tests) the environment variable decides.
 */
export const SHOWCASE: boolean = typeof document !== 'undefined'
  ? document.documentElement.dataset.showcase === '1'
  : process.env.EEG_SHOWCASE === '1';

export const SHOWCASE_INSTALL_URL = 'https://github.com/Yiming-S/EEGLayoutLab#run-locally';
