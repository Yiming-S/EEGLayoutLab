import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { normalizeRequest } from '../server/local-compute-server.mjs';
import { normalizeDesignRequest } from '../server/design-evaluation-server.mjs';
import {
  normalizeSourceRequest, normalizeReceptionRequest,
  validateSourceResult, validateReceptionResult, SOURCE_REGIONS,
} from '../server/contracts/source-reception.mjs';
import * as legacy from '../server/source-reception-server.mjs';
import * as v2 from '../server/reception-v2-support.mjs';

const corpus = JSON.parse(await readFile(new URL('../../contracts/fixtures/requests.json', import.meta.url), 'utf8'));
const normalize = { radius: normalizeRequest, source: normalizeReceptionRequest, design: normalizeDesignRequest };

void test('versioned API samples preserve accepted fields, rejection rules and exact canonical JSON', () => {
  assert.equal(corpus.version, 'eeglayoutlab-request-fixtures/1');
  const names = new Set();
  for (const sample of corpus.cases) {
    assert.ok(!names.has(sample.name), `duplicate sample ${sample.name}`);
    names.add(sample.name);
    const input = structuredClone(sample.request);
    if (sample.valid) {
      const canonical = normalize[sample.service](input);
      assert.deepEqual(canonical, sample.canonical, sample.name);
      // Property order is significant to the existing request/cache serializers.
      assert.equal(JSON.stringify(canonical), JSON.stringify(sample.canonical), sample.name);
      assert.equal(JSON.stringify(normalize[sample.service](canonical)), JSON.stringify(canonical), sample.name);
    } else {
      assert.throws(() => normalize[sample.service](input), undefined, sample.name);
    }
    assert.deepEqual(input, sample.request, `${sample.name}: normalization mutated input`);
  }
});

void test('source service compatibility exports keep the same pure validators', () => {
  assert.equal(legacy.normalizeSourceRequest, normalizeSourceRequest);
  assert.equal(legacy.validateSourceResult, validateSourceResult);
  assert.equal(legacy.SOURCE_REGIONS, SOURCE_REGIONS);
  assert.equal(v2.normalizeReceptionRequest, normalizeReceptionRequest);
  assert.equal(v2.validateReceptionResult, validateReceptionResult);
});
