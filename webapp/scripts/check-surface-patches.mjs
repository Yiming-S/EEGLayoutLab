import test from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import { surfacePatchGeometry } from '../lib/surface-patches.ts';
import { LocalComputeQueue } from './local-compute-server.mjs';
import { readFile } from 'node:fs/promises';

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

void test('current native two-region patches preserve 32+32 and match the reported areas', async () => {
  const queue = new LocalComputeQueue({repositoryRoot:'..'});
  try {
    const data=await queue.library.list();
    const row=data.records.find(r=>r.dataset_id==='strict_area'&&r.mode==='whole_scalp_free'&&r.area_cap_cm2===60&&r.region_count===2);
    const record=await queue.library.get(row.id);
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
  } finally {queue.dispose();}
});
