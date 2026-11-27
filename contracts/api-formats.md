# Current application API formats

## Transport version and errors

JSON API responses include `X-EEG-API-Version: 1`. Existing endpoints remain
unchanged. A missing header is accepted for older servers; a different explicit
version requires a compatible client. Errors retain the existing `error` string
and add a stable `code`: `invalid_request`, `authentication_required`,
`request_forbidden`, `not_found`, `method_not_allowed`, `compute_busy`,
`request_too_large`, `unsupported_media_type`, `queue_limited`, `internal_error`,
or `service_unavailable`. HTTP status remains authoritative for transport retry
decisions. These transport codes do not replace scientific result validation.

Contract documentation version: `eeglayoutlab-api-formats/1`.
This documents the existing endpoints; it does not add a new `/api/v1` route or
change stored protocol identifiers.

## Requests

All write requests are JSON objects. The Python service (`eeglayoutlab serve`)
requires its session cookie on every request and, on writes, a same-origin
request and `X-EEG-Compute-Token`, the token from health. A request without the
cookie, such as one from a tab of an earlier run, gets `401` with code
`authentication_required`; the interface then asks to run the `eeglayoutlab`
command again. The legacy Node host validates origin, the token and anonymous
task ownership instead. These controls are separate from the request data
formats below.

| Service | Required fields | Rules |
| --- | --- | --- |
| `/api/data-status` | *(GET only)* | Returns read-only readiness booleans (`base_installed`, `scalp_node_table_installed`, `simnibs_available`, `installed_form`, `ready_for_search`, `ready_for_coordinate_evaluation`) and ready-to-run `commands` for missing model packages. |
| `/api/local-compute` | `region_count`, `radius_mm`, `mode` | Counts: 1, 2, 3, 4, 6. Radius: 15–80 mm in steps of 5. Mode: `whole_surface`, `low_hair`, or `preset`. Optional `electrode_count`, `allocation_mode`, `objective_mode`, `noise_model`, `data_prior`. |
| `/api/source-reception`, legacy | `record_id`, `brain_region`, `waveform`, `artifact_scale`, `seed` | No `mode` field. Record is a lowercase 64-character hexadecimal identifier. |
| `/api/source-reception`, version 2 | `record_id`, `mode`, mode-specific source field, `waveform`, `artifact_scale`, `seed` | Mode selects exactly one source field, described below. Optional `region_definition` must equal `dk40-six-roi-v1`. |
| `/api/design-evaluation` | `action`, `design`, `radius_mm`, `seed` | Action: `evaluate` or `perturb`. Perturbation radius: 3, 6, 10 mm. Seed: integer 0–9999. |
| `/api/electrode-editor`, preparation | `action`, `parent_id` | Action: `prepare`. Parent is a lowercase 64-character hexadecimal identifier. |
| `/api/electrode-editor`, evaluation | `action`, `parent_id`, `parent_digest`, `seed`, `slots` | Action: `evaluate`. Parent identity and digest are lowercase 64-character hexadecimal identifiers. Seed: 2026. |
| `/api/robustness-studies` | `protocol`, `design`, `cases` | Protocol: `noise_seeds`, `grid_displacements` or `heads`. 1–12 cases of `seed` and `radius_mm`, plus `head_id` in a cross-head study. Optional `title`, `notes`, `noise_model`, `conductivity_scenario`. |
| `/api/projects`, create | `title`, `owner_name` | Optional `notes`. Title at most 200, name at most 120, notes at most 8000 UTF-16 units, without control characters other than tab and line breaks; title and name not blank. Texts are trimmed. No other fields. |
| `/api/projects/<id>`, change | `revision` and at least one of `title`, `owner_name`, `notes`, `workflow` | `revision` is the project's current revision, a positive safe integer. `workflow`: `reference_entry_id`, `candidate_entry_id` (saved layouts of the project, or `null`) and `comparison_href` (`null` or a `/decision?` link of at most 4096 units naming both layouts' records with `a` and `b`, and optionally `ar`, `thresholdMode`, `sensitivity`, `localization`, `p90`). |
| `/api/projects/<id>/entries`, attach | `revision`, `kind`, `record_id` or `receipt_id` | Kind: `layout`, `editor` (with `record_id`, a lowercase 64-character hexadecimal identifier) or `source` (with `receipt_id`, a completed signal task). Optional `annotation_id` (a layout's electrode-name annotation), `title`, `notes`. |
| `/api/projects/<id>/entries/<entry>`, change | `revision` and at least one of `title`, `notes` | Same text rules as the project. |
| `/api/projects/<id>/entries/<entry>`, detach | `revision` | Sent as the body, or as the `If-Match` header. |

The radius request permits `mask_codes`. Preset mode requires exactly
`region_count` entries drawn from `PL`, `PR`, `AL`, `AR`, `FL`, `FM`, `FR`, `OL`,
`OR`, retaining their supplied order. Free modes permit omission or an empty
array, which the HTTP normalizer omits from canonical output. The Python worker
adds an empty array.

Radius requests also accept three optional layout-search controls, each omitted
from canonical JSON when equal to its default so existing 64-electrode minimax
requests keep their original cache keys:

- `electrode_count`: integer in `8, 12, 16, 24, 32, 48, 64` (default `64`,
  omitted when `64`). Balanced allocation requires `electrode_count >= 2 * region_count`;
  adaptive allocation requires `electrode_count >= 4 * region_count`.
- `allocation_mode`: `"balanced"` (default, omitted) or `"adaptive"` (requires
  `region_count >= 2`).
- `objective_mode`: `"min"` (default `min(R_field, R_sens)`, omitted) or
  `"composite"` (joint mutual-information and dictionary confusion-margin objective).

Other fields are rejected.

Radius and design-evaluation requests also accept an optional `noise_model`.
Absent means the production model, independent equal-variance electrode noise;
`{"kind": "iid"}` is accepted and omitted from canonical output, so default
requests keep their original canonical JSON and cache keys. Allowed presets:

- `{"kind": "spatial", "rho": 0.5, "length_mm": 10 | 20 | 40}`: spatially
  correlated electrode noise with Gaussian correlation over electrode distance
  and unchanged per-electrode variance. Radius search and design evaluation.
- `{"kind": "brain_background", "fraction": 0.5}`: half of the reference noise
  power is cortical background activity. Design evaluation only; it changes
  localization, not field reconstruction or amplitude, so radius search rejects it.
  Only the total noise power at the reference matches the 20 dB sensor noise:
  the background is 0.005 times the signal source prior and concentrated in a
  few directions, so most whitened directions carry less noise and absolute
  localization errors are smaller than under independent noise. Compare
  reference-normalized ratios across noise models, not absolute errors.

Fields must match a preset exactly (`rho` and `fraction` are numbers, `length_mm`
an integer). A robustness study may set one top-level `noise_model`, applied to
every case. Signal simulation and the electrode editor keep independent noise
and do not accept layouts searched or evaluated under another model.

Design evaluation with `action: "evaluate"` also accepts an optional
`conductivity_scenario`, the name of a scenario in
`configs/conductivity_scenarios.json` (`skull_x0.5` or `skull_x2`). Absent means
the matched model. With a scenario, the data come from that scenario's
scalp-node table while reconstruction and localization keep the nominal model;
the result's provenance records the matched scores under `model_mismatch`.
Perturbation requests reject it. A robustness study may set it for the
`noise_seeds` protocol. Such evaluations are not offered to signal simulation.

Design evaluation with `action: "evaluate"` also accepts an optional `head_id`,
a lowercase package identifier (`[a-z0-9]` words joined by `_` or `-`, at most
40 characters) naming a head package under `results/v2/heads/`. Absent or empty
means the production Ernie head and is omitted from canonical output. With a
head, the coordinates and the standard64 reference are mapped from Ernie through
MNI onto that head and scored with its own sources and scalp-node table at
default conductivities. It cannot be combined with `conductivity_scenario`, and
perturbation requests reject it. `GET /api/design-evaluation/heads` lists the
packages whose table is published. The robustness `heads` protocol takes cases
`{head_id, seed, radius_mm}` with one radius, one seed shared by every case and
each head at most once. Each `heads` case stores its own `identity_sha256`,
since different heads read different packages and tables, and the study
`identity_sha256` is the SHA-256 of the ordered case identities. `noise_seeds`
and `grid_displacements` studies keep one shared study identity. Such
evaluations are not offered to signal simulation or to the decision page.

Design evaluation with `action: "evaluate"` also accepts an optional
`robustness`, whose only value is `"standard/1"`; absent, `null`, `false` or empty
means no robustness block and is omitted from canonical output. It cannot be
combined with `conductivity_scenario` or `head_id`, and perturbation requests
reject it. The result then carries `robustness`: `dropout` (`single` with 64
values and the reference summary; `random` for 2, 4 and 8 removed electrodes),
`impedance` (log SD 0.5 and 1.0) and `replacement` (`status: "completed"` with
levels 5 and 10 mm, or `status: "unavailable"` with a `reason`). Each summary
holds `median`, `p10`, `minimum` and `count`. Only such requests add
`src/compact_eeg/workflows/design_robustness.py` to the identity, so other
requests keep their keys. Library records of such evaluations carry a
`robustness` summary of the medians and remain default-protocol records. See
[Model and metrics](../docs/model-and-metrics.md#cross-session-robustness).

Radius and design-evaluation requests also accept an optional `data_prior`,
the `request` value of an `eeg-data-prior/1` file:
`{"region_gain": [7 numbers], "rho": number, "length_mm": integer | null}`.
`region_gain` follows `frontal`, `central`, `parietal`, `occipital`,
`temporal_left`, `temporal_right`, `other` (atlas `dk40-six-roi-v1`), each a
positive number with at most 4 significant digits in [0.001, 1000]. `rho` lies in
[0, 0.95] with at most 2 decimals; `length_mm` is `null` exactly when `rho` is 0,
otherwise one of 5, 10, 15, 20, 30, 40. Any other form is rejected, not rounded.
The prior multiplies each dictionary and generation source's area weight by its
region's gain and replaces the noise model by `(1 − rho) I + rho exp(−d²/2L²)`,
so `noise_model` and `head_id` are rejected with it. The radius search seed
excludes it. Only such requests add `src/compact_eeg/workflows/data_prior.py`,
`src/compact_eeg/workflows/eeg_recording.py` and
`webapp/public/models/ernie/source-roi.json` to the identity. Records under a
prior are compared only with records under the same prior and are not offered to
signal simulation or the electrode editor. The result's provenance records
`source_prior: "data_prior_region_gains_on_area_weights"` and `data_prior`
(the value and its 16-character `id`). See
[Model and metrics](../docs/model-and-metrics.md#data-derived-source-prior).

The command line writes three file formats for recorded EEG; none is an HTTP
request:

- `eeg-covariance-summary/1` (`eeg-summary`): `label`, `source` (`format`, `file`,
  `bytes`, `sha256`, `sampling_rate_hz`, `duration_s`, `segment_count`),
  `mapping_id` of the cap positions, `channels` (10-05 names), `input_labels`,
  `xyz_mm` (Ernie native), `skipped_channels` and `bad_channels` with reasons,
  `processing` (band, notches, epoch length and stride, filter, reference and
  rejection rules), `epochs` (`total`, `analysed`, `used`, `rejected`), `unit`
  `"uV^2"` and `covariance`, the average-referenced channel covariance.
  New summaries add `source.files` with `role`, `file`, `bytes`, and `sha256`
  for the entry file and any external sample file, in that order. The legacy
  `source.file`, `source.bytes`, and `source.sha256` still describe the entry.
  `source.recording_sha256` equals the entry digest for a single-file input.
  For multiple files it hashes the UTF-8 JSON object with `schema` set to
  `eeg-recording-inputs/1` and `files` listing the `role`, `bytes`, and `sha256`
  of each file, using sorted object keys and no whitespace.
- `eeg-data-prior/1` (`prior`): `id`, `request` (the `data_prior` value),
  `regions`, `atlas`, `fit` (in-sample residuals of the prior and the area prior,
  fitted gains before shrinkage, `shrinkage`, `cross_validated`, `held_out` with
  the leave-one-out residuals per shrinkage value, and `per_summary` fits),
  `channels`, `channels_outside_table`, `summaries_excluded`, `inputs` (label, file,
  entry SHA-256, recording SHA-256 when the summary supplies it, channel and
  epoch counts), `band_hz`, `channel_model` (trace-normalized
  model covariances of the prior and of the area prior at `channels`) and
  `provenance`.
- `eeg-channel-subset/1` (`channels`, or the coordinates page): `universe`,
  `counts`, `training`, `test`, `test_skipped`, `prior`, `methods` (`data`,
  and with a prior `data_prior` and `area_prior`: the greedy `order` and, per
  count, `channels`, `train_error` and `test_error` with `mean`, `median`, `p10`,
  `p90`), `standard_10_20`, `random` (draws, seed and per-count error
  distributions) and `definition`.

Source regions are `frontal`, `central`, `parietal`, `occipital`, `temporal_left`,
`temporal_right`, in that canonical order. Waveform is `burst` or `rhythm`;
artifact scale is 0, 0.5, 1, 2, or 4; seed is an integer from 0 through 9999.
Version 2 modes are:

- `single_source`: `source_index`, an integer from 0 through 255.
- `multi_source`: `brain_region`, one supported region.
- `cross_region`: `brain_regions`, one to six unique supported regions, sorted
  by the canonical region order during normalization.

Source requests reject unknown fields, mixed source selectors, arbitrary
coordinates and direction overrides. The optional atlas definition stays in the
request identity. Existing source normalization and result validation are shared
by the service through `webapp/server/contracts/source-reception.mjs`; old module
exports remain available. The HTTP rules of both versions are the
`source-reception` format of `eeglayoutlab.schemas`, which also gives Node's
rejection messages.

The design object uses `schema: eeg-electrode-design/1`,
`coordinate_system: ernie_native_mm`, and `unit: mm`. It contains 64 distinct
finite `xyz_mm` triples, with absolute coordinate values at most 500 and at least
4 mm spacing (existing numerical comparison tolerance: 1e-7 mm), plus 64
`region_indices` with balanced zero-based allocation to 1, 2, 3, 4, or 6 regions.
The HTTP normalizer copies the listed design fields and sets `name` to the first
100 characters of a string, or the existing default `导入布局`. Additional design
metadata is not forwarded. Unknown fields in the top-level request are rejected.
Coordinates must already refer to the Ernie native model space.

A robustness study evaluates one design in explicit cases, each normalized as a
design-evaluation request (`evaluate`, or `perturb` for `grid_displacements`)
with the study's noise model and conductivity scenario. Noise-seed studies hold
the radius fixed and grid-displacement studies vary it, each with unique
seed/radius pairs; a cross-head study names each head package once, shares one
seed and one radius and takes no conductivity scenario. The title (default
`Robustness study`) is trimmed, not blank and at most 200 UTF-16 units; notes
are at most 2000. The design's `electrode_names` and `source_metadata` are kept
as the study's annotation, outside every request (a source without names gets
`E1`–`E64`). The HTTP rules are the `robustness-study` format of
`eeglayoutlab.schemas`, whose canonical value is the normalized study;
`eeglayoutlab.jobs.studies.normalize_study_input` also gives Node's rejection
messages.

Editor requests keep 64 stable slots. Each slot contains only `bank_index` and
boolean `enabled`; the HTTP index bound is integer 0–1,000,000. At least two
slots must be enabled. The Python workflow additionally validates membership in
the parent region, distinct active positions and minimum spacing against the
verified parent data. The HTTP rules are the `electrode-editor` format of
`eeglayoutlab.schemas`, which also gives Node's rejection messages; the
workflow's slot/domain regressions remain in `tests/test_electrode_editor.py`.

## Results and task state

Each service retains its existing result protocol and detailed scientific
validator. Source results use `schema_version: source-reception/1` or
`source-reception/2`; coordinate evaluations use `schema: design-evaluation/1`;
editor results use `schema: electrode-editor/1`. Radius results retain
`completed` or `no_layout` outcomes. A source result must retain the requested
layout coordinates and source identity; waveform dimensions, physical
conditions, and derived metrics are checked before caching or display.

Task records retain their service-specific response shape. Shared lifecycle
states include `queued`, `running`, `cancelling`, `completed`, `failed`,
`cancelled`, and `timeout`; radius tasks can finish as `no_layout`. Browser
connection state is tracked separately from these backend states. The extraction
does not merge the result formats or rewrite historical records.

## Shared library visibility (legacy Node host)

The Python service lists every record of the library for its one local user and
returns no `visibility` or `library_scope`; its
`/api/local-compute/library/<id>/visibility` is `404`, and the interface has no
visibility control. On the legacy Node host,
`GET /api/local-compute/library`, `GET /api/electrode-editor/records`,
`GET /api/electrode-editor/parents` and `GET /api/source-reception/layouts`
list one browser's view. Each visitor-produced record (`cache`,
`design_evaluation`, electrode edits) carries `visibility`:

| Field | Values |
| --- | --- |
| `scope` | `shared` (default: everything not removed is listed) or `owner` (optional) |
| `review` | `true` when publications wait for the operator |
| `owned` | Whether this browser owns the record |
| `state` | `private`, `pending`, `public` or `removed` |
| `published_by_me` | Whether this browser's publication is active |
| `reason` | Removal reason, shown to owners only |

The library list also returns `library_scope: { scope, review }`. Official
records carry no `visibility` field. `GET /api/local-compute/library/<id>`
returns the same `visibility` on visitor records; it and `/bundle` return 404
to a non-owner when the operator removed the record.

`POST /api/local-compute/library/<id>/visibility` with body exactly
`{"public": true}` or `{"public": false}` publishes or withdraws this browser's
publication. It needs `X-EEG-Compute-Token` and counts toward the submission
rate limit. Responses: 200 `{ visibility }`; 400 invalid body; 403 not an
owner or missing token; 404 no completed visitor record with this identifier;
409 publishing a removed record; 413 body over 256 bytes; 429 rate limit.

## Compatibility verification

The shared corpus covers radius, legacy and version-2 source requests, and
fixed-coordinate evaluation. Node tests check rejection, non-mutation,
idempotence, and exact canonical serialization. Python tests validate the same
canonical wire requests and shared rejected cases without starting a worker or
reading scientific model files. The existing editor tests cover its distinct
parent-dependent validation boundary.

Run from `webapp/`:

```sh
node --test scripts/check-api-contracts.mjs
```

Run from the repository root:

```sh
.runtime/simnibs-4.6.0/bin/python -B -m pytest -q -p no:cacheprovider tests/test_api_contracts.py
```
