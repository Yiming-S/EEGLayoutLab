# Data and reproducibility

The application code and the numerical data bundle are separate deliverables. [`data/manifest.json`](../data/manifest.json) is the checked-in inventory for the supported bundle. Each entry specifies a repository-relative path, byte count, and SHA-256. The manifest schema is `eeglayoutlab-data-bundle/1`.

## What is included

The bundle supplies the exact files needed by the current application: frozen forward-bank and candidate geometry arrays; source arrays and their manifest; surface-admission data; the Ernie volume mesh and exterior scalp mappings; selected current result reports and pointers; and declared seed records. Its 21 files total 406,226,293 bytes (387.41 MiB), including the source declaration. Consult the manifest for the exact members of this release.

The web application's compact result exports and anatomical display buffers are versioned separately under [`webapp/public/`](../webapp/public/). Display buffers do not substitute for the volume mesh used by native computation.

The bundle is limited to the application inputs and supplied records. Installed runtimes, `node_modules`, complete historical calculation directories, and newly generated user jobs are distributed or stored separately. Reproducing a wider research campaign requires that campaign's inputs, protocol, code, and environment.

## Install and verify

Download the archive and checksum from [Release v0.1.2](https://github.com/Yiming-S/EEGLayoutLab/releases/tag/v0.1.2), using an account with access to this private repository. With [GitHub CLI](https://cli.github.com/) installed, run from the matching source checkout:

```sh
gh auth login
mkdir -p releases
gh release download v0.1.2 --repo Yiming-S/EEGLayoutLab \
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

## Optional scenario tables and head packages

Conductivity-scenario tables (`results/v2/scalp_node_table_scenarios/`) and head packages (`results/v2/heads/`) are generated outputs of `scripts/build_scalp_node_table.py` and `scripts/build_head_package.py`. They are not members of `data/manifest.json` or of the data bundle. Each records its own input hashes, code hashes and source terms in its manifest. A head package records the code hash of each build stage, so a package rebuilt after a code change has a new SHA256 and its table must be rebuilt. After the builder code last changed, the nominal table, both scenario tables and five head tables (`ernie_xh`, IXI002, IXI012, IXI013, IXI230) were rebuilt. Their `rows.npy` and `index.npz` matched the previous builds byte for byte. Only the recorded code hashes, build timings and, for heads, the package SHA256 and table ID changed. Each published table passes `build_scalp_node_table.py --verify`. Builds run on the Mac; `charm` needs Rosetta 2 on Apple silicon and peaks at 34–38 GB (see [server deployment](server-deployment.md#building-head-packages)).

- **`ernie_xh`.** Built from the full SimNIBS example dataset v4.1: the same `ernie.msh` bytes as the bundle, plus that dataset's central and registered sphere surfaces. It carries the dataset's CC BY-NC 4.0 terms.
- **`ixi*` packages.** Derived by SimNIBS `charm` from the [IXI dataset](https://brain-development.org/ixi-dataset/) under CC BY-SA 3.0 (attribution: "IXI dataset, https://brain-development.org/ixi-dataset/"). Redistributing them is subject to those share-alike terms.
  - Archives: `IXI-T1.tar`, MD5 `34901a0593b41dd19c1a1f746eac2d58`; `IXI-T2.tar`, MD5 `e3140d78730ecdd32ba92da48c0a9aaa`.
  - Subjects: at each site, the lowest-numbered subjects that have both T1 and T2. Guys: IXI002, IXI017, IXI019, IXI020. HH: IXI012, IXI013, IXI015. IOP: IXI035, IXI230, IXI231.
    - IXI014 was skipped before any build: its T2 has 28 slices of 5 mm.
    - IXI016 is not published. Its `charm` run finished, but the package failed source QA: 15 cortical sources in the right parietal lobe lie in skull labels, up to 4.2 mm from grey matter, over the 3 mm limit. IXI020, the next Guys subject, replaces it.
  - Demographic data were not used to select them.
  - IXI002 and IXI012 first failed in `charm`'s spherical registration (`CAT_Surf2Sphere`, Rosetta 2 not installed), before the surface-based label update. Their m2m folders were continued with `charm <id> --surfaces --mesh`, and the builder adopts them with `--charm-resume` (`charm_action: "adopt"`).
  - IXI015, IXI017, IXI019, IXI020, IXI035 and IXI231 are built with `--charm-forceqform`. In their headers the qform and sform matrices differ by rounding, at most 2.3e-5 per entry. `charm` refused IXI017, IXI019, IXI035 and IXI231 without that option; IXI015 and IXI020 were built with it from the start. Their `package.json` records `charm_forceqform: true`.

## Recorded EEG

Recordings stay where they are. `eeg-summary` reads a file in place and writes only its channel covariance, the processing record and the file's SHA-256. Prior fits and channel subsets read summaries, and the coordinates page computes subsets in the browser without uploading anything. A prior file lists each input by label, file name and SHA-256, so a fit can be checked against the original recordings by whoever holds them.

The validation in [Model and metrics](model-and-metrics.md#data-derived-source-prior) used public datasets that are not distributed with this repository or the data bundle. Their summaries, priors and subsets were computed with the command line on the machine holding the recordings.
