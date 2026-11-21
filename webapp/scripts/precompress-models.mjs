/**
 * Build-only lossless .br/.gz sidecars; original public assets remain untouched.
 * The production server serves a sidecar only when one exists: a built file without
 * one is sent uncompressed, so text assets are encoded here as well as model binaries.
 */
import { readdir, readFile, writeFile, rename, rm } from 'node:fs/promises';
import { resolve, join, relative, sep } from 'node:path';
import { pathToFileURL } from 'node:url';
import { promisify } from 'node:util';
import { randomUUID } from 'node:crypto';
import { brotliCompress, gzip, constants } from 'node:zlib';

const brotli = promisify(brotliCompress), gz = promisify(gzip);
const TEXT_ASSETS = /\.(?:js|mjs|css|json|svg|txt|html|map)$/;

async function precompress(directory, { include, quality, skip = () => false }) {
  const outputs = [];
  async function visit(folder) {
    const entries = await readdir(folder, { withFileTypes: true });
    for (const entry of entries) {
      const path = join(folder, entry.name);
      if (entry.isSymbolicLink()) throw new Error('Model build directory cannot contain symlinks');
      if (entry.isDirectory()) { if (!skip(path)) await visit(path); continue; }
      if (!entry.isFile() || !include(entry.name)) continue;
      const original = await readFile(path);
      for (const { extension, encode } of [
        { extension: 'br', encode: bytes => brotli(bytes, { params: { [constants.BROTLI_PARAM_QUALITY]: quality, [constants.BROTLI_PARAM_SIZE_HINT]: bytes.length } }) },
        { extension: 'gz', encode: bytes => gz(bytes, { level: quality > 5 ? 9 : 6 }) },
      ]) {
        const bytes = await encode(original), target = `${path}.${extension}`;
        if (bytes.length >= original.length) { await rm(target, { force: true }); continue; }
        const temporary = `${target}.${process.pid}.${randomUUID()}.tmp`;
        try { await writeFile(temporary, bytes, { flag: 'wx' }); await rename(temporary, target); }
        finally { await rm(temporary, { force: true }); }
        outputs.push({ file: path, encoding: extension, originalBytes: original.length, encodedBytes: bytes.length });
      }
    }
  }
  await visit(directory);
  return outputs;
}

/** Model binaries: fast brotli, since they are large. */
export function precompressModels(directory) {
  return precompress(directory, { include: name => name.endsWith('.bin'), quality: 5 });
}

/** Scripts, styles and JSON of the client build (fonts are already compressed); `models/` is left to precompressModels. */
export function precompressAssets(clientDirectory) {
  const models = join(clientDirectory, 'models');
  return precompress(clientDirectory, { include: name => TEXT_ASSETS.test(name), quality: 11,
    skip: path => path === models || relative(models, path).split(sep)[0] !== '..' });
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const client = resolve(import.meta.dirname, '../dist/client');
  const outputs = [...await precompressModels(join(client, 'models')), ...await precompressAssets(client)];
  const total = (key, encoding) => outputs.filter(entry => entry.encoding === encoding).reduce((sum, entry) => sum + entry[key], 0);
  console.log(`precompressed ${outputs.length} sidecars; brotli ${total('originalBytes', 'br')} -> ${total('encodedBytes', 'br')} bytes`);
}
