# Data sources and frozen payload declaration

## SimNIBS example dataset, release v4.1

- Upstream: SimNIBS Developers.
- Copyright: © SimNIBS developers 2024.
- Release: https://github.com/simnibs/example-dataset/releases/tag/v4.1
- Archive: https://github.com/simnibs/example-dataset/releases/download/v4.1/simnibs4_examples.zip
- Dataset documentation: https://simnibs.github.io/simnibs/build/html/dataset.html
- Release-specific license: CC BY-NC 4.0.
- License text: https://creativecommons.org/licenses/by-nc/4.0/legalcode
- The release page explicitly licenses its example data under CC BY-NC 4.0;
  the repository's general GPL badge is not used as the data license.

The upstream member `m2m_ernie/ernie.msh` is included without byte changes at
`data/external/simnibs4_examples_partial/m2m_ernie/ernie.msh`. Its SHA-256 is
`847707671cc93db548948b46b715c4c67513e1cb7fbed289b6609963174e67cc`.
The source workspace recorded ZIP member CRC32 `7bb35420`, compressed size
98,389,001 bytes and uncompressed size 174,021,639 bytes. The export does not
include the full upstream archive or other subjects.

## Locally derived frozen application data

The included scalp arrays, cortical input arrays, candidate geometry, exposure
mask, forward bank and optimization/area reports were produced by the original
research workspace from the Ernie template. They are selected application
inputs and results, not an unmodified upstream dataset. Their complete
repository-relative paths, byte sizes and SHA-256 hashes are in `manifest.json`.
The upstream attribution and noncommercial conditions accompany these Ernie
derived artifacts. This declaration does not assign a new license to the
research author's original contributions.

The source arrays represent the frozen 4,096 dictionary sources and 256
generation sources. The data support the application's existing single-template
workflows; they do not establish independent-head or population validation.

All 20 original payload files retain the source workspace's exact bytes, IDs
and relative paths. The six current/historical pointers select only the files
needed by the application. The forward bank's `run_manifest.json` is included
because runtime identity checks and the frozen source catalog require it. Its
software versions, conda package hashes, library hashes and original run IDs
are provenance records, not installation requirements. Generator script hashes
refer to the original generation environment; this package is not the complete
campaign reproduction archive.

The original JSON payload was inspected for absolute paths during preparation;
no local absolute filesystem paths were found. No frozen JSON was redacted or
rewritten. Personal jobs, caches, local environment directories, source archives
and unrelated campaigns are excluded.

## Transfer boundary

This declaration is shipped with the offline archive. The archive contains
exactly the files named in the checked-in `data/manifest.json`, plus an exact
copy of that manifest. Public redistribution and commercial rights must be
assessed against the source-specific terms; the package does not grant rights
beyond those terms. The packaging script performs no network downloads.
