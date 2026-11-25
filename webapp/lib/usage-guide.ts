// One explanation per guide step, in the order of the five areas.
export const USAGE_EXPLANATIONS = [
  ['1. 五个板块', '工作区：最近的布局、计算任务、研究和项目。布局：新建布局（区域设计、坐标导入、电极编辑）和布局列表。分析：方案对比、稳健性研究、信号仿真和通道子集。研究结果：已发表的总面积研究与历史批次。文档：本指南与建模原理。'],
  ['2. 研究结果', '总面积研究比较相同总面积上限下1、2、3、4、6个区域各保留多少信号。选择一行查看点位与三项保留率；查看、筛选和调整AR不会启动新计算。'],
  ['3. 新建布局', '区域设计固定64点并按区域均衡分配，按每区半径上限搜索；坐标导入读取已有电极坐标并在当前条件下评价；电极编辑从已有布局删减或移动点位，另存为编辑副本。新结果自动保存，相同配置优先直接读取。'],
  ['4. 布局详情', '每个布局一页：同一组坐标在不同噪声模型、电导率、头模或数据先验下的评价排成一张表，名义Ernie评价在前。不同条件的分数只与相同条件比较。'],
  ['5. 一个问题，一次操作或一项研究', '一次请求就能回答的问题是一个操作：在其他条件下评价、位置偏移测试、与另一个布局对比。需要多次请求的问题是稳健性研究：按随机种子、头模或网格位移重复评价并汇总。'],
  ['6. 信号仿真', '先选一个完整的64点布局，再设置脑源位置、波形和模拟干扰。布局坐标固定；此页比较所选场景下标准64导与当前布局的接收波形和信号重建。只有独立噪声下得到的布局进入信号仿真。'],
  ['7. 三项保留率与AR', '与同一协议下的标准全头64导比较。信号重建保留率衡量恢复全头信号的能力；幅度保留率（最差10%）取相对损失最大的10%源面积权重的幅度比；相对定位评分由误差换算。默认三项都要达到同一最低要求AR；修改AR只重新判断已有数值，不改变点位、不重新计算。'],
] as const;

/**
 * The address a guide step opens. The showcase has no workspace home (design 0004, section 1), so the step that
 * opens it has no page link there; every other step opens its own page, which the showcase shows read-only.
 */
export function guideStepHref(path: string, ar: number, showcase: boolean): string | null {
  return showcase && path === '/' ? null : path + '?ar=' + ar;
}
