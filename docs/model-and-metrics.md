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
