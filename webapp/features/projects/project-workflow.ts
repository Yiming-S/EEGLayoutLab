import type { ProjectEntry, ProjectWorkflow, ResearchProject } from '../../client/projects';
import { decisionHref, jointDecisionThresholds, parseDecisionThresholds } from '../../lib/design-decision.ts';

export const emptyWorkflow: ProjectWorkflow = { reference_entry_id: null, candidate_entry_id: null, comparison_href: null };
export const comparableProjectEntries = (entries: ProjectEntry[]) => entries.filter(entry =>
  entry.kind === 'layout' && ['cache', 'strict_area', 'design_evaluation'].includes(entry.summary?.protocol ?? ''));

export function projectWorkflowFor(project: ResearchProject, referenceId: string | null, candidateId: string | null) {
  const entries = comparableProjectEntries(project.entries);
  const reference = entries.find(entry => entry.id === referenceId), candidate = entries.find(entry => entry.id === candidateId);
  if ((referenceId && !reference) || (candidateId && !candidate) || (referenceId && referenceId === candidateId))
    throw new Error('请选择项目中两个不同的可比较布局。');
  const thresholds = project.workflow?.comparison_href
    ? parseDecisionThresholds(new URL(project.workflow.comparison_href, 'http://localhost').searchParams)
    : jointDecisionThresholds(90);
  return { reference_entry_id: reference?.id ?? null, candidate_entry_id: candidate?.id ?? null,
    comparison_href: reference && candidate ? decisionHref([reference.record_id, candidate.record_id], thresholds) : null };
}

export function projectWorkflowFromComparison(project: ResearchProject, href: string): ProjectWorkflow {
  const url = new URL(href, 'http://localhost');
  if (url.origin !== 'http://localhost' || url.pathname !== '/decision') throw new Error('方案对比链接无效');
  const entries = comparableProjectEntries(project.entries), a = url.searchParams.get('a'), b = url.searchParams.get('b');
  const reference = entries.find(entry => entry.record_id === a), candidate = entries.find(entry => entry.record_id === b);
  if (!reference || !candidate || reference.id === candidate.id) throw new Error('请先将两个布局保存到此项目。');
  return { reference_entry_id: reference.id, candidate_entry_id: candidate.id,
    comparison_href: decisionHref([reference.record_id, candidate.record_id], parseDecisionThresholds(url.searchParams)) };
}
