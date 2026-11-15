/* oxlint-disable typescript/no-implied-eval -- compile trusted repository code for behavior tests */
import { readFile } from 'node:fs/promises';
import ts from 'typescript';

/** Run a real controller module with deterministic hooks and isolated I/O. */
export async function createHookHarness({ filename, exportName, imports, globals = {}, maxTimerMs = 20, args = [] }) {
  let source = await readFile(filename, 'utf8');
  const tree = ts.createSourceFile(String(filename), source, ts.ScriptTarget.Latest, true);
  for (const statement of [...tree.statements].reverse()) {
    if (ts.isImportDeclaration(statement)) source = source.slice(0, statement.pos) + source.slice(statement.end);
  }
  const code = ts.transpileModule(source, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
  }).outputText;
  const nativeTimeout = globalThis.setTimeout;
  const nativeInterval = globalThis.setInterval;
  const nativeClearTimeout = globalThis.clearTimeout;
  const nativeClearInterval = globalThis.clearInterval;
  const timers = new Set();
  const previous = new Map();
  const replace = (key, value) => {
    previous.set(key, Object.getOwnPropertyDescriptor(globalThis, key));
    Object.defineProperty(globalThis, key, { configurable: true, writable: true, value });
  };
  const duration = ms => Number.isFinite(maxTimerMs) ? Math.min(Number(ms) || 0, maxTimerMs) : ms;
  replace('setTimeout', (fn, ms, ...args) => {
    const timer = nativeTimeout(() => { timers.delete(timer); fn(...args); }, duration(ms));
    timers.add(timer); return timer;
  });
  replace('setInterval', (fn, ms, ...args) => {
    const timer = nativeInterval(fn, duration(ms), ...args); timers.add(timer); return timer;
  });
  replace('clearTimeout', timer => { timers.delete(timer); nativeClearTimeout(timer); });
  replace('clearInterval', timer => { timers.delete(timer); nativeClearInterval(timer); });
  for (const [key, value] of Object.entries(globals)) replace(key, value);

  const slots = [];
  let cursor = 0, effects = [], scheduled = false, disposed = false, current, renderError;
  const same = (a, b) => a && b && a.length === b.length && a.every((v, i) => Object.is(v, b[i]));
  const schedule = () => {
    if (scheduled || disposed) return;
    scheduled = true;
    queueMicrotask(() => {
      scheduled = false;
      if (disposed) return;
      try { render(); } catch (error) { renderError = error; }
    });
  };
  const useState = initial => {
    const i = cursor++;
    if (!(i in slots)) slots[i] = { value: typeof initial === 'function' ? initial() : initial };
    return [slots[i].value, next => {
      if (disposed) return;
      const value = typeof next === 'function' ? next(slots[i].value) : next;
      if (!Object.is(value, slots[i].value)) { slots[i].value = value; schedule(); }
    }];
  };
  const memo = (fn, deps) => {
    const i = cursor++;
    if (!slots[i] || !same(slots[i].deps, deps)) slots[i] = { value: fn(), deps };
    return slots[i].value;
  };
  const useRef = initial => {
    const i = cursor++;
    if (!(i in slots)) slots[i] = { value: { current: initial } };
    return slots[i].value;
  };
  const useEffect = (fn, deps) => {
    const i = cursor++;
    if (!slots[i] || !same(slots[i].deps, deps)) {
      const old = slots[i]; slots[i] = { deps };
      effects.push(() => { old?.cleanup?.(); slots[i].cleanup = fn(); });
    }
  };
  const hooks = { useState, useMemo: memo, useRef, useEffect, useLayoutEffect: useEffect, useCallback: (fn, deps) => memo(() => fn, deps) };
  const bindings = { ...imports, ...hooks };
  const exports = {};
  const dispose = () => {
    if (disposed) return;
    disposed = true;
    for (const slot of slots) slot?.cleanup?.();
    for (const timer of timers) { nativeClearTimeout(timer); nativeClearInterval(timer); }
    for (const [key, descriptor] of previous) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor);
      else delete globalThis[key];
    }
  };
  let controller;
  function render() {
    cursor = 0; current = controller(...args);
    const queued = effects; effects = [];
    for (const effect of queued) effect();
  }
  try {
    new Function('exports', ...Object.keys(bindings), code)(exports, ...Object.values(bindings));
    controller = exports[exportName];
    if (typeof controller !== 'function') throw new Error(`Missing controller export: ${exportName}`);
    render();
  } catch (error) { dispose(); throw error; }
  const flush = async () => {
    await new Promise(resolve => nativeTimeout(resolve, 0));
    if (renderError) throw renderError;
  };
  return {
    get current() { if (renderError) throw renderError; return current; },
    flush,
    async rerender() { render(); await flush(); },
    async act(fn) { const value = await fn(current); await flush(); return value; },
    async waitFor(predicate, { timeoutMs = 1000 } = {}) {
      const deadline = Date.now() + timeoutMs;
      while (!predicate(current)) {
        if (renderError) throw renderError;
        if (Date.now() >= deadline) throw new Error('Hook condition did not become true');
        await new Promise(resolve => nativeTimeout(resolve, 2));
      }
      return current;
    },
    evaluate(expression, extra = {}) {
      const values = { ...imports, current, ...extra };
      return new Function(...Object.keys(values), `return (${expression});`)(...Object.values(values));
    },
    dispose,
  };
}
