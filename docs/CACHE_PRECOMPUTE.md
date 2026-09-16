# Atlas source cache campaign

This campaign warms the existing App cache through its normal local API and
single-worker FIFO. It does not insert synthetic cache records, change scientific
algorithms, alter thresholds, or bypass request limits.

## Frozen coverage

- 30 current `strict_area` layouts: 1/2/3/4/6 electrode regions, two placement
  domains, and 60/120/180 cm² area caps.
- 6 local six-source scenarios and all 63 nonempty cross-ROI combinations.
- Both burst and rhythm waveforms.
- Atlas protocol `dk40-six-roi-v1`, seed 2026, artifact scale 1.
- Nominal total: **4,140 exact request configurations**. Preflight accepted 29
  layouts (**4,002 requests**); the whole-head, one-region, 180 cm² layout has one
  coordinate component differing from the bank by 2.7755575615628914e-17 mm and
  is excluded pending separate handling. Strict matching is not relaxed.
  Other seeds, individual-source
  indices, artifact scales and newly edited layouts are not claimed as cache hits.
- Each result also contains the existing four-condition comparison and the
  five-strength evaluation curves. This does not mean another selected artifact
  scale has its complete waveform response precomputed.

The first 406 accepted requests cover all six local-source scenarios plus the six-ROI
mixture on every layout, using both waveforms. Remaining requests cover the
smaller cross-region combinations. Previously completed exact matches are reused.

## Run / resume

Start the local App, then from the repository root:

```sh
.runtime/simnibs-4.6.0/bin/python scripts/preflight_source_cache.py
node scripts/precompute_source_cache.mjs
```

The default address is `http://127.0.0.1:3001`. Override it with
`EEG_PRECOMPUTE_URL` for another local port. Progress and the frozen plan are in
`results/precompute/dk40-default-v1/`. The runner is restartable using the same
command. It keeps a single active job, waits behind interactive jobs, and does not
cancel another visitor's computation.

To pause before the next job, create an empty file named `PAUSE` in that campaign
directory. Remove that file and run the same command to resume. SIGTERM also
stops the submitter; an already accepted App job can finish and is recovered on
resume. The app and computer must remain running for progress.

Limits: at least 80 GiB free disk space; stop when the source cache exceeds
40 GiB; at least 3.5 seconds between submissions; no parallel solver jobs.
Scientific-file changes or a failed job pause the campaign for inspection.

`status.json` contains a private local session cookie needed to resume ownership
of an accepted job. It is created with owner-only permissions. Do not publish the
campaign status or queue/session files. Share verified scientific caches through
a separate data package, not Git. Cached results are reusable only when the full
experiment identity matches; another numerical runtime can legitimately miss.

## Retired data

The four coordinate-proxy source-simulation cache groups were removed from the
active app, along with their terminal queue receipts. The current atlas caches,
FEM lead fields, source catalog, model inputs, saved layout results, editor data
and other dependencies were retained. The retirement manifest records exact
source paths, hashes, byte counts and a recoverable destination.
