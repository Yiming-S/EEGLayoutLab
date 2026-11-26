// Node reference for tests/service/test_worker.py: webapp/server/jobs/python-worker.mjs (startPythonWorker) on
// scripted fake children and on real processes. Starts only the processes the spec names; writes only <out.json>.
// Usage: node tests/service/parity/worker.mjs <spec.json> <out.json>
//
// spec: {cases: [...]}, each case {id, mode, timeoutMs, maxOutputBytes, killAfterMs?, input?, mask?}; `input` is
// written as given (a string as it is, anything else as JSON), `mask` lists event members recorded as null.
// - mode 'fake': a child as check-worker-lifecycle.mjs builds it (EventEmitter, PassThrough streams, kill recorded)
//   driven by `steps`, run synchronously in order: ['stdout', base64], ['stderr', base64], ['error', message],
//   ['stdin_error', message, code], ['close', code, signal], ['stop', reason], ['closed']. Recorded: every callback
//   in order (['event', event], ['log', text], ['stderr', text], ['error', message], ['stop', reason],
//   ['close', code, signal]), each kill (['kill', signal]), each step's return (['stopped', bool], ['closed', bool])
//   and finally ['input', base64] of what was written to stdin. An event with a string `append` member has it
//   appended with the diagnostic function onEvent gets.
// - mode 'real': spawn(executable, args, {cwd?, env?, stdio: [stdin ?? 'pipe', 'pipe', 'pipe']}); `stopOnEvent`
//   stops with that reason at the first event (and once more, which must return false). Recorded once onClose has
//   run (plus 100 ms for late errors): events, logs, the last diagnostic, error messages, stop reasons, the stop
//   returns, the close and the number of closes; or {thrown, code} when startPythonWorker throws.
// Each case is recorded as its own JSON.stringify text, so member order is compared too.
import { EventEmitter } from 'node:events';
import { PassThrough } from 'node:stream';
import { readFileSync, writeFileSync } from 'node:fs';
import { startPythonWorker } from '../../../webapp/server/jobs/python-worker.mjs';

const [specPath, outPath] = process.argv.slice(2);
if (!specPath || !outPath) throw new Error('usage: worker.mjs <spec.json> <out.json>');
const { cases } = JSON.parse(readFileSync(specPath, 'utf8'));

const masked = (event, mask = []) => {
  if (!mask.length) return event;
  const copy = { ...event };
  for (const key of mask) if (key in copy) copy[key] = null;
  return copy;
};

async function fake(spec) {
  const calls = [], input = [];
  const child = new EventEmitter();
  child.stdin = new PassThrough(); child.stdout = new PassThrough(); child.stderr = new PassThrough();
  child.kill = signal => { calls.push(['kill', signal]); return true; };
  child.stdin.on('data', chunk => input.push(chunk));
  const instance = startPythonWorker({
    spawnProcess: () => child, executable: 'python', args: [], options: {}, input: spec.input,
    timeoutMs: spec.timeoutMs, maxOutputBytes: spec.maxOutputBytes, killAfterMs: spec.killAfterMs ?? 2000,
    onEvent: (event, diagnostic) => {
      calls.push(['event', masked(event, spec.mask)]);
      if (typeof event.append === 'string') diagnostic(event.append);
    },
    onLog: text => calls.push(['log', text]), onStderr: text => calls.push(['stderr', text]),
    onError: error => calls.push(['error', error.message]), onStop: reason => calls.push(['stop', reason]),
    onClose: (code, signal) => calls.push(['close', code, signal]),
  });
  for (const [kind, ...args] of spec.steps) {
    if (kind === 'stdout') child.stdout.write(Buffer.from(args[0], 'base64'));
    else if (kind === 'stderr') child.stderr.write(Buffer.from(args[0], 'base64'));
    else if (kind === 'error') child.emit('error', new Error(args[0]));
    else if (kind === 'stdin_error') child.stdin.emit('error', Object.assign(new Error(args[0]), { code: args[1] }));
    else if (kind === 'close') child.emit('close', args[0], args[1]);
    else if (kind === 'stop') calls.push(['stopped', instance.stop(args[0])]);
    else if (kind === 'closed') calls.push(['closed', instance.closed]);
    else throw new Error(`unknown step ${kind}`);
  }
  if (!instance.closed) child.emit('close', null, null);
  await new Promise(resolve => setImmediate(resolve)); // the PassThrough delivers stdin data asynchronously
  calls.push(['input', Buffer.concat(input).toString('base64')]);
  return { calls };
}

function real(spec) {
  return new Promise(resolve => {
    const record = { events: [], logs: [], stderr: null, errors: [], stops: [], stopped: [], close: null, closes: 0 };
    let instance;
    try {
      instance = startPythonWorker({
        executable: spec.executable, args: spec.args,
        options: { ...(spec.cwd ? { cwd: spec.cwd } : {}), ...(spec.env ? { env: spec.env } : {}),
          stdio: [spec.stdin ?? 'pipe', 'pipe', 'pipe'] },
        input: spec.input, timeoutMs: spec.timeoutMs, maxOutputBytes: spec.maxOutputBytes,
        killAfterMs: spec.killAfterMs ?? 2000,
        onEvent: (event, diagnostic) => {
          record.events.push(masked(event, spec.mask));
          if (typeof event.append === 'string') diagnostic(event.append);
          if (spec.stopOnEvent && record.stopped.length === 0) {
            record.stopped.push(instance.stop(spec.stopOnEvent), instance.stop('again'));
          }
        },
        onLog: text => record.logs.push(text), onStderr: text => { record.stderr = text; },
        onError: error => record.errors.push(error.message), onStop: reason => record.stops.push(reason),
        onClose: (code, signal) => {
          record.closes++; record.close = [code, signal];
          setTimeout(() => resolve(record), 100);
        },
      });
    } catch (error) {
      resolve({ thrown: error.message, code: error.code ?? null });
    }
  });
}

const out = [];
for (const spec of cases) {
  const record = spec.mode === 'fake' ? await fake(spec) : await real(spec);
  out.push({ id: spec.id, text: JSON.stringify(record) });
}
writeFileSync(outPath, JSON.stringify({ node: process.version, platform: process.platform, cases: out }));
