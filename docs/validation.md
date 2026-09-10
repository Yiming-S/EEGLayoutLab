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
| Are the production scores from independent heads? | No. They use the single Ernie template. |
| Are generation sources separate from the inverse dictionary? | Yes for the recorded localization protocols; generation and inversion still share head-model assumptions. |
| Has volume-mesh convergence been established? | No. The available checks do not establish convergence across qualified volume-mesh levels. |
| Has continuous/global layout optimality been established? | No. Search is bounded and uses a finite candidate surface representation. |
| Are ECG/EOG fields physiologically validated? | No. Reception interference fields are declared scenario assumptions. |
| Are human EEG, MI/P300 classification, or wearable performance validated? | No. Those outcomes are outside the supplied evidence. |

Independent-head validation remains incomplete. Neither additional noise repetitions nor new source locations within Ernie increase the number of independent heads.

## Installation and portability

The intended initial environment is macOS on Apple Silicon, with Node.js 22.13.0 or newer and the specified native Python runtime. The pinned native wheels require macOS 14 or newer, and the installer enforces that requirement. This is a source checkout with a local Node host. It is not a signed `.app` or DMG.

The repository has not been validated on a second independent Mac. The dependency requirement does not establish a tested macOS support range. Peak memory for all native jobs, installation time, and support for Intel Macs, Windows, or Linux are not established by this handoff. A working source build on the preparation computer does not establish those properties.

## Recording verification

Use the commands in [CONTRIBUTING.md](../CONTRIBUTING.md). For a reported test result, record the commit or source identity, data-manifest SHA-256, operating system and architecture, Node/Python versions, command, completion status, and skipped tests. Record native runtime identity for FEM-dependent checks.

The ordinary test suite is separate from opt-in existing-bank integrations and interactive jobs. Jobs can create new results. Do not report skipped real-data checks as passed, or interpret a small numerical unit test as a new FEM validation.

Changes to source sampling, conductivity, geometry admission, the noise model, scoring, or search budgets require new scientific identities and a description of the changed scope. UI translation, formatting, and acceptance-threshold changes do not on their own create new scientific evidence.
