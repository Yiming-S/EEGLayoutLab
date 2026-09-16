/** Resumable, low-priority atlas cache warming through the normal application FIFO.
 * No alternate solver, manufactured scores, rate-limit bypass or cache injection.
 */
import { createHash } from 'node:crypto';
import { readFile, writeFile, rename, mkdir, statfs, stat, unlink, readdir } from 'node:fs/promises';
import { resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const REGIONS=['frontal','central','parietal','occipital','temporal_left','temporal_right'];
export function scenarios() {
  const local=REGIONS.map(brain_region=>({mode:'multi_source',brain_region}));
  const cross=[];
  for(let mask=1;mask<64;mask++) cross.push({mode:'cross_region',brain_regions:REGIONS.filter((_,i)=>mask&(1<<i))});
  cross.sort((a,b)=>b.brain_regions.length-a.brain_regions.length);
  return [...local,...cross];
}
export function makePlan(records,excluded=[]) {
  const all=records.filter(r=>r.dataset_id==='strict_area' && r.status==='completed');
  if(all.length!==30 || new Set(all.map(r=>r.id)).size!==30) throw Error('Expected 30 distinct completed current strict-area layouts');
  if(excluded.some(id=>!all.some(r=>r.id===id)))throw Error('Excluded layout absent from current records');
  const layouts=all.filter(r=>!excluded.includes(r.id));
  const preferred='c7171f27c4a94b668cda3ab68a6f44f40fde5d8adaded628838320b562dfce1a';
  layouts.sort((a,b)=>Number(b.id===preferred)-Number(a.id===preferred) || a.region_count-b.region_count || a.id.localeCompare(b.id));
  // Broad coverage first: all six local scenarios and the six-ROI mix on every
  // layout, before the remaining cross-region combinations.
  const requests=[];
  for(const scenario of scenarios()) for(const waveform of ['burst','rhythm']) for(const layout of layouts)
    requests.push({record_id:layout.id,waveform,artifact_scale:1,seed:2026,region_definition:'dk40-six-roi-v1',...scenario});
  return {version:1,excluded_record_ids:excluded,layouts:layouts.map(({id,label,region_count,area_cap_cm2,mode})=>({id,label,region_count,area_cap_cm2,mode})),requests};
}
const digest=value=>createHash('sha256').update(value).digest('hex');
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const exists=async p=>{try{await stat(p);return true;}catch(e){if(e.code==='ENOENT')return false;throw e;}};
async function atomic(path,value){const tmp=path+'.tmp';await writeFile(tmp,JSON.stringify(value,null,2),{mode:0o600});await rename(tmp,path);}
async function bytesUnder(path){let total=0;for(const e of await readdir(path,{withFileTypes:true})){const p=join(path,e.name);if(e.isDirectory()) total+=await bytesUnder(p);else if(e.isFile())total+=(await stat(p)).size;}return total;}

export async function main() {
  const root=resolve(fileURLToPath(new URL('..',import.meta.url)));
  const url=new URL(process.env.EEG_PRECOMPUTE_URL || 'http://127.0.0.1:3001');
  if(url.protocol!=='http:' || !['127.0.0.1','localhost'].includes(url.hostname))throw Error('Precomputation accepts a local app only');
  const directory=join(root,'results/precompute/dk40-default-v1');await mkdir(directory,{recursive:true});
  const lock=join(directory,'runner.lock');
  if(await exists(lock)) {
    const old=JSON.parse(await readFile(lock));let active=false;try{process.kill(old.pid,0);active=true;}catch(e){if(e.code!=='ESRCH')throw e;}
    if(active)throw Error('A precompute runner is already active');await unlink(lock);
  }
  await writeFile(lock,JSON.stringify({pid:process.pid,started:new Date().toISOString()}),{flag:'wx'});
  let state,cookie='',token='',stop=false,lastSubmit=0;
  process.once('SIGTERM',()=>{stop=true;});process.once('SIGINT',()=>{stop=true;});
  const request=async(path,body)=>{
    const response=await fetch(new URL(path,url),{method:body?'POST':'GET',headers:{...(cookie?{cookie}:{}),...(body?{'content-type':'application/json','x-eeg-compute-token':token,origin:url.origin}: {})},...(body?{body:JSON.stringify(body)}:{}),signal:AbortSignal.timeout(60000)});
    const set=response.headers.get('set-cookie');if(set)cookie=set.split(';')[0];
    const value=await response.json();if(!response.ok)throw Object.assign(Error(value.error || response.statusText),{status:response.status});return value;
  };
  const checkpoint=async(status,extra={})=>{Object.assign(state,{status,updated_at:new Date().toISOString(),pid:process.pid,...extra});await atomic(join(directory,'status.json'),state);};
  const fingerprint=async()=>{
    const files=['webapp/public/models/ernie/source-roi.json','webapp/public/models/ernie/source-roi-definition.json',
      'src/compact_eeg/workflows/source_roi.py','src/compact_eeg/workflows/source_reception_v2.py','src/compact_eeg/workflows/source_reception.py',
      'src/compact_eeg/workflows/reception_forward_provider.py','results/v2/current_strict_area_budget_study.json','results/v2/current_multiregion_bank.json'];
    return digest(JSON.stringify(await Promise.all(files.map(async p=>[p,digest(await readFile(join(root,p)))]))));
  };
  try {
    const health=await request('/api/source-reception/health');token=health.token;
    const preflight=JSON.parse(await readFile(join(root,'results/precompute/source-preflight.json')));
    if(preflight.report_sha256!==digest(await readFile(join(root,preflight.report_path))))throw Error('Preflight report identity changed');
    if(preflight.bank_sha256!==digest(await readFile(join(root,preflight.bank_path))))throw Error('Preflight bank identity changed');
    const plan=makePlan((await request('/api/source-reception/layouts')).records,preflight.excluded.map(r=>r.id));
    const planHash=digest(JSON.stringify(plan)), identity=await fingerprint();
    const statusPath=join(directory,'status.json');
    state=await exists(statusPath)?JSON.parse(await readFile(statusPath)):{version:1,plan_sha256:planHash,science_sha256:identity,total:plan.requests.length,next_index:0,completed:0,reused:0,failures:[],started_at:new Date().toISOString(),results:[]};
    if(state.plan_sha256!==planHash || state.science_sha256!==identity)throw Error('Plan or scientific files changed; use a separately named campaign');
    if(state.cookie)cookie=state.cookie;
    // Cookie is private local resume state; never printed or included in reports.
    state.cookie=cookie;await atomic(join(directory,'plan.json'),plan);
    await checkpoint('running');
    const started=Date.now(),initial=state.completed;
    while(state.next_index<plan.requests.length && !stop) {
      if(await exists(join(directory,'PAUSE'))) {await checkpoint('paused_by_file');break;}
      if(await fingerprint()!==identity){await checkpoint('paused_science_changed');break;}
      const disk=await statfs(root);if(disk.bavail*disk.bsize<80*1024**3){await checkpoint('paused_low_disk');break;}
      if(state.next_index%25===0){
        const bytes=await bytesUnder(join(root,'results/v2/source_reception_v2_jobs'));
        if(bytes>40*1024**3){await checkpoint('paused_cache_budget',{cache_bytes:bytes});break;}
        state.cache_bytes=bytes;
      }
      try {
        const health=await request('/api/source-reception/health');token=health.token;
        const stats=await request('/api/community/status');
        if(stats.recovery_blocked) {await checkpoint('paused_queue_recovery');break;}
        if(!state.active && (stats.running_tasks || stats.queued_tasks)) {await checkpoint('yielding_to_interactive_jobs');await sleep(5000);continue;}
        const configuration=plan.requests[state.next_index];
        let job;
        if(state.active) {
          try {job=(await request('/api/source-reception/jobs/'+state.active.id)).job;}
          catch(e){if(e.status!==404)throw e;state.active=null;}
        }
        if(!job) {
          await sleep(Math.max(0,3500-(Date.now()-lastSubmit)));
          job=(await request('/api/source-reception/jobs',configuration)).job;lastSubmit=Date.now();
          if(!job?.id)throw Error('No job receipt returned');
          state.active={id:job.id,key:job.key,index:state.next_index};await checkpoint('running');
        }
        while(['queued','running','cancelling'].includes(job.status)) {
          await sleep(1500);job=(await request('/api/source-reception/jobs/'+job.id)).job;
          if(stop){await checkpoint('paused_after_signal');return;}
        }
        if(job.status!=='completed') {
          state.failures.push({index:state.next_index,status:job.status,message:job.message});
          await checkpoint('paused_job_failure');break;
        }
        const r=job.result;
        if(r?.request?.region_definition!=='dk40-six-roi-v1'||r?.source?.region_definition!=='dk40-six-roi-v1'||r?.request?.record_id!==configuration.record_id)throw Error('Unexpected result identity');
        state.results.push({index:state.next_index,key:job.key,id:job.id,cached:job.cached,finished_at:job.finished_at});
        state.completed++;if(job.cached)state.reused++;state.next_index++;state.active=null;
        const done=state.completed-initial;
        await checkpoint('running',{seconds_per_result:done?(Date.now()-started)/1000/done:null});
        console.log(JSON.stringify({completed:state.completed,total:state.total,reused:state.reused,index:state.next_index,seconds_per_result:state.seconds_per_result}));
      }catch(e){
        if(e.status===429 || e.status===403 || e.status===503 || e.name==='TimeoutError' || e.cause?.code==='ECONNREFUSED'){
          await checkpoint('waiting_for_service',{last_error:e.message});await sleep(60000);continue;
        }
        throw e;
      }
    }
    if(state.next_index===plan.requests.length)await checkpoint('completed');
    else if(stop)await checkpoint('paused_after_signal');
  }catch(e){if(state)await checkpoint('failed',{last_error:e.message});throw e;}
  finally {await unlink(lock).catch(()=>{});}
}
if(process.argv[1] && resolve(process.argv[1])===fileURLToPath(import.meta.url))main().catch(e=>{console.error(e.message);process.exitCode=1;});
