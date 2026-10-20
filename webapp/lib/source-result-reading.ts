import type { SourceScore } from './source-reception';

/** Explain saved scores without changing the scores or their acceptance rule. */
export function reconstructionNotice(score: SourceScore) {
  if (score.baseline.explained_energy < 0 && score.candidate.explained_energy < 0) {
    return {
      title: '两套布局的重建解释率均为负。',
      explanation: '重建误差超过干净信号功率，当前相对保留率无法定义。',
    };
  }
  if (score.field_retention === null) {
    return {
      title: '当前相对保留率无法定义。',
      explanation: '标准布局的重建解释率非正或过小，无法作为有效的相对比较基准。',
    };
  }
  if (score.candidate.explained_energy < 0) {
    return {
      title: '自定义布局的重建解释率为负。',
      explanation: '自定义布局的重建误差超过干净信号功率。原始评分保留在下表中。',
    };
  }
  return null;
}

export function lowerArtifactScale(scale: number) {
  return [0, 0.5, 1, 2, 4].filter((value) => value < scale).at(-1) ?? null;
}
