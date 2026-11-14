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

All write requests are JSON objects. The existing local HTTP boundary validates
origin, session token, and anonymous task ownership. These controls are separate
from the request data formats below.

| Service | Required fields | Rules |
| --- | --- | --- |
| `/api/local-compute` | `region_count`, `radius_mm`, `mode` | Counts: 1, 2, 3, 4, 6. Radius: 15–80 mm in steps of 5. Mode: `whole_surface`, `low_hair`, or `preset`. |
| `/api/source-reception`, legacy | `record_id`, `brain_region`, `waveform`, `artifact_scale`, `seed` | No `mode` field. Record is a lowercase 64-character hexadecimal identifier. |
| `/api/source-reception`, version 2 | `record_id`, `mode`, mode-specific source field, `waveform`, `artifact_scale`, `seed` | Mode selects exactly one source field, described below. Optional `region_definition` must equal `dk40-six-roi-v1`. |
| `/api/design-evaluation` | `action`, `design`, `radius_mm`, `seed` | Action: `evaluate` or `perturb`. Perturbation radius: 3, 6, 10 mm. Seed: integer 0–9999. |
| `/api/electrode-editor`, preparation | `action`, `parent_id` | Action: `prepare`. Parent is a lowercase 64-character hexadecimal identifier. |
| `/api/electrode-editor`, evaluation | `action`, `parent_id`, `parent_digest`, `seed`, `slots` | Action: `evaluate`. Parent identity and digest are lowercase 64-character hexadecimal identifiers. Seed: 2026. |

The radius request permits `mask_codes`. Preset mode requires exactly
`region_count` entries drawn from `PL`, `PR`, `AL`, `AR`, `FL`, `FM`, `FR`, `OL`,
`OR`, retaining their supplied order. Free modes permit omission or an empty
array, which the HTTP normalizer omits from canonical output. The Python worker
adds an empty array. Other fields are rejected.

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
exports remain available.

The design object uses `schema: eeg-electrode-design/1`,
`coordinate_system: ernie_native_mm`, and `unit: mm`. It contains 64 distinct
finite `xyz_mm` triples, with absolute coordinate values at most 500 and at least
4 mm spacing (existing numerical comparison tolerance: 1e-7 mm), plus 64
`region_indices` with balanced zero-based allocation to 1, 2, 3, 4, or 6 regions.
The HTTP normalizer copies the listed design fields and sets `name` to the first
100 characters of a string, or the existing default `导入布局`. Additional design
metadata is not forwarded. Unknown fields in the top-level request are rejected.
Coordinates must already refer to the Ernie native model space.

Editor requests keep 64 stable slots. Each slot contains only `bank_index` and
boolean `enabled`; the HTTP index bound is integer 0–1,000,000. At least two
slots must be enabled. The Python workflow additionally validates membership in
the parent region, distinct active positions and minimum spacing against the
verified parent data. The editor has no standalone Python envelope normalizer;
its slot/domain regressions remain in `tests/test_electrode_editor.py`.

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
