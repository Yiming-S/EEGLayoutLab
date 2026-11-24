'use client';
import { useLanguage } from '@/components/language-provider';
import { DataPriorPicker } from '@/features/data/data-prior-picker';
import { CONDUCTIVITY_SCENARIOS } from '../../contracts/scientific-options.mjs';
import { conditionChoices, type ConditionAction, type ConditionValues, type StudyProtocol } from '@/lib/evaluation-conditions';
import { cn } from '@/lib/utils';

/**
 * The evaluation conditions of one action — a search, an evaluation, a position-offset
 * test or a study protocol. Values, labels and the combinations offered all come from
 * the scientific-options contract; a page passes only the conditions it manages.
 */
export function EvaluationConditions({ action, protocol, values, onChange, disabled = false, className, hints = {} }: {
  action: ConditionAction;
  protocol?: StudyProtocol;
  values: ConditionValues;
  onChange: (patch: Partial<ConditionValues>) => void;
  disabled?: boolean;
  className?: string;
  /** Page-specific explanations shown under a control. */
  hints?: { noise?: string; scenario?: string; robustness?: string; robustnessBlocked?: string };
}) {
  const { tx } = useLanguage();
  const choices = conditionChoices(action, values, protocol);
  const prior = values.dataPrior ?? null;
  return <div className={cn('grid gap-3', className)} data-evaluation-conditions={action}>
    <label className="lab-label">
      {tx('噪声模型')}
      <select className="lab-select mt-2" aria-label={tx('噪声模型')} value={values.noiseModelId} disabled={disabled || choices.noiseLocked}
        onChange={event => { if (choices.noisePresets.some(preset => preset.id === event.target.value)) onChange({ noiseModelId: event.target.value }); }}>
        {choices.noisePresets.map(preset => <option key={preset.id} value={preset.id}>{tx(preset.label)}</option>)}
      </select>
      {(choices.noiseLocked || hints.noise) && <span className="mt-1 block text-xs font-normal leading-5 text-muted-foreground">
        {tx(choices.noiseLocked ? '已载入数据先验，噪声结构由数据先验给出。' : hints.noise!)}
      </span>}
    </label>
    {choices.dataPriorOffered && <DataPriorPicker value={prior} source={values.dataPriorSource ?? ''} disabled={disabled}
      onChange={(value, source) => onChange({ dataPrior: value, dataPriorSource: source ?? '' })} />}
    {choices.scenarioOffered && <label className="lab-label">
      {tx('数据生成头模电导率')}
      <select className="lab-select mt-2" aria-label={tx('数据生成头模电导率')} value={values.scenarioId ?? ''} disabled={disabled}
        onChange={event => { if (CONDUCTIVITY_SCENARIOS.some(item => item.id === event.target.value)) onChange({ scenarioId: event.target.value }); }}>
        {CONDUCTIVITY_SCENARIOS.map(item => <option key={item.id} value={item.id}>{tx(item.label)}</option>)}
      </select>
      {hints.scenario && <span className="mt-1 block text-xs font-normal leading-5 text-muted-foreground">{tx(hints.scenario)}</span>}
    </label>}
    {choices.robustnessOffered && <label className="flex items-start gap-2 text-sm">
      <input type="checkbox" className="mt-1" checked={!!values.robustness && choices.robustnessAllowed} disabled={disabled || !choices.robustnessAllowed}
        onChange={event => onChange({ robustness: event.target.checked })} />
      <span>{tx('同时评价跨会话稳健性（电极脱落、电极噪声不均、重新佩戴）')}
        {(hints.robustness || hints.robustnessBlocked) && <span className="mt-1 block text-xs leading-5 text-muted-foreground">
          {tx(!choices.robustnessAllowed && hints.robustnessBlocked ? hints.robustnessBlocked : hints.robustness ?? '')}
        </span>}
      </span>
    </label>}
  </div>;
}
