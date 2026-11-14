import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { PassThrough } from 'node:stream';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { ExecutionSlot } from '../server/jobs/execution-slot.mjs';
import { startPythonWorker } from '../server/jobs/python-worker.mjs';
import { LocalComputeQueue } from '../server/local-compute-server.mjs';
import { DesignEvaluationService } from '../server/design-evaluation-server.mjs';

const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(check) {
  for (let i = 0; i < 200; i++) { if (check()) return; await wait(5); }
  assert.fail('worker lifecycle did not settle');
}
function fakeChild() {
  const child = new EventEmitter();
  child.stdin = new PassThrough(); child.stdout = new PassThrough(); child.stderr = new PassThrough();
  child.signals = []; child.kill = signal => { child.signals.push(signal); return true; };
  return child;
}
function worker(t, override = {}) {
  const child = fakeChild(), events = [], logs = [], stops = [], errors = [];
  let diagnostic = '', closes = 0;
  const instance = startPythonWorker({
    spawnProcess: () => child, executable: 'python', args: [], options: {},
    timeoutMs: 1000, maxOutputBytes: 1024, killAfterMs: 15,
    onEvent: value => events.push(value), onLog: value => logs.push(value),
    onStop: reason => stops.push(reason), onError: error => errors.push(error),
    onStderr: text => { diagnostic = text; }, onClose: () => { closes++; }, ...override,
  });
  t.after(() => { if (!instance.closed) child.emit('close', null); });
  return { child, instance, events, logs, stops, errors, diagnostic: () => diagnostic, closes: () => closes };
}

void test('execution permit is exclusive, idempotent, and maintenance blocks new owners only', () => {
  const slot = new ExecutionSlot(), release = slot.acquire('first');
  assert.equal(slot.busy, true); assert.equal(slot.acquire('second'), null);
  slot.pause(); release(); assert.equal(slot.busy, false); assert.equal(slot.acquire('second'), null);
  slot.resume(); const second = slot.acquire('second'); release(); assert.equal(slot.busy, true);
  second(); assert.equal(slot.busy, false);
});

void test('worker decodes split UTF-8 and the final unterminated event without treating diagnostics as data', t => {
  const f = worker(t), line = Buffer.from(JSON.stringify({ type: 'progress', message: '计算' }) + '\n');
  const offset = line.indexOf(Buffer.from('计')) + 1;
  f.child.stdout.write(line.subarray(0, offset)); f.child.stdout.write(line.subarray(offset));
  f.child.stdout.write('native diagnostic\nnull\n' + JSON.stringify({ type: 'result', result: { value: 2 } }));
  f.child.emit('close', 0); f.child.emit('close', 0);
  assert.deepEqual(f.events, [{ type: 'progress', message: '计算' }, { type: 'result', result: { value: 2 } }]);
  assert.deepEqual(f.logs, ['native diagnostic', 'null']); assert.equal(f.closes(), 1);
});

void test('stderr is bounded and spawn errors wait for actual close', t => {
  const f = worker(t);
  f.child.stderr.write('x'.repeat(18000)); f.child.emit('error', new Error('spawn failed'));
  assert.equal(f.diagnostic().length, 16000); assert.match(f.diagnostic(), /spawn failed$/);
  assert.equal(f.errors.length, 1); assert.equal(f.instance.closed, false);
  f.child.emit('close', -2); assert.equal(f.closes(), 1);
});

void test('timeout escalates termination and never closes transport before the child closes', async t => {
  const f = worker(t, { timeoutMs: 10 });
  await until(() => f.child.signals.length === 2);
  assert.deepEqual(f.stops, ['timeout']); assert.deepEqual(f.child.signals, ['SIGTERM', 'SIGKILL']);
  assert.equal(f.instance.closed, false); assert.equal(f.instance.stop('user'), false);
  f.child.emit('close', null); assert.equal(f.closes(), 1);
});

void test('output overflow and failed stdin stop once, retaining capacity until close', t => {
  const overflow = worker(t, { maxOutputBytes: 10 });
  overflow.child.stdout.write('x'.repeat(11)); overflow.child.stdout.write('x'.repeat(11));
  assert.deepEqual(overflow.stops, ['output_limit']); assert.equal(overflow.closes(), 0);
  const input = worker(t);
  input.child.stdin.emit('error', Object.assign(new Error('broken pipe'), { code: 'EPIPE' }));
  assert.deepEqual(input.stops, ['input_error']); assert.deepEqual(input.child.signals, ['SIGTERM']);
  assert.equal(input.closes(), 0);
});

const radius = { region_count: 2, radius_mm: 35, mode: 'whole_surface' };
async function services(t, spawnOverride) {
  const root = await mkdtemp(join(tmpdir(), 'eeg-shared-runner-')), children = [];
  const spawnProcess = spawnOverride || (() => { const child = fakeChild(); children.push(child); return child; });
  const queue = new LocalComputeQueue({ repositoryRoot: root, getIdentity: () => ({}), spawnProcess });
  const design = new DesignEvaluationService(queue, { spawnProcess, context: async request => ({ key: String(request.n).padStart(64, '0'), identity: {} }) });
  design.normalize = value => value; design.validate = () => {};
  t.after(async () => {
    queue.dispose(); design.dispose();
    for (const child of children) child.emit('close', null);
    await until(() => !queue.active && !design.active);
    await rm(root, { recursive: true, force: true });
  });
  return { queue, design, children };
}

void test('competing services share one permit and result validation retains it after process close', async t => {
  const f = await services(t);
  const outcomes = await Promise.all([f.queue.submit(radius), f.design.submit({ n: 1 })]);
  assert.equal(outcomes.filter(value => value.busy).length, 1); assert.equal(f.children.length, 1);
  const owner = f.queue.active ? f.queue : f.design;
  owner.cancel(owner.active.id); assert.equal(f.queue.executionSlot.busy, true);
  f.children[0].emit('close', null); await until(() => !owner.active);
  assert.equal(f.queue.executionSlot.busy, false);
  await f.design.submit({ n: 2 });
  let releaseValidation;
  f.design.context = () => new Promise(resolve => { releaseValidation = () => resolve({ key: '2'.padStart(64, '0'), identity: {} }); });
  f.children[1].stdout.write('{"type":"result","result":{"valid":true}}\n');
  f.children[1].emit('close', 0);
  assert.equal(f.queue.executionSlot.busy, true); assert.equal((await f.queue.submit(radius)).busy, true);
  releaseValidation(); await until(() => !f.design.active); assert.equal(f.queue.executionSlot.busy, false);
});

void test('maintenance requested after permit acquisition prevents a late process start', async t => {
  const f = await services(t), slot = f.queue.executionSlot, acquire = slot.acquire.bind(slot);
  slot.acquire = owner => { const release = acquire(owner); if (release) queueMicrotask(() => slot.pause()); return release; };
  const result = await f.queue.submit(radius);
  assert.equal(result.maintenance, true); assert.equal(f.children.length, 0); assert.equal(slot.busy, false);
});

void test('spawn and durable-write failures release the permit without a success result', async t => {
  const broken = await services(t, () => { throw new Error('executable missing'); });
  const result = await broken.queue.submit(radius); await until(() => !broken.queue.active);
  assert.equal(broken.queue.jobs.get(result.job.id).status, 'failed'); assert.equal(broken.queue.executionSlot.busy, false);
  const f = await services(t); const { job } = await f.design.submit({ n: 1 });
  await rm(f.design.active.batch, { recursive: true, force: true });
  f.design.cancel(job.id); f.children[0].emit('close', null); await until(() => !f.design.active);
  assert.equal(f.design.jobs.get(job.id).status, 'failed'); assert.equal(f.queue.executionSlot.busy, false);
});

void test('real process transport completes after collecting its final event', async () => {
  const events = [];
  await new Promise((resolve, reject) => {
    startPythonWorker({ executable: process.execPath,
      args: ['-e', 'process.stdout.write(JSON.stringify({type:"result",result:{ok:true}}))'],
      options: { stdio: ['ignore', 'pipe', 'pipe'] }, timeoutMs: 3000, maxOutputBytes: 1024,
      onEvent: event => events.push(event), onError: reject,
      onClose: code => { if (code === 0) resolve(); else reject(new Error(`Worker exited ${code}`)); },
    });
  });
  assert.deepEqual(events, [{ type: 'result', result: { ok: true } }]);
});

void test('worker completion waits for a surviving native descendant to exit', { skip: process.platform === 'win32', timeout: 5000 }, async t => {
  let descendant, worker;
  t.after(() => {
    for (const pid of [descendant, worker?.child.pid]) {
      if (pid) { try { process.kill(pid, 'SIGKILL'); } catch { /* Already reaped. */ } }
    }
  });
  const childSource = 'process.on("SIGTERM",()=>{}); process.stdout.write("ready"); setInterval(()=>{},1000)';
  const parentSource = `const {spawn}=require('node:child_process'); const child=spawn(process.execPath,['-e',${JSON.stringify(childSource)}],{stdio:['ignore','pipe','ignore']}); child.stdout.once('data',()=>{process.stdout.write(JSON.stringify({type:'progress',pid:child.pid})+'\\n',()=>process.exit(0));});`;
  await new Promise((resolve, reject) => {
    worker = startPythonWorker({ executable: process.execPath, args: ['-e', parentSource],
      options: { stdio: ['ignore', 'pipe', 'pipe'] }, timeoutMs: 2000, killAfterMs: 25, maxOutputBytes: 1024,
      onEvent: event => { descendant = event.pid; }, onError: reject,
      onClose: code => { if (code === 0) resolve(); else reject(new Error(`Parent exited ${code}`)); },
    });
  });
  assert.ok(descendant);
  assert.throws(() => process.kill(descendant, 0), { code: 'ESRCH' });
});
