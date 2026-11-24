/**
 * Request types generated from the Python schemas (contracts/generated/openapi.d.ts; see contracts/README.md).
 * Build requests with these types instead of writing their shapes by hand, so that a change of a request
 * format fails type checking here instead of being rejected by the service at run time.
 */
import type { components } from '../../contracts/generated/openapi';

type Schemas = components['schemas'];

export type DesignEvaluationRequest = Schemas['DesignEvaluationRequest'];
/** The body of POST /api/design-evaluation/jobs: a bare request or a design-submission/1 envelope. */
export type DesignEvaluationBody = Schemas['DesignEvaluationBody'];
/** The body of POST /api/local-compute/jobs and /lookup (a radius search), in its canonical form. */
export type RadiusSearchRequest = Schemas['RadiusSearchRequest'];
/** The body of POST /api/electrode-editor/jobs: a preparation or an evaluation of 64 stable slots. */
export type ElectrodeEditorRequest = Schemas['ElectrodeEditorRequest'];
// The coordinate-source types are in webapp/contracts/coordinate-source.ts, next to their validator.

export type PerturbationRadius = DesignEvaluationRequest['radius_mm'];
export type ConductivityScenarioId = NonNullable<DesignEvaluationRequest['conductivity_scenario']>;
export type DataPriorRequest = NonNullable<DesignEvaluationRequest['data_prior']>;
