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
/** The body of POST /api/source-reception/jobs and /lookup: a v1 request (no mode) or a v2 request of one mode. */
export type SourceReceptionRequest = Schemas['SourceReceptionRequest'];
/** The body of POST /api/robustness-studies: one design in 1 to 12 explicit cases of one protocol. */
export type RobustnessStudyInput = Schemas['RobustnessStudyInput'];
/** The body of POST /api/projects: a new research project. */
export type ProjectCreate = Schemas['ProjectCreate'];
/** The body of PATCH /api/projects/<id>: the project's texts or comparison settings at its current revision. */
export type ProjectPatch = Schemas['ProjectPatch'];
/** The body of POST /api/projects/<id>/entries: a saved layout, named evaluation, electrode edit or signal result. */
export type ProjectEntryInput = Schemas['ProjectEntryInput'];
/** The body of PATCH /api/projects/<id>/entries/<entry>: an entry's title or notes at the current revision. */
export type ProjectEntryPatch = Schemas['ProjectEntryPatch'];
/** The body of DELETE /api/projects/<id>/entries/<entry> when no If-Match header names the revision. */
export type ProjectEntryDelete = Schemas['ProjectEntryDelete'];
// The coordinate-source types are in webapp/contracts/coordinate-source.ts, next to their validator.

export type PerturbationRadius = DesignEvaluationRequest['radius_mm'];
export type ConductivityScenarioId = NonNullable<DesignEvaluationRequest['conductivity_scenario']>;
export type DataPriorRequest = NonNullable<DesignEvaluationRequest['data_prior']>;
