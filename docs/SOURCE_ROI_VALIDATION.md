# DK-defined source ROIs: implementation and verification

## Scope

This change replaces coordinate-anchor **region membership** with DK40 atlas
membership while retaining the six region IDs and the existing three source
modes. It does not change electrode layouts, source coordinates, source normals,
the FEM lead fields, the 4096-source reconstruction prior, noise calibration,
waveform construction, or the three layout-evaluation metrics.

Protocol identifier: `dk40-six-roi-v1`.

The six groups are research ROIs made by merging atlas parcels, not a claim that
human cortex consists of six standard anatomical lobes. The complete label
mapping is in `webapp/public/models/ernie/source-roi-definition.json` and the
App's modeling page. The sensorimotor group contains precentral, postcentral and
paracentral labels; these are excluded from the frontal and parietal groups.

## Native geometry and membership

The frozen cortical input archive already contains DK40 labels mapped from the
template to Ernie's registered spheres. The export reproduces that mapping
byte-for-byte using the original, checksum-verified template annotations,
registered spheres and native central surfaces. No nearest-coordinate
classification or geometry synthesis is used to assign ROIs.

Each source retains its original parent triangle and barycentric position. It
belongs to a group only when all three native vertices have labels in that same
group. Mixed-group boundary faces, insula, cingulate and other unassigned parcels
remain gray. They are available in single-source mode but excluded from grouped
selection. Fine-parcel labels can differ within one merged ROI; the result
records all parent labels instead of inventing a single fine-parcel label.

The displayed brain is the same left/right central surface used for source
generation. Source membership and rendering use the same face definition.
Triangle material groups avoid interpolation of colors across ROI boundaries.
Float32 display positions and packed display normals do not replace the exact
coordinates or normals used in the lead fields.

| ROI | Eligible frozen generators |
| --- | ---: |
| Frontal | 70 |
| Sensorimotor | 34 |
| Parietal | 56 |
| Occipital | 33 |
| Left temporal | 20 |
| Right temporal | 18 |
| Other cortex / boundary faces | 25 |
| Total | 256 |

Within a requested ROI, the existing fixed anchor ranks only eligible sources.
Local mode takes six; cross-region mode takes one stable representative per
selected ROI. No fallback pulls sources from another ROI. Cross-region source
power weights remain `1/K`; local weights retain the existing normalized
generation-area weights. The 4096-source prior remains all-brain and does not
depend on selected test ROIs.

The old frontal representative, generation source **201**, has the DK label
`rostralanteriorcingulate`, outside the declared frontal group. The new frontal
representative is **160**, labeled `superiorfrontal`. Other cross-region
representatives remain 142, 139, 194, 57 and 153 in canonical order. These are
zero-based generation IDs, not the per-experiment S1–SK display numbers.

## Cache and compatibility

New UI requests explicitly contain `region_definition: dk40-six-roi-v1`.
Experiment fingerprints include the atlas membership JSON, definition JSON and
selection code. Old coordinate-proxy request/result files remain intact and
cannot be returned as hits for a new atlas-defined request. The inner forward
cache is unaffected because anatomy, source geometry and electrode coordinates
have not changed. A different selected source can legitimately change a scenario
score even though H and the estimator are unchanged.

## Verification performed

- Template, central surface and registered-sphere checksums match the frozen
  source configuration; both hemispheres reproduce the archived atlas labels.
- All 4096 dictionary coordinates and all 256 generated coordinates are checked
  against the original native geometry; all generated normals reproduce the
  original normalized barycentric normals.
- All 63 nonempty regional combinations select stable, unique, in-ROI sources.
  Local six-source sets are contained in the requested ROI; insufficient sets
  fail without borrowing sources from another region.
- Source-to-rendered-parent-triangle membership agrees for all 256 sources.
  Applying material groups does not change positions, normals or indices.
- A synthetic and an actual-bank single-source experiment have identical
  waveforms, conditions, curves, events and metrics with/without atlas metadata.
- Actual-bank tests use the existing two-region, 60 cm² low-hair layout and run
  one, two and six cross-region sources, a sensorimotor local six-source case,
  and an unassigned single-source case. Fields match direct projection through
  the original H columns; no FEM was recomputed.
- Scientific regression: **81 passed, 2 skipped, 103 subtests passed**. The two
  opt-in legacy real-data tests are separate from the five actual-bank cases
  above, which were executed.
- Frontend/service checks: **183 passed**, including atlas identity, mesh
  grouping, bilingual text, cache separation and existing workflows.
- TypeScript checking and production build passed.

This verifies the implemented mapping and numerical invariants. The atlas is
template-transferred to the existing Ernie head; this change does not constitute
independent-subject or clinical validation.

## Reproduction

```sh
python -m pytest tests/test_source_reception.py tests/test_source_reception_v2.py \
  tests/test_source_roi.py tests/test_reception_forward_provider.py -q
cd webapp
npm run test:unit
npm run typecheck
npm run build
```

Regenerate the derivative using `scripts/export_source_roi.py` with the original
checksum-pinned source configuration, archive, subject surfaces and SimNIBS
templates. The generated manifest records hashes and transformations. See the
asset README and `THIRD_PARTY_NOTICES.md` for attribution.

## Sources

- Desikan et al. (2006), *An automated labeling system for subdividing the human
  cerebral cortex on MRI scans into gyral based regions of interest*.
  https://doi.org/10.1016/j.neuroimage.2006.01.021
- FreeSurfer, *Cortical parcellation*.
  https://www.freesurfer.net/fswiki/CorticalParcellation
- SimNIBS, *ROI analysis using surfaces*.
  https://simnibs.github.io/simnibs/build/html/tutorial/analysis.html#roi-analysis-using-surfaces
