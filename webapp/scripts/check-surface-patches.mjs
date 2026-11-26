import test from 'node:test';
import { dataTest } from './test-tiers.mjs';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import { surfacePatchGeometry } from '../lib/surface-patches.ts';
import { readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';

function area(geometry) {
  const p = geometry.getAttribute('position'); let sum = 0;
  for (let i=0;i<p.count;i+=3) {
    const [a,b,c] = [i,i+1,i+2].map(j => new THREE.Vector3().fromBufferAttribute(p,j));
    sum += b.sub(a).cross(c.sub(a)).length()/2;
  }
  return sum;
}

void test('barycentric dual patches integrate one third of each incident triangle', () => {
  const s = new THREE.BufferGeometry();
  s.setAttribute('position', new THREE.Float32BufferAttribute([0,0,0,3,0,0,0,2,0],3));
  s.setIndex([0,1,2]); s.computeVertexNormals();
  for (const ids of [[0],[1],[2],[0,1],[0,1,2]]) {
    const p = surfacePatchGeometry(s,ids);
    assert.ok(Math.abs(area(p.fill)-ids.length)<1e-6);
    if(ids.length===3) assert.equal(p.boundary.getAttribute('position').count,12);
  }
  assert.throws(()=>surfacePatchGeometry(s,[3]));
  assert.throws(()=>surfacePatchGeometry(s,[1,1]));
});

void dataTest('current native two-region patches preserve 32+32 and match the reported areas', async () => {
  // The current strict-area report, read through its checksummed pointer (as the record library reads it).
  const pointer=JSON.parse(await readFile('../results/v2/current_strict_area_budget_study.json','utf8'));
  assert.match(pointer.report,/^results\/v2\/campaigns\/.+\.json$/); assert.doesNotMatch(pointer.report,/\.\./);
  const report=await readFile('../'+pointer.report);
  assert.equal(createHash('sha256').update(report).digest('hex'),pointer.sha256);
  const data=JSON.parse(report);
  assert.equal(data.schema_version,'compact-eeg-area-budget-study/4-external-exposure');
  const entry=data.conditions.find(({condition:c})=>c.domain==='whole_scalp_free'&&c.area_cap_cm2===60&&c.region_count===2);
  const final=entry.finalists.find(v=>v.objective==='min_field_sensitivity20').final;
  const record={layout:{regionIndices:final.region_indices,regionPatchVertexIndices:final.surface_patch_vertex_indices,regionAreasCm2:final.geometry.region_areas_cm2}};
  const manifest=JSON.parse(await readFile('public/models/ernie/manifest.json','utf8'));
  const d=manifest.meshes.find(m=>m.id==='scalp');
  const bytes=await readFile('public/models/ernie/'+d.file);
  const buffer=bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength);
  const s=new THREE.BufferGeometry();
  s.setAttribute('position', new THREE.BufferAttribute(new Float32Array(buffer,d.attributes.position.byteOffset,d.attributes.position.count),3));
  s.setIndex(new THREE.BufferAttribute(new Uint16Array(buffer,d.index.byteOffset,d.index.count),1));
  assert.equal(record.layout.regionPatchVertexIndices.length,2);
  for(let r=0;r<2;r++) {
    assert.equal(record.layout.regionIndices.filter(i=>i===r).length,32);
    const patch=surfacePatchGeometry(s,record.layout.regionPatchVertexIndices[r]);
    assert.ok(Math.abs(area(patch.fill)*10000-record.layout.regionAreasCm2[r])<1e-4);
    assert.ok(patch.boundary.getAttribute('position').count>0);
  }
  assert.ok(record.layout.regionAreasCm2.reduce((a,b)=>a+b,0)<=60+1e-8);
});
