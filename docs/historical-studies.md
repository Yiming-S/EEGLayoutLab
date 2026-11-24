# Historical studies

The application keeps two early batches on the Ernie head: the radius batch and the first two-region pilot. Each keeps its own protocol and its scores qualify only its own layouts. Current radius searches are described in [method details](method-details.md#local-layout-search), and the production fixed-area collection in [validation](validation.md#production-results). The last section records the validation plan written for the early protocol; [validation](validation.md) has replaced it.

## Radius batch

The radius batch (`stage4_ernie_single_head_multiregion_optimization`, batch `20260908T050222.497308Z`) compares spatial layouts of the same 64 electrodes. Its regions may overlap. The data are in [`single_head_optimization.json`](../webapp/public/data/single_head_optimization.json), and the application shows them under the historical results.

### Conditions

Layouts with 1, 2, 3, 4 or 6 regions place 64; 32+32; 22+21+21; 16+16+16+16; or 11+11+11+11+10+10 electrodes. Each region count has two families with free centres, one on the whole scalp and one on the low-hair proxy. Seven further families fix ear, forehead and periorbital regions:

| Regions | Family |
| --- | --- |
| 2 | Left and right near-postauricular |
| 2 | Left near-postauricular and upper forehead |
| 2 | Right near-postauricular and upper forehead |
| 2 | Left and right expanded periauricular |
| 3 | Both near-postauricular and upper forehead |
| 4 | Both near-postauricular, left and right forehead |
| 6 | Both near-postauricular, left and right forehead, left and right superolateral periorbital |

The 17 families are crossed with six radius caps (20, 30, 40, 50, 65 and 80 mm) and two minimum straight-line spacings (4 and 6 mm): 204 conditions. 171 conditions completed with a best-found layout for each of the two objectives, 342 layouts in all. 33 constructed no complete layout. They keep the attempts and the number of electrodes placed, and their geometric feasibility is undetermined.

### Forward fields

5,387 candidate points on Ernie's scalp each have a volume FEM lead field solved directly at the point. All use the same 4,096 area-weighted cortical-normal sources and the same whole-head reference. The candidates are independent of the BioSemi64 positions. The radius is a cap on shortest paths along the mesh edge graph, the spacing is the Euclidean chord distance, and the area is an apportioned approximation over connected vertex masks. All three are discrete approximations of the surface geometry.

### Search

Each condition tests at most 24 sets of region centres, with 4 geometric starts per set. Two starts are kept for each of two objectives at 20 dB: field retention, and the minimum of field retention and sensitivity. Each kept start goes through 2 rounds of electrode-wise exchanges, with at most 16 candidates per exchange. One round of centre exchanges then tests at most 4 centre proposals per region. A centre move must keep every current electrode in its region, and the region is scanned again afterwards. All accepted moves, direct rescoring and geometric checks are recorded. Larger radii start from re-checked results of smaller radii.

The results are the best layouts found on the candidate grid within this budget, not global optima.

### Evaluation

The final layouts of both objectives report field retention, sensitivity and localization at 0, 10 and 20 dB. The physical channel noise is calibrated at the whole-head reference, so every layout has the same physical noise scale. Localization uses 256 off-dictionary generation sources, 16 noise realizations per source and a 4,096-source fixed-normal maximum-likelihood dictionary: 4,096 simulated trials per layout and SNR. Localization did not guide the coordinate search; it compares the final layouts.

The layouts share the noise distribution but use independent seeded realizations, so localization ratios keep Monte Carlo variability. Generation and inversion share anatomy and conductivity. Discretization, orientation and spatial ambiguity of the 4,096-source dictionary give a nonzero error floor within the model. The standard64 reference reads:

| SNR | Field explained energy | Median error | P90 error |
| --- | --- | --- | --- |
| 0 dB | 84.00% | 19.64 mm | 46.20 mm |
| 10 dB | 96.26% | 11.35 mm | 22.34 mm |
| 20 dB | 99.31% | 10.75 mm | 20.80 mm |

### Threshold rule

```text
U = LCVaR_10%,w [ mean_noise( max(0, 1 - error_mm / 50) ) ]
R_loc = U(X) / U(B_64)
G(X; SNR) = min(R_field, R_sens, R_loc)
pass = [G >= AR]
```

The utility is first averaged over the 16 noise realizations of each source. The area-weighted mean over the lowest 10% of generation-source area gives the lower-tail utility `U`. `R_loc` divides the layout's `U` by the standard64 `U`. When the reference `U` is zero or not finite, `R_loc` and `G` are undefined. The three relative metrics are reported separately, `G` gives their joint decision, and each SNR is judged on its own. The decision is a point estimate under the single model, not a population bound.

The batch evaluated layouts in one head and named validation across independent heads, source priors and model mismatch as a later stage. Those protocols now exist as options: [other heads and conductivity mismatch](model-and-metrics.md#model-mismatch-and-other-heads) and the [data-derived source prior](model-and-metrics.md#data-derived-source-prior). Population confidence bounds remain [open](validation.md#open-items).

## Two-region pilot

The first batch preceded any optimization. It used the SimNIBS Ernie volume FEM with two regions of 32 electrodes each. 32 geometric construction attempts completed 28 configurations, with 26 distinct electrode sets. The configurations cover four region pairs: left and right near-postauricular, left and right expanded periauricular, and each near-postauricular region with the upper forehead. Their radius caps are 20–50 mm and their spacings 4 or 6 mm. Region centres and coordinates within regions were not optimized. The data are in [`fixed64_results.json`](../webapp/public/data/fixed64_results.json).

### Forward computation

The reference uses Ernie–SPM12 whole-head template coordinates matched to the BioSemi64 channel names. The 571 unique candidate points and the 64 reference points were solved directly in the same FEM. Helmert contrasts give 63 reference-free observation dimensions for each layout.

### Source prior and noise

The prior has 4,096 cortical-normal dictionary sources, a diagonal covariance weighted by cortical area and a dipole-moment scale of 10 nA m. Nominal SNRs of 0, 10 and 20 dB are calibrated at the whole-head reference; at each SNR every layout has the same channel-noise standard deviation.

### Field reconstruction

The target `z` is the clean reference-free field at the 64 reference positions. The LMMSE estimator is built from the source prior, the forward model and the noise covariance, and the expected error is computed analytically:

```text
A* = Σ_zy Σ_yy⁻¹
F(X) = 1 - tr(Σ_z|y) / tr(Σ_zz)
R_field(X) = F(X) / F(B_64)
```

Ratios above 1 are kept. The reference's relative value is therefore 100% by definition, while its absolute explained energy at 20 dB is 99.31%. The results page shows both scales.

### Sensitivity and localization

Sensitivity compares the largest bipolar amplitude of the layout and the whole-head reference for each source. The ratios are sorted, and the area-weighted mean over the lowest 10% of cortical area is taken.

Localization was computed only for four layouts frozen beforehand, all with a 30 mm radius cap and 6 mm spacing, and for the reference. It scans 4,096 fixed-normal dictionary sources for 256 off-dictionary generation sources with 16 noise realizations each: 61,440 simulated trials over five layouts and three SNRs. Without noise, the reference still has a median error of 10.73 mm and a P90 error of 20.57 mm, a limit of matching with the discrete fixed-normal dictionary. Generation and inversion share the head model and conductivity, so off-grid generation keeps a shared-model bias. These results diagnose the inverse method; they do not measure human localization accuracy.

### Reproducibility and approximations

Twelve computational checks passed. Two independent process runs produced byte-identical forward and metric NPZ files on the same head model. 108 of the 4,352 sources do not lie in a gray-matter element and use nearest gray-matter recovery; four of them lie outside every gray-matter, white-matter and CSF element. They are kept as an explicit gray-matter approximation. Regions are graph-path patches clipped by coordinate masks, and spacing is the Euclidean chord distance.

The pilot covers two-region geometry only. Layouts with 1, 3, 4 or 6 regions, coordinate optimization and the new-source reevaluation belong to later batches.

## Early validation plan

This plan was written for the early protocol. It is superseded: [validation](validation.md) states what is established, and its [open items](validation.md#open-items) list what of this plan remains. It is kept here as a record.

**Variables.** The total is fixed at 64 electrodes in R = 1, 2, 3, 4 or 6 regions with balanced allocations. Each region was to be the smallest geodesic disc containing its electrodes. The main size is the largest actual radius; the control sets a common upper bound without forcing equal regions. All electrodes keep a minimum geodesic distance:

```text
N = 64;  m(R) = (64), (32,32), (22,21,21), (16,16,16,16), (11,11,11,11,10,10)
Ω_r(c_r, a_r) = { x ∈ M : d_M(x, c_r) ≤ a_r };   d_M(x_i, x_j) ≥ δ
a_max(X) = max_r a_r(X);   a_r(X) ≤ a
```

**Comparison families.** Free centres on the whole qualified surface, the least constrained family; a low-hair union of ear, periauricular, forehead and periorbital masks, with equal noise at every site; and specified anatomical prototypes such as both strict postauricular regions, postauricular with forehead, and both full periauricular regions.

**Metrics.** Field retention as now. Sensitivity was to be a two-level lower tail: an area-weighted lower-10% CVaR over sources within each head, then a lower-10% CVaR across heads. Localization was to use a frozen fixed-normal single-dipole maximum-likelihood scan, scored by the area under the 0–50 mm success curve, with median, P90 and P95 errors. The plan's acceptance used lower 95% confidence bounds with heads as the bootstrap unit and at least 100 independent locked test heads:

```text
Pass(X; AR) = 1[ LCB95(R_field) ≥ AR ∧ LCB95(R_sens) ≥ AR ∧ LCB95(R_loc) ≥ AR ]
```

**Radius–performance curve.** The plan defined the best found minimum metric under a radius cap and the smallest cap with a verified passing layout. Geometric infeasibility was to be shown by strict packing bounds or a complete proof, and performance infeasibility by strict upper bounds. A finite search below AR was to be recorded as "no passing layout found within the preset search budget".

```text
γ̂_R,D(a) = best found over a_max(X) ≤ a of min{ R_field, R_sens, R_loc }
â_pass(AR) = smallest radius cap with a verified passing layout
```

**Order.** (1) Choose an anatomical head surface that includes the full postauricular, periauricular, forehead and periorbital areas, and check its source and licence. (2) Register BioSemi64, a continuous candidate surface, the source space and the low-hair masks in one frame. (3) Fix the minimum geodesic spacing by packing experiments and show that each region holds its electrodes. (4) Freeze the clean target, source covariance, noise scale and localizer, then check reference invariance and mesh-refinement stability. (5) Run the bilateral postauricular 32+32, postauricular 32 + forehead 32 and full periauricular 32+32 prototypes. (6) After the prototypes, run the full search over R = 1, 2, 3, 4, 6 and the population threshold validation.

**What was implemented instead.** Regions are graph-path patches with chord spacing, not geodesic discs. Localization uses the utility `u(d) = max(0, 1 - d / 50 mm)`; for one trial it equals the area under the 0–50 mm success curve divided by 50 mm. Sensitivity is the lower tail within one head. Acceptance is a point estimate within one head, not a confidence bound. Other heads, conductivity mismatch and a data-derived prior exist as optional protocols ([model and metrics](model-and-metrics.md#model-mismatch-and-other-heads)).
