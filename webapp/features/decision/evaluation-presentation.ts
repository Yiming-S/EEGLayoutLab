import type { DesignJob, DesignResult } from '../../lib/design-decision';

/** Current read/compute status and the saved scientific origin are separate facts. */
export function evaluationPresentation(job: Pick<DesignJob, 'cached'> | null, result: Pick<DesignResult, 'forward_mode'>) {
  return {
    heading: job?.cached ? '已读取保存的坐标评价' : '坐标评价结果',
    origin: result.forward_mode === 'direct_fem' ? '新位置FEM' : result.forward_mode === 'cached_fem' ? '已有前向库FEM' : '未记录',
    forward_mode: result.forward_mode,
  };
}
