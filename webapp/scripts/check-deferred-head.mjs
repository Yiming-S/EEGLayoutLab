import test from 'node:test';
import assert from 'node:assert/strict';
import { createHookHarness } from './helpers/hook-harness.mjs';

const filename = new URL(
  '../features/reception/use-deferred-head.ts',
  import.meta.url,
);

async function fixture(t, available = true) {
  const observers = [];
  class Observer {
    constructor(callback, options) {
      this.callback = callback;
      this.options = options;
      observers.push(this);
    }
    observe(target) {
      this.target = target;
    }
    disconnect() {
      this.disconnected = true;
    }
  }
  const hook = await createHookHarness({
    filename,
    exportName: 'useDeferredHead',
    imports: {},
    globals: { IntersectionObserver: available ? Observer : undefined },
  });
  t.after(() => hook.dispose());
  return { hook, observers };
}

void test('3D activation waits until the placeholder is within the viewport margin', async (t) => {
  const { hook, observers } = await fixture(t);
  assert.equal(hook.current.active, false);
  assert.equal(observers.length, 0);
  const target = { id: 'placeholder' };
  await hook.act((state) => state.hostRef(target));
  assert.equal(observers.length, 1);
  const observer = observers[0];
  assert.equal(observer.target, target);
  assert.equal(observer.options.rootMargin, '200px');
  await hook.act(() => observer.callback([{ isIntersecting: false }]));
  assert.equal(hook.current.active, false);
  await hook.act(() => observer.callback([{ isIntersecting: true }]));
  assert.equal(hook.current.active, true);
  assert.equal(observer.disconnected, true);
  await hook.act(() => observer.callback([{ isIntersecting: false }]));
  assert.equal(
    hook.current.active,
    true,
    'Scrolling away must preserve the mounted viewer',
  );
  assert.equal(observers.length, 1);
});

void test('3D activation falls back on mount when observers are unavailable', async (t) => {
  const { hook, observers } = await fixture(t, false);
  await hook.act((state) => state.hostRef({ id: 'placeholder' }));
  assert.equal(hook.current.active, true);
  assert.equal(observers.length, 0);
});

void test('the explicit load action activates a viewer without waiting for visibility', async (t) => {
  const { hook, observers } = await fixture(t);
  await hook.act((state) => state.hostRef({ id: 'placeholder' }));
  await hook.act((state) => state.activate());
  assert.equal(hook.current.active, true);
  assert.equal(observers[0].disconnected, true);
});

void test('a removed placeholder disconnects its observer and ignores late delivery', async (t) => {
  const { hook, observers } = await fixture(t);
  await hook.act((state) => state.hostRef({ id: 'placeholder' }));
  const first = observers[0];
  await hook.act((state) => state.hostRef(null));
  assert.equal(first.disconnected, true);
  await hook.act(() => first.callback([{ isIntersecting: true }]));
  assert.equal(hook.current.active, false);
  await hook.act((state) => state.hostRef({ id: 'replacement' }));
  assert.equal(observers.length, 2);
  hook.dispose();
  assert.equal(observers[1].disconnected, true);
});
