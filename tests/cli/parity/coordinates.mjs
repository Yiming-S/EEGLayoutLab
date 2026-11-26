import { readFileSync, writeFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { validateDesign, parseDesign, designCSV } from '../../../webapp/lib/design-decision.ts';
import {
  parseElectrodeLabels,
  parseBIDSElectrodes,
  exportBIDSElectrodes,
  exportMniBIDSElectrodes,
} from '../../../webapp/lib/bids-electrodes.ts';
import { exportMneElc, exportEeglabSfp } from '../../../webapp/lib/montage-files.ts';
import { assignBalancedRegions } from '../../../webapp/lib/head-registration.ts';
import { parseMontageFile } from '../../../webapp/lib/head-frame-import.ts';
import { ERNIE_MNI_MAPPING, verifiedSurface } from '../../../webapp/lib/ernie-mni.ts';

const here = dirname(fileURLToPath(import.meta.url));
const publicDir = join(here, '../../../webapp/public');

function loadSurface() {
  const buf = rel => {
    const bytes = readFileSync(join(publicDir, rel));
    return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
  };
  return verifiedSurface(buf(ERNIE_MNI_MAPPING.scalp_buffer.file), buf(ERNIE_MNI_MAPPING.mni_buffer.file));
}

const spec = JSON.parse(readFileSync(process.argv[2], 'utf8'));
let surface = null;
const getSurface = async () => {
  if (!surface) surface = await loadSurface();
  return surface;
};

const results = [];
for (const c of spec.cases) {
  try {
    let value;
    if (c.op === 'stringify2') {
      value = JSON.stringify(c.input, null, 2);
    } else if (c.op === 'validateDesign') {
      value = JSON.stringify(validateDesign(c.input), null, 2);
    } else if (c.op === 'parseDesign') {
      value = JSON.stringify(parseDesign(c.text, c.name), null, 2);
    } else if (c.op === 'designCSV') {
      value = designCSV(c.design);
    } else if (c.op === 'parseElectrodeLabels') {
      value = JSON.stringify(parseElectrodeLabels(c.file, c.options ?? {}), null, 2);
    } else if (c.op === 'parseBIDSElectrodes') {
      value = JSON.stringify(
        parseBIDSElectrodes(c.files, c.withSurface ? await getSurface() : undefined, c.options ?? {}),
        null,
        2,
      );
    } else if (c.op === 'exportBIDSElectrodes') {
      value = exportBIDSElectrodes(c.design);
    } else if (c.op === 'exportMniBIDSElectrodes') {
      value = exportMniBIDSElectrodes(c.design, await getSurface());
    } else if (c.op === 'exportMneElc') {
      value = exportMneElc(c.design);
    } else if (c.op === 'exportEeglabSfp') {
      value = exportEeglabSfp(c.design);
    } else if (c.op === 'parseMontageFile') {
      value = JSON.stringify(parseMontageFile(c.file, await getSurface(), c.options ?? {}), null, 2);
    } else if (c.op === 'assignBalancedRegions') {
      value = assignBalancedRegions(c.points, c.count);
    } else {
      throw new Error(`unknown op ${c.op}`);
    }
    results.push({ id: c.id, ok: true, value });
  } catch (error) {
    results.push({ id: c.id, ok: false, message: error.message });
  }
}
writeFileSync(process.argv[3], JSON.stringify({ results }));
