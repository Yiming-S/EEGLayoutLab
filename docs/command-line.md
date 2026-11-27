# Command line

`eeglayoutlab` runs all nine scientific commands, the reproducible examples and the data-package commands from Python without a browser or Node.js. Each computation request goes through the same steps as in the web application:

- the HTTP API's normalizer and result validator;
- the same Python worker, with the same thread limits;
- the same scientific identity: SHA-256 of the model inputs, worker code and runtime files.

The request key is therefore the one the web service would use for the same request on the same installation. Nothing is written to the web service's queue, library or projects.

In an installed Conda environment, run `eeglayoutlab` directly; in a source checkout, run `.venv/bin/eeglayoutlab`:

```bash
eeglayoutlab --help
```

`--root DIR` selects another scientific root holding `configs/`, `data/` and `results/v2/`. The default is `EEG_REPOSITORY_ROOT`, else the checkout holding the package, else the installed root of the conda environment (`$PREFIX/share/eeglayoutlab/root`). `--python PATH` overrides the worker interpreter: following the service (decision U8), `search` runs and fingerprints the compute interpreter (`--python`, else `EEG_COMPUTE_PYTHON`, else `.runtime/simnibs-4.6.0/bin/python`, else the installed environment's `bin/python`, else `python3`), while `evaluate`, `study`, `eeg-summary` and `prior` use the native interpreter (`.runtime/simnibs-4.6.0/bin/python` when present, else `--python`, else `EEG_COMPUTE_PYTHON`, else the installed environment's `bin/python`, else `python3`). `webapp/scripts/eeglayoutlab.mjs` remains unchanged only as the legacy parity reference until phase 4.

## Commands

| Command | Input | Output |
| --- | --- | --- |
| `eeglayoutlab quickstart [WORKSPACE] [--from URL\|DIR] [--base-only] [--examples] [--verify] [--no-browser]` | Optional workspace directory (defaults to current directory if already a workspace, else `~/eeglayoutlab-workspace`) | Installs/links missing model data, optionally runs `--verify` smoke calculations, and opens the local web application on `127.0.0.1` |
| `eeglayoutlab doctor [--root DIR] [--python PATH] [--smoke]` | Optional root or interpreter; `--smoke` runs Examples 1 & 2 in a temporary directory | Readiness report for scientific root, compute Python, model data and static UI (plus `1e-6` score check with `--smoke`) |
| `eeglayoutlab design FILE... --out DESIGN.json [--name NAME] [--regions N] [--unit U] [--root DIR]` | A BIDS pair (Ernie native, MNI or a digitized head frame with landmarks), an `.elc` or `.sfp` montage, a 10-05 name list, the layout CSV, a design JSON, or a search result (`eeglayoutlab-cli-run/1`). `--regions 1\|2\|3\|4\|6` assigns balanced spatial regions to files without a region column; `--unit mm\|cm\|m` gives the unit of an `.sfp` file | A design: `eeg-electrode-design/1` with names and coordinate source |
| `eeglayoutlab export DESIGN.json --format F --out-dir DIR [--labels yes\|no] [--root DIR]` | A design | `bids`, `mni`, `mne` (`.elc`), `eeglab` (`.sfp`) or `svg` (layout figure; `--labels yes\|no`) |
| `eeglayoutlab evaluate REQUEST.json... --out-dir DIR [--data-prior PRIOR.json] [--root DIR] [--python PATH]` | Requests in the `/api/design-evaluation` format, or `design-submission/1` with names | One `<name>.result.json` per request |
| `eeglayoutlab evaluate --design DESIGN.json --radius 6 --seed 42 --out-dir DIR [...]` | A design and options: `--action evaluate\|perturb`, `--noise iid\|spatial_10\|spatial_20\|spatial_40\|brain_background`, `--conductivity skull_x0.5\|skull_x2`, `--head ID`, `--robustness standard/1`, `--data-prior PRIOR.json` | `request.result.json` |
| `eeglayoutlab search REQUEST.json... --out-dir DIR [--data-prior PRIOR.json] [--root DIR] [--python PATH]` | Requests in the `/api/local-compute` format; `--data-prior PRIOR.json` adds the prior to each | One `<name>.result.json` per request |
| `eeglayoutlab eeg-summary RECORDING... --out-dir DIR [--band 1,40] [--epoch 2] [--label TEXT] [--root DIR] [--python PATH]` | EDF/EDF+C, BDF, BrainVision `.vhdr` or EEGLAB `.set` recordings. The recording is read in place; only its summary is written | One `<name>.summary.json` (`eeg-covariance-summary/1`) per recording |
| `eeglayoutlab prior SUMMARY.json\|DIR... --out PRIOR.json [--root DIR] [--python PATH]` | Covariance summaries of one band; a directory stands for the summaries in it | `eeg-data-prior/1`, with region gains, noise and the leave-one-out check printed |
| `eeglayoutlab channels SUMMARY.json\|DIR... --out SUBSET.json [--test FILE,...\|DIR] [--prior PRIOR.json] [--counts 8,16,24,32] [--draws 200] [--seed 1] [--figure FIGURE.svg]` | Training summaries, optional held-out summaries and an optional prior | `eeg-channel-subset/1`, with the training/held-out errors printed per method and size; `--figure` also writes the error against subset size as an SVG figure |
| `eeglayoutlab pareto RUN.result.json... --out PARETO.json [--objectives LIST]` | `evaluate` and `search` results of one evaluation condition. LIST is comma-separated from `field`, `sensitivity`, `localization`, `p90`, `area`, `dropout`, `impedance`, `replacement` (default `field,sensitivity,localization`) | `eeglayoutlab-cli-pareto/1`: rank, dominating count and values per file, and the files missing an objective |
| `eeglayoutlab study STUDY.json --out-dir DIR [--root DIR] [--python PATH]` | A study in the robustness-study format (`noise_seeds`, `grid_displacements` or `heads`) | `study.json` with case summaries and the aggregation, plus `cases/NN.result.json` |
| `eeglayoutlab examples run [--root DIR] [--out-dir DIR] [--python PATH] [--skip-cross-head] [--update-expected]` | Runs the reproducible examples in `examples/` and checks all 24 scores against `examples/expected.json` within `1e-6` | In a checkout `examples/outputs/` by default; in an installed environment `./eeglayoutlab-examples` unless `--out-dir` is given |
| `eeglayoutlab data list\|verify\|install\|compose\|remove\|build` | Data packages from `data/packages.json` (see [data packages](data-packages.md)) | Verified read-only packages in the user data directory and composed links in the scientific root |

The request formats are defined in [API formats](../contracts/api-formats.md) and the coordinate files in the [coordinate file interface](coordinate-file-interface.md). A batch continues after a failed request, writes `<name>.error.json` for `evaluate` and `search`, and exits with status 1. Invalid command arguments or input files exit with status 2 and print `error: <message>` on stderr.

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

The key and the identity include the interpreter path, so they differ between installations. Compare scores, not keys, across machines; `eeglayoutlab examples run` (and [`examples/run-examples.mjs`](../examples/run-examples.mjs)) checks scores within `1e-6`.

## Example

```bash
.venv/bin/eeglayoutlab design labels.tsv --name "my layout" --out my-layout.json
.venv/bin/eeglayoutlab evaluate --design my-layout.json --radius 6 --seed 42 --out-dir runs/
.venv/bin/eeglayoutlab export my-layout.json --format mne --out-dir files/
.venv/bin/eeglayoutlab design sub-01_electrodes.tsv sub-01_coordsystem.json --regions 4 --out digitized.json
```

Three complete examples, with their expected scores, are in [`examples/`](../examples/README.md).

## Python workers

The workers can also be called directly. Each reads one JSON request from standard input and writes progress, result or error events as JSON lines:

```bash
.runtime/simnibs-4.6.0/bin/python scripts/design_evaluation.py < request.json
.runtime/simnibs-4.6.0/bin/python scripts/run_local_radius_compute.py < search.json
```

This skips the HTTP normalizer, the result validation and the identity record, and the worker receives the request exactly as written. Use `eeglayoutlab` when results must match the web application's.
