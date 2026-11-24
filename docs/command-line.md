# Command line

`webapp/scripts/eeglayoutlab.mjs` runs the scientific services without the browser. It is meant for batches, scripts and reproducible examples. Each request goes through the same steps as in the web application:

- the HTTP API's normalizer and result validator;
- the same Python worker, with the same thread limits;
- the same scientific identity: SHA-256 of the model inputs, worker code and runtime files.

The request key is therefore the one the web service would use for the same request on the same installation. Nothing is written to the web service's queue, library or projects.

It needs Node.js 22.18 or later and, for calculations, the installed data bundle and scientific runtime ([source installation](source-installation.md)). Run it from the repository root:

```bash
node webapp/scripts/eeglayoutlab.mjs help
```

`--root DIR` selects another checkout that holds the data and runtime. The default is `EEG_REPOSITORY_ROOT`, or else this repository. `--python PATH` overrides the interpreter. By default the managed runtime is used when it is present; otherwise `EEG_COMPUTE_PYTHON`, otherwise `python3`.

## Commands

| Command | Input | Output |
| --- | --- | --- |
| `design FILE... --out DESIGN.json [--name NAME] [--regions N] [--unit U]` | A BIDS pair (Ernie native, MNI or a digitized head frame with landmarks), an `.elc` or `.sfp` montage, a 10-05 name list, the layout CSV, a design JSON, or a search result from this tool. `--regions 1\|2\|3\|4\|6` assigns balanced spatial regions to files without a region column; `--unit mm\|cm\|m` gives the unit of an `.sfp` file | A design: `eeg-electrode-design/1` with names and coordinate source |
| `export DESIGN.json --format F --out-dir DIR` | A design | `bids`, `mni`, `mne` (`.elc`), `eeglab` (`.sfp`) or `svg` (layout figure; `--labels yes\|no`) |
| `evaluate REQUEST.json... --out-dir DIR` | Requests in the `/api/design-evaluation` format, or `design-submission/1` with names | One `<name>.result.json` per request |
| `evaluate --design DESIGN.json --radius 6 --seed 42 --out-dir DIR` | A design and options: `--action evaluate\|perturb`, `--noise iid\|spatial_10\|spatial_20\|spatial_40\|brain_background`, `--conductivity skull_x0.5\|skull_x2`, `--head ID`, `--robustness standard/1`, `--data-prior PRIOR.json` | `request.result.json` |
| `search REQUEST.json... --out-dir DIR` | Requests in the `/api/local-compute` format; `--data-prior PRIOR.json` adds the prior to each | One `<name>.result.json` per request |
| `eeg-summary RECORDING... --out-dir DIR [--band 1,40] [--epoch 2] [--label TEXT]` | EDF/EDF+C, BDF, BrainVision `.vhdr` or EEGLAB `.set` recordings. The recording is read in place; only its summary is written | One `<name>.summary.json` (`eeg-covariance-summary/1`) per recording |
| `prior SUMMARY.json\|DIR... --out PRIOR.json` | Covariance summaries of one band; a directory stands for the summaries in it | `eeg-data-prior/1`, with region gains, noise and the leave-one-out check printed |
| `channels SUMMARY.json\|DIR... --out SUBSET.json [--test FILE,...\|DIR] [--prior PRIOR.json] [--counts 8,16,24,32] [--draws 200] [--seed 1] [--figure FIGURE.svg]` | Training summaries, optional held-out summaries and an optional prior | `eeg-channel-subset/1`, with the training/held-out errors printed per method and size; `--figure` also writes the error against subset size as an SVG figure |
| `pareto RUN.result.json... --out PARETO.json [--objectives LIST]` | `evaluate` and `search` results of one evaluation condition. LIST is comma-separated from `field`, `sensitivity`, `localization`, `p90`, `area`, `dropout`, `impedance`, `replacement` (default `field,sensitivity,localization`) | `eeglayoutlab-cli-pareto/1`: rank, dominating count and values per file, and the files missing an objective |
| `study STUDY.json --out-dir DIR` | A study in the robustness-study format (`noise_seeds`, `grid_displacements` or `heads`) | `study.json` with case summaries and the aggregation, plus `cases/NN.result.json` |

The request formats are defined in [API formats](../contracts/api-formats.md) and the coordinate files in the [coordinate file interface](coordinate-file-interface.md). A batch continues after a failed request, writes `<name>.error.json` for it and exits with status 1.

## Result files

`evaluate` and `search` write `eeglayoutlab-cli-run/1`:

```json
{
  "schema": "eeglayoutlab-cli-run/1",
  "service": "design-evaluation",
  "request": { "action": "evaluate", "design": { "...": "..." }, "radius_mm": 6, "seed": 42 },
  "key": "<request key>",
  "identity": { "schema": "design-evaluation-cache/1", "digests": { "<path>": "<sha256>" }, "python": "<path>", "threads": 1 },
  "annotation": { "electrode_names": ["..."] },
  "result": { "schema": "design-evaluation/1", "nominal": { "field_relative": 1.0 } }
}
```

`result` is exactly what the worker returned, after the service's validation. `annotation` is present when the input carried electrode names. As on the web, names are not part of the scientific request.

`study` writes `eeglayoutlab-cli-study/1`. It holds the normalized study, each case's request, key, status and summary, and the aggregation computed by the same code as the robustness study page (type 7 quantiles: median, P10, P90). For a `heads` study, each case records its own identity and the study identity is the SHA-256 of the ordered case identities. Otherwise all cases share one identity.

The key and the identity include the interpreter path, so they differ between installations. Compare scores, not keys, across machines; [`examples/run-examples.mjs`](../examples/run-examples.mjs) does this within 1e-6.

## Example

```bash
node webapp/scripts/eeglayoutlab.mjs design labels.tsv --name "my layout" --out my-layout.json
node webapp/scripts/eeglayoutlab.mjs evaluate --design my-layout.json --radius 6 --seed 42 --out-dir runs/
node webapp/scripts/eeglayoutlab.mjs export my-layout.json --format mne --out-dir files/
node webapp/scripts/eeglayoutlab.mjs design sub-01_electrodes.tsv sub-01_coordsystem.json --regions 4 --out digitized.json
```

Three complete examples, with their expected scores, are in [`examples/`](../examples/README.md).

## Python workers

The workers can also be called directly. Each reads one JSON request from standard input and writes progress, result or error events as JSON lines:

```bash
.runtime/simnibs-4.6.0/bin/python scripts/design_evaluation.py < request.json
.runtime/simnibs-4.6.0/bin/python scripts/run_local_radius_compute.py < search.json
```

This skips the HTTP normalizer, the result validation and the identity record, and the worker receives the request exactly as written. Use the command line when results must match the web application's.
