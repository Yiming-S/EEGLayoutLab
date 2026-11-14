import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { setImmediate } from 'node:timers/promises';
import * as THREE from 'three';
import { createHeadAssetLoader } from '../viewer/assets.ts';
import { SOURCE_ROI_DEFINITION } from '../lib/source-regions.ts';

const hash = (bytes) =>
  createHash('sha256').update(new Uint8Array(bytes)).digest('hex');
const signal = () => new AbortController().signal;
const dispose = (geometries) =>
  geometries.forEach((geometry) => geometry.dispose());

function model(version = 1, useUint32 = false) {
  const bytes = new ArrayBuffer(useUint32 ? 60 : 52);
  new Float32Array(bytes, 0, 9).set([0, 0, 0, version / 10, 0, 0, 0, 0.1, 0]);
  new Int8Array(bytes, 36, 9).set([0, 0, 127, 0, 0, 127, 0, 0, 127]);
  const indexOffset = useUint32 ? 48 : 46;
  const Index = useUint32 ? Uint32Array : Uint16Array;
  new Index(bytes, indexOffset, 3).set([0, 1, 2]);
  const scalp = {
    id: 'scalp',
    file: 'scalp.bin',
    sha256: hash(bytes),
    attributes: {
      position: {
        type: 'Float32Array',
        byteOffset: 0,
        count: 9,
        itemSize: 3,
        normalized: false,
      },
      normal: {
        type: 'Int8Array',
        byteOffset: 36,
        count: 9,
        itemSize: 3,
        normalized: true,
      },
    },
    index: {
      type: Index.name,
      byteOffset: indexOffset,
      count: 3,
      itemSize: 1,
      normalized: false,
    },
  };
  const groups = Array.from({ length: 7 }, (_, materialIndex) => ({
    materialIndex,
    start: materialIndex <= 1 ? 0 : 3,
    count: materialIndex === 1 ? 3 : 0,
  }));
  const atlas = {
    definition_id: SOURCE_ROI_DEFINITION,
    mesh: {
      ...structuredClone(scalp),
      id: 'cortex',
      file: 'cortex.bin',
      groups,
    },
  };
  return { bytes, scalp, atlas };
}

function fixture({
  held = false,
  heldDigests = false,
  useUint32 = false,
  ...limits
} = {}) {
  const requests = [],
    digests = [],
    digestReleases = [];
  let current = model(1, useUint32),
    failure;
  const loader = createHeadAssetLoader({
    ...limits,
    sha256: async (bytes) => {
      digests.push(bytes);
      if (heldDigests)
        await new Promise((resolve) => digestReleases.push(resolve));
      return hash(bytes);
    },
    fetch: async (requestedUrl, init) => {
      const url = requestedUrl.split('?')[0];
      let release;
      const gate = new Promise((resolve) => {
        release = resolve;
      });
      const request = { url, requestedUrl, ...init, release };
      requests.push(request);
      const snapshot = current;
      if (url.endsWith('manifest.json'))
        return {
          ok: true,
          json: async () => ({ meshes: [structuredClone(snapshot.scalp)] }),
        };
      if (url.endsWith('source-roi.json'))
        return { ok: true, json: async () => structuredClone(snapshot.atlas) };
      const mode = url.endsWith('cortex.bin') ? failure : undefined;
      if (mode === 'network') throw new Error('Network failed');
      if (mode === 'http') return { ok: false, status: 503 };
      return {
        ok: true,
        arrayBuffer: async () => {
          // Intentionally ignore abort here: a late response must not replace a retry.
          if (held) await gate;
          const copy = snapshot.bytes.slice(0);
          if (mode === 'corrupt') new Uint8Array(copy)[0] ^= 1;
          return copy;
        },
      };
    },
  });
  return {
    loader,
    requests,
    digests,
    get model() {
      return current;
    },
    get binaryRequests() {
      return requests.filter(({ url }) => url.endsWith('.bin'));
    },
    get metadataRequests() {
      return requests.filter(({ url }) => url.endsWith('.json'));
    },
    update(version) {
      current = model(version, useUint32);
    },
    fail(mode) {
      failure = mode;
    },
    release() {
      requests.forEach((request) => request.release());
    },
    releaseDigests() {
      digestReleases.forEach((release) => release());
    },
  };
}

async function until(predicate) {
  for (let attempt = 0; attempt < 100 && !predicate(); attempt++)
    await setImmediate();
  assert.ok(predicate(), 'Expected asynchronous loading state was reached');
}

void test('concurrent viewers download and verify each versioned model once', async () => {
  const f = fixture({ held: true });
  const first = f.loader(signal()),
    second = f.loader(signal());
  await until(
    () => f.binaryRequests.length === 2 && f.metadataRequests.length === 4,
  );
  f.release();
  const [a, b] = await Promise.all([first, second]);
  assert.equal(f.binaryRequests.length, 2);
  assert.equal(f.digests.length, 2);
  for (const request of f.metadataRequests)
    assert.equal(request.cache, 'no-cache');
  for (const request of f.binaryRequests) {
    assert.equal(request.cache, 'default');
    assert.equal(
      new URL(request.requestedUrl, 'http://localhost').searchParams.get(
        'sha256',
      ),
      f.model.scalp.sha256,
    );
  }
  dispose(a);
  dispose(b);
  const warm = await f.loader(signal());
  assert.equal(
    f.metadataRequests.length,
    6,
    'new loads revalidate both indexes',
  );
  assert.equal(f.binaryRequests.length, 2);
  assert.equal(f.digests.length, 2);
  dispose(warm);
});

for (const useUint32 of [false, true]) {
  void test(`scene arrays and disposal remain independent with ${useUint32 ? '32' : '16'}-bit indices`, async () => {
    const f = fixture({ useUint32 });
    const [a, b] = await Promise.all([f.loader(signal()), f.loader(signal())]);
    for (let mesh = 0; mesh < 2; mesh++) {
      assert.notEqual(a[mesh], b[mesh]);
      for (const name of ['position', 'normal', 'index']) {
        const attribute = (geometry) =>
          name === 'index' ? geometry.index : geometry.getAttribute(name);
        const left = attribute(a[mesh]),
          right = attribute(b[mesh]);
        assert.notEqual(left.array.buffer, right.array.buffer);
        assert.deepEqual(left.array, right.array);
        left.array[0] = 99;
        assert.notEqual(right.array[0], 99);
      }
    }
    let bDisposals = 0;
    b.forEach((geometry) =>
      geometry.addEventListener('dispose', () => bDisposals++),
    );
    dispose(a);
    assert.equal(bDisposals, 0);
    assert.deepEqual(b[1].groups, f.model.atlas.mesh.groups);
    const warm = await f.loader(signal());
    assert.equal(warm[0].getAttribute('position').array[0], 0);
    assert.equal(warm[0].getAttribute('normal').array[0], 0);
    assert.equal(warm[0].index.array[0], 0);
    assert.ok(Math.abs(warm[0].getAttribute('position').getX(1) - 1) < 1e-7);
    assert.equal(warm[0].getAttribute('normal').normalized, true);
    assert.deepEqual(
      Array.from(warm[0].getAttribute('normal').array),
      [0, 0, 127, 0, 0, 127, 0, 0, 127],
    );
    dispose(b);
    dispose(warm);
    assert.equal(bDisposals, 2);
  });
}

void test('canceling one viewer leaves the other viewer and its download active', async () => {
  const f = fixture({ held: true }),
    canceled = new AbortController();
  const first = f.loader(canceled.signal),
    second = f.loader(signal());
  await until(
    () => f.binaryRequests.length === 2 && f.metadataRequests.length === 4,
  );
  canceled.abort();
  await assert.rejects(first, { name: 'AbortError' });
  assert.ok(f.binaryRequests.every((request) => !request.signal.aborted));
  f.release();
  dispose(await second);
  assert.equal(f.binaryRequests.length, 2);
  assert.equal(f.digests.length, 2);
});

void test('canceling all viewers aborts both downloads and a late response cannot poison their retry', async () => {
  const f = fixture({ held: true }),
    left = new AbortController(),
    right = new AbortController();
  const first = f.loader(left.signal),
    second = f.loader(right.signal);
  await until(
    () => f.binaryRequests.length === 2 && f.metadataRequests.length === 4,
  );
  const original = [...f.binaryRequests];
  left.abort();
  right.abort();
  await Promise.all([
    assert.rejects(first, { name: 'AbortError' }),
    assert.rejects(second, { name: 'AbortError' }),
  ]);
  assert.ok(original.every((request) => request.signal.aborted));
  const retry = f.loader(signal());
  await until(() => f.binaryRequests.length === 4);
  original.forEach((request) => request.release());
  await setImmediate();
  assert.equal(
    f.digests.length,
    0,
    'canceled bytes are discarded before checksum work',
  );
  f.release();
  dispose(await retry);
  dispose(await f.loader(signal()));
  assert.equal(
    f.binaryRequests.length,
    4,
    'late rejection did not remove the replacement',
  );
  assert.equal(f.digests.length, 2);
});

void test('an already canceled viewer makes no metadata or binary requests', async () => {
  const f = fixture(),
    controller = new AbortController();
  controller.abort();
  await assert.rejects(f.loader(controller.signal), { name: 'AbortError' });
  assert.equal(f.requests.length, 0);
});

void test('canceling after one geometry is built disposes it exactly once', async (t) => {
  const f = fixture({ held: true }),
    controller = new AbortController(),
    disposed = [];
  // oxlint-disable-next-line typescript/unbound-method -- preserve the geometry receiver
  const originalDispose = THREE.BufferGeometry.prototype.dispose;
  t.mock.method(THREE.BufferGeometry.prototype, 'dispose', function () {
    disposed.push(this);
    return originalDispose.call(this);
  });
  const pending = f.loader(controller.signal);
  await until(() => f.binaryRequests.length === 2);
  f.binaryRequests.find(({ url }) => url.endsWith('scalp.bin')).release();
  await until(() => f.digests.length === 1);
  await setImmediate();
  controller.abort();
  await assert.rejects(pending, { name: 'AbortError' });
  assert.equal(disposed.length, 1);
  assert.equal(
    f.binaryRequests.find(({ url }) => url.endsWith('cortex.bin')).signal
      .aborted,
    true,
  );
  f.release();
});

void test('canceling during checksum verification cannot retain abandoned bytes', async () => {
  const f = fixture({ heldDigests: true }),
    controller = new AbortController();
  const pending = f.loader(controller.signal);
  await until(() => f.digests.length === 2);
  controller.abort();
  await assert.rejects(pending, { name: 'AbortError' });
  const retry = f.loader(signal());
  await until(() => f.digests.length === 4);
  f.releaseDigests();
  dispose(await retry);
  dispose(await f.loader(signal()));
  assert.equal(f.binaryRequests.length, 4);
  assert.equal(f.digests.length, 4);
});

for (const mode of ['network', 'http', 'corrupt']) {
  void test(`${mode} failure is removed so the same model version can be retried`, async () => {
    const f = fixture();
    f.fail(mode);
    await assert.rejects(f.loader(signal()));
    f.fail(undefined);
    dispose(await f.loader(signal()));
    assert.equal(
      f.binaryRequests.filter(({ url }) => url.endsWith('scalp.bin')).length,
      1,
    );
    assert.equal(
      f.binaryRequests.filter(({ url }) => url.endsWith('cortex.bin')).length,
      2,
    );
    assert.equal(
      f.binaryRequests.findLast(({ url }) => url.endsWith('cortex.bin')).cache,
      'reload',
    );
    dispose(await f.loader(signal()));
    assert.equal(f.binaryRequests.length, 3);
  });
}

void test('changed checksums at unchanged URLs load the new deployment', async () => {
  const f = fixture();
  const old = await f.loader(signal());
  f.update(2);
  const updated = await f.loader(signal());
  assert.equal(f.binaryRequests.length, 4);
  assert.equal(f.digests.length, 4);
  assert.notEqual(
    f.binaryRequests[0].requestedUrl,
    f.binaryRequests[2].requestedUrl,
  );
  assert.notEqual(
    f.binaryRequests[1].requestedUrl,
    f.binaryRequests[3].requestedUrl,
  );
  assert.ok(Math.abs(old[0].getAttribute('position').getX(1) - 1) < 1e-7);
  assert.ok(Math.abs(updated[0].getAttribute('position').getX(1) - 2) < 1e-7);
  dispose(old);
  dispose(updated);
});

void test('fresh atlas grouping metadata applies even when verified bytes are reused', async () => {
  const f = fixture();
  dispose(await f.loader(signal()));
  f.model.atlas.mesh.groups = Array.from({ length: 7 }, (_, materialIndex) => ({
    materialIndex,
    start: materialIndex <= 2 ? 0 : 3,
    count: materialIndex === 2 ? 3 : 0,
  }));
  const updated = await f.loader(signal());
  assert.deepEqual(updated[1].groups, f.model.atlas.mesh.groups);
  assert.equal(f.binaryRequests.length, 2);
  dispose(updated);
});

void test('unversioned scalp files are refreshed between loads', async () => {
  const f = fixture();
  delete f.model.scalp.sha256;
  dispose(await f.loader(signal()));
  dispose(await f.loader(signal()));
  assert.equal(
    f.binaryRequests.filter(({ url }) => url.endsWith('scalp.bin')).length,
    2,
  );
  assert.equal(
    f.binaryRequests.filter(({ url }) => url.endsWith('cortex.bin')).length,
    1,
  );
});

for (const limits of [{ maxCacheBytes: 104 }, { maxCacheEntries: 2 }]) {
  void test(`old models are evicted within ${Object.keys(limits)[0]}`, async () => {
    const f = fixture(limits);
    dispose(await f.loader(signal()));
    f.update(2);
    dispose(await f.loader(signal()));
    dispose(await f.loader(signal()));
    assert.equal(f.binaryRequests.length, 4, 'current version remains warm');
    f.update(1);
    dispose(await f.loader(signal()));
    assert.equal(f.binaryRequests.length, 6, 'old version was evicted');
  });
}

void test('models larger than the byte budget are shared in flight but not retained', async () => {
  const f = fixture({ maxCacheBytes: 1 });
  const pair = await Promise.all([f.loader(signal()), f.loader(signal())]);
  pair.forEach(dispose);
  assert.equal(f.binaryRequests.length, 2);
  dispose(await f.loader(signal()));
  assert.equal(f.binaryRequests.length, 4);
});
