# Coordinate file interface

EEGLayoutLab imports and exports a small subset of BIDS electrode coordinate files, with its own explicit region extension. This interface handles 64 electrodes already declared in the Ernie native coordinate frame. It performs no registration or unit conversion.

BIDS defines `name`, `x`, `y`, and `z` as the first four electrode columns, requires a coordinate-system JSON alongside electrode coordinates, and requires a description when the coordinate system is `Other`. Additional electrode columns need metadata descriptions. See the [official BIDS EEG specification](https://bids-specification.readthedocs.io/en/stable/modality-specific-files/electroencephalography.html#electrodes-description-_electrodestsv).

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

`region` is an EEGLayoutLab extension. Regions must be explicitly assigned, numbered continuously from zero, and balanced across 1, 2, 3, 4 or 6 regions. The importer rejects missing regions and does not invent an assignment. Supply the column description in `EEGLayoutLabRegionDescription`, or select a matching `electrodes.json` with a `region.Description` field. Export provides all three files, including `electrodes.json`.

The interface rejects MNI, head and undeclared frames; units other than `mm`; missing or `n/a` coordinates; unsupported columns; and layouts outside the existing 64-point validation rules. The declaration identifies the supplied frame; it does not establish that external digitized coordinates have been registered correctly. A complete BIDS dataset and general BIDS validation are outside this coordinate-file interface.

The import stores the original filenames and coordinate/region descriptions as bounded `source_metadata`. This metadata follows the immutable electrode annotation into project snapshots and deliveries. Changing a source description creates a distinct annotation and leaves the scientific request, cache key, coordinates, scoring inputs and original result files unchanged. Older records without this metadata remain readable.

The coordinate review displays original and evaluated coordinates separately. Before evaluation, it reports `not_evaluated`, without projected coordinates or a displacement value. After an existing validated result is loaded, it computes each displacement for display against the existing 2 mm projection limit. Review JSON retains the full coordinate numbers; it does not round or replace scientific inputs.
