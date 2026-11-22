# Copyright and third-party notices

© 2026 Yiming Shen for original EEG Layout Lab code and documentation.

EEG Layout Lab is a community-oriented research software project supporting EEG research, education, and scientific collaboration.

The project's original source code and accompanying documentation are licensed under the [GNU General Public License version 3 only (GPL-3.0-only)](LICENSE). Third-party software and materials, including Ernie data and its derived scientific and display assets, retain their respective licenses below.

## SimNIBS

The native computation environment uses **SimNIBS 4.6.0**, published by the SimNIBS developers. Its package declares **GPL-3.0-only**. The runtime setup obtains upstream software; the source checkout does not contain a copied installation.

- [SimNIBS 4.6.0 source](https://github.com/simnibs/simnibs/tree/v4.6.0)
- [Upstream GPL version 3 license text](https://raw.githubusercontent.com/simnibs/simnibs/v4.6.0/LICENSE.txt)
- [SimNIBS releases](https://github.com/simnibs/simnibs/releases/tag/v4.6.0)

Preserve upstream copyright and license files with redistributed SimNIBS material. Distribution of runtime binaries and any corresponding-source obligations are governed by the upstream license.

## Ernie head model and derived data

The Ernie inputs originate from **SimNIBS example dataset v4.1**. The release states **© SimNIBS developers 2024**, under **Creative Commons Attribution-NonCommercial 4.0 International (CC BY-NC 4.0)**. The dataset's release-specific license is distinct from the SimNIBS software license.

- [Official dataset release and attribution](https://github.com/simnibs/example-dataset/releases/tag/v4.1)
- [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/)
- [Dataset documentation](https://simnibs.github.io/simnibs/build/html/dataset.html)

The separately supplied numerical bundle includes selected Ernie inputs and derived arrays, with exact identities in [`data/manifest.json`](data/manifest.json) and provenance in [`data/SOURCES.md`](data/SOURCES.md). Derived files include candidate geometry, surface-admission information, scalp mappings, source arrays, lead fields, and model-dependent result records. Preserve the dataset attribution, license link, noncommercial condition, and description of modifications when sharing those materials.

The anatomical display under `webapp/public/models/ernie/` contains selected scalp and gray-matter surface components. Coordinates are converted from millimetres to metres and rounded into display buffers. These buffers are for visualization; they do not replace the original scientific mesh. Their [`manifest`](webapp/public/models/ernie/manifest.json) and [`asset notice`](webapp/public/models/ernie/README.md) document the transformations and source identity.

`webapp/public/data/ernie-scalp-mni.bin` and [`ernie-mni-mapping.json`](webapp/public/data/ernie-mni-mapping.json) are also derived from the Ernie example dataset and keep its CC BY-NC 4.0 terms. They contain the SimNIBS nonlinear Ernie-to-MNI warp sampled at the display scalp vertices, Ernie's charm-placed `EEG10-20_extended_SPM12` cap positions and fiducials, and the MNI fiducials from the SimNIBS 4.6.0 `ElectrodeCaps_MNI` resources (GPL-3.0-only). [`scripts/build_ernie_mni_mapping.py`](scripts/build_ernie_mni_mapping.py) records every input hash.

The added `source-roi-cortex.bin` displays the original left/right **central cortical surfaces** used for the frozen source geometry. Its vertices are converted to float32 metres, normals are packed as int8, and triangles are reordered into atlas-defined material groups; geometry is not deformed or simplified. `source-roi.json` records source checksums and the exact mapping. The Ernie data attribution and CC BY-NC 4.0 terms above apply to these derived surfaces.

The six research ROIs merge Desikan–Killiany labels from the `aparc_DK40` annotations distributed with SimNIBS. Existing registered-sphere label transfer to Ernie is reproduced and checked against the frozen source archive; these are project-defined ROI groupings of atlas parcels, not a new atlas or manual individual segmentation. Atlas material retains its upstream notices. See [Desikan et al. (2006)](https://doi.org/10.1016/j.neuroimage.2006.01.021), [FreeSurfer cortical parcellation documentation](https://www.freesurfer.net/fswiki/CorticalParcellation), and [SimNIBS surface ROI analysis](https://simnibs.github.io/simnibs/build/html/tutorial/analysis.html#roi-analysis-using-surfaces).

## Other dependencies

The stylesheet [`webapp/styles/vendor/shadcn/tailwind.css`](webapp/styles/vendor/shadcn/tailwind.css) is copied without modification from **shadcn 4.18.0**, © 2023 shadcn, under the MIT License. Its [complete license](webapp/styles/vendor/shadcn/LICENSE.md) is retained beside the file. The application uses this local stylesheet; the component-generator CLI is not required at runtime.

The web dependencies are recorded in [`webapp/package-lock.json`](webapp/package-lock.json). Python project dependencies are recorded in [`pyproject.toml`](pyproject.toml); the native runtime setup uses [`configs/runtime/manifest.json`](configs/runtime/manifest.json), the accompanying environment specifications, and upstream package metadata. Each dependency retains its own copyright and license.

This file identifies the principal software and data sources used by the application. It is not a replacement for individual package license files or a complete license inventory for a future bundled binary distribution. Such a distribution must retain the notices for the exact dependency versions it contains.
