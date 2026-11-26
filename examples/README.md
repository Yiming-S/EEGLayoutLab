# Reproducible examples

Three examples run from input files to result files through the [Python command line](../docs/command-line.md) without needing Node.js. They use the same request checks, Python workers and scientific identity as the web application. `expected.json` holds their scores, and the runner compares a new run with them.

```bash
# Quick first-calculation verification (examples 1 and 2; needs only the base data package):
.venv/bin/eeglayoutlab examples run --skip-cross-head

# Full suite including the 11-head study (example 3):
.venv/bin/eeglayoutlab examples run
```

In a source checkout, results default to `examples/outputs/` (ignored by Git). In an installed conda environment, results default to `./eeglayoutlab-examples` in the current working directory unless `--out-dir DIR` is passed, and writing inside the read-only package root is refused. Pass `--root DIR` when the scientific root is elsewhere, or `--python PATH` to override the worker interpreter. On the reference Mac, examples 1 and 2 take about 10 seconds and all three take about 35 seconds.

| Example | Input | Data packages needed | What it does | Result files |
| --- | --- | --- | --- | --- |
| 1. Standard 64 | `01-standard64/standard64-labels.tsv` | `base` | Builds the standard 64-electrode reference from its 10-05 names, writes BIDS, MNE (`.elc`), EEGLAB (`.sfp`) and SVG files, and scores it. | `design.json`, `files/`, `request.result.json` |
| 2. Compact search | `02-compact-search/search.json` | `base` | Searches a two-region layout with a 30 mm radius on the whole scalp, turns the result into a design, draws it and scores it as fixed coordinates. | `search.result.json`, `design.json`, `files/layout.svg`, `request.result.json` |
| 3. Cross-head | `03-cross-head/heads.json` | `base`, `head-ernie_xh`, and the 10 IXI head packages (`--examples`) | Scores the layout from example 2 on eleven heads with one shared noise seed. | `study-input.json`, `study.json`, `cases/*.result.json` |

## What the scores show

Example 1 is the reference itself, so its relative scores are 1. Its absolute localization error (median 10.75 mm, 90th percentile 20.80 mm) is the baseline that the other layouts are divided by.

Example 2 keeps 66 % of the reference field reconstruction. It keeps 17 % of the amplitude for the worst 10 % of sources, and 27 % of localization in the search (28 % when evaluated). The search and the evaluation score the same coordinates. Field and amplitude agree to about 1e-14. Localization differs because the search draws its noise from a seed derived from the request, while the evaluation uses seed 42.

Example 3 gives the field retention of that layout across the eleven heads: median 0.665, with 10th to 90th percentile 0.638 to 0.669. The localization retention is median 0.307, with 10th to 90th percentile 0.206 to 0.346. These are empirical summaries of eleven cases, not confidence intervals.

## Comparing runs

The runner compares the 24 scores within `1e-6`. Each result file also records the request key and the SHA-256 of every model input and worker file. The key includes the Python path, so it differs between installations even when every score matches.

Example 3 needs the eleven head packages (`head-ernie_xh` plus the ten IXI heads) placed under `results/v2/heads/`; see [data packages](../docs/data-packages.md) and [data and reproducibility](../docs/data-and-reproducibility.md). Without them the run fails and names the missing packages; `--skip-cross-head` runs examples 1 and 2 only and reports that example 3 was not compared.

`.venv/bin/eeglayoutlab examples run --update-expected` rewrites `expected.json` (permitted only in a source checkout with all three examples enabled). Use it only after an intended change to the model or the methods, and record why in the commit. `node examples/run-examples.mjs` remains available as the legacy parity reference until phase 4.
