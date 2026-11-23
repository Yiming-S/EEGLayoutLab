#!/usr/bin/env node
// Serves showcase-dist/ the way GitHub Pages does, for checking the showcase locally:
// /name answers name.html, a directory answers its index.html, anything else 404.html with status 404.
//
//   node scripts/serve-showcase.mjs [--port 3332] [--dir showcase-dist]
import { createReadStream } from 'node:fs';
import { stat } from 'node:fs/promises';
import { createServer } from 'node:http';
import { dirname, extname, join, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';

const { values } = parseArgs({ options: { port: { type: 'string', default: '3332' }, dir: { type: 'string', default: 'showcase-dist' } } });
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..', values.dir);
const types = {
  '.html': 'text/html; charset=utf-8', '.txt': 'text/plain; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8', '.json': 'application/json; charset=utf-8', '.svg': 'image/svg+xml',
  '.woff2': 'font/woff2', '.png': 'image/png', '.bin': 'application/octet-stream', '.ico': 'image/x-icon',
};
const file = async (path) => {
  try { return (await stat(path)).isFile() ? path : null; } catch { return null; }
};

createServer(async (request, response) => {
  const pathname = decodeURIComponent(new URL(request.url ?? '/', 'http://localhost').pathname);
  const target = resolve(root, '.' + pathname);
  if (target !== root && !target.startsWith(root + sep)) { response.writeHead(400).end(); return; }
  const found = (await file(target)) ?? (await file(target + '.html')) ?? (await file(join(target, 'index.html')));
  const path = found ?? join(root, '404.html');
  response.writeHead(found ? 200 : 404, { 'Content-Type': types[extname(path)] ?? 'application/octet-stream', 'Cache-Control': 'no-cache' });
  if (request.method === 'HEAD') response.end();
  else createReadStream(path).pipe(response);
}).listen(Number(values.port), '127.0.0.1', () => console.log(`showcase on http://127.0.0.1:${values.port} from ${root}`));
