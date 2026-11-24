# Method details

This page describes how the forward model, the source prior, the simulated signals and the layout computations are implemented. [Model and metrics](model-and-metrics.md) defines the comparison and the three metrics. [Historical studies](historical-studies.md) describes earlier batches that keep their own protocols.

The values below are those of the current default Ernie protocol, with 4,096 dictionary sources and 256 generation sources. Interpret each result under the protocol, source counts and noise settings recorded with it.

## Signal model

The application first specifies the source activity `j`, then computes the electrode signals with the forward matrix `H` of the head:

```text
y(t) = H j(t) + epsilon(t)
y_i(t) = Σ_q H_iq j_q(t) + epsilon_i(t),   q = 1, ..., Q
```

- `j`: the signed strength of each source along its fixed cortical normal. Positions and orientations are encoded in `H`; the components of `j` are current dipole moments in A m.
- `H`: one column per source at a fixed position and orientation, one row per electrode. An entry is the potential produced by a unit dipole moment, in V/(A m).
- `epsilon`: noise added to the electrode observations. The main metrics use independent Gaussian electrode noise calibrated at the standard 64-electrode layout ([layout comparison](#layout-comparison)).
- `y`: the sum of all source contributions at each electrode plus noise, in V. The interface shows waveforms in µV.

For N electrodes and Q sources, `H` is N × Q, `j(t)` is Q × 1 and `y(t)` is N × 1. Automatic layouts have N = 64. The electrode editor can change the number of active electrodes; the reconstruction target remains the standard64 field.

## Forward model

1. Head: the SimNIBS Ernie volume mesh, whose tetrahedra carry tissue labels.
2. Conductivity: one isotropic conductivity per tissue label. These are model parameters, not values inferred from observations. [Conductivity scenarios](model-and-metrics.md#model-mismatch-and-other-heads) change them on purpose.
3. Geometry: source positions and fixed normals on the central cortical surface, point electrodes on the exterior scalp surface.
4. Solution: SimNIBS FEM with reciprocity gives the potential at each electrode for a unit dipole at each source. These responses form `H`.

Positions in the candidate bank reuse their bank rows. Removing electrodes selects the remaining rows; moving an electrode to another candidate selects that candidate's row. A new coordinate is projected onto the scalp and its row is computed ([coordinate evaluation](#coordinate-evaluation)). Scores of an old layout are never interpolated.

`H` already contains the effects of tissue conductivity, source orientation and source position. It is a fixed quasi-static matrix: no separate distance-decay factor, propagation delay or frequency-dependent tissue filter is applied.

### FEM and reciprocity

The potential satisfies the quasi-static equation

```text
div( sigma(r) grad phi(r) ) = div J_p(r)
```

`sigma` is the tissue conductivity, `phi` the potential and `J_p` the primary current density in continuous space. `J_p` and the discrete dipole moments `j` are different physical quantities. FEM discretizes the equation into a sparse linear system, which is factorized and solved with MUMPS. One fixed gauge node of the volume mesh is held at zero potential.

By reciprocity, the solver injects a normalization current `I` at the electrode and withdraws it at the gauge node. It solves for the field `E_i` and evaluates the component along the source normal `n_q` at the source position `r_q`:

```text
H_iq = -n_qᵀ E_i(r_q) / I
[H] = V/(A m),   [j] = A m,   [H j] = V
```

The injected current is a computational device, not a stimulation. A point electrode distributes it over the three nodes of its scalp triangle with barycentric weights, and its potential is read with the same weights. The field at a source is interpolated from the gray-matter elements, as in the SimNIBS leadfield workflow, and projected onto the normal. On Ernie, 108 of the 4,352 sources do not lie inside a gray-matter element and take the field of the nearest gray-matter node, at most 1.55 mm away. The raw `H` is referenced to the gauge node; metrics and displays apply their own reference when they use it. Gradients are computed per millimetre, so the code multiplies by 1000 to obtain V/m.

The implementation is `FixedMeshLeadfield.evaluate` in [`cortical_fem.py`](../src/compact_eeg/cortical_fem.py). The theory and workflow follow the SimNIBS [EEG leadfield documentation](https://simnibs.github.io/simnibs/build/html/tutorial/advanced/eeg_leadfields.html).

## Source activity

The four kinds of calculation use the source model differently:

| Calculation | Use of source activity |
| --- | --- |
| Field reconstruction retention | The expected reconstruction error is computed analytically from the source covariance. No time series is generated. |
| Amplitude retention (lower 10%) | Each unit-source column of `H` is compared by its largest potential difference. The common source amplitude cancels in the ratio. |
| Relative localization score | Off-dictionary test sources are activated one at a time with repeated noise; the fixed dictionary is scanned and the position error is computed. |
| Signal simulation | Time series for 1–6 selected sources are generated and passed through both layouts' `H` to compute observations and reconstructions. |

The layout metrics are therefore not computed from the waveform that signal simulation plays. Layout evaluation uses the fixed source prior; signal simulation evaluates specified sources, waveforms and interference.

### Source sampling and covariance

Dictionary sources are native vertices of the central cortical surface. They are chosen by deterministic farthest-point sampling within the retained cortical domain of each hemisphere, 2,048 per hemisphere, and keep their original normals. Generation sources, 128 per hemisphere, are drawn with probability proportional to cortical triangle area and placed inside the drawn triangle. Their normal is interpolated from the triangle's vertex normals and normalized. A generation source lies a median 2.7 mm from its nearest dictionary source. Off-dictionary means a different position on the same head, not an independent head model.

Both sets are frozen in the cortical input archive (`cortical_input_arrays.npz`), whose SHA-256 the forward bank records. The script that prepared the archive is not part of the repository.

```text
E[j] = 0
C_j = a² diag(w_1, ..., w_Q),   Σ_q w_q = 1
C_yy = H C_j Hᵀ + C_epsilon
```

`w_q` is the share of retained cortical area assigned to source q, and `a` = 10 nA m is the dipole-moment scale. The diagonal covariance makes the source coefficients uncorrelated under this prior, each with variance `a² w_q`. The area weights belong to the prior; they are not multiplied into the raw `H`. Observation covariances are computed with the same reference transform as the observations.

The prior allocates variance by retained cortical area and gives no extra weight to a task region. The prior and the waveforms are simulation specifications, not estimates from MI or P300 recordings. A [data-derived prior](model-and-metrics.md#data-derived-source-prior) can replace the area weights when a request names one. The metric engine is `LayoutSearchMetrics` in [`layout_search_metrics.py`](../src/compact_eeg/layout_search_metrics.py).

Signal simulation groups the generation sources into six research regions defined by DK40 atlas labels; see [source ROIs](SOURCE_ROI_VALIDATION.md).

### Waveforms

Single-source mode selects one frozen generation source. Local mode selects six generation sources within one chosen ROI; cross-region mode activates one fixed representative in each of 1–6 chosen ROIs. The atlas label of a source's original parent triangle decides its ROI; coordinate anchors only rank the eligible sources within an ROI. All modes keep the cortical normals of the forward bank.

```text
s_q(t) = 0.65 b_0(t) + 0.50 b_q(t) + 0.30 sin(2π f_q t + φ_q)
j_q(t) = a sqrt(w̃_q) UnitRMS[ g(t) s_q(t) ]
g(t)   = 0.12 + Σ_{c ∈ {2.5, 7, 12, 17} s} exp(-0.5 ((t - c) / 0.65 s)²)
a = 10 nA m,   Σ_q w̃_q = 1,   sqrt( Σ_q mean_t j_q(t)² ) = a
```

- `b_0` is shared by all sources and `b_q` belongs to source q. Both are Gaussian noise band-limited to 6–18 Hz (third-order Butterworth, applied forward and backward), each demeaned and scaled to unit RMS before mixing. The shared component makes the source waveforms correlated.
- `f_q` is drawn between 9 and 11 Hz and `φ_q` is a random phase. A fixed seed makes the generation reproducible.
- Rhythm mode uses `g(t) = 1`. Burst mode multiplies by the envelope `g(t)`; `UnitRMS` then demeans each source and scales it to unit RMS. The 0.65 s is the standard deviation of each Gaussian bump, not the length of a burst. Both modes have the same strength scale.
- The weights are `w̃ = 1` for one source, the normalized generation-area weights of the six selected sources in local mode, and `w̃_q = 1/K` for K cross-region sources. A single source has an RMS moment of 10 nA m. For several sources, the root of the summed mean-square moments is 10 nA m; each source is weaker.

The reconstruction keeps the whole-brain dictionary prior; it is not refitted to the test waveforms. The implementation is `generate_latents` and `fit_decoders` in [`source_reception.py`](../src/compact_eeg/workflows/source_reception.py), and `_single_source_result` in [`source_reception_v2.py`](../src/compact_eeg/workflows/source_reception_v2.py).

## Layout comparison

The standard64 layout B and the evaluated layout X receive the same sources:

```text
y_B(t) = H_B j(t) + epsilon_B(t)
y_X(t) = H_X j(t) + epsilon_X(t)
z_B(t) = H_B j(t)
```

Both share the anatomy, the tissue parameters and the source specification; only the electrode coordinates differ, and they determine `H_B` and `H_X`. Both reconstructions estimate the same clean target `z_B`. A different measurement position does not change the target.

Reconstruction and localization remove the common reference with Helmert contrasts. The contrast `P_N` is an (N − 1) × N matrix whose orthonormal rows are orthogonal to the all-ones vector. N electrodes therefore give N − 1 independent potential differences, and the standard64 target has 63 dimensions. Waveform displays use each layout's own average reference instead.

The noise is calibrated once at the standard64 layout under the dictionary prior and kept in volts:

```text
sigma² = 10^(-SNR/10) · tr( P_64 H_B C_j H_Bᵀ P_64ᵀ ) / 63
```

Both layouts use the same physical noise standard deviation `sigma`, so a layout's actual SNR changes with the brain signal it receives. Equal noise strength does not mean identical noise samples. Whether draws are paired depends on the protocol: the electrode editor pairs them by electrode slot, while the [radius batch](historical-studies.md#radius-batch) draws them independently per layout.

## ECG and EOG

```text
y(t) = H j(t) + a_ECG(t) + a_EOG(t) + epsilon(t)
```

ECG uses a synthetic P–Q–R–S–T template repeated at about 72 beats per minute, with beat intervals jittered between 0.72 and 0.95 s. EOG uses a synthetic blink waveform at five jittered times. Fixed functions of the electrode coordinates spread them over both layouts: a low-order polynomial for ECG and two Gaussian lobes centred near the eyes for EOG. These functions define interference conditions. They are not outputs of a cardiac, torso or ocular FEM.

Each spatial map is calibrated once at standard64. After the mean is removed, its spatial RMS at standard64 is set to 1 (ECG) or 3 (EOG) times the standard64 reference-free brain-signal standard deviation under the source prior. The same voltage coefficient is applied to the evaluated layout, and both maps are average referenced. The strength control multiplies the interference by 0, 0.5, 1, 2 or 4. It changes neither `H` nor the reconstruction, and comparisons across strengths reuse the same brain signals and noise samples.

Layout metrics include only the specified measurement noise. ECG and EOG conditions are evaluated in signal simulation only ([reception simulation](#reception-simulation)).

## Default parameters

| Item | Default |
| --- | --- |
| Head and reference | One anatomical Ernie FEM head. Standard64 uses template coordinates in Ernie space matched to the BioSemi64 channel names. |
| Sources | 4,096 dictionary sources (2,048 per hemisphere) and 256 off-dictionary generation sources (128 per hemisphere), with fixed normals in the retained cortical domain. |
| Forward banks | Candidate bank 5,387 × 4,352; reference bank 64 × 4,352. The 4,352 columns are the dictionary and generation sources together; they are never all active at once. The exposure screen leaves 4,847 candidates selectable. |
| Strength, noise and localization | Source scale `a` = 10 nA m; nominal SNR 20 dB, calibrated at standard64. Localization tests the 256 generation sources one at a time, with 16 noise realizations per source. |
| Signal simulation | Scored waveforms: 200 Hz for 20 s (4,000 samples). Display preview: the first 8 s at 50 Hz, anti-aliased. Scores use the full waveforms. |

These values do not describe the historical batches or the separate 512-new-source reevaluation; each record states its own protocol.

## Local layout search

The layout page calls the computation service, which runs the Python search. The search keeps 64 electrodes, a 4 mm minimum straight-line spacing and a nominal standard64 SNR of 20 dB. The forward bank holds 5,387 candidate positions, of which the [exposure screen](model-and-metrics.md#placement-sites-and-terms) admits 4,847. Changing the radius or the regions starts a new search in the screened domain, reusing the FEM rows of the candidates.

Each region is grown by ROI-constrained paths on the edge graph of the scalp surface. The regions must form exactly R connected components that do not touch on the original surface adjacency graph. The radius control sets a common upper bound; where regions would connect, the actual radius is reduced. Both the actual radius and the area are reported. Ear-adjacent and low-hair regions are coordinate masks.

The search budget of `strict-radius-local/3-external-exposure` ([`local_radius_compute.py`](../src/compact_eeg/local_radius_compute.py)) is:

- Region centres: every combination of candidate centres when there are at most 256; otherwise a bounded shortlist of at most 16 combinations.
- For each combination, a check that every region has enough candidates, then 2 seeded initial layouts.
- From the best initial layout, one sweep over the 64 electrodes in random order, with at most 12 proposals per electrode. An exchange is accepted only when it raises the objective by more than 10⁻⁹.

The objective is fixed in advance: the lower of field retention and amplitude retention at 20 dB. Localization is computed after the coordinates are frozen, with the 4,096-source dictionary and the 256 generation sources at 16 noise realizations each. The search covers these centres and within-region proposals. It certifies neither a global optimum on the continuous surface nor infeasibility.

One job runs at a time, with 2 threads, and stops after 180 s. Results are looked up before anything is computed, also when automatic computation is off. A hit restores the coordinates and scores; Python starts only when no matching record exists. The match covers the parameters, the scientific code identity and the forward data identity. Changing AR only re-evaluates the three threshold decisions. When the computation service is not running, the interface shows it as disconnected; the computation never runs on the visitor's computer.

Completed results, including bounded searches that constructed no layout, are stored in the service's result files. They survive restarts and stay valid when AR changes. Cancelled, failed and timed-out jobs keep only their logs and enter no cache. A change of input files triggers the model and data version checks. After the search algorithm changes, older records remain readable and their original parameters can be restored; the layout page reads the results of the current version.

The record list shows the strict-area and radius layouts read-only. The historical filter shows the 342 layouts of the [radius batch](historical-studies.md#radius-batch), whose regions may overlap. The total-area results use the same 4,096-source dictionary and 256 generation sources. Curves of different protocols are drawn separately.

## Electrode editing

The editor loads a recorded 64-electrode layout that has saved region boundaries. The 64 electrode slots keep stable numbers.

- Disabling an electrode removes it; no electrode is added or redistributed. The region areas do not change.
- A moved electrode snaps to a bank candidate with an existing FEM row, inside the recorded region of its slot and the exposure screen.
- At least 2 electrodes must stay active, distinct and at least 4 mm apart.

Evaluation uses only the forward rows of the active electrodes and recomputes the reference-free contrasts, the estimator and the metrics. N active electrodes give N − 1 reference-free dimensions; the target remains the 63-dimensional clean standard64 field. The noise keeps its standard64 calibration and is not rescaled when electrodes are removed.

Standard64, the original layout and the edited layout are re-evaluated under one protocol. Localization uses the 4,096 dictionary sources, the 256 generation sources and 16 noise realizations per source. Noise is drawn for the 64 parent slots, and the same draws are restricted to the active slots before re-referencing. With 2 electrodes there is only one potential difference, so a source of unknown amplitude cannot be localized and localization is reported as unavailable.

Drafts and evaluated results are stored separately. Editing invalidates the earlier scores. Evaluations have their own cache and do not enter the fixed-64 curves. An edited layout cannot be passed to signal simulation, which requires 64 electrodes. The implementation is [`electrode_editor.py`](../src/compact_eeg/workflows/electrode_editor.py).

## Coordinate evaluation

The layout comparison takes two records, shows their protocols, actual areas and placement ranges, and checks them against the requirements set for each metric. It exports a Markdown report, the full JSON and the 64 coordinates as CSV.

Imported coordinates are evaluated in the Ernie native frame, in millimetres: X to the right, Y anterior, Z superior. The template records the frame, the units, the 64 points and the zero-based region labels. Files in MNI space, in a digitizer head frame or in a montage format are first mapped onto Ernie ([coordinate file interface](coordinate-file-interface.md)). The 3D preview shows the input only and produces no score.

On evaluation, points in the candidate bank reuse their FEM rows. Other points are projected onto the Ernie scalp:

- the projection may move a point by at most 2 mm;
- the projected triangle must pass the exposure screen;
- the projected electrodes must be at least 4 mm apart.

Their rows come from the published scalp-node table when it is installed ([architecture](architecture.md#execution-and-records)), otherwise from a direct FEM solve on one thread. The direct solve recomputes the standard64 rows as well; they must match the forward bank within a relative difference of 10⁻⁸. Its relative residuals and current-conservation errors must stay below 10⁻⁷. Results keep the evaluated coordinates, and the 3D view switches between the input and the evaluated positions. Localization uses the 4,096-source dictionary, the 256 generation sources and 16 paired noise realizations per source. The new scores are shown apart from the scores of the original record.

### Grid displacement test

The displacement test uses only bank candidates ([`design_evaluation.py`](../src/compact_eeg/workflows/design_evaluation.py)). Each region receives one random unit direction, and each electrode a target at displacement d (3, 6 or 10 mm) along its region's direction. 64 distinct admissible candidates, each within d of its original position, are assigned to the targets by minimizing the total squared distance to target. Four trials use deterministic seeds and are never redrawn because of their scores.

Each trial reports the actual displacement, the target error, the fraction of unmoved electrodes and the minimum spacing. A trial whose spacing falls below 4 mm keeps its coordinates and the reason, without scores. The original region labels are kept; patch boundaries and connectivity are not recertified.

```text
y_0 = H_0 j + epsilon,   y_δ = H_δ j + epsilon,   z = H_64 j
recalibrated:  the LMMSE estimator of H_δ, applied to y_δ
original:      the fixed LMMSE estimator of H_0, applied to y_δ
E = 1 - expected(||z - estimate(y_δ)||²) / expected(||z||²)
```

Both estimators target the clean standard64 field, and the physical noise scale is unchanged. The retention divides `E` by the standard64 value. These are expected errors under the source covariance, not results of finite training samples. The fixed estimator's explained-energy score can be negative: its error then exceeds that of predicting zero. [Repeated evaluation studies](robustness-studies.md#protocols) run the test over several seeds and radii.

### Compute limits

Local layout search, signal simulation and coordinate evaluation share one computation slot. The radius search and the original multi-source reception use at most 2 threads. Single-source reception, reception at new coordinates and coordinate evaluation use 1 thread. Jobs that involve new coordinates stop after 10 minutes, can be cancelled, and reuse cached results for identical inputs.

## Reception simulation

The record view shows the initialization, the curve of accepted position exchanges and the final layout. The search objective keeps its original definition; the curve omits rejected proposals, which are not saved. The experiment package contains the original record, configuration, trajectory and SHA-256 identities. Re-running it requires the matching code version, head model and forward matrices.

Reception holds one completed layout fixed. The user chooses a single source, six local sources or 1–6 cross-region sources, sets the waveform and interference, and runs it ([waveforms](#waveforms)). Each layout reconstructs the standard64 target from its own observation:

```text
ẑ_X(t) = A_X y_X(t)
e_X(t) = ẑ_X(t) - z(t)
```

Reception uses the record's original coordinates. It runs no layout optimization and no new surface-admission check. Historical layouts keep their original coordinate protocol and are not compared with layouts under the current exposure screen; original records and multi-source analyses remain readable.

Display rules:

- Received potentials use each layout's 64-channel average reference. Electrode colours show the potential at the actual coordinates in µV: blue negative, red positive. Both layouts and all preview frames share one colour scale.
- Reception maps use each layout's own coordinates. Reconstruction and residual maps use the average-referenced standard64 target field. Nothing is interpolated between electrodes.
- Markers S1, S2, … are the actual generation sources, coloured by their source region; the selected source's trace has the same colour.
- Dragging the time control or playing updates all potentials at the same time point. Clicking an electrode selects its channel; clicking a source selects its waveform.
- The animation reads the anti-aliased preview: the full 20 s is filtered, resampled to 50 Hz and cut to the first 8 s. Scores always come from the full 200 Hz, 20 s simulation. The display shows quasi-static potentials, not a signal travelling over the scalp.

After a coordinate evaluation, reception can use the saved evaluated coordinates. The first run computes and archives the 64 × 4,352 forward matrix of those coordinates; later scenarios reuse it, and changing the sources or interference recomputes only the signals. Original multi-source results, new source scenarios and new-coordinate forward matrices are cached separately.

The workflow organization follows [SEPIO](https://github.com/TBBL-UTHealth/SEPIO) and the source–field interaction follows the [MNE Dipole Simulator](https://github.com/mne-tools/dipole-simulator). Neither project's optimization objectives nor code were ported; this project keeps its fixed 64-electrode layouts and metric definitions.

## Display geometry

The scalp, with face and ears, and the left and right central cortical surfaces come from the same SimNIBS Ernie example head. The display keeps the original geometry. Surface components were extracted, converted to metres and packed for the browser; skin colour and electrode appearance are styling.

When the current configuration has no result yet, the layout page shows a radial projection as a geometric schematic. When the job completes, the schematic is replaced by the 64 MRI coordinates of the computed layout and the matching standard64 reference. After a parameter change the page shows the state of the new configuration.

Computed layouts and result pages use the saved FEM electrode coordinates, converted at 100 mm per display unit without radial re-projection. Contact markers are raised 1.2 mm along the surface normal so that the surface does not hide them. This is a display offset; the computation uses the original coordinates. Each figure states whether its positions are a schematic or a computed record.

The display assets come from the [SimNIBS example dataset v4.1](https://github.com/simnibs/example-dataset/releases/tag/v4.1), © SimNIBS developers 2024, under [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/). The original head is truncated at the lower face and neck. The assets serve visualization only; see the [third-party notices](../THIRD_PARTY_NOTICES.md#ernie-head-model-and-derived-data).
