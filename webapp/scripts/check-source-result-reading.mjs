import test from 'node:test';
import assert from 'node:assert/strict';
import { reconstructionNotice, lowerArtifactScale } from '../lib/source-result-reading.ts';

const score = (baseline, candidate, retention) => ({
  baseline: { explained_energy: baseline },
  candidate: { explained_energy: candidate },
  field_retention: retention,
});

void test('negative reconstruction and an unusable reference receive distinct explanations without altering scores', () => {
  const both = score(-26.9566, -21.079, null);
  const before = structuredClone(both);
  assert.equal(reconstructionNotice(both).title, '两套布局的重建解释率均为负。');
  assert.deepEqual(both, before);
  assert.equal(reconstructionNotice(score(0, 0.4, null)).title, '当前相对保留率无法定义。');
  assert.equal(reconstructionNotice(score(0.9, -0.2, -0.2 / 0.9)).title, '自定义布局的重建解释率为负。');
  assert.equal(reconstructionNotice(score(0.9, 0.4, 0.4 / 0.9)), null);
});

void test('reducing artifacts follows the supported amplitude settings and stops at zero', () => {
  assert.deepEqual([4, 2, 1, 0.5, 0].map(lowerArtifactScale), [2, 1, 0.5, 0, null]);
});
