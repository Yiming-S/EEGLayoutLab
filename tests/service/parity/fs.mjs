// Node reference for tests/service/test_nodefs.py: fs.realpathSync (lib/fs.js, link targets resolved lexically),
// fs.promises.realpath (libuv's realpath(3)), fs.promises.readdir and fs.promises.readFile of each path, with the
// code and message of each failure. Reads the paths only; writes only <out.json>.
// Usage: node tests/service/parity/fs.mjs <spec.json> <out.json>    spec: {paths: [string]}
import { readFileSync, realpathSync, writeFileSync } from 'node:fs';
import { readdir, readFile, realpath } from 'node:fs/promises';

const [specPath, outPath] = process.argv.slice(2);
if (!specPath || !outPath) throw new Error('usage: fs.mjs <spec.json> <out.json>');
const { paths } = JSON.parse(readFileSync(specPath, 'utf8'));

const failure = (error) => ({ ok: false, code: error?.code ?? null, message: String(error?.message ?? error) });
const attempt = async (work) => { try { return { ok: true, value: await work() }; } catch (error) { return failure(error); } };
const results = [];
for (const path of paths) {
  results.push({ path, sync: await attempt(() => realpathSync(path)), promise: await attempt(() => realpath(path)),
    list: await attempt(async () => (await readdir(path)).sort()), read: await attempt(async () => (await readFile(path)).length) });
}
writeFileSync(outPath, JSON.stringify({ node: process.version, platform: process.platform, results }));
