# Data and reproducibility

The application code and the numerical data bundle are separate deliverables. [`data/manifest.json`](../data/manifest.json) is the checked-in inventory for the supported bundle. Each entry specifies a repository-relative path, byte count, and SHA-256. The manifest schema is `eeglayoutlab-data-bundle/1`.

## What is included

The bundle supplies the exact files needed by the current application: frozen forward-bank and candidate geometry arrays; source arrays and their manifest; surface-admission data; the Ernie volume mesh and exterior scalp mappings; selected current result reports and pointers; and declared seed records. Consult the manifest for the exact members of this release.

The web application's compact result exports and anatomical display buffers are versioned separately under [`webapp/public/`](../webapp/public/). Display buffers do not substitute for the volume mesh used by native computation.

The bundle does not include an installed Python runtime, `node_modules`, a complete offline experiment archive, or a user's future job history. It does not imply that every research experiment mentioned by a retained record can be rerun with this application-focused handoff alone.

## Install and verify

Run from the repository root:

```sh
python3 scripts/data_bundle.py install releases/eeglayoutlab-data-v1.tar.gz
python3 scripts/data_bundle.py verify
```

Use the actual archive location if it differs. No public download URL is assumed. The tool operates on local files and uses only the Python standard library. An explicit `--root` can select another checkout.

Installation uses the destination checkout's manifest as the trust baseline. The archive manifest must match it byte for byte. The installer rejects members outside the inventory, path traversal, links, mismatched content, and conflicting files already present at the destination. A mismatch should be resolved by obtaining the matching archive or selecting the appropriate code/data version; do not edit the manifest to make an unknown file pass.

`verify` checks the installed payload against the inventory. It does not recompute FEM fields or prove the numerical assumptions that produced them. Keep the code version and data-manifest identity together when reporting a result.

## Export a matching bundle

From a checkout whose installed data verify successfully:

```sh
mkdir -p releases
python3 scripts/data_bundle.py export --output releases/eeglayoutlab-data-v1-export.tar.gz
```

The manifest determines the exported files. This command does not turn the entire `results/` directory into a release, publish an archive, or include newly generated user jobs automatically. The local `releases/` archive is a handoff artifact; it does not need to be committed to the source repository.

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
