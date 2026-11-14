import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter, once } from 'node:events';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createServer, get } from 'node:http';
import { createAccessPolicy } from '../server/http/access-policy.mjs';
import { hostConfig } from '../server/host/config.mjs';
import { installOperatorSignals } from '../server/host/operator-signals.mjs';
import { createLocalComputeService } from '../server/local-compute-server.mjs';

const request = (headers = {}, address = '127.0.0.1') => ({ socket: { remoteAddress: address }, headers: { host: 'eeg.example.org', origin: 'https://eeg.example.org', 'x-forwarded-proto': 'https', 'x-forwarded-for': '203.0.113.8', ...headers } });
const hosted = () => createAccessPolicy({ publicOrigin: 'https://eeg.example.org', trustedProxyAddresses: ['127.0.0.1'] });

void test('hosted access requires configured proxy, HTTPS host and single client address', () => {
  const policy = hosted();
  assert.equal(policy.guard(request()), true);
  assert.equal(policy.visitorAddress(request()), '203.0.113.8');
  assert.equal(policy.guard(request({}, '::ffff:127.0.0.1')), true);
  for (const headers of [{host:'attacker.example.org'}, {origin:'https://attacker.example.org'}, {'x-forwarded-proto':'http'}, {'x-forwarded-proto':'https,http'}, {'x-forwarded-for':'203.0.113.8, 127.0.0.1'}, {'x-forwarded-for':undefined}, {'x-forwarded-for':'not-an-ip'}, {'sec-fetch-site':'cross-site'}]) assert.equal(policy.guard(request(headers)), false, JSON.stringify(headers));
  assert.equal(policy.guard(request({}, '192.0.2.6')), false);
  assert.equal(createAccessPolicy().guard(request()), false);
  const local=request({host:'127.0.0.1:3000',origin:'http://127.0.0.1:3000'});
  assert.equal(policy.guard(local), true);
  assert.equal(policy.visitorAddress(local), '127.0.0.1');
  assert.equal(createAccessPolicy().visitorAddress(local), '127.0.0.1');
});
void test('invalid host configuration fails before service creation', () => {
  for (const publicOrigin of ['http://eeg.example.org','https://eeg.example.org/path','https://u:p@eeg.example.org','https://eeg.example.org/?x=1']) assert.throws(() => createAccessPolicy({publicOrigin,trustedProxyAddresses:['127.0.0.1']}));
  assert.throws(() => createAccessPolicy({publicOrigin:'https://eeg.example.org'}));
  assert.throws(() => createAccessPolicy({trustedProxyAddresses:['127.0.0.1']}));
  assert.throws(() => createAccessPolicy({publicOrigin:'https://eeg.example.org',trustedProxyAddresses:['127.0.0.0/8']}));
  const base={webappRoot:process.cwd(),env:{}};
  assert.equal(hostConfig(base).port,3000);assert.equal(hostConfig(base).policy.localOnly,true);
  assert.equal(hostConfig({...base,env:{EEG_COMPUTE_PYTHON:'/env/python'}}).python,'/env/python');
  assert.equal(hostConfig({...base,env:{EEG_COMPUTE_PYTHON:'/env/python'},python:'/explicit/python'}).python,'/explicit/python');
  assert.equal(hostConfig({...base,env:{EEG_MAINTENANCE:'1'}}).initialMaintenance,true);
  assert.equal(hostConfig({...base,env:{EEG_MAINTENANCE:'1'},initialMaintenance:false}).initialMaintenance,false);
  for (const env of [{PORT:'NaN'},{PORT:'65536'},{EEG_MAINTENANCE:'yes'},{EEG_REPOSITORY_ROOT:'relative-root'},{EEG_REPOSITORY_ROOT:'/nonexistent-eeg-test-root'}]) assert.throws(()=>hostConfig({...base,env}));
});
void test('proxy HTTP sets Secure cookies and resolves the validated visitor address', async () => {
  const root=mkdtempSync(join(tmpdir(),'eeg-proxy-'));
  const service=createLocalComputeService(root,{policy:hosted(),getIdentity:()=>({})});
  const server=createServer((req,res)=>{ void service.middleware(req,res,()=>{res.end('ui');});});
  server.listen(0,'127.0.0.1');await once(server,'listening');
  try {
    const url=`http://127.0.0.1:${server.address().port}/api/local-compute/health`;
    const read = headers => new Promise((resolve,reject) => {
      get(url,{headers},res=>{let body='';res.on('data',chunk=>{body+=chunk;});res.on('end',()=>resolve({status:res.statusCode,headers:res.headers,body:JSON.parse(body)}));}).on('error',reject);
    });
    const response=await read(request().headers);
    assert.equal(response.status,200);assert.match(response.headers['set-cookie'][0],/; Secure$/);
    assert.equal(response.body.local_only,false);
    assert.equal((await read(request({'x-forwarded-for':'8.8.8.8, 1.1.1.1'}).headers)).status,403);
    assert.equal(service.scheduler.session(request(),{setHeader(){}}).ip,'203.0.113.8');
  } finally {
    const done=once(server,'close');server.close();server.closeAllConnections();await done;
    await service.dispose();rmSync(root,{recursive:true,force:true});
  }
});
void test('maintenance signals use operator access and remove handlers on shutdown', () => {
  const target=new EventEmitter(),changes=[],logs=[];
  const remove=installOperatorSignals({scheduler:{setMaintenance(enabled){changes.push(enabled);return {maintenance:enabled,drained:enabled};}}},{target,log:value=>logs.push(JSON.parse(value))});
  target.emit('SIGUSR2');target.emit('SIGUSR1');assert.deepEqual(changes,[true,false]);assert.equal(logs[0].drained,true);
  remove();target.emit('SIGUSR2');assert.deepEqual(changes,[true,false]);
});
