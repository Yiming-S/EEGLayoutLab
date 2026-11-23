// Does the request the interface builds type-check against the types generated from the Python schema?
// Run: tsc -p tests/schema_parity/tsconfig.json. Not part of the webapp build.
// Each @ts-expect-error records a current mismatch; when the interface adopts the generated types, tsc
// reports the directive as unused and this file should be updated.
import type { components, operations } from './generated/openapi';
import { designSubmission, scientificDesign, type ElectrodeDesign, type NoiseModel } from '../../webapp/lib/design-decision.ts';
import type { DataPrior } from '../../webapp/lib/local-compute';

type Body = operations['normalize_design_evaluation_api_spike_design_evaluation_normalize_post']['requestBody']['content']['application/json'];
type Request = components['schemas']['DesignEvaluationRequest'];
type Submission = components['schemas']['DesignSubmission'];

declare const design: ElectrodeDesign;
declare const action: 'evaluate' | 'perturb';
declare const radius: number;
declare const seed: number;
declare const noise: NoiseModel | undefined;
declare const scenario: string | undefined;
declare const robustness: boolean;
declare const prior: DataPrior | undefined;

// 1. The whole value, as sent by features/decision/use-decision-controller.ts.
// @ts-expect-error radius_mm is typed number in designSubmission (and see the fields below).
export const body: Body = designSubmission(design, action, radius, seed, noise, scenario, robustness, prior);

// 2. Field by field, so each incompatibility is reported on its own.
type Built = ReturnType<typeof designSubmission>;
type Plain = Exclude<Built, { schema: string }>;
type Envelope = Extract<Built, { schema: string }>;
declare const plain: Plain;
declare const envelope: Envelope;
export const fieldAction: Request['action'] = plain.action;
export const fieldDesign: Request['design'] = plain.design;
// @ts-expect-error parameter radius_mm: number; the contract is 3 | 6 | 10.
export const fieldRadius: Request['radius_mm'] = plain.radius_mm;
export const fieldSeed: Request['seed'] = plain.seed;
export const fieldNoise: Request['noise_model'] = plain.noise_model;
// @ts-expect-error parameter conductivity_scenario: string; the contract is 'skull_x0.5' | 'skull_x2'.
export const fieldScenario: Request['conductivity_scenario'] = plain.conductivity_scenario;
// @ts-expect-error the literal 'standard/1' is widened to string inside the object literal.
export const fieldRobustness: Request['robustness'] = plain.robustness;
// @ts-expect-error DataPrior.length_mm is number | null in lib/local-compute.ts; the contract lists 5, 10, 15, 20, 30, 40.
export const fieldPrior: Request['data_prior'] = plain.data_prior;
// @ts-expect-error the literal 'design-submission/1' is widened to string.
export const fieldEnvelopeSchema: Submission['schema'] = envelope.schema;
// @ts-expect-error the same request fields as above.
export const fieldEnvelopeRequest: Submission['request'] = envelope.request;
export const fieldEnvelopeNames: Submission['electrode_names'] = envelope.electrode_names;
export const fieldEnvelopeSource: Submission['source_metadata'] = envelope.source_metadata;

// 3. The same function with parameters typed from the generated schema type-checks without casts.
export function designSubmissionFromSchema(design: ElectrodeDesign, action: Request['action'], radius_mm: Request['radius_mm'], seed: number,
  noise_model?: NoiseModel, conductivity_scenario?: NonNullable<Request['conductivity_scenario']>, robustness?: boolean,
  data_prior?: NonNullable<Request['data_prior']>): Body {
  const request: Request = { action, design: scientificDesign(design), radius_mm, seed, ...(noise_model && !data_prior ? { noise_model } : {}),
    ...(conductivity_scenario && action === 'evaluate' ? { conductivity_scenario } : {}),
    ...(robustness && action === 'evaluate' && !conductivity_scenario ? { robustness: 'standard/1' as const } : {}),
    ...(data_prior ? { data_prior } : {}) };
  return design.electrode_names || design.source_metadata ? { schema: 'design-submission/1', request,
    electrode_names: design.electrode_names ?? Array.from({ length: 64 }, (_, index) => `E${index + 1}`),
    ...(design.source_metadata ? { source_metadata: design.source_metadata } : {}) } : request;
}
