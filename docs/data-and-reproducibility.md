# Data and reproducibility

The application code and the numerical data bundle are separate deliverables. [`data/manifest.json`](../data/manifest.json) is the checked-in inventory for the supported bundle. Each entry specifies a repository-relative path, byte count, and SHA-256. The manifest schema is `eeglayoutlab-data-bundle/1`.

## What is included

The bundle supplies the exact files needed by the current application: frozen forward-bank and candidate geometry arrays; source arrays and their manifest; surface-admission data; the Ernie volume mesh and exterior scalp mappings; selected current result reports and pointers; and declared seed records. Its 21 files total 406,226,293 bytes (387.41 MiB), including the source declaration. Consult the manifest for the exact members of this release.

The web application's compact result exports and anatomical display buffers are versioned separately under [`webapp/public/`](../webapp/public/). Display buffers do not substitute for the volume mesh used by native computation.

The bundle is limited to the application inputs and supplied records. Installed runtimes, `node_modules`, complete historical calculation directories, and newly generated user jobs are distributed or stored separately. Reproducing a wider research campaign requires that campaign's inputs, protocol, code, and environment.

## Install and verify

Download the archive and checksum from [Release v0.1.1](https://github.com/Yiming-S/EEGLayoutLab/releases/tag/v0.1.1), using an account with access to this private repository. With [GitHub CLI](https://cli.github.com/) installed, run from the matching source checkout:

```sh
gh auth login
mkdir -p releases
gh release download v0.1.1 --repo Yiming-S/EEGLayoutLab \
  --pattern eeglayoutlab-data-v1.tar.gz \
  --pattern eeglayoutlab-data-v1.tar.gz.sha256 \
  --dir releases
(cd releases && shasum -a 256 -c eeglayoutlab-data-v1.tar.gz.sha256)
python3 scripts/data_bundle.py install releases/eeglayoutlab-data-v1.tar.gz
python3 scripts/data_bundle.py verify
```

Check the checksum before installing. Browser downloads require the same repository access; place both downloaded files in `releases/` to use these commands. The bundle tool operates on local files and uses only the Python standard library. An explicit `--root` can select another checkout. See the [source installation guide](source-installation.md) for the current Apple Silicon macOS setup.

Installation uses the destination checkout's manifest as the trust baseline. The archive manifest must match it byte for byte. The installer rejects members outside the inventory, path traversal, links, mismatched content, and conflicting files already present at the destination. A mismatch should be resolved by obtaining the matching archive or selecting the appropriate code/data version; do not edit the manifest to make an unknown file pass.

`verify` checks the installed payload against the inventory. It does not recompute FEM fields or prove the numerical assumptions that produced them. Keep the code version and data-manifest identity together when reporting a result.

## Export a matching bundle

From a checkout whose installed data verify successfully:

```sh
mkdir -p releases
python3 scripts/data_bundle.py export --output releases/eeglayoutlab-data-v1-export.tar.gz
```

The manifest determines the exported files. Export creates a local archive for the selected inputs and records; publishing it is a separate step. Complete historical calculation directories and new user jobs remain outside the bundle. Store published archives as release attachments and keep their inventory in Git.

## Why the relative paths matter

Current pointers under `results/v2/` identify exact files under frozen run and batch directories. The forward-bank loader also follows its report and run manifest to the source arrays. The native head loader reads the mesh location from [`ernie_fem_point_pilot.json`](../configs/ernie_fem_point_pilot.json), then finds the associated scalp mappings, vertices, and triangles.

Keep these paths intact. The application currently resolves inputs relative to the checkout, not an arbitrary external data directory. Installing through the bundle tool recreates the expected layout without changing the scientific files.

## New records and cache behavior

Application tasks save new requests, results, diagnostics, and cache metadata under `results/v2/`. Different workflows have separate directories, while the local host shares one computation slot. Changing an acceptance threshold reuses existing scores; changing a layout or scientific input requires matching computation identity.

The current identity checks include implementation bytes, input hashes, and, for native computations, installed runtime details and paths. Moving the checkout or rebuilding the environment can invalidate cache reuse. Historical records are still evidence of their recorded inputs; they are not automatically current results.

The data bundle preserves supplied records rather than rewriting their IDs, hashes, or protocols. Empty result folders can be created by subsequent jobs. User-generated records are not automatically deleted or added to the fixed data inventory.

## Reproducible comparisons

Record at least the layout coordinates and order, source/dictionary specification, head and bank identities, noise calibration and seed rules, metric definitions, search budget, code identity, and numerical environment. State whether scores are original frozen scores, a new fixed-layout evaluation, or a new search.

The production 30-condition fixed-area collection uses the 4,096 dictionary and 256 generation-source protocol. Separate 512-new-source validation belongs to another protocol and is not the default production score. Preserve this distinction in exported reports and comparisons.

Source attribution and data-specific terms are provided in [`data/SOURCES.md`](../data/SOURCES.md) and [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md). The Ernie-derived data retain their third-party attribution and noncommercial terms.
