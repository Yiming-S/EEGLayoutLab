# Reproducible examples

Three examples run from input files to result files through the [command line](../docs/command-line.md). They use the same request checks, Python workers and scientific identity as the web application. `expected.json` holds their scores, and the runner compares a new run with them.

```bash
node examples/run-examples.mjs
```

They need Node.js, the installed data bundle and the scientific runtime ([source installation](../docs/source-installation.md)). Pass `--root DIR` when the data and runtime are in another checkout. Results are written to `examples/outputs/`, which Git ignores. On the reference Mac the three examples take about 35 seconds.

| Example | Input | What it does | Result files |
| --- | --- | --- | --- |
| 1. Standard 64 | `01-standard64/standard64-labels.tsv` | Builds the standard 64-electrode reference from its 10-05 names, writes BIDS, MNE (`.elc`), EEGLAB (`.sfp`) and SVG files, and scores it. | `design.json`, `files/`, `request.result.json` |
| 2. Compact search | `02-compact-search/search.json` | Searches a two-region layout with a 30 mm radius on the whole scalp, turns the result into a design, draws it and scores it as fixed coordinates. | `search.result.json`, `design.json`, `files/layout.svg`, `request.result.json` |
| 3. Cross-head | `03-cross-head/heads.json` | Scores the layout from example 2 on eleven heads with one shared noise seed. | `study.json`, `cases/*.result.json` |

## What the scores show

Example 1 is the reference itself, so its relative scores are 1. Its absolute localization error (median 10.75 mm, 90th percentile 20.80 mm) is the baseline that the other layouts are divided by.

Example 2 keeps 66 % of the reference field reconstruction. It keeps 17 % of the amplitude for the worst 10 % of sources, and 27 % of localization in the search (28 % when evaluated). The search and the evaluation score the same coordinates. Field and amplitude agree to about 1e-14. Localization differs because the search draws its noise from a seed derived from the request, while the evaluation uses seed 42.

Example 3 gives the field retention of that layout across the eleven heads: median 0.665, with 10th to 90th percentile 0.638 to 0.669. The localization retention is median 0.307, with 10th to 90th percentile 0.206 to 0.346. These are empirical summaries of eleven cases, not confidence intervals.

## Comparing runs

The runner compares the scores within 1e-6. Each result file also records the request key and the SHA-256 of every model input and worker file. The key includes the Python path, so it differs between installations even when every score matches.

Example 3 needs the cross-head packages under `results/v2/heads/`. They are generated outputs and not part of the data bundle; see [data and reproducibility](../docs/data-and-reproducibility.md) and [building head packages](../docs/server-deployment.md#building-head-packages). Without them the run fails and names the missing packages; `--skip-cross-head` runs examples 1 and 2 only and reports that example 3 was not compared.

`node examples/run-examples.mjs --update-expected` rewrites `expected.json`. Use it only after an intended change to the model or the methods, and record why in the commit.
