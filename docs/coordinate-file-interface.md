# Coordinate file interface

EEGLayoutLab imports and exports a small subset of BIDS electrode coordinate files, with its own explicit region extension. A layout always has 64 electrodes. It is evaluated in the Ernie native coordinate frame. Coordinates can arrive in five ways:

- as an Ernie-native file pair, read as given;
- as an MNI file pair, mapped onto Ernie's scalp;
- as a list of 10-05 electrode names, looked up in a template cap on Ernie;
- as a BIDS file pair in a digitized head frame (for example `CapTrak`) with NAS, LPA and RPA landmarks, registered onto Ernie's scalp;
- as an MNE-Python `.elc` or EEGLAB `.sfp` montage file, read as given when it carries Ernie's template landmarks and registered otherwise.

Units are never inferred. Head-frame files may declare `mm`, `cm` or `m`, and are converted to millimetres; all other inputs must be in `mm`.

BIDS defines `name`, `x`, `y`, and `z` as the first four electrode columns, requires a coordinate-system JSON alongside electrode coordinates, and requires a description when the coordinate system is `Other`. Additional electrode columns need metadata descriptions. See the [official BIDS EEG specification](https://bids-specification.readthedocs.io/en/stable/modality-specific-files/electroencephalography.html#electrodes-description-_electrodestsv).

## Ernie-native files

Select `electrodes.tsv` and `coordsystem.json` together. Matching BIDS filename prefixes are also accepted. Each file is limited to 64 KiB. The accepted TSV columns are `name`, `x`, `y`, `z`, and `region`, in that order. Names, row order and numeric values are retained.

The coordinate-system file must contain these declarations:

```json
{
  "EEGCoordinateSystem": "Other",
  "EEGCoordinateUnits": "mm",
  "EEGCoordinateSystemDescription": "Ernie native coordinate frame used by EEGLayoutLab, in millimetres.",
  "EEGLayoutLabCoordinateSystem": "ernie_native_mm",
  "EEGLayoutLabRegionIndexBase": 0,
  "EEGLayoutLabRegionDescription": "EEGLayoutLab balanced region index, numbered continuously from zero."
}
```

`region` is an EEGLayoutLab extension. Regions in the file must be numbered continuously from zero and balanced across 1, 2, 3, 4 or 6 regions. Supply the column description in `EEGLayoutLabRegionDescription`, or select a matching `electrodes.json` with a `region.Description` field. A file without a `region` column is accepted only when a region count is chosen ([region assignment](#region-assignment-on-import)).

## MNI files

The same file pair is accepted when `EEGCoordinateSystem` names an MNI template space: `MNI152NLin6Asym`, another `MNI152*` space, `MNI305`, `MNIColin27`, `IXI549Space` or `ICBM452*`. `EEGLayoutLabCoordinateSystem` must then be absent, and the units must be `mm`.

Each point is projected onto Ernie's scalp warped to MNI. The barycentric weights of the triangle it falls on give the point on Ernie's native scalp.

The warp is SimNIBS `subject2mni_coords` (nonlinear, Ernie `toMNI/Conform2MNI_nonl.nii.gz`), evaluated at every vertex of the forward bank's scalp surface. This is the transform the cross-head packages use. Its target is the SimNIBS template `MNI152_T1_1mm`, which is FSL's MNI152 nonlinear 6th generation (`MNI152NLin6Asym`). Points declared in another MNI space are mapped with the same warp, and the recorded description says that differences between templates are not modelled.

The warp is not usable on the lower face, ears and neck. There, 33 scalp vertices have no warp value, and about 4,800 of 104,864 triangles are stretched more than three-fold against the native mesh. Mapping uses the usable triangles only. Nine of the bank's 5,387 candidate sites touch an unusable triangle.

An MNI point farther than 10 mm from the warped scalp is rejected. This is the same tolerance the cross-head mapping uses.

The imported design records the declared MNI space, the mapping identity and the largest distance from the warped scalp. The evaluated coordinates are the mapped Ernie coordinates. They still pass the evaluator's own projection checks (2 mm, admissible triangles, 4 mm spacing).

## 10-05 electrode names

A `.tsv`, `.csv` or `.txt` file with the header `name` and `region` (or `name` alone, with a chosen region count) and 64 rows gives each electrode by its 10-05 name. Positions come from the SimNIBS `EEG10-20_extended_SPM12` cap (343 positions) as placed on Ernie's skin by charm (`eeg_positions`). The standard64 reference uses the same source: its 64 BioSemi64-named positions equal these to within 1.5e-14 mm.

Names are matched without regard to case. The old 10-20 names T3, T4, T5 and T6 are read as T7, T8, P7 and P8. Unknown or repeated names are rejected. The file has no coordinate-system file, so its source records `coordsystem_file: null`.

## Digitized head-frame coordinates

A BIDS pair is read as a head frame when `EEGCoordinateSystem` names a system other than the Ernie-native and MNI spaces (for example `CapTrak`, `ElektaNeuromag`, `EEGLAB`, `ACPC`) and `AnatomicalLandmarkCoordinates` gives `NAS` (or `Nasion`, `NZ`), `LPA` and `RPA`. `AnatomicalLandmarkCoordinateSystem` and `AnatomicalLandmarkCoordinateUnits`, when present, must equal the electrode declarations. `EEGCoordinateUnits` may be `mm`, `cm` or `m`.

Digitized files often list more than the cap. The importer keeps rows whose optional `type` column is `EEG` (or absent) and that have coordinates. Ground, reference and EOG rows of another type, and rows whose coordinates are all `n/a`, are skipped. The remaining rows must be exactly 64 EEG electrodes with unique names. Besides `name`, `x`, `y`, `z` and `region`, the columns `type`, `material`, `impedance`, `group` and `hemisphere` are accepted and ignored.

Registration (`head-landmarks-surface/1`, `webapp/lib/head-registration.ts`) has three steps:

1. The nasion and preauricular points define a fiducial frame in the file and on Ernie (Neuromag convention: origin on the LPA–RPA line closest to the nasion, x towards RPA, y towards the nasion). Aligning the two frames with one isotropic scale, from the inter-preauricular width and the nasion depth, gives the starting similarity transform. Ernie's landmarks are the SimNIBS template fiducials also written by the export.
2. Iterated closest points refine that similarity transform: each electrode is paired with its closest point on Ernie's scalp, and the three landmarks are kept as pairs with eight times an electrode's weight (Horn's closed-form weighted solution). Iteration stops when no point moves more than 1e-4 mm, after at most 500 iterations.
3. Each transformed electrode is projected onto Ernie's scalp. If any electrode was more than 10 mm from the scalp before projection, or the scale lies outside 0.5–2, the file is rejected; this usually means a wrong unit, frame or landmark.

The result is a placement of the measured montage on the template head. Its accuracy is bounded by how much the participant's head differs from Ernie's, which the three landmarks cannot capture. Two checks in `webapp/scripts/check-head-registration.mjs` measure this:

| Check | Median | Maximum |
| --- | --- | --- |
| Ernie's own positions after scaling (×1.07), rotation (25°, 8°) and a shift: offset after registration | < 1e-4 mm | < 1e-4 mm |
| The same with 1.5 mm electrode and 3 mm landmark digitization noise | about 3 mm | < 10 mm |
| MNE `standard_1005` positions on fsaverage, against Ernie's own 10-05 positions for the same 64 names | 10.0 mm | 22.9 mm |

The last row compares two heads, not a registration error. Relative to NAS, LPA and RPA, the occipital sites of fsaverage lie about 2 cm higher than Ernie's (Oz +22.6 mm). Per-axis scaling of the landmark frame did not reduce the difference (median 11.5 mm), so a single isotropic scale is used. MNE's `biosemi64` montage, which lies on a sphere, is refused: for template caps, import the electrode names instead.

The imported design records the declared frame and unit, the landmark source, the scale, the rotation angle, the largest landmark residual against Ernie's template landmarks, the largest distance from the scalp before projection and the iteration count. Its coordinate description states that this is a template-head placement, not an individual anatomical registration.

## MNE and EEGLAB montage files

`.elc` (ASA, as read by `mne.channels.read_custom_montage`) and `.sfp` (BESA/EGI, as read by EEGLAB `readlocs`) files of at most 64 KiB are accepted.

- `.elc` must declare `UnitPosition` (`mm`, `cm` or `m`). The positions may be numbered or prefixed by their label (`Fp1: x y z`).
- `.sfp` has no unit field, so the unit must be chosen (`--unit` on the command line).

The labels `Nz`, `NAS`, `Nasion`, `FidNz`, `LPA`, `FidT9`, `RPA` and `FidT10` (any case) are read as landmarks. `CMS`, `DRL`, ground, head-shape and HPI points are skipped. The file must then hold exactly 64 uniquely named electrodes and all three landmarks.

When the unit is `mm` and the landmarks equal Ernie's template landmarks to within 1e-6 mm, the file is an Ernie-native export and its coordinates are read unchanged. Otherwise it is registered as above. Both formats carry no regions, so a region count must be chosen.

## Region assignment on import

Files without regions (head-frame pairs, montage files, BIDS pairs and name lists without a `region` column) need a region count of 1, 2, 3, 4 or 6. The regions are then assigned by position (`balanced-spatial/1`). It is a size-constrained k-means on the Ernie coordinates with the evaluator's balanced sizes (for four regions, 16 each). Each step is solved exactly as an assignment problem, and the initial centres are chosen by farthest-point sampling. Regions are numbered from anterior to posterior by their centres, ties from left to right. The assignment does not depend on the order of the electrodes in the file. Regions given in a file are never changed.

## Export

**Ernie native.** Export writes `electrodes.tsv`, `coordsystem.json` and `electrodes.json` with the input coordinates. The coordinate-system file adds:

- `EEGLayoutLabPositionProvenance`: these are design or template positions on the Ernie template head, not positions digitized on a participant. Template coordinates should not be presented as the measured electrode positions of a BIDS recording.
- `AnatomicalLandmarkCoordinates` with `NAS`, `LPA` and `RPA` in the same frame, from SimNIBS `eeg_positions/Fiducials.csv`. These are template landmarks mapped to Ernie, not digitized landmarks. With them, the coordinates can be transformed into a fiducial-based head frame such as the Neuromag head frame.

**MNI.** **Convert to MNI coordinate files** writes the same layout as `space-MNI152NLin6Asym_electrodes.tsv`, `space-MNI152NLin6Asym_coordsystem.json` and `space-MNI152NLin6Asym_electrodes.json`. These carry the MNI template landmarks from SimNIBS `ElectrodeCaps_MNI/Fiducials.csv` and the same provenance statement. Electrodes more than 2 mm from the usable scalp are refused, which covers the jaw, ear and neck regions.

**MNE-Python and EEGLAB.** Two montage files carry the Ernie native coordinates in millimetres (x right, y anterior, z superior) and the same template landmarks:

- `electrodes.elc` (ASA format) for MNE-Python. It declares `UnitPosition mm` and names the landmarks `Nz`, `LPA` and `RPA`, which MNE reads as fiducials. Read it with `mne.channels.read_custom_montage("electrodes.elc", head_size=None)`; the default `head_size` rescales the positions to a 95 mm sphere. `raw.set_montage(montage)` then places the layout in MNE's fiducial head frame.
- `electrodes.sfp` (BESA/EGI format) for EEGLAB. It lists the landmarks as `FidNz`, `FidT9` and `FidT10`, which `readlocs` marks as fiducials, and EEGLAB turns the coordinates to its nose-along-+X convention on import: `pop_chanedit(EEG, 'load', {'electrodes.sfp', 'filetype', 'sfp'})`. The `.sfp` format has no unit field, so MNE would read these millimetres as metres; use the `.elc` file for MNE.

Both formats separate columns by white space and reserve landmark labels. Export refuses electrode names that contain a space or equal a landmark label that MNE or EEGLAB recognizes (for example `Nz`, `LPA`, `FidT9`, `CMS`). `webapp/scripts/check-coordinate-interop.mjs` reads the `.elc` file with MNE when it is installed. It checks the millimetre positions and that MNE's head-frame coordinates equal the Neuromag frame built from the same landmarks to within 1e-6 mm. EEGLAB itself is not run; the `.sfp` layout follows `readlocs`' documented format (label, x, y, z without a header).

**Layout figure.** **Layout figure (SVG, PNG)** draws the layout in 2D for papers and reports. The electrodes are placed in the head frame of the same landmarks with an azimuthal equidistant projection from the vertical axis. The circle is the NAS–LPA–RPA plane, and electrodes below it lie outside. Each region has its own colour and marker shape. Names are hidden by default when they would overlap. The PNG is rendered from the same SVG at three times the resolution.

## Mapping data and checks

The mapping consists of two files:

- `webapp/public/data/ernie-scalp-mni.bin`: float32 MNI coordinates per scalp vertex, then one usable flag per triangle.
- `webapp/public/data/ernie-mni-mapping.json`: bindings to `scalp.bin` and to that buffer, landmarks, cap labels and verification values.

`scripts/build_ernie_mni_mapping.py` builds both from the data bundle and the full SimNIBS Ernie example dataset. The browser verifies both buffers' SHA-256 before use.

The builder records these checks (median / maximum):

| Check | Median | Maximum |
| --- | --- | --- |
| SimNIBS MNI cap positions → distance from the warped Ernie scalp | 0.32 mm | 6.95 mm |
| Same positions mapped to Ernie, against charm's Ernie cap positions | 0.03 mm | 2.24 mm |
| Barycentric surface mapping, against the direct SimNIBS warp at the same points | 0.009 mm | 0.11 mm |
| Ernie → MNI → Ernie round trip on scalp points (web implementation) | | < 0.001 mm |

The web implementation reproduces the builder's Python mapping of ten reference labels to within 1e-4 mm. `tests/test_ernie_mni_mapping.py` and `webapp/scripts/check-coordinate-interop.mjs` keep these checks.

The mapping changes only how coordinates enter or leave the application. It does not establish that an external measured montage has been registered correctly to Ernie, and it is not an individual registration. The interface rejects undeclared coordinates, head frames without landmarks, units other than `mm` outside head frames, missing or `n/a` electrode coordinates, unsupported columns, and layouts outside the existing 64-point validation rules. A complete BIDS dataset and general BIDS validation are outside this interface.

## Source metadata

The import stores the original filenames and coordinate/region descriptions as bounded `source_metadata`:

- `electrode-coordinate-source/1` is an Ernie-native file.
- `electrode-coordinate-source/2` adds a `conversion` record: method `ernie-mni-scalp/1` or `cap-labels/1`, the `mapping_id`, the input coordinate system and, for MNI, the largest distance from the warped scalp.
- `electrode-coordinate-source/3` is written for head-frame registration, montage files and assigned regions. It allows the formats `mne-elc/1` and `eeglab-sfp/1` and a `conversion` that is `null` (Ernie-native), one of the `/2` records or a `head-landmarks-surface/1` record. It adds `region_assignment`: `{"method": "file"}` or `{"method": "balanced-spatial/1", "region_count": N}`.

Files that `/1` and `/2` already described still produce `/1` and `/2` records.

This metadata follows the immutable electrode annotation into project snapshots and deliveries. Changing a source description creates a distinct annotation and leaves the scientific request, cache key, coordinates, scoring inputs and original result files unchanged. Older records without this metadata remain readable.

The coordinate review displays original and evaluated coordinates separately. Before evaluation, it reports `not_evaluated`, without projected coordinates or a displacement value. After an existing validated result is loaded, it computes each displacement for display against the existing 2 mm projection limit. Review JSON retains the full coordinate numbers; it does not round or replace scientific inputs.
