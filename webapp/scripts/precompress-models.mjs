/** Build-only lossless model variants; original public assets remain untouched. */
import { readdir, readFile, writeFile, rename, rm } from 'node:fs/promises';
import { resolve, join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { promisify } from 'node:util';
import { randomUUID } from 'node:crypto';
import { brotliCompress, gzip, constants } from 'node:zlib';

const brotli = promisify(brotliCompress), gz = promisify(gzip);

export async function precompressModels(directory) {
  const outputs = [];
  async function visit(folder) {
    const entries = await readdir(folder, { withFileTypes: true });
    for (const entry of entries) {
      const path = join(folder, entry.name);
      if (entry.isSymbolicLink()) throw new Error('Model build directory cannot contain symlinks');
      if (entry.isDirectory()) { await visit(path); continue; }
      if (!entry.isFile() || !entry.name.endsWith('.bin')) continue;
      const original = await readFile(path);
      for (const { extension, encode } of [
        { extension: 'br', encode: bytes => brotli(bytes, { params: { [constants.BROTLI_PARAM_QUALITY]: 5 } }) },
        { extension: 'gz', encode: bytes => gz(bytes, { level: 6 }) },
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

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const outputs = await precompressModels(resolve(import.meta.dirname, '../dist/client/models'));
  for (const entry of outputs) console.log(`${entry.file}: ${entry.encoding} ${entry.originalBytes} -> ${entry.encodedBytes} bytes`);
}
