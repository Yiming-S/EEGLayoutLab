# Model and metrics

EEG Layout Lab compares electrode layouts under a specified volume-conductor model, cortical source model, and measurement-noise model. The reference layout has 64 BioSemi positions. Its relative scores equal 1 by normalization; its absolute reconstruction and localization errors remain nonzero.

## Head model, sources, and observations

The current data use the SimNIBS example subject Ernie. Sensor candidates occupy a qualified exterior scalp surface. Sources use a cortical surface with fixed normal orientations and cortical-area weights. Anatomical region names describe coordinate-based proxy masks; they are not reviewed hair-distribution maps or atlas parcellations.

For a layout X, the clean observation is the forward matrix multiplied by the source activity:

```text
y_X = H_X j + epsilon_X
z_64 = H_64 j
```

`H_X` contains the electric potential at each sensor per unit source moment; its units are V/(A m). `j` contains source moments. `epsilon_X` is measurement noise. `z_64` is the clean target field at the reference sensors. SimNIBS FEM and reciprocity provide the forward fields. The comparisons remove a common voltage reference; changing reference does not create additional spatial information.

The model assumes a fixed conductivity distribution. The application does not acquire EEG from an amplifier or infer a participant's anatomy. Its display meshes are visualization buffers; scientific solves use the original mesh and verified numerical inputs.

The current production bank contains 5,387 sensor candidates, a 4,096-source dictionary, and 256 separate generation sources for the associated localization evaluations. Layout reconstruction uses the prescribed source covariance and noise covariance to calculate expected error. It is not scored from the short waveform preview shown by the reception workspace.

## Layout constraints

The standard layout-design comparison holds the physical measurement count at 64. Reference and ground/bias electrodes do not count toward those 64 points. Supported region counts are 1, 2, 3, 4, and 6, with balanced allocations of 64; 32+32; 22+21+21; 16+16+16+16; and 11+11+11+11+10+10.

The local radius search uses ROI-constrained paths on the surface edge graph, checks region separation, and enforces a 4 mm minimum straight-line sensor spacing. This graph radius approximates continuous surface distance. Area uses the original surface's vertex-area weights. A finite search that returns no layout has not proved mathematical infeasibility.

The production fixed-area collection has 30 conditions: five region counts, two placement domains, and three total-area caps (60, 120, and 180 cm²). An area cap and a radius cap define different design problems. Their scores and search results should retain the protocol attached to each record.

Electrode-editor evaluations that change the active sensor count form a separate comparison. They do not inherit the fixed-64 scope merely because they started from a 64-point parent layout.

## Noise and reconstruction

For local radius design, nominal reference SNR is 20 dB. The reference calibrates one physical independent electrode-noise scale, which is also applied to the candidate. The candidate's actual SNR can differ because its brain-signal amplitude differs. Localization noise realizations are generated for each layout under the recorded seed rules; equal noise scale does not mean identical draws.

The linear minimum mean-square error estimator reconstructs the same clean reference field from either layout's noisy measurements. Its explained-energy score is:

```text
E_X = 1 - expected(||z_64 - estimated_z_64(y_X)||²)
            / expected(||z_64||²)
R_field = E_X / E_64
```

The result is a ratio of explained-energy scores. It is not a voltage-amplitude ratio, waveform correlation, or classification accuracy. The reference and candidate absolute scores should accompany the ratio. The implementation is in [`layout_search_metrics.py`](../src/compact_eeg/layout_search_metrics.py) and [`metrics.py`](../src/compact_eeg/metrics.py).

### Optional noise models

The default noise is independent with equal variance at every electrode. Under that model, closely spaced electrodes average noise away, which favours dense clusters. Two optional models, implemented in [`noise_models.py`](../src/compact_eeg/noise_models.py), test that assumption:

- `spatial`: the physical noise covariance is `sigma² N` with `N = (1 - rho) I + rho exp(-d² / 2L²)` over electrode distance `d`, `rho = 0.5` and `L` of 10, 20 or 40 mm. The diagonal stays 1, so every electrode keeps the 20 dB noise power and only the correlations change. It applies to field reconstruction, the radius search and localization. Sensitivity has no noise term and is unchanged.
- `brain_background`: at the reference layout, half of the noise power is cortical background activity, `kappa H diag(area) Hᵀ` over the dictionary sources, and half is independent sensor noise. It applies to localization only: the field metric reconstructs the whole brain field, so background activity is already part of its target. The calibration matches only the total reference-free noise power at the reference to the 20 dB sensor noise. The background is `fraction × 10^(-SNR/10) = 0.005` times the same area-weighted source prior that defines the signal, so it is concentrated in a few directions. The scanner whitens with the full covariance, so most directions carry about half the independent noise level and the reference localizes better than under independent noise (Ernie standard64: median error about 8.6 mm against 10.75 mm). Absolute errors are therefore not comparable across noise models; compare reference-normalized ratios.

The noise scale is still calibrated once at the reference and kept in volts. The independent model reproduces the original scores bit for bit. The radius search seed is derived from the request without `noise_model`, so independent and spatial searches of the same request start from the same random stream. Under spatial noise, the reported effective rank is whitened by the correlated noise covariance. On the production data, spatial noise changed the reference-normalized field score of a compact layout only slightly (0.704 against 0.699, 0.709 and 0.715 for L = 10, 20 and 40 mm); localization changed more. Whether a given layout gains or loses is an empirical result of the model, not a fixed rule.

## Model mismatch and other heads

Production scores generate and invert data with the same head and the same conductivities. Two optional evaluation protocols relax that.

**Conductivity mismatch** (`conductivity_scenario`, Ernie only). The scenarios in [`configs/conductivity_scenarios.json`](../configs/conductivity_scenarios.json) scale compact and spongy bone (tetrahedron tags 7 and 8) by 0.5 or 2; all other tissues keep their SimNIBS 4.6 values. Each scenario has its own scalp-node table. The data come from the scenario head and the inversion keeps the nominal model:

- field: the nominal LMMSE estimator is applied to the scenario observations, scored against the scenario reference field and normalized by the reference layout under the same mismatch; the noise variance stays fixed in volts;
- sensitivity: scenario fields;
- localization: nominal dictionary, scenario generation fields, noise covariance from the scenario head.

The matched-model scores are kept in the result's provenance under `model_mismatch`.

**Other heads** (`head_id`). A head package under `results/v2/heads/<id>/` holds that head's exterior scalp, admissibility mask, cortical sources, mapping from the Ernie surface and its own scalp-node table. [`build_head_package.py`](../scripts/build_head_package.py) builds it from a SimNIBS `charm` segmentation with the same rules as Ernie:

- Exterior scalp: the largest connected skin component, with the same exposure screen. Both rules reproduce Ernie's frozen outputs exactly.
- Sources: deterministic farthest-point sampling of 4,096 dictionary and 256 generation sources on the charm central surfaces. Medial-wall vertices (no DK40 cortical label) are excluded. Area weights come from the labelled vertices nearest each source.
- Gauge: a deep white-matter node.
- Source QA: the same native interpolation checks; each package records its own exception list.

Coordinates and the standard64 reference are mapped from Ernie to MNI space and then into the head, and projected onto its scalp. Candidate and reference are treated identically. A head refuses a layout when any of these holds for a mapped electrode:

- it lies more than 10 mm from that head's scalp before projection;
- it lands on a non-admissible triangle, or on a vertex missing from the head's table;
- it comes closer than 3 mm to another electrode.

Both limits are tolerance conventions. The 10 mm limit bounds the mapping error that is accepted. Projection distances are continuous around it: beyond 10 mm lie the outer ear, the face and, on `ixi012`, the lowest occipital row of candidates (10.3–11.8 mm; the same points project 7–10 mm on `ixi002` and `ixi013`).

Layouts keep at least 4 mm on Ernie. The mapped layout is the anatomically corresponding one, so its spacing follows the local head size. The 3 mm limit is an absolute floor, the 4 mm minimum less 25%. It does not bound the relative loss, so a layout designed wider than 4 mm can lose more than 25% locally and still pass.

Measured on the 356 library layouts that pass the Ernie screen, mapped onto `ixi002`, `ixi012` and `ixi013`:
- at the 1st percentile, nearest-neighbour distances kept 0.75–0.83 of their Ernie value;
- 99% of electrodes projected less than 6 mm, the rest up to 43 mm.

A point on a vertex or an edge is judged by the vertices that carry it, not by a zero-weight corner of the triangle that projection picked. On `ernie_xh` this matches the production admission for all admitted candidates but one: candidate 4925, whose vertex has no admissible triangle and is therefore not in the head's table.

Each result records the mapped minimum spacing and projection distances under `native_qa.head` (`minimum_spacing_mm`, `mapping_projection_mm`) and the mapped coordinates (`head_xyz_mm`). The mapped standard64 reference must pass the same screen: a package whose reference fails it is not published, and evaluation refuses such a package. Conductivities keep their defaults. Head results report `forward_mode: head_scalp_node_table`. `independent_head_validation` is true only for a head whose mesh differs from the frozen Ernie mesh (`mapping.same_subject_as_ernie: false`).

Ernie itself is also packaged under this protocol (`ernie_xh`). Cross-head distributions therefore share one source-sampling rule, and they are a separate protocol from the production Ernie scores. Use `ernie_xh`, not the production score, as the Ernie baseline in cross-head comparisons; see [validation](validation.md#single-layout-readings).

## Cross-session robustness

Between recording sessions a cap loses channels, contacts differ in quality and the cap sits slightly differently. With `robustness: "standard/1"` an evaluation adds these three perturbations ([`design_robustness.py`](../src/compact_eeg/workflows/design_robustness.py)). Each is scored as LMMSE field retention at 20 dB, relative to the unperturbed standard64 reference, the same normalizer as `field_relative`. Standard64 receives the same draws, paired by list position and rotation, and is reported beside the layout.

| Perturbation | Model | Draws |
| --- | --- | --- |
| Electrode dropout | Bad channels removed; the rest re-referenced to their own average and the estimator retrained on them | Each single electrode (64 cases); 32 random sets of 2, 4 and 8 |
| Unequal electrode noise | The nominal noise is the floor of a good contact; a contact multiplies its noise SD by `max(1, exp(s z))`, `z ~ N(0, 1)`, so half the electrodes keep the nominal noise. The estimator knows each channel's noise, which can be measured | `s` = 0.5 and 1.0, 32 draws each |
| Cap re-placement | The whole cap is rotated about the head centre (the centre of the sphere fitted to standard64) around a uniformly random axis, by the angle that moves standard64 by 5 or 10 mm RMS. Each electrode also gets 2 mm (per axis) independent jitter and is projected onto the scalp. Fields come from the scalp-node table | 16 per level |

Re-placement is scored twice:
- `fixed_estimator`: the estimator of the nominal positions is applied to the moved cap, as when positions are not re-measured;
- `redigitized`: the estimator is retrained on the new positions.

A trial in which a layout electrode lands on a non-admissible triangle, or any electrode on a vertex outside the table, is not counted. Its count is reported. Without a published scalp-node table, re-placement is reported as unavailable. Each perturbation uses its own seeded stream of the request seed.

Rescaling a lognormal noise factor to unit mean, or leaving it without the floor, would let the estimator gain from the quieter channels. With that model, highly redundant compact layouts scored above their nominal value. The floor keeps every draw at or below nominal.

On the Ernie model (seed 42) the perturbations give these median retentions:

| Perturbation | standard64 | Compact 2-region 30 mm search layout |
| --- | --- | --- |
| None (nominal) | 100.00% | 66.06% |
| 4 electrodes dropped | 99.85% | 65.90% |
| Unequal noise, `s` = 1.0 | 99.36% | 65.04% |
| Re-placement 10 mm, original estimator | 97.10% | 64.14% |
| Re-placement 10 mm, re-measured positions | 99.84% | 66.52% |

With re-measured positions a compact layout can score above its nominal value, because the moved patches cover a different part of the head. The gap between the two re-placement scores is what re-digitizing each session recovers.

The robustness block does not change the nominal scores, and it is not part of the decision thresholds. Robustness applies to `evaluate` on the nominal Ernie head only, without a conductivity scenario or another head. Spatially correlated noise of the request enters every perturbation. Brain background applies to localization only, so it does not change these field scores.

## Multi-objective comparison

The result library ranks completed layouts by Pareto dominance ([`lib/pareto.ts`](../webapp/lib/pareto.ts)). One layout dominates another when it is at least as good on every chosen objective and better on one; differences within 1e-12 are ties. Rank 1 is the front; rank *k* is the front once ranks below *k* are removed. The available objectives are:
- maximized: field, amplitude and localization retention, and the robustness medians (4 electrodes dropped, unequal noise at `s` = 1.0, 10 mm re-placement with the original estimator);
- minimized: localization P90 and the search's total patch area.

A record is compared only with records of the same evaluation condition (noise model, conductivity scenario, head) and of a current protocol. Historical experiments are interpreted under their own protocols. Records missing a chosen objective are listed as excluded. Area exists only for searches, and robustness only for evaluations that requested it. The command line ranks result files the same way (`pareto`).

## Data-derived source prior

The area prior gives every cortical source power in proportion to its area. Recorded EEG does not have that distribution. A data prior fits regional source power and electrode-noise structure to recordings. Evaluation and search then use it in place of the area prior and the noise model.

**Covariance summaries.** `eeg-summary` ([`eeg_recording.py`](../src/compact_eeg/workflows/eeg_recording.py)) reads EDF/EDF+C, BDF, BrainVision (`.vhdr`, 16- or 32-bit integer or 32-bit float) and EEGLAB `.set` (with or without `.fdt`; boundary events split the recording into segments). Discontinuous EDF+D/BDF+D and MATLAB v7.3 files are rejected.

Channels are matched to the SimNIBS 10-05 cap on Ernie, the same positions as the standard 64-channel reference. An `EEG` prefix and a reference suffix such as `-REF` are removed, and T3, T4, T5 and T6 are read as T7, T8, P7 and P8. Bipolar, auxiliary and unknown names are skipped, and each skipped channel is listed with its reason. Units V, mV, µV and nV are converted to µV. A `?V` unit, a micro sign lost in some BDF headers, is read as µV. A channel whose physical or digital range is blank or malformed is skipped as `invalid_header_range`; the rest of the file is still read.

The data are processed as follows:
- band-pass with a 4th-order Butterworth filter (default 1–40 Hz), plus 50 and 60 Hz notches (Q 30) below the Nyquist frequency;
- filtering is causal and chunked, starting from the steady state at the first sample, and the first epoch of each segment is discarded;
- 2 s epochs;
- a channel is excluded when it is flat (median epoch variance below 10⁻⁶ of the channel median), or when its log variance has a robust z beyond 5 and its variance is more than 4 times or less than a quarter of the channel median (the ratio keeps near-median channels when channels are so alike that the median absolute deviation is tiny);
- after average reference, an epoch is rejected when its log total power has a robust z above 3 or below −4;
- the summary is the mean covariance of the kept epochs, re-referenced to the average (µV²).

The summary records the input file's name, size and SHA-256 and every exclusion. It does not contain the samples. On four public datasets the readers match MNE-Python to a maximum relative difference of 2 × 10⁻¹⁶ (EDF and BDF). The test suite compares all four formats with MNE on written files.

**Model.** At the recorded channels' cap positions, a trace-normalized summary covariance is modelled as

```text
C ≈ P [ Σ_r a_r H_r diag(w_r) H_rᵀ + c G_L + diag(d) ] P
```

Here `H_r` are the scalp-node-table fields of the dictionary sources in region `r` and `w_r` their area weights. The regions are the six atlas ROIs plus the unassigned sources, "other" ([source regions](SOURCE_ROI_VALIDATION.md)). `G_L = exp(-d² / 2L²)` is a correlated-noise term, `d` is one nonnegative noise variance per channel, and `P` is the average-reference projector.

The per-channel term absorbs contact noise and local artefacts, which differ several-fold between channels of real recordings. The region coefficients therefore follow the covariance shared between channels. The fit minimizes the Frobenius residual by bounded least squares, for `L` in 5, 10, 15, 20, 30 and 40 mm and without the correlated term. Longer lengths are left out because a smooth correlation that wide competes with the brain signal itself. First one common signal scale `s₀` is fitted (the area prior). Then the seven coefficients are fitted, bounded to [0.1, 10] `s₀`.

The prior's region gains are the coefficients divided by their area-weighted mean. Its noise is the evaluation's unit-diagonal model `(1 − ρ) I + ρ G_L`, with `ρ = c / (c + mean d)`, rounded to 0.01 and at most 0.95. When `ρ` rounds to 0, the noise is independent.

**Channels and shrinkage.** A fit uses the channels present in at least 90% of the summaries and leaves out summaries missing one of them, listing them. Region gains from a few dozen channels are noisy, so they are shrunk toward the area prior: `g_t = 1 + t (g − 1)`. With three or more summaries, `t ∈ {0, 0.25, 0.5, 0.75, 1}` is chosen by leave-one-out:
1. each summary is held out in turn and the prior is fitted to the others;
2. with the region pattern and `L` fixed, the signal scale, correlated noise and per-channel noise are refitted to the held-out covariance;
3. the `t` with the smallest mean held-out residual is used.

`t = 0` means the data do not support regional differences, and the prior keeps the area weights. With fewer than three summaries `t = 1`, and the file says the fit was not cross-validated.

**Use.** `data_prior` in an evaluation or search request multiplies the dictionary and generation-source weights by their region's gain and replaces `noise_model` by the fitted correlation. The prior is defined on the Ernie head only. The 20 dB reference-calibrated noise level is kept, so scores stay normalized to standard64 under the same prior. The data's own signal-to-noise ratio is reported but not used. The search seed excludes the prior, so a search with and without it starts from the same random stream. Records under a prior are compared only with records under the same prior. They do not enter signal simulation or the electrode editor.

**Validation.** Summaries were made with the default settings (1–40 Hz) and with an 8–30 Hz band. The table shows one pooled prior per dataset, with the leave-one-out comparison against the area prior:

| Dataset | Band (Hz) | Summaries used | Channels | Held-out summaries fitted better than the area prior | Mean held-out residual, prior / area prior | Fitted noise |
| --- | --- | --- | --- | --- | --- | --- |
| Ma2022 (figshare 19228725 v1) | 1–40 | 102 | 32 | 62 | 0.584 / 0.588 | ρ = 0.36, L = 20 mm |
| | 8–30 | 96 | 32 | 61 | 0.543 / 0.550 | ρ = 0.39, L = 30 mm |
| Yang2025 (BDF) | 1–40 | 134 | 58 | 127 | 0.682 / 0.711 | independent |
| | 8–30 | 128 | 56 | 118 | 0.483 / 0.529 | independent |
| PhysioNet eegmmidb 1.0.0, runs 4, 8, 12 | 1–40 | 61 | 61 | 54 | 0.642 / 0.666 | independent |
| | 8–30 | 55 | 63 | 48 | 0.499 / 0.533 | ρ = 0.23, L = 40 mm |
| High-Gamma Dataset (Schirrmeister et al. 2017) | 1–40 | 25 | 121 | 25 | 0.609 / 0.630 | independent |
| | 8–30 | 26 | 122 | 24 | 0.499 / 0.546 | ρ = 0.28, L = 40 mm |

Leave-one-out selected `t = 1` in every case. The mean held-out residual decreased monotonically with `t`. Across datasets the central (sensorimotor) gain was 1.8–3.5. At 8–30 Hz the occipital gain was 2.8–5.2, as expected from the alpha rhythm.

The parietal and "other" gains were at the lower bound in every fit. That means the recorded channels do not separate those regions' fields from their neighbours'. It does not mean those regions are silent. The bounds keep them in the prior at 0.1 of the area scale instead of removing them.

The residuals are large (0.28–0.66 in sample). A 7-region source model with smooth noise explains about half of the recorded covariance structure, and the prior should be read as a coarse reweighting. Residuals are lower at 8–30 Hz, where the structured rhythms dominate.

## Channel subsets from recordings

`channels` and the coordinates page choose subsets of recorded channels from covariance summaries ([`lib/channel-subset.ts`](../webapp/lib/channel-subset.ts)). A subset `S` is recorded against one of its own channels, so it measures the `|S| − 1` differences `x_c − x_s0`. Their span does not depend on which channel is the reference. The target is the average-referenced signal of every channel shared by the training summaries.

A linear minimum mean-square error reconstructor `W = C Dᵀ (D C Dᵀ)⁻¹` is fitted on the pooled trace-normalized training covariance `C`. The error on a covariance `C'` is the unexplained variance fraction:

```text
error = tr((I − W D) C' (I − W D)ᵀ) / tr(C')
```

Here `C'` is the training covariance itself, or a held-out summary. Errors are linear in a trace-normalized `C'`, so the mean over held-out summaries equals the error on their mean.

Selection is greedy: first the best pair, then the channel that explains the most residual variance. Each step is a rank-one update of the residual covariance. The methods differ only in the covariance used for selection; all of them use the same training-data reconstructor:
- the training data;
- the data prior's model covariance at the same channels (`--prior`);
- the area prior's model covariance (`--prior`);
- for comparison, the 10-20 channels present and seeded random subsets of each size (200 draws, mulberry32).

The universe and the left-out summaries follow the same 90% presence rule as the prior fit. Requested sizes must be smaller than the universe. Default sizes that do not fit are dropped. The data-greedy order is also evaluated at the size of the 10-20 subset, so the two can be compared at equal channel counts. The tests check the error against an explicit projection, its independence from the reference channel, and each greedy step against exhaustive search.

**Validation.** Each dataset (1–40 Hz) was split by subject into two halves of its sorted summaries. Selection, the reconstructor and the prior were fitted on the first half; the table gives the mean error on the second:

| Dataset | Channels | Summaries, training / held-out | 16 channels: data | data-prior model | area-prior model | random, median (P10–P90) | 10-20 subset (size) | data greedy at that size |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Ma2022 | 32 | 47 / 55 | 0.394 | 0.403 | 0.403 | 0.445 (0.392–0.498) | 0.304 (19) | 0.318 |
| Yang2025 | 58 | 64 / 70 | 0.144 | 0.168 | 0.156 | 0.196 (0.174–0.231) | 0.134 (18) | 0.130 |
| eegmmidb | 62 | 30 / 29 | 0.187 | 0.200 | 0.190 | 0.258 (0.227–0.320) | 0.214 (18) | 0.164 |
| High-Gamma Dataset | 124 | 12 / 8 | 0.131 | 0.147 | 0.147 | 0.196 (0.163–0.256) | 0.126 (18) | 0.118 |

Greedy subsets were better than the median random subset of the same size for every dataset and size (8, 16, 24 and 32 channels). Selecting on the data was the best method in every case but one: on Ma2022 at 8 channels the data-prior model was lower by 0.010.

The data-prior model was better than the area-prior model in only 3 of 15 dataset–size pairs and equal in 4. For choosing channels, the recorded covariance is the useful input, and the regional reweighting adds nothing. The prior's purpose is the source weighting of evaluation and search.

At the 10-20 size, the data-greedy subset had a lower held-out error in three datasets; for Ma2022 the 10-20 subset was lower.

## Amplitude retention in the lower 10% tail

For each source q, the largest available bipolar amplitude is the difference between the largest and smallest sensor potentials:

```text
A_X(q) = max_i phi_i(q) - min_i phi_i(q)
r(q) = A_X(q) / A_64(q)
R_sens = cortical-area-weighted mean of the lowest 10% mass of r(q)
```

The final boundary source contributes only the weight required to reach exactly 10%. This is a tail average, not a guarantee for every source. Numerical handling excludes near-zero reference denominators and renormalizes the valid weights; the score is unavailable when the exclusion exceeds the allowed area budget.

## Relative localization score

Localization uses a fixed-normal discrete inverse dictionary and separate generation locations. The production comparison evaluates 256 generation sources with 16 noise repetitions per source against the 4,096-source dictionary. The generation and inverse calculations still share the same head model and forward assumptions.

Each localization error d in millimetres is mapped to a utility:

```text
u(d) = max(0, 1 - d / 50 mm)
```

First average utility over noise repetitions for each source. Then, separately for each layout, take the cortical-area-weighted lower 10% mean, U. Finally compute `R_loc = U_X / U_64`. The two lower tails need not contain the same sources. A zero or invalid reference utility cannot support a valid ratio. Report median and upper-quantile errors in millimetres alongside the relative score.

The 50 mm scale is a scoring choice, not a physiological constant. See [`prototype_localization.py`](../src/compact_eeg/prototype_localization.py) and [`inverse_pilot.py`](../src/compact_eeg/inverse_pilot.py).

## Thresholds and search objectives

For the standard three-metric comparison:

```text
G = min(R_field, R_sens, R_loc)
accepted at AR <=> each required metric >= AR
```

AR is a user-selected relative acceptance threshold. Changing AR reinterprets existing scores and does not change the head model, sensors, or computation. The current search objective uses reconstruction and amplitude sensitivity; localization is evaluated on the resulting fixed layouts. This does not establish a joint global optimum.

Acceptance in the application uses model-conditional point estimates. It does not establish a population confidence bound, BCI task accuracy, or measured human performance.

## Source reception

The reception workspace holds a layout fixed and selects source locations, waveforms, noise, and interference settings. It propagates those source moments through the matching forward field. ECG and EOG components use explicitly assumed spatial fields; these are scenario controls rather than validated physiological propagation models.

Reception outputs and layout-search scores have different inputs and evaluation scopes. A waveform demonstration is not an independent validation of all cortical sources. The [validation document](validation.md) separates production evaluation, independent source controls, mesh convergence, and independent-head evidence.

## Method references

The references below document the external modeling methods. They do not validate this application's layouts or implementation.

- Nielsen JD, Puonti O, Xue R, Thielscher A, Madsen KH (2023). [Evaluating the influence of anatomical accuracy and electrode positions on EEG forward solutions](https://doi.org/10.1016/j.neuroimage.2023.120259). *NeuroImage*, 277, 120259.
- Saturnino GB, Madsen KH, Thielscher A (2019). [Electric field simulations for transcranial brain stimulation using FEM: an efficient implementation and error analysis](https://doi.org/10.1088/1741-2552/ab41ba). *Journal of Neural Engineering*, 16, 066032.
- [SimNIBS coordinate conventions](https://simnibs.github.io/simnibs/build/html/documentation/coordinates.html) and [example dataset release](https://github.com/simnibs/example-dataset/releases/tag/v4.1).
