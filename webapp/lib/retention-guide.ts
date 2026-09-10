/** Frozen teaching example, not the currently selected design or a cache lookup. */
export const RETENTION_EXAMPLE = Object.freeze({
  recordId: 'd474e3b2006437767104367a8860d792e0b942963d08594ced8c82d96a2d722d',
  date: '2026-09-08',
  algorithm: 'strict-radius-local/2',
  fieldAbsolute: 0.56757062169407,
  referenceFieldAbsolute: 0.9930987747499561,
  fieldRelative: 0.57151477388236,
  sensitivity: 0.12504365995217767,
  localizationRelative: 0.18542696104991171,
  utility: 0.09662716771042167,
  referenceUtility: 0.5211063545630366,
  medianMm: 21.98380485308453,
  referenceMedianMm: 10.924877260771844,
  p90Mm: 58.8346141906012,
  referenceP90Mm: 20.594093975491354,
  global: 0.12504365995217767,
});

export const RETENTION_SECTIONS = [
  ['retention-comparison', '一、比较条件'],
  ['retention-field', '二、信号重建'],
  ['retention-sensitivity', '三、幅度保留率（最差10%）'],
  ['retention-localization', '四、相对定位评分'],
  ['retention-ar', '五、G与AR'],
  ['retention-geometry', '六、几何与性能'],
  ['retention-scope', '七、适用范围'],
  ['retention-reading', '八、阅读顺序'],
] as const;

export const isRetentionGuideHash = (hash: string) =>
  hash === '#retention-guide' || RETENTION_SECTIONS.some(([id]) => hash === '#' + id);

export const guidePercent = (value: number) => `${(value * 100).toFixed(2)}%`;
