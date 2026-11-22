# Coordinate file interface

EEGLayoutLab imports and exports a small subset of BIDS electrode coordinate files, with its own explicit region extension. A layout always has 64 electrodes. It is evaluated in the Ernie native coordinate frame. Coordinates can arrive in three ways:

- as an Ernie-native file pair, read as given;
- as an MNI file pair, mapped onto Ernie's scalp;
- as a list of 10-05 electrode names, looked up in a template cap on Ernie.

Units are never inferred or converted.

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

`region` is an EEGLayoutLab extension. Regions must be explicitly assigned, numbered continuously from zero, and balanced across 1, 2, 3, 4 or 6 regions. The importer rejects missing regions and does not invent an assignment. Supply the column description in `EEGLayoutLabRegionDescription`, or select a matching `electrodes.json` with a `region.Description` field.

## MNI files

The same file pair is accepted when `EEGCoordinateSystem` names an MNI template space: `MNI152NLin6Asym`, another `MNI152*` space, `MNI305`, `MNIColin27`, `IXI549Space` or `ICBM452*`. `EEGLayoutLabCoordinateSystem` must then be absent, and the units must be `mm`.

Each point is projected onto Ernie's scalp warped to MNI. The barycentric weights of the triangle it falls on give the point on Ernie's native scalp.

The warp is SimNIBS `subject2mni_coords` (nonlinear, Ernie `toMNI/Conform2MNI_nonl.nii.gz`), evaluated at every vertex of the forward bank's scalp surface. This is the transform the cross-head packages use. Its target is the SimNIBS template `MNI152_T1_1mm`, which is FSL's MNI152 nonlinear 6th generation (`MNI152NLin6Asym`). Points declared in another MNI space are mapped with the same warp, and the recorded description says that differences between templates are not modelled.

The warp is not usable on the lower face, ears and neck. There, 33 scalp vertices have no warp value, and about 4,800 of 104,864 triangles are stretched more than three-fold against the native mesh. Mapping uses the usable triangles only. Nine of the bank's 5,387 candidate sites touch an unusable triangle.

An MNI point farther than 10 mm from the warped scalp is rejected. This is the same tolerance the cross-head mapping uses.

The imported design records the declared MNI space, the mapping identity and the largest distance from the warped scalp. The evaluated coordinates are the mapped Ernie coordinates. They still pass the evaluator's own projection checks (2 mm, admissible triangles, 4 mm spacing).

## 10-05 electrode names

A `.tsv`, `.csv` or `.txt` file with the header `name` and `region` and 64 rows gives each electrode by its 10-05 name. Positions come from the SimNIBS `EEG10-20_extended_SPM12` cap (343 positions) as placed on Ernie's skin by charm (`eeg_positions`). The standard64 reference uses the same source: its 64 BioSemi64-named positions equal these to within 1.5e-14 mm.

Names are matched without regard to case. The old 10-20 names T3, T4, T5 and T6 are read as T7, T8, P7 and P8. Unknown or repeated names are rejected. The file has no coordinate-system file, so its source records `coordsystem_file: null`.

## Export

**Ernie native.** Export writes `electrodes.tsv`, `coordsystem.json` and `electrodes.json` with the input coordinates. The coordinate-system file adds:

- `EEGLayoutLabPositionProvenance`: these are design or template positions on the Ernie template head, not positions digitized on a participant. Template coordinates should not be presented as the measured electrode positions of a BIDS recording.
- `AnatomicalLandmarkCoordinates` with `NAS`, `LPA` and `RPA` in the same frame, from SimNIBS `eeg_positions/Fiducials.csv`. These are template landmarks mapped to Ernie, not digitized landmarks. With them, the coordinates can be transformed into a fiducial-based head frame such as the Neuromag head frame.

**MNI.** **Convert to MNI coordinate files** writes the same layout as `space-MNI152NLin6Asym_electrodes.tsv`, `space-MNI152NLin6Asym_coordsystem.json` and `space-MNI152NLin6Asym_electrodes.json`. These carry the MNI template landmarks from SimNIBS `ElectrodeCaps_MNI/Fiducials.csv` and the same provenance statement. Electrodes more than 2 mm from the usable scalp are refused, which covers the jaw, ear and neck regions.

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

The mapping changes only how coordinates enter or leave the application. It does not establish that an external measured montage has been registered correctly to Ernie, and it is not an individual registration. The interface rejects head-frame and undeclared coordinates, units other than `mm`, missing or `n/a` coordinates, unsupported columns, and layouts outside the existing 64-point validation rules. A complete BIDS dataset and general BIDS validation are outside this interface.

## Source metadata

The import stores the original filenames and coordinate/region descriptions as bounded `source_metadata`:

- `electrode-coordinate-source/1` is an Ernie-native file.
- `electrode-coordinate-source/2` adds a `conversion` record: method `ernie-mni-scalp/1` or `cap-labels/1`, the `mapping_id`, the input coordinate system and, for MNI, the largest distance from the warped scalp.

This metadata follows the immutable electrode annotation into project snapshots and deliveries. Changing a source description creates a distinct annotation and leaves the scientific request, cache key, coordinates, scoring inputs and original result files unchanged. Older records without this metadata remain readable.

The coordinate review displays original and evaluated coordinates separately. Before evaluation, it reports `not_evaluated`, without projected coordinates or a displacement value. After an existing validated result is loaded, it computes each displacement for display against the existing 2 mm projection limit. Review JSON retains the full coordinate numbers; it does not round or replace scientific inputs.
