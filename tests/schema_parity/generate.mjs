// Runs the real Node normalizers over the generated request texts of every format in formats/ and writes the
// corpus that tests/schema_parity_support.py compares with eeglayoutlab.schemas. Deterministic.
// Usage: node tests/schema_parity/generate.mjs <output.json>
//
// A format module exports `name` (the key in eeglayoutlab.schemas.registry.REQUEST_FORMATS), `normalize`
// (Node's own functions: returns the canonical value, or a promise of it, or throws or rejects) and `variants`
// ({name, text} or {name, bytes}, optionally with `expect` for a shared fixture), and optionally `options`: Node's
// lists of allowed values.
import { writeFileSync } from 'node:fs';
import * as coordinateSource from './formats/coordinate-source.mjs';
import * as designEvaluation from './formats/design-evaluation.mjs';
import * as electrodeEditor from './formats/electrode-editor.mjs';
import * as projectCreate from './formats/project-create.mjs';
import * as projectEntry from './formats/project-entry.mjs';
import * as projectEntryDelete from './formats/project-entry-delete.mjs';
import * as projectEntryPatch from './formats/project-entry-patch.mjs';
import * as projectPatch from './formats/project-patch.mjs';
import * as radiusSearch from './formats/radius-search.mjs';
import * as robustnessStudy from './formats/robustness-study.mjs';
import * as sourceReception from './formats/source-reception.mjs';
import { internalFault } from '../../webapp/server/http/public-errors.mjs';
import { referenceCorpora } from './reference.mjs';

const FORMATS = [coordinateSource, designEvaluation, electrodeEditor, projectCreate, projectEntry, projectEntryDelete,
  projectEntryPatch, projectPatch, radiusSearch, robustnessStudy, sourceReception];

const output = process.argv[2];
if (!output) throw new Error('usage: generate.mjs <output.json>');

// Request bodies are decoded as Node's services decode them: UTF-8 with replacement, then JSON.parse.
const decode = variant => (variant.bytes !== undefined ? Buffer.from(variant.bytes, 'base64').toString() : variant.text);
// A TypeError, RangeError or ReferenceError is a fault of the normalizer, which the host answers with 500, not a
// rejected request; it stops generation instead of being recorded as a rejection.
const outcome = async (text, normalize, where) => {
  let parsed;
  try { parsed = JSON.parse(text); } catch { return { parsed: false, accepted: false, canonical: null }; }
  try { return { parsed: true, accepted: true, canonical: JSON.stringify(await normalize(parsed)) }; }
  catch (error) {
    if (internalFault(error)) throw new Error(`the Node normalizer failed on ${where}: ${error.stack}`);
    return { parsed: true, accepted: false, canonical: null, error: error.message };
  }
};

const formats = {};
for (const format of FORMATS) {
  if (formats[format.name]) throw new Error(`duplicate format ${format.name}`);
  const names = new Set();
  const variants = [];
  for (const variant of format.variants) {
    if (names.has(variant.name)) throw new Error(`duplicate variant ${format.name}/${variant.name}`);
    names.add(variant.name);
    const { expect, ...input } = variant;
    const result = { ...input, ...await outcome(decode(variant), format.normalize, `${format.name}/${variant.name}`) };
    if (expect && (result.accepted !== expect.accepted || result.canonical !== expect.canonical))
      throw new Error(`fixture ${format.name}/${variant.name} disagrees with Node`);
    variants.push(result);
  }
  const accepted = variants.filter(variant => variant.accepted).length;
  if (!accepted || accepted === variants.length) throw new Error(`format ${format.name} needs accepted and rejected variants`);
  formats[format.name] = { variants, ...(format.options ? { options: format.options } : {}) };
}

writeFileSync(output, JSON.stringify({ node: process.version, formats, ...referenceCorpora() }));
