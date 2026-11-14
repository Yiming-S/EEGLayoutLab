import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { PassThrough } from 'node:stream';
import { mkdtemp, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createHash } from 'node:crypto';
import { initialSlots, draftError, editHistory, slotKey, editorLink } from '../lib/electrode-editor.ts';
import { normalizeEditorRequest, validateEditorResult, ElectrodeEditorService } from './electrode-editor-server.mjs';
import { computeMiddleware } from './local-compute-server.mjs';
import { translateText } from '../lib/i18n/core.ts';
import catalog from '../lib/i18n/editor-catalog.json' with { type: 'json' };

const parent = 'a'.repeat(64), digest = 'b'.repeat(64);
const xyz = Array.from({length:64},(_,i)=>[i*5,0,0]);
const labels = Array.from({length:64},(_,i)=>Number(i>=32));
const domain = { parent:{id:parent,region_count:2,layout:{regionIndices:labels}},original_indices:Array.from({length:64},(_,i)=>i),
  regions:[0,1].map(r=>({bank_indices:Array.from({length:32},(_,i)=>i+r*32),xyz_mm:xyz.slice(r*32,r*32+32)})) };
const request = () => ({action:'evaluate',parent_id:parent,parent_digest:digest,seed:2026,slots:initialSlots(domain)});
const metrics = {field_relative:.8,field_absolute:.7,sensitivity_tail:.4,localization_relative:.3,median_mm:20,p90_mm:40,conditional_global:.3};
const result = r => ({schema:'electrode-editor/1',status:'completed',request:r,electrode_count:64,active_slots:Array.from({length:64},(_,i)=>i),
  evaluated_xyz_mm:xyz,region_indices:labels,minimum_distance_mm:5,baseline:metrics,parent_metrics:metrics,edited_metrics:metrics});
void test('protocol permits unbalanced deletion, not arbitrary code, thresholds or added slots',()=>{
  const r=request();r.slots[0].enabled=false;
  assert.equal(normalizeEditorRequest(r).slots.filter(s=>s.enabled).length,63);
  for(const patch of [{ar:32},{locale:'en'},{seed:9},{slots:[]},{slots:[...r.slots,r.slots[0]]}]) assert.throws(()=>normalizeEditorRequest({...r,...patch}));
  assert.throws(()=>normalizeEditorRequest({...r,parent_id:'../../private'}));
});
void test('deactivation preserves all stable identities and undo/redo restores exact state',()=>{
  const initial=initialSlots(domain), changed=initial.map((s,i)=>({...s,enabled:i>=8}));
  let h=editHistory({past:[],present:initial,future:[]},changed);
  assert.equal(h.present.filter(s=>s.enabled).length,56);assert.equal(draftError(h.present,domain),null);
  h=editHistory(h,'undo');assert.equal(slotKey(h.present),slotKey(initial));
  h=editHistory(h,'redo');assert.equal(slotKey(h.present),slotKey(changed));
  assert.equal(initial.filter(s=>s.enabled).length,64);
});
void test('whole-region deletion updates allocation without redistributing remaining slots',()=>{
  const s=initialSlots(domain).map((v,i)=>({...v,enabled:i>=32}));assert.equal(draftError(s,domain),null);
  assert.equal(s.filter(v=>v.enabled).length,32);assert.equal(s[32].bank_index,32);
});
void test('geometry rejects cross-region movement and restore collisions',()=>{
  const s=initialSlots(domain);s[0].bank_index=40;assert.equal(draftError(s,domain),'region');
  s[0]={bank_index:1,enabled:false};assert.equal(draftError(s,domain),null);
  s[0].enabled=true;assert.equal(draftError(s,domain),'spacing');
  assert.equal(draftError(null,domain),'count');
});
void test('result schema rejects stale requests, malformed geometry and fabricated combined score',()=>{
  const r=request();validateEditorResult(result(r),r);
  for(const patch of [{electrode_count:63},{minimum_distance_mm:0},{active_slots:Array(64).fill(1)},{edited_metrics:{...metrics,conditional_global:.8}}]) assert.throws(()=>validateEditorResult({...result(r),...patch},r));
});
void test('new local endpoint retains loopback and session-token protection',async()=>{
  let invoked=false;const middleware=computeMiddleware({token:digest,editor:{handle(){invoked=true;}}});
  for(const remote of ['192.168.1.1','127.0.0.1']) {
    let status;await middleware({url:'/api/electrode-editor/jobs',method:'POST',socket:{remoteAddress:remote},headers:{host:'localhost:3000'}},{writeHead(s){status=s;},end(){}},()=>{});
    assert.equal(status,403);assert.equal(invoked,false);
  }
});
void test('editor dictionary and new navigation render in English',()=>{
  for(const entry of Object.values(catalog)){assert.ok(entry.en);assert.doesNotMatch(entry.en,/[\u3400-\u9fff]/);assert.doesNotMatch(translateText(entry.source,'en'),/[\u3400-\u9fff]/);}
  assert.equal(translateText('启用电极：63','en'),'Active electrodes: 63');
  assert.equal(editorLink(parent,32),`/electrodes?parent=${parent}&ar=32`);
});

const hash=x=>createHash('sha256').update(JSON.stringify(x)).digest('hex');
function child(){const c=new EventEmitter();c.stdin=new PassThrough();c.stdout=new PassThrough();c.stderr=new PassThrough();c.kill=()=>true;return c;}
const wait=()=>new Promise(r=>setTimeout(r,8));
void test('editor shares capacity, caches completed results and retains capacity while cancelling',async()=>{
  const root=await mkdtemp(join(tmpdir(),'eeg-editor-unit-')), queue={root,python:'python',library:{},active:null};
  const children=[];const service=new ElectrodeEditorService(queue,{spawnProcess:()=>{const c=child();children.push(c);return c;}});queue.editor=service;
  service.context=async r=>({identity:{schema:'test'},key:hash({request:r,identity:{schema:'test'}}),parent:{id:parent},parent_digest:digest});
  const releaseDesign=queue.executionSlot.acquire('existing');assert.equal((await service.submit(request())).busy,true);assert.equal(children.length,0);
  releaseDesign();const first=await service.submit(request());assert.equal(children.length,1);
  children[0].stdout.write(JSON.stringify({type:'result',result:result(request())})+'\n');children[0].emit('close',0);
  for(let i=0;i<80&&service.active;i++)await wait();assert.equal(service.jobs.get(first.job.id).status,'completed');
  const releaseOther=queue.executionSlot.acquire('other');assert.equal((await service.submit(request())).job.cached,true);assert.equal(children.length,1);releaseOther();
  const next=request();next.slots[0].enabled=false;const second=await service.submit(next);service.cancel(second.job.id);
  assert.ok(service.active);children[1].emit('close',0);for(let i=0;i<80&&service.active;i++)await wait();
  assert.equal(service.jobs.get(second.job.id).status,'cancelled');assert.equal(service.jobs.get(second.job.id).result,null);
  const cache=JSON.parse(await readFile(service.store.path(service.recordKind,first.job.key,'cache.json'),'utf8'));assert.equal(cache.result.electrode_count,64);
});
