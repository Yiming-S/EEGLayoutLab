import test from 'node:test';

export const testTier = process.env.EEG_TEST_TIER || 'all';
if (!['all', 'fast'].includes(testTier)) throw new Error(`Unsupported EEG_TEST_TIER: ${testTier}`);

// Only explicit external-bundle regressions are skipped. Synthetic fixtures and
// tracked browser assets remain part of fast checks, including within this file.
export const dataTest = (name, fn) => test(name, {
  skip: testTier === 'fast' ? 'Data tier: restore the separately verified scientific bundle' : false,
}, fn);
