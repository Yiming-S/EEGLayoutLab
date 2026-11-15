import type { ComputeJob } from '../../lib/local-compute';

type DesignStateInput = {
  ready: boolean;
  error: string;
  editing: boolean;
  hasLayout: boolean;
  hasChoice: boolean;
  // The controller already limits this to the current scientific request.
  currentStatus: Pick<ComputeJob, 'status' | 'cached'> | null;
};

export type DesignViewState = {
  phase: 'loading' | 'load-error' | 'area-record' | 'draft' | 'result-loading' | ComputeJob['status'];
  title: string;
  detail: string;
  action: 'new-radius' | 'configure' | 'task' | 'retry' | null;
  actionLabel?: string;
};

/** Display state only: scientific requests, layouts and scores stay in the controller. */
export function designViewState(input: DesignStateInput): DesignViewState {
  const { ready, error, editing, hasLayout, hasChoice, currentStatus } = input;
  if (error) return { phase: 'load-error', title: '所选方案无法读取', detail: '', action: null };
  if (!ready) return { phase: 'loading', title: '正在读取所选布局', detail: '正在读取布局记录和参数。', action: null };
  if (!editing) return {
    phase: 'area-record', title: '查看已有面积约束布局',
    detail: '当前显示总面积上限约束的原始布局。可查看指标、编辑电极，或新建每区半径约束方案。',
    action: 'new-radius', actionLabel: '新建每区半径约束方案',
  };
  switch (currentStatus?.status) {
    case 'queued': return {
      phase: 'queued', title: '布局计算已排队', detail: '当前配置已提交，等待计算。',
      action: 'task', actionLabel: '查看任务状态',
    };
    case 'running': return {
      phase: 'running', title: '正在计算布局', detail: '当前配置正在搜索和评价，完成后显示布局与指标。',
      action: 'task', actionLabel: '查看任务状态',
    };
    case 'cancelling': return {
      phase: 'cancelling', title: '正在停止布局计算', detail: '停止请求已提交，等待任务返回最终状态。',
      action: 'task', actionLabel: '查看任务状态',
    };
    case 'failed': return {
      phase: 'failed', title: '布局计算失败', detail: '查看计算面板中的原因后，可重试或调整条件。',
      action: 'retry', actionLabel: '查看原因与计算设置',
    };
    case 'timeout': return {
      phase: 'timeout', title: '布局计算已超时', detail: '可调整条件后重试，或重新提交当前配置。',
      action: 'retry', actionLabel: '查看原因与计算设置',
    };
    case 'cancelled': return {
      phase: 'cancelled', title: '布局计算已停止', detail: '可调整条件或重新提交当前配置。',
      action: 'retry', actionLabel: '查看原因与计算设置',
    };
    case 'no_layout': return {
      phase: 'no_layout', title: '本次搜索未找到完整布局',
      detail: '本次搜索未找到完整64点布局。可扩大半径或调整位置范围后再次计算。',
      action: 'configure', actionLabel: '查看布局参数与计算',
    };
  }
  if (hasLayout) return {
    phase: 'completed', title: '查看已完成的半径约束布局',
    detail: currentStatus?.cached === true ? '已有结果已读取，未重新计算。'
      : currentStatus?.status === 'completed' && currentStatus.cached === false ? '计算完成，结果已自动保存。'
        : '当前显示完整布局及其评价结果。',
    action: null,
  };
  if (currentStatus?.status === 'completed') return {
    phase: 'result-loading', title: '正在读取布局结果', detail: '任务已完成，布局与指标尚未载入。',
    action: 'task', actionLabel: '查看任务状态',
  };
  return {
    phase: 'draft', title: '设置半径约束布局',
    detail: hasChoice ? '已有匹配结果会自动读取；没有记录时，设置区域部位和每区半径后点击“开始布局计算”。'
      : '请先选择与区域数量兼容的位置组合。',
    action: 'configure', actionLabel: '查看布局参数与计算',
  };
}
