import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { normalizeReceptionRequest } from '../server/reception-v2-support.mjs';
import { SOURCE_REGIONS, SOURCE_ROI_DEFINITION } from '../lib/source-regions.ts';
import { sourceKey } from '../lib/source-reception.ts';

const common = { record_id:'a'.repeat(64), waveform:'burst', artifact_scale:1, seed:2026 };
await test('atlas version separates every regional combination from legacy cache identity', () => {
  for (let mask = 1; mask < 64; mask++) {
    const brain_regions = SOURCE_REGIONS.filter((_,i) => mask & (1 << i)).map(r => r.id);
    const old = {...common, mode:'cross_region', brain_regions};
    const request = normalizeReceptionRequest({...old, brain_regions:[...brain_regions].reverse(), region_definition:SOURCE_ROI_DEFINITION});
    assert.equal(sourceKey(request), JSON.stringify(request));
    assert.notEqual(sourceKey(request), sourceKey(old));
  }
  for (const mode of ['single_source','multi_source']) {
    const old = {...common, mode, ...(mode === 'single_source' ? {source_index:0} : {brain_region:'frontal'})};
    const request = normalizeReceptionRequest({...old, region_definition:SOURCE_ROI_DEFINITION});
    assert.equal(sourceKey(request), JSON.stringify(request));
    assert.notEqual(sourceKey(request), sourceKey(old));
    assert.throws(() => normalizeReceptionRequest({...request, region_definition:'unverified'}));
  }
});

await test('all new UI modes use the atlas version; scientific context hashes both membership and definition', () => {
  const ui = readFileSync(new URL('../features/reception/use-reception-controller.ts', import.meta.url),'utf8');
  const server = readFileSync(new URL('../server/reception-v2-support.mjs', import.meta.url),'utf8');
  assert.match(ui, /region_definition: 'dk40-six-roi-v1'/);
  assert.doesNotMatch(ui, /\{ \.\.\.common, brain_region: region \}/);
  for (const file of ['src/compact_eeg/workflows/source_roi.py','webapp/public/models/ernie/source-roi.json','webapp/public/models/ernie/source-roi-definition.json']) assert.ok(server.includes(file));
});

await test('atlas assets contain no local user paths; research ROI merges are disjoint by hemisphere', () => {
  const bytes = readFileSync(new URL('../public/models/ernie/source-roi.json', import.meta.url),'utf8');
  assert.doesNotMatch(bytes, /\/Users\/|\/private\/tmp\//);
  const atlas = JSON.parse(bytes), claimed = new Set();
  for (const group of atlas.definition.groups) for (const h of group.hemispheres) for (const label of group.parcels) {
    const key = `${h}:${label}`;
    assert.ok(!claimed.has(key), key); claimed.add(key);
  }
  assert.equal(atlas.generation_sources.length,256);
  assert.equal(atlas.dictionary_roi_indices.length,4096);
});
