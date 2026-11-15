# Repeated evaluation studies

The web workspace at `/robustness` saves explicit batches of existing coordinate evaluations. Each case retains its original `design-evaluation/1` request and scientific cache key. The study wrapper is independently versioned as `eeg-robustness-study/1`.

Start from **Coordinates → Create a robustness study with these coordinates**, or import a 64-electrode coordinate file in the study workspace. The handoff retains the original input coordinates, electrode names and coordinate-source declarations. Give the study a title, choose a protocol and list 1–12 seed/radius cases. Saving creates a draft; computation begins after **Start**.

## Protocols

- `noise_seeds`: evaluate the same coordinates with explicitly listed localization-noise seeds. All cases hold the radius parameter fixed. The original evaluation uses 16 localization-noise repetitions. Field reconstruction and sensitivity metrics retain their original deterministic values when only this noise seed changes.
- `grid_displacements`: run the original four grid-displacement trials for each listed seed and radius. The original protocol accepts 64 distinct points in the candidate forward bank and radii of 3, 6 or 10 mm. It retains each trial’s geometry acceptance or rejection and original scores.

The server submits one case at a time through the existing shared queue. Each browser can run one study at a time. Other browsers retain their original queue ownership and cancellation behavior.

## Read the results

The nominal evaluation remains separate from displacement-trial summaries. For each radius, the study reports the median, P10 and P90 across case values, using type-7 linear interpolation. Displacement summaries first describe each case’s valid original trials, then give each case equal weight in the across-case distribution.

`n` counts finite readings for that metric. A case with four rejected trials remains in the case list and rejection counts; its trial summary has `n = 0` and null quantiles. Failed, uncertain and cancelled cases remain listed. The distribution describes the explicitly recorded cases in the Ernie model.

## Stop and recover

Opening, refreshing or exporting a study does not submit work. After a service restart, further submissions pause until **Resume**. A child already accepted by the shared queue retains its original queue behavior. Recovery first checks an owned receipt or a complete exact cache for an interrupted submission. If neither confirms the outcome, the case is recorded as uncertain and is not resubmitted automatically.

**Cancel** stops further case submissions and cancels this browser’s current child subscription. Already completed case archives remain available. Changes in scientific identity require a new study with the updated model.

Studies belong to the current browser session. Export the study JSON to retain the explicit case list, every case state, summary definitions and complete verified scientific cache copies. Export schema: `eeg-robustness-study-export/1`. The service backup includes the `studies/` tree together with its queue and session secret.

## Service interface

All routes use the existing signed browser session. Writes require the normal same-origin access checks and computation-session token.

| Method | Route | Result |
| --- | --- | --- |
| GET | `/api/robustness-studies` | Current browser's study directory |
| POST | `/api/robustness-studies` | Save a draft from `protocol`, `design`, explicit `cases`, `title` and `notes` |
| GET | `/api/robustness-studies/:id` | Read the owned study and case-level summaries |
| POST | `/api/robustness-studies/:id/start` | Explicitly start a draft; body `{}` |
| POST | `/api/robustness-studies/:id/resume` | Reconcile and resume a paused study; body `{}` |
| POST | `/api/robustness-studies/:id/cancel` | Cancel this browser's study subscription and remaining cases; body `{}` |
| GET | `/api/robustness-studies/:id/export` | Export all case states, parsed caches, original `cache_json` strings and checksums |

When cancellation has been requested but saving an already completed result is temporarily blocked, recovery saves that existing result and finishes cancellation. It does not submit remaining cases. The original cache text can be verified directly against `source_sha256`, including its original whitespace and number spelling.
