/** The three terms a first-time reader meets before anything else, each with its method chapter. */
export const TERMS = {
  retention: { question: '相对保留效用是什么？', text: '当前布局在实验场景下的得分除以同条件标准64导刻度。100%是归一化标尺，轻便局部方案无需追求100%。', hash: '#retention-guide' },
  ar: { question: '场景目标参考线 τ 是什么？', text: '你按具体应用设定的对照参考线（如耳周穿戴35%、靶向脑区60%、全脑高密85%）。调整它只更新对照标尺，不重新计算。', hash: '#retention-ar' },
  head: { question: '头模与个体适配是什么？', text: '用于三维电场仿真的头部几何模型。默认使用Ernie有限元头模，同时支持个体头型照片/解剖尺度配准与跨头模尺码公差评估。', hash: '#retention-comparison' },
} as const;
export type Term = keyof typeof TERMS;
