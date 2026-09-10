# Copyright and third-party notices

© 2026 Yiming Shen for original EEG Layout Lab code and documentation. A general license for that original material has not been selected. No MIT or other open-source license is granted for it by this repository. Third-party rights and licenses are separate and are not replaced by this notice.

## SimNIBS

The native computation environment uses **SimNIBS 4.6.0**, published by the SimNIBS developers. Its package declares **GPL-3.0-only**. The runtime setup obtains upstream software; the source checkout does not contain a copied installation.

- [SimNIBS 4.6.0 source](https://github.com/simnibs/simnibs/tree/v4.6.0)
- [Upstream GPL version 3 license text](https://raw.githubusercontent.com/simnibs/simnibs/v4.6.0/LICENSE.txt)
- [SimNIBS releases](https://github.com/simnibs/simnibs/releases/tag/v4.6.0)

Preserve upstream copyright and license files with redistributed SimNIBS material. Distribution of runtime binaries and any corresponding-source obligations are governed by the upstream license. This notice does not designate all application code as SimNIBS code or select a license for the original project.

## Ernie head model and derived data

The Ernie inputs originate from **SimNIBS example dataset v4.1**. The release states **© SimNIBS developers 2024**, under **Creative Commons Attribution-NonCommercial 4.0 International (CC BY-NC 4.0)**. The dataset's release-specific license is distinct from the SimNIBS software license.

- [Official dataset release and attribution](https://github.com/simnibs/example-dataset/releases/tag/v4.1)
- [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/)
- [Dataset documentation](https://simnibs.github.io/simnibs/build/html/dataset.html)

The separately supplied numerical bundle includes selected Ernie inputs and derived arrays, with exact identities in [`data/manifest.json`](data/manifest.json) and provenance in [`data/SOURCES.md`](data/SOURCES.md). Derived files include candidate geometry, surface-admission information, scalp mappings, source arrays, lead fields, and model-dependent result records. Preserve the dataset attribution, license link, noncommercial condition, and description of modifications when sharing those materials. No replacement license is assigned to an author-owned contribution by this notice.

The anatomical display under `webapp/public/models/ernie/` contains selected scalp and gray-matter surface components. Coordinates are converted from millimetres to metres and rounded into display buffers. These buffers are for visualization; they do not replace the original scientific mesh. Their [`manifest`](webapp/public/models/ernie/manifest.json) and [`asset notice`](webapp/public/models/ernie/README.md) document the transformations and source identity.

## Other dependencies

The web dependencies are recorded in [`webapp/package-lock.json`](webapp/package-lock.json). Python project dependencies are recorded in [`pyproject.toml`](pyproject.toml); the native runtime setup uses [`configs/runtime/manifest.json`](configs/runtime/manifest.json), the accompanying environment specifications, and upstream package metadata. Each dependency retains its own copyright and license.

This file identifies the principal software and data sources used by the application. It is not a replacement for individual package license files or a complete license inventory for a future bundled binary distribution. Such a distribution must retain the notices for the exact dependency versions it contains.
