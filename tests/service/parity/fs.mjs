// Node reference for tests/service/test_nodefs.py: fs.realpathSync (lib/fs.js, link targets resolved lexically)
// and fs.promises.realpath (libuv's realpath(3)) of each path. Reads the paths only; writes only <out.json>.
// Usage: node tests/service/parity/fs.mjs <spec.json> <out.json>    spec: {paths: [string]}
import { readFileSync, realpathSync, writeFileSync } from 'node:fs';
import { realpath } from 'node:fs/promises';

const [specPath, outPath] = process.argv.slice(2);
if (!specPath || !outPath) throw new Error('usage: fs.mjs <spec.json> <out.json>');
const { paths } = JSON.parse(readFileSync(specPath, 'utf8'));

const failure = (error) => ({ ok: false, code: error?.code ?? null, message: String(error?.message ?? error) });
const results = [];
for (const path of paths) {
  let sync, promise;
  try { sync = { ok: true, value: realpathSync(path) }; } catch (error) { sync = failure(error); }
  try { promise = { ok: true, value: await realpath(path) }; } catch (error) { promise = failure(error); }
  results.push({ path, sync, promise });
}
writeFileSync(outPath, JSON.stringify({ node: process.version, platform: process.platform, results }));
