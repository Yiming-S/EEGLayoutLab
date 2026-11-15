import test from 'node:test';
import assert from 'node:assert/strict';
import { createHookHarness } from './helpers/hook-harness.mjs';
import { DELIVERY_INPUT_LIMIT } from '../features/projects/research-delivery-reader.ts';
import { originalDeliveryDownload, deliverySnapshotDownload, deliveryReadmeDownload } from '../features/projects/delivery-reader-downloads.ts';

const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
const file = (name, text, size = 2) => ({ name, size, text: typeof text === 'function' ? text : async () => text });
const opened = id => ({ project: { id, revision: 7 }, entries: [{ entry: { id: id + '-entry' }, snapshot: {}, snapshot_json: '{"x":-0}\r\n' }], readme: '# Study\r\n脑电研究\n', original_text: '{"package":"' + id + '"}', manifest_sha256: 'a'.repeat(64), exported_at: '2026-11-14T00:00:00Z', total_bytes: 10 });
async function controller(t, parse) {
  let sideEffects = 0;
  const forbidden = () => { sideEffects++; throw new Error('A local-file controller cannot use network or storage.'); };
  const harness = await createHookHarness({
    filename: new URL('../features/projects/use-delivery-reader.ts', import.meta.url), exportName: 'useDeliveryReader',
    imports: { DELIVERY_INPUT_LIMIT, openResearchDelivery: parse },
    globals: { fetch: forbidden, localStorage: { getItem: forbidden, setItem: forbidden }, sessionStorage: { getItem: forbidden, setItem: forbidden } },
  });
  t.after(() => { assert.equal(sideEffects, 0); harness.dispose(); });
  return harness;
}

void test('only a validated local package becomes selectable and clearing it discards all package state', async t => {
  const result = opened('one'), input = file('one.json', 'raw package');
  const harness = await controller(t, async (raw, signal) => { assert.equal(raw, 'raw package'); assert.equal(signal.aborted, false); return result; });
  await harness.act(state => state.openFile(input));
  assert.equal(harness.current.status, 'ready'); assert.equal(harness.current.opened.delivery, result); assert.equal(harness.current.opened.file, input);
  assert.equal(harness.current.selected, result.entries[0]);
  await harness.act(state => state.select('unvalidated-entry')); assert.equal(harness.current.selected, result.entries[0]);
  await harness.act(state => state.clear());
  assert.equal(harness.current.status, 'idle'); assert.equal(harness.current.opened, null); assert.equal(harness.current.selected, null);
});

void test('oversized files are rejected by byte size before File.text or parsing is called', async t => {
  let reads = 0, parses = 0;
  const harness = await controller(t, async () => { parses++; return opened('unexpected'); });
  await harness.act(state => state.openFile(file('large.json', () => { reads++; return '{}'; }, DELIVERY_INPUT_LIMIT + 1)));
  assert.equal(harness.current.status, 'error'); assert.equal(harness.current.opened, null); assert.equal(reads, 0); assert.equal(parses, 0);
  assert.match(harness.current.error, /大小上限/);
});

void test('validation errors clear any earlier valid package and are shown without rendering unverified data', async t => {
  const harness = await controller(t, async raw => { if (raw === 'bad') throw new Error('Checksum mismatch'); return opened('valid'); });
  await harness.act(state => state.openFile(file('good.json', 'good')));
  await harness.act(state => state.openFile(file('bad.json', 'bad')));
  assert.equal(harness.current.opened, null); assert.equal(harness.current.selected, null);
  assert.equal(harness.current.status, 'error'); assert.equal(harness.current.error, 'Checksum mismatch');
});

void test('a cancelled pending File.text never starts validation when its unabortable read later finishes', async t => {
  const pending = deferred(); let parses = 0;
  const harness = await controller(t, async () => { parses++; return opened('late'); });
  const reading = harness.current.openFile(file('slow.json', () => pending.promise)); await harness.flush();
  assert.equal(harness.current.status, 'loading'); await harness.act(state => state.clear(true));
  assert.equal(harness.current.status, 'idle'); assert.match(harness.current.notice, /取消/);
  pending.resolve('late'); await reading; await harness.flush();
  assert.equal(parses, 0); assert.equal(harness.current.opened, null);
});

void test('reselection ignores stale file reads while keeping the newer validated package', async t => {
  const pending = deferred(), parsed = [];
  const harness = await controller(t, async raw => { parsed.push(raw); return opened(raw); });
  const oldRead = harness.current.openFile(file('old.json', () => pending.promise));
  await harness.act(state => state.openFile(file('new.json', 'new')));
  pending.resolve('old'); await oldRead; await harness.flush();
  assert.deepEqual(parsed, ['new']); assert.equal(harness.current.opened.delivery.project.id, 'new');
});

void test('a late validator result cannot overwrite a reselected package even if the validator ignores its abort signal', async t => {
  const pending = deferred(); let oldSignal;
  const harness = await controller(t, async (raw, signal) => { if (raw === 'old') { oldSignal = signal; return pending.promise; } return opened(raw); });
  const oldRead = harness.current.openFile(file('old.json', 'old')); await harness.flush();
  await harness.act(state => state.openFile(file('new.json', 'new'))); assert.equal(oldSignal.aborted, true);
  pending.resolve(opened('old')); await oldRead; await harness.flush();
  assert.equal(harness.current.opened.delivery.project.id, 'new'); assert.equal(harness.current.status, 'ready');
});

void test('unmount cancels a pending file read without later validation or state writes', async t => {
  const pending = deferred(); let parses = 0;
  const harness = await controller(t, async () => { parses++; return opened('late'); });
  const reading = harness.current.openFile(file('slow.json', () => pending.promise)); await harness.flush(); harness.dispose();
  pending.resolve('late'); await reading; assert.equal(parses, 0);
});

void test('download descriptors retain exact original Blob bytes and original snapshot and readme strings', async () => {
  const result = opened('00000000-0000-4000-8000-000000000001');
  const bytes = new Uint8Array([239, 187, 191, ...new TextEncoder().encode(result.original_text)]);
  const input = new File([bytes], 'original.json', { type: 'application/json' });
  const original = originalDeliveryDownload(result, input);
  assert.equal(original.content, input); assert.deepEqual(new Uint8Array(await original.content.arrayBuffer()), bytes);
  assert.equal(deliverySnapshotDownload(result.entries[0]).content, '{"x":-0}\r\n');
  assert.equal(deliveryReadmeDownload(result).content, '# Study\r\n脑电研究\n');
  assert.match(original.filename, /^eeg-research-project-.*-r7\.json$/);
});
