import {
  CONDUCTIVITY_SCENARIOS,
  NOISE_MODEL_PRESETS,
  ROBUSTNESS_PROTOCOL,
  normalizeConductivityScenario,
  normalizeDataPrior,
  normalizeHeadId,
  normalizeNoiseModel,
  normalizeRobustness,
} from '../contracts/scientific-options.mjs';
import type { DataPrior } from './local-compute';

/**
 * The action the conditions are for. A study protocol names the requests it sends:
 * noise seeds evaluate on Ernie, heads evaluate with one head per case, grid
 * displacements run `perturb`.
 */
export type ConditionAction = 'search' | 'evaluate' | 'perturb' | 'study';
export type StudyProtocol = 'noise_seeds' | 'grid_displacements' | 'heads';
export type ConditionValues = {
  noiseModelId: string;
  /** Present when the caller manages the conductivity scenario ('' is the default). */
  scenarioId?: string;
  /** Present when the caller manages cross-session robustness. */
  robustness?: boolean;
  /** Present when the caller manages a data prior. */
  dataPrior?: DataPrior | null;
  dataPriorSource?: string;
};

const accepts = (check: () => unknown) => { try { check(); return true; } catch { return false; } };
/** Any valid head id: only whether one is set matters to the rules. */
const SOME_HEAD = 'head';
const SPATIAL = NOISE_MODEL_PRESETS.find(preset => preset.id !== 'iid' && preset.value)!.value;

function requestShape(action: ConditionAction, protocol?: StudyProtocol) {
  if (action !== 'study') return { action, head: undefined as string | undefined };
  return protocol === 'grid_displacements' ? { action: 'perturb' as const, head: undefined }
    : { action: 'evaluate' as const, head: protocol === 'heads' ? SOME_HEAD : undefined };
}

/**
 * What the condition form may offer for one action, decided by the contract's own
 * normalizers so the form adds no rule of its own: it offers exactly the combinations
 * the service accepts.
 */
export function conditionChoices(action: ConditionAction, values: ConditionValues, protocol?: StudyProtocol) {
  const { action: sent, head } = requestShape(action, protocol);
  const prior = values.dataPrior ?? undefined;
  const scenario = values.scenarioId || undefined;
  const noisePresets = NOISE_MODEL_PRESETS.filter(preset =>
    accepts(() => normalizeNoiseModel(preset.value, { allowBrainBackground: action !== 'search' })));
  const scenarioOffered = 'scenarioId' in values && CONDUCTIVITY_SCENARIOS.some(item => item.id && accepts(() => {
    const value = normalizeConductivityScenario(item.id, sent);
    normalizeHeadId(head, sent, value);
  }));
  // A study sends neither a robustness block nor a data prior.
  const robustnessOffered = 'robustness' in values && action !== 'study' && accepts(() => normalizeRobustness(ROBUSTNESS_PROTOCOL, sent, undefined, head));
  const robustnessAllowed = robustnessOffered && accepts(() => normalizeRobustness(ROBUSTNESS_PROTOCOL, sent, scenario, head));
  const dataPriorOffered = 'dataPrior' in values && action !== 'study' && !head;
  return {
    noisePresets,
    /** A data prior carries its own noise structure, so no noise model goes with it. */
    noiseLocked: !!prior && !accepts(() => normalizeDataPrior(prior, { noiseModel: SPATIAL })),
    scenarioOffered,
    robustnessOffered,
    robustnessAllowed,
    dataPriorOffered,
  };
}
