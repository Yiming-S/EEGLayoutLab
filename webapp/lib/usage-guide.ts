import type { Locale } from './i18n/core.ts';
import { type DocsSite, docsHref } from './method-index.ts';

// One explanation per guide step, in the order of the five areas.
export const USAGE_EXPLANATIONS = [
  ['1. 五个板块', '工作区：最近的布局、计算任务、稳健性研究和项目。布局：新建布局（区域场景搜索、坐标导入与头型配准、电极编辑）和布局列表。分析：方案对比、稳健性与硬件尺码研究、信号仿真和通道子集。研究结果：总面积研究与历史批次。文档：本指南与建模原理。'],
  ['2. 研究结果', '总面积研究比较相同总面积上限下1、2、3、4、6个区域各保留多少信号（本历史批次固定64导）。选择一行查看点位与三项保留率；查看、筛选和调整场景参考线 τ 不会启动新计算。'],
  ['3. 新建布局与个体适配', '区域设计支持8、12、16、24、32、48、64七档导数、均分或跨区自适应配额，并可加载真实EEG或fMRI（NIfTI/MNI152峰值）任务先验；坐标导入既可评估外部64点坐标，也可通过头围/头长宽指数或正侧面头型照片标定生成个体化3D电极坐标；电极编辑可从已有64点布局删减或微调点位。'],
  ['4. 布局详情', '每个布局一页：同一组坐标在不同噪声模型、电导率、头模或数据先验下的评价排成一张表，名义Ernie评价在前。不同条件的分数只与相同条件比较。'],
  ['5. 稳健性与硬件尺码公差', '单次操作可检查位置偏移、跨条件复评或双方案对比；批量稳健性研究可跨随机种子、网格位移和11个头模汇总分位数，并提供成人 S/M/L 头围分档与弹簧顶针行程、切向漂移的硬件结构设计参考（支持CAD坐标表导出）。'],
  ['6. 信号仿真', '先选一个完整的64点布局，再设置脑源位置、波形和模拟干扰。布局坐标固定；此页比较所选场景下标准64导与当前布局的接收波形和信号重建。只有独立噪声下得到的布局进入信号仿真。'],
  ['7. 场景效能画像与参考线 τ', '全头64导仅作为同条件100%物理归一化刻度尺，并非所有穿戴应用都要追求100%。综合下界 G 与定位中位误差直观反映当前场景效能；拖动参考线 τ（如轻便穿戴35%、靶向脑区60%、全脑高密85%）只更新对照标尺，不改变点位、不重新计算。'],
] as const;

/**
 * The address a guide step opens. The showcase has no workspace home (design 0004, section 1), so the step that
 * opens it has no page link there; every other step opens its own page, which the showcase shows read-only.
 */
export function guideStepHref(path: string, ar: number, showcase: boolean): string | null {
  return showcase && path === '/' ? null : path + '?ar=' + ar;
}

/**
 * Locale-matched links from the in-app User Guide (/guide) to the full illustrated manuals
 * and command-line reference, resolving to local /docs/ when built (or in the showcase) and
 * falling back to GitHub Markdown otherwise.
 */
export function guideManualHrefs(locale: Locale, site: DocsSite, showcase = false) {
  const effectiveSite: DocsSite = showcase ? 'local' : site;
  const suffix = locale === 'zh-CN' ? '.zh-CN/' : '/';
  return {
    userManual: docsHref('user-manual' + suffix, effectiveSite),
    installation: docsHref('installation' + suffix, effectiveSite),
    sourceInstallation: docsHref('source-installation' + suffix, effectiveSite),
    commandLine: docsHref('command-line/', effectiveSite),
    external: effectiveSite === 'github',
  };
}
