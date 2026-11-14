import test from 'node:test';
import assert from 'node:assert/strict';
import {
  peakSourceTime,
  sourcePresentation,
  receiverTraces,
  reconstructionTrace,
  sharedAmplitude,
  strengthCurve,
  sourceTraceAt,
  layoutPresentation,
} from '../features/reception/result-view-model.ts';
import {
  SOURCE_ROI_DEFINITION,
  SOURCE_REGIONS,
  UNASSIGNED_SOURCE_COLOR,
} from '../lib/source-regions.ts';
import { createHookHarness } from './helpers/hook-harness.mjs';

function resultFixture() {
  const component = (factor) =>
    Array.from({ length: 64 }, (_, channel) =>
      Array.from({ length: 12 }, (_, time) => factor * (channel + time + 1)),
    );
  const side = (factor) => ({
    brain_uv: component(factor),
    ecg_uv: component(2),
    eog_uv: component(3),
    noise_uv: component(4),
    reconstructed_brain_uv: component(factor * 10),
    reconstructed_ecg_uv: component(20),
    reconstructed_eog_uv: component(30),
    reconstructed_noise_uv: component(40),
  });
  const score = (scale, retention) => ({
    condition: 'mixed',
    artifact_scale: scale,
    field_retention: retention,
    baseline: { explained_energy: -0.2 },
    candidate: { explained_energy: -0.4 },
  });
  return {
    request: { record_id: 'a'.repeat(64) },
    source: {
      region_definition: SOURCE_ROI_DEFINITION,
      source_regions: ['frontal', null],
      xyz_mm: [
        [1, 2, 3],
        [4, 5, 6],
      ],
    },
    layout: {
      xyzMm: Array.from({ length: 64 }, (_, i) => [i, i + 1, i + 2]),
      referenceXyzMm: Array.from({ length: 64 }, (_, i) => [
        i + 3,
        i + 4,
        i + 5,
      ]),
      regionIndices: Array.from({ length: 64 }, (_, i) => (i < 32 ? 0 : 1)),
    },
    strength_curve: [
      score(0, null),
      score(1, 0.85),
      score(2, 0.95),
      { ...score(3, 1), condition: 'ecg' },
    ],
    waveforms: {
      time_s: Array.from({ length: 12 }, (_, i) => i / 10),
      source_nam: [[0, 1, 2, 3, 4, 5, 6, 10, 8, 7, 6, 5], Array(12).fill(1)],
      baseline: side(1),
      candidate: side(5),
    },
  };
}

void test('receiver and reconstruction projections preserve condition sums, target truth and shared scale', () => {
  const result = resultFixture(),
    before = structuredClone(result);
  for (const [condition, artifact] of [
    ['clean', 0],
    ['ecg', 2],
    ['eog', 3],
    ['mixed', 5],
  ]) {
    const traces = receiverTraces(result, [1, 2], condition);
    assert.deepEqual(traces[0][0], {
      time: 0,
      brain: 2,
      artifact: artifact * 2,
      mixed: (1 + artifact + 4) * 2,
    });
    assert.deepEqual(traces[1][0], {
      time: 0,
      brain: 15,
      artifact: artifact * 3,
      mixed: (5 + artifact + 4) * 3,
    });
    const reconstructed = reconstructionTrace(result, 3, condition);
    assert.deepEqual(reconstructed[0], {
      time: 0,
      truth: 4,
      baseline: (10 + artifact * 10 + 40) * 4,
      candidate: (50 + artifact * 10 + 40) * 4,
    });
    assert.equal(sharedAmplitude(traces), (5 + artifact + 4) * 14 * 1.08);
  }
  assert.deepEqual(result, before);
  assert.equal(
    sharedAmplitude([[{ brain: 0, artifact: 0, mixed: 0 }]]),
    0.00108,
  );
});

void test('display curves retain negative scores and unavailable ratios; AR only selects existing samples', () => {
  const result = resultFixture(),
    before = structuredClone(result);
  const view = strengthCurve(result, 'mixed', 90);
  assert.deepEqual(view.curve, [
    { strength: 0, baseline: -20, candidate: -40, retention: null },
    { strength: 1, baseline: -20, candidate: -40, retention: 85 },
    { strength: 2, baseline: -20, candidate: -40, retention: 95 },
  ]);
  assert.deepEqual(
    view.passing.map((score) => score.artifact_scale),
    [2],
  );
  assert.deepEqual(
    strengthCurve(result, 'mixed', 80).passing.map(
      (score) => score.artifact_scale,
    ),
    [1, 2],
  );
  assert.deepEqual(result, before);
});

void test('source selection and layout projections keep coordinates and atlas colors unchanged', () => {
  const result = resultFixture(),
    before = structuredClone(result);
  assert.equal(peakSourceTime(result.waveforms), 7);
  assert.deepEqual(sourceTraceAt(result, 0)[7], { time: 0.7, source: 10 });
  const sources = sourcePresentation(result);
  assert.deepEqual(sources.colors, [
    SOURCE_REGIONS.find((region) => region.id === 'frontal').color,
    UNASSIGNED_SOURCE_COLOR,
  ]);
  assert.deepEqual(
    sourcePresentation({
      ...result,
      source: { ...result.source, region_definition: undefined },
    }).regions,
    [null, null],
  );
  const layouts = layoutPresentation(result);
  assert.equal(layouts.counts, 2);
  assert.deepEqual(layouts.allocation, [32, 32]);
  assert.equal(layouts.baselineLayout.xyzMm, result.layout.referenceXyzMm);
  assert.equal(layouts.candidateLayout.xyzMm, result.layout.xyzMm);
  assert.equal(
    layouts.candidateLayout.regionIndices,
    result.layout.regionIndices,
  );
  assert.deepEqual(result, before);
});

void test('playback starts at peak energy, wraps by five samples, seeks, pauses and cleans its only timer', async (t) => {
  const timers = new Map();
  let nextTimer = 0;
  const harness = await createHookHarness({
    filename: new URL(
      '../features/reception/use-result-playback.ts',
      import.meta.url,
    ),
    exportName: 'useResultPlayback',
    args: [resultFixture().waveforms],
    imports: { peakSourceTime },
    globals: {
      setInterval: (callback, ms) => {
        assert.equal(ms, 100);
        const id = nextTimer++;
        timers.set(id, callback);
        return id;
      },
      clearInterval: (id) => timers.delete(id),
    },
  });
  t.after(() => harness.dispose());
  assert.equal(harness.current.time, 7);
  assert.equal(timers.size, 0);
  await harness.act((state) => state.setPlaying(true));
  assert.equal(timers.size, 1);
  await harness.act(() => [...timers.values()][0]());
  assert.equal(harness.current.time, 0);
  await harness.act(() => [...timers.values()][0]());
  assert.equal(harness.current.time, 5);
  await harness.act((state) => {
    state.setTime(3);
    state.setPlaying(false);
  });
  assert.equal(harness.current.time, 3);
  assert.equal(timers.size, 0);
  await harness.act((state) => state.setPlaying(true));
  assert.equal(timers.size, 1);
  harness.dispose();
  assert.equal(timers.size, 0);
});

void test('hidden pages suspend playback work and resume from the same sample', async (t) => {
  class Page extends EventTarget {
    hidden = true;
    listeners = new Set();
    addEventListener(name, callback) {
      super.addEventListener(name, callback);
      this.listeners.add(callback);
    }
    removeEventListener(name, callback) {
      super.removeEventListener(name, callback);
      this.listeners.delete(callback);
    }
    show(visible) {
      this.hidden = !visible;
      this.dispatchEvent(new Event('visibilitychange'));
    }
  }
  const page = new Page(),
    timers = new Map();
  let nextTimer = 0;
  const harness = await createHookHarness({
    filename: new URL(
      '../features/reception/use-result-playback.ts',
      import.meta.url,
    ),
    exportName: 'useResultPlayback',
    args: [resultFixture().waveforms],
    imports: { peakSourceTime },
    globals: {
      document: page,
      setInterval: (callback) => {
        const id = nextTimer++;
        timers.set(id, callback);
        return id;
      },
      clearInterval: (id) => timers.delete(id),
    },
  });
  t.after(() => harness.dispose());
  await harness.act((state) => state.setPlaying(true));
  assert.equal(harness.current.playing, true);
  assert.equal(harness.current.time, 7);
  assert.equal(timers.size, 0);
  await harness.act(() => page.show(true));
  assert.equal(timers.size, 1);
  const queued = [...timers.values()][0];
  await harness.act(() => queued());
  assert.equal(harness.current.time, 0);
  await harness.act(() => page.show(false));
  assert.equal(timers.size, 0);
  assert.equal(harness.current.playing, true);
  await harness.act(() => queued());
  assert.equal(
    harness.current.time,
    0,
    'A queued callback cannot advance a hidden page',
  );
  await harness.act((state) => state.setTime(3));
  await harness.act(() => page.show(true));
  assert.equal(timers.size, 1);
  await harness.act(() => [...timers.values()][0]());
  assert.equal(harness.current.time, 8);
  await harness.act(() => page.show(true));
  assert.equal(
    timers.size,
    1,
    'Repeated visibility events cannot create duplicate timers',
  );
  await harness.act(() => page.show(false));
  await harness.act((state) => state.setPlaying(false));
  assert.equal(page.listeners.size, 0);
  await harness.act(() => page.show(true));
  assert.equal(timers.size, 0, 'Manual pause remains paused after returning');
  await harness.act((state) => state.setPlaying(true));
  harness.dispose();
  assert.equal(timers.size, 0);
  assert.equal(page.listeners.size, 0);
});
