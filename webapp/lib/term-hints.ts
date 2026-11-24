/** The three terms a first-time reader meets before anything else, each with its method chapter. */
export const TERMS = {
  retention: { question: '保留率是什么？', text: '布局的得分除以标准64导全头布置的得分。100%表示与全头64导相同。', hash: '#retention-guide' },
  ar: { question: '最低保留要求是什么？', text: '你设定的合格线：三项保留率都达到它才算合格。改变它只重新判断，不重新计算。', hash: '#retention-ar' },
  head: { question: '头模是什么？', text: '用于仿真的头部模型（由MRI重建的头皮、颅骨和脑组织）。默认是Ernie；其他头模用来检查结论是否只适用于一个人的头。', hash: '#retention-comparison' },
} as const;
export type Term = keyof typeof TERMS;
