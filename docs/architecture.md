# Architecture

EEG Layout Lab runs a local browser interface, a Node HTTP host, and bounded Python workers. The browser selects parameters and displays records; scientific computation and persistence run on the same computer as the host.

The planned hosted version and changes needed for a public server are documented in [Server deployment preparation](server-deployment.md).

## Request path

```text
Browser route
  -> feature controller
  -> local HTTP API
  -> shared computation queue
  -> Python command in scripts/
  -> compact_eeg.workflows
  -> scientific core + verified input files
  -> result record + cache
```

| Location | Responsibility |
| --- | --- |
| [`webapp/app/`](../webapp/app/) | Routes and page entry points |
| [`webapp/features/`](../webapp/features/) | Reception, electrode editing, and comparison workspaces |
| [`webapp/components/`](../webapp/components/) | Shared controls, explanations, and 3D rendering |
| [`webapp/lib/`](../webapp/lib/) | Types, display logic, translations, and URL state |
| [`webapp/server/`](../webapp/server/) | HTTP handling, input validation, job state, caches, and record loading |
| [`src/compact_eeg/workflows/`](../src/compact_eeg/workflows/) | Application computation workflows |
| [`src/compact_eeg/`](../src/compact_eeg/) | Geometry, forward modeling, reconstruction, and numerical metrics |
| [`scripts/`](../scripts/) | Setup, data management, and Python worker entry points |
| [`configs/`](../configs/) | Scientific configuration used by the application |
| [`data/manifest.json`](../data/manifest.json) | Exact external data inventory |

## Computation paths

Radius design uses the frozen candidate lead-field bank. It selects and evaluates sensor locations without a new native finite-element solve. Electrode editing within that bank also reads existing field rows.

Fixed-coordinate evaluation reuses exact bank or reference coordinates when they match. Other qualified coordinates require the native Ernie mesh and a SimNIBS FEM solve. Source reception uses the matching forward fields for the selected, fixed layout.

The current electrode-editor and V2 reception services also validate native inputs and runtime identity. Installing only NumPy and SciPy does not enable every service, even when a particular scientific operation can reuse the bank. The full application setup therefore includes the native runtime.

The main Python interfaces are [`local_radius_compute.py`](../src/compact_eeg/local_radius_compute.py), [`design_evaluation.py`](../src/compact_eeg/workflows/design_evaluation.py), [`electrode_editor.py`](../src/compact_eeg/workflows/electrode_editor.py), and the two [`source_reception`](../src/compact_eeg/workflows/source_reception.py) [workflows](../src/compact_eeg/workflows/source_reception_v2.py). The [`forward provider`](../src/compact_eeg/workflows/reception_forward_provider.py) manages exact-coordinate fields and native cache validation.

## Process and storage boundaries

The local APIs restrict hosts and origins to loopback, require a session token for writes, and share one computation slot. Workers receive validated inputs rather than shell commands from the browser. Cancellation, timeouts, thread limits, and output limits are enforced by the host and worker entry points.

For the web source, input data and outputs live under the checkout. The default native Python location is `.runtime/simnibs-4.6.0/bin/python`; `EEG_COMPUTE_PYTHON` selects a server-side Python interpreter for the queue. Native services prefer the project runtime when it exists. The separately packaged desktop wrapper has its own installation and application-data paths.

The web source now uses `community-queue.mjs` for anonymous task ownership and
a persistent FIFO shared by the four scientific services. Its adapters preserve
the existing request normalization, cache identity and worker implementations.
Operational state is stored separately in `results/web-service/`; the header
shows estimated active browsers and queue counts. See
[anonymous visitors and scheduling](anonymous-queue.md).

New application records are written to `results/v2/local_app_jobs`, `design_evaluation_jobs`, `electrode_editor_jobs`, `source_reception_jobs`, `source_reception_v2_jobs`, and `reception_forward`. The data bundle supplies frozen inputs and selected records; the application adds its own new outputs locally.

## Compatibility and cache identity

The small Python files with matching names in `scripts/` forward to the implementations in `compact_eeg.workflows`. Keep these entry points: the Node host, command-line clients, and cache fingerprints refer to them. The matching compatibility exports in `webapp/scripts/` also remain available to checks and imports.

The radius queue fingerprints all top-level Python files under `src/compact_eeg/`, together with its entry point, configuration, and current input pointers. Other services fingerprint their actual workflow implementation and model inputs. Some scientific modules retain names from the computation stage they implement; file names alone do not establish that a module is unused.

Native identities include installed package bytes, solver libraries, conda metadata, and filesystem locations. A new checkout path or runtime can produce a new cache identity. Existing results remain historical records; changing their IDs or hashes to force a current cache hit would break provenance.

See [data and reproducibility](data-and-reproducibility.md) for the installation and record rules, and [contributing](../CONTRIBUTING.md) for verification commands.
