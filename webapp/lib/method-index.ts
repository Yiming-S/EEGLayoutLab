/**
 * The method page is an index: the method itself is written once, in the
 * repository's documentation (docs/). Each entry names a chapter and the
 * anchors the page used to have, so older links land on a pointer to it.
 */
export type MethodEntry = { ids: readonly string[]; title: string; doc: string };
export type MethodGroup = { id: string; title: string; text: string; page: string; entries: readonly MethodEntry[] };

export const METHOD_GROUPS: readonly MethodGroup[] = [
  { id: 'method-model', title: '模型与指标', page: 'model-and-metrics', text: '头模、脑源、噪声、三项保留率的定义与公式、阈值与布局约束，以及分数的适用范围。', entries: [
    { ids: ['retention-guide'], title: '三项指标与计算公式', doc: 'model-and-metrics/#three-relative-metrics' },
    { ids: ['retention-comparison'], title: '头模、脑源与观测', doc: 'model-and-metrics/#head-model-sources-and-observations' },
    { ids: ['retention-field'], title: '噪声与信号重建', doc: 'model-and-metrics/#noise-and-reconstruction' },
    { ids: ['retention-sensitivity'], title: '幅度保留率（最差10%）', doc: 'model-and-metrics/#amplitude-retention-in-the-lower-10-tail' },
    { ids: ['retention-localization'], title: '相对定位评分', doc: 'model-and-metrics/#relative-localization-score' },
    { ids: ['retention-ar'], title: 'AR阈值与搜索目标', doc: 'model-and-metrics/#thresholds-and-search-objectives' },
    { ids: ['retention-geometry'], title: '布局约束', doc: 'model-and-metrics/#layout-constraints' },
    { ids: ['model-terms'], title: '布置部位与术语', doc: 'model-and-metrics/#placement-sites-and-terms' },
    { ids: ['retention-reading'], title: '结果阅读顺序', doc: 'model-and-metrics/#reading-order' },
    { ids: ['retention-scope'], title: '分数的适用范围', doc: 'model-and-metrics/#scope-of-the-scores' },
    { ids: ['method-references'], title: '参考文献与模型来源', doc: 'model-and-metrics/#method-references' },
    { ids: ['reference-list'], title: '完整参考文献（按主题）', doc: 'references/' },
  ] },
  { id: 'method-details', title: '方法细节', page: 'method-details', text: '信号生成、组织传播、脑源与波形、干扰、默认参数，以及每个工具（搜索、编辑、坐标评价、信号仿真）的计算方式。', entries: [
    { ids: ['simulation-model', 'simulation-overview'], title: '脑源、头模与信号生成', doc: 'method-details/#signal-model' },
    { ids: ['simulation-forward'], title: '组织传播与导联场 H', doc: 'method-details/#forward-model' },
    { ids: ['simulation-fem-details'], title: 'FEM与互易定理', doc: 'method-details/#fem-and-reciprocity' },
    { ids: ['simulation-sources'], title: '4096、256与当前模拟源', doc: 'method-details/#source-activity' },
    { ids: ['simulation-prior-details'], title: '源采样与协方差', doc: 'method-details/#source-sampling-and-covariance' },
    { ids: ['simulation-waveform-details'], title: '脑源波形', doc: 'method-details/#waveforms' },
    { ids: ['simulation-source-regions'], title: '六个脑区（DK40）', doc: 'SOURCE_ROI_VALIDATION/#native-geometry-and-membership' },
    { ids: ['simulation-comparison'], title: '标准64导与布局对照', doc: 'method-details/#layout-comparison' },
    { ids: ['simulation-artifacts'], title: '噪声、心电与眼电干扰', doc: 'method-details/#ecg-and-eog' },
    { ids: ['simulation-parameters'], title: '默认参数', doc: 'method-details/#default-parameters' },
    { ids: ['local-compute'], title: '布局搜索与缓存规则', doc: 'method-details/#local-layout-search' },
    { ids: ['electrode-editor'], title: '电极编辑', doc: 'method-details/#electrode-editing' },
    { ids: ['design-decision'], title: '坐标评价与位置偏移测试', doc: 'method-details/#coordinate-evaluation' },
    { ids: ['source-field-interaction'], title: '信号仿真', doc: 'method-details/#reception-simulation' },
    { ids: ['anatomical-display'], title: '三维显示与模型来源', doc: 'method-details/#display-geometry' },
  ] },
  { id: 'method-history', title: '历史研究与验证', page: 'historical-studies', text: '最初的半径批次与两区域原型按原协议保留；验证页列出已完成的检查与仍未完成的工作。', entries: [
    { ids: ['single-head-optimization'], title: '半径批次实验', doc: 'historical-studies/#radius-batch' },
    { ids: ['first-batch'], title: '两区域原型', doc: 'historical-studies/#two-region-pilot' },
    { ids: ['planned-validation'], title: '早期验证计划', doc: 'historical-studies/#early-validation-plan' },
    { ids: ['method-validation'], title: '验证与未完成项', doc: 'validation/' },
  ] },
];

export const METHOD_ENTRIES = METHOD_GROUPS.flatMap(group => group.entries);
/** The chapter an old method-page anchor now lives in. */
export const movedSection = (hash: string) => METHOD_ENTRIES.find(entry => entry.ids.includes(hash.replace(/^#/, '')));

export type DocsSite = 'local' | 'github';
const GITHUB_DOCS = 'https://github.com/Yiming-S/EEGLayoutLab/blob/main/docs/';
/**
 * A chapter on the documentation site the local service serves under /docs/,
 * else the Markdown on GitHub (same headings, so the same anchors).
 */
export function docsHref(doc: string, site: DocsSite) {
  const [page, anchor = ''] = doc.split('/#');
  const name = page.replace(/\/$/, '');
  return site === 'local' ? `/docs/${name}/${anchor ? '#' + anchor : ''}` : `${GITHUB_DOCS}${name}.md${anchor ? '#' + anchor : ''}`;
}
