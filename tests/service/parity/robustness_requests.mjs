// Node reference for tests/service/test_study_routes.py: the canonical requests of the stage-5 robustness inputs.
// Usage: node tests/service/parity/robustness_requests.mjs <out.json>
//
// For each case of tests/service/fixtures/robustness/{noise_seeds,grid_displacements}-input.json, the request that
// check-robustness-browser.mjs proved cached before the fixture replaced its import: JSON.stringify of
// normalizeDesignRequest({action, design, ...case}), with action 'evaluate' for noise seeds and 'perturb' for grid
// displacements. Writes {node, noise_seeds: [text, ...], grid_displacements: [text, ...]}.
import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { normalizeDesignRequest } from '../../../webapp/server/design-evaluation-server.mjs';

const [outPath] = process.argv.slice(2);
if (!outPath) throw new Error('usage: robustness_requests.mjs <out.json>');
const fixture = join(import.meta.dirname, '../fixtures/robustness');
const output = { node: process.version };
for (const protocol of ['noise_seeds', 'grid_displacements']) {
  const input = JSON.parse(readFileSync(join(fixture, `${protocol}-input.json`), 'utf8'));
  const action = input.protocol === 'noise_seeds' ? 'evaluate' : 'perturb';
  output[protocol] = input.cases.map(entry => JSON.stringify(
    normalizeDesignRequest({ action, design: input.design, ...entry })));
}
writeFileSync(outPath, JSON.stringify(output));
