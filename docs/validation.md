# Validation scope

Software checks, within-model numerical checks, and validation on independent data answer different questions. Passing an installation check establishes that required components can be found and inspected; it does not establish scientific convergence or participant-level validity.

## Production results

The application retains 30 fixed-area conditions from the current Ernie model: 1/2/3/4/6 regions, whole-scalp/low-hair proxy domains, and 60/120/180 cm² total-area caps. Their production scores use the recorded 4,096-source dictionary and 256 generation sources. The selected fixed branch and the original coordinate ordering are retained with the records.

A separate evaluation using 512 new sources exists outside the production scoring path. Those results do not replace the application's default scores. The compact application data bundle is not the complete archive of that validation campaign.

Historical radius studies, current local radius jobs, fixed-area results, imported-coordinate evaluations, edited layouts, and reception scenarios retain distinct protocols. A score copied from one of these contexts does not qualify a different layout or source condition.

## Retained protocol file

[`webapp/public/data/experiment_protocol_v2.json`](../webapp/public/data/experiment_protocol_v2.json) is retained in its original form and contains historical research-planning fields, including `TBD` values, status labels, and planned validation stages. The current application uses only its `anatomical_preset_matrix` to construct placement presets. Those historical fields are not a current validation-status report. Read the production scope above and each result's recorded protocol when interpreting the application; do not infer current readiness or completed validation from the old file's `TBD` or `status` values.

## Established limits

| Question | Scope supported by this release |
| --- | --- |
| Do the files match the data manifest? | The bundle verifier checks bytes and SHA-256 against the checked-in inventory. |
| Do the numerical routines and services behave as specified? | The supplied tests exercise mathematical identities, input checks, queue behavior, result integrity, and compatibility. The outcome must be recorded for the tested checkout and environment. |
| Are the production scores from independent heads? | No. They use the single Ernie template. The optional `heads` study evaluates fixed coordinates on other segmented heads; it describes spread across those heads under one mapping and default conductivities, not a population bound. |
| Are generation sources separate from the inverse dictionary? | Yes for the recorded localization protocols. Generation and inversion share head-model assumptions unless an evaluation names a conductivity scenario. |
| Is sensitivity to skull conductivity established? | Partly. Two named scenarios (skull ×0.5 and ×2) generate data from a mismatched head and invert with the nominal one. Other tissues, anisotropy and geometry errors are not covered. |
| Do correlated-noise scores replace the independent-noise scores? | No. They are optional protocols under declared covariance models; the production scores keep independent noise. |
| Has volume-mesh convergence been established? | No. The available checks do not establish convergence across qualified volume-mesh levels. |
| Has continuous/global layout optimality been established? | No. Search is bounded and uses a finite candidate surface representation. |
| Are ECG/EOG fields physiologically validated? | No. Reception interference fields are declared scenario assumptions. |
| Are human EEG, MI/P300 classification, or wearable performance validated? | No. Those outcomes are outside the supplied evidence. |

Independent-head validation remains incomplete. Neither additional noise repetitions nor new source locations within Ernie increase the number of independent heads. The IXI-derived head packages come from automatic charm segmentations of healthy adults. Their segmentation quality is not reviewed manually, and their scalp positions come from an MNI mapping of Ernie coordinates, not from measured electrode positions.

## Single-layout readings

The readings below are for one compact two-region layout (AL + AR, radius ≤ 35 mm). They are not population results.

`ernie_xh` packages Ernie under the cross-head protocol, whose source sampling differs from the production sources. Its scores for this layout therefore differ from production: field 0.708 against 0.704, sensitivity 0.202 against 0.198, and localization 0.458–0.496 across noise seeds 42, 1234 and 2026 against 0.325. Cross-head comparisons must use `ernie_xh` as the Ernie baseline, not the production score.

Across the 11 published heads (`ernie_xh` and ten IXI heads; IXI014 and IXI016 are not published, see [data and reproducibility](data-and-reproducibility.md#optional-scenario-tables-and-head-packages)), one `heads` study was run per noise seed, with independent noise and default conductivities. Each score is relative to standard64 mapped to the same head, so standard64 reads 1 on every head. Quantiles are across heads (type 7):

| Metric | Median | P10 | P90 | `ernie_xh` |
| --- | --- | --- | --- | --- |
| Field | 0.697 | 0.680 | 0.714 | 0.708 |
| Sensitivity | 0.200 | 0.181 | 0.215 | 0.202 |
| Localization, seed 42 | 0.371 | 0.305 | 0.459 | 0.459 |
| Localization, seed 1234 | 0.382 | 0.324 | 0.454 | 0.458 |
| Localization, seed 2026 | 0.368 | 0.349 | 0.451 | 0.496 |
| Median error, compact | 19.0 mm | 17.8 mm | 19.5 mm | 19.2 mm |
| Median error, standard64 | 11.7 mm | 11.2 mm | 12.4 mm | 12.4 mm |

Field and sensitivity do not depend on the noise seed. Median errors are for seed 42; the other seeds change them by at most 0.3 mm. Per head, field ranges from 0.658 (IXI017) to 0.758 (IXI019), and localization from 0.293 (IXI002, seed 42) to 0.496 (`ernie_xh`, seed 2026). For localization, `ernie_xh` is at or above the cross-head P90 for all three seeds. A localization score read on Ernie alone therefore overstates this layout's localization on the other heads; field and sensitivity on Ernie lie inside the cross-head range.

Under skull-conductivity mismatch the data come from the scenario head and the inversion keeps the nominal model (see [Model and metrics](model-and-metrics.md#model-mismatch-and-other-heads)):

| Data-generating head | Field | Sensitivity | Localization | Median error |
| --- | --- | --- | --- | --- |
| Matched (nominal) | 0.704 | 0.198 | 0.325 | 18.4 mm |
| `skull_x0.5` | 0.755 | 0.237 | 0.271 | 22.5 mm |
| `skull_x2` | 0.607 | 0.159 | 0.429 | 17.8 mm |

## Installation and portability

The intended initial environment is macOS on Apple Silicon, with Node.js 22.13.0 or newer and the specified native Python runtime. The pinned native wheels require macOS 14 or newer, and the installer enforces that requirement. This is a source checkout with a local Node host. It is not a signed `.app` or DMG.

The repository has not been validated on a second independent Mac. The dependency requirement does not establish a tested macOS support range. Peak memory for all native jobs, installation time, and support for Intel Macs, Windows, or Linux are not established by this handoff. A working source build on the preparation computer does not establish those properties.

## Recording verification

Use the commands in [CONTRIBUTING.md](../CONTRIBUTING.md). For a reported test result, record the commit or source identity, data-manifest SHA-256, operating system and architecture, Node/Python versions, command, completion status, and skipped tests. Record native runtime identity for FEM-dependent checks.

The ordinary test suite is separate from opt-in existing-bank integrations and interactive jobs. Jobs can create new results. Do not report skipped real-data checks as passed, or interpret a small numerical unit test as a new FEM validation.

Changes to source sampling, conductivity, geometry admission, the noise model, scoring, or search budgets require new scientific identities and a description of the changed scope. UI translation, formatting, and acceptance-threshold changes do not on their own create new scientific evidence.
