# Data packages

Model data is shipped as separate, versioned packages, each with a SHA-256 manifest ([design 0001](design/0001-local-first-architecture.md), decision 7). The code is in [`src/eeglayoutlab/data`](../src/eeglayoutlab/data); the commands are `eeglayoutlab data …`.

| Package | Kind | Contents |
| --- | --- | --- |
| `base` | base | The files of the data bundle in [`data/manifest.json`](../data/manifest.json): the Ernie FEM mesh, the frozen forward bank, candidate geometry, scalp mappings, source arrays and the supplied result records |
| `scalp-node-table` | scalp-node-table | `results/v2/current_scalp_node_table.json` and the nominal table it names (`manifest.json`, `index.npz`, `rows.npy`) |
| `scalp-node-table-<scenario>` | conductivity-scenario-table | `results/v2/scalp_node_table_scenarios/<scenario>/current.json` and its table |
| `head-<id>` | head | `results/v2/heads/<id>/`: `package.json`, the four arrays, `table.json`, `stages.json` and the head's table |

A package's files keep their paths relative to the scientific root, because those paths and the file bytes enter scientific identities (`webapp/server/runtime/scientific-context.mjs`). Packaging therefore never changes a file: a result computed from installed files has the same identity as one computed from the originals.

## Manifest

Schema `eeglayoutlab-data-package/1`, one JSON file per package version:

| Field | Meaning |
| --- | --- |
| `name`, `version`, `kind` | Package name, `MAJOR.MINOR.PATCH`, and one of the four kinds above |
| `accepts_code` | Code versions the package works with, for example `>=0.2.0,<1.0.0`; `install` refuses others unless `--any-code-version` is given |
| `requires` | Packages used together with this one (a table needs `base`; a scenario table also needs the nominal table) |
| `files` | Every file: root-relative `path`, `size` and `sha256`. Paths are plain POSIX paths under `data/external/`, `results/v2/` or `data/SOURCES.md` |
| `total_size`, `content_sha256` | Sum of the file sizes, and the SHA-256 of the sorted `<sha256> <size> <path>` lines: the identity of the file set, independent of the version label |
| `licenses`, `notes` | Source, licence, URL and the files each licence applies to; open questions |
| `archive` | When the package is published as an archive: its file name (`<name>-<version>.tar`), size and SHA-256. The archive sits beside the manifest |

The archive is an uncompressed pax tar with the files in manifest order, fixed owner, mode and time, so the same files always give the same bytes. The tables are binary arrays that compress little.

## Commands

```bash
eeglayoutlab data list
eeglayoutlab data verify [NAME ...]
eeglayoutlab data install https://…/head-ixi002-1.0.0.json
eeglayoutlab data install ./head-ixi002-1.0.0.json --from-root /path/to/scientific/root
eeglayoutlab data compose [NAME ...] [--root R] [--copy] [--dry-run]
eeglayoutlab data remove head-ixi002
```

- **Data directory.** `EEGLAYOUTLAB_DATA_DIR` or `--data-dir`; otherwise `~/Library/Application Support/EEGLayoutLab` on macOS and `$XDG_DATA_HOME/eeglayoutlab` (default `~/.local/share/eeglayoutlab`) on Linux. A package is installed in `packages/<name>/<version>/`, with `manifest.json` and the files at their root-relative paths. One version of a package is installed at a time.
- **install** reads the manifest from a path or an `https://` or `file://` address. It reads the archive beside it as a stream (redirects only to `https://`), so a download is never stored twice. Every member must be a regular file listed in the manifest, listed once. Each file's size and SHA-256 and the archive's own size and SHA-256 are checked. The package is written to a staging directory and renamed into place only when everything matches, so a failed or interrupted install leaves nothing. Installed files are read-only. `--from-root` copies the files from a scientific root instead, with the same checks; this installs packages published without an archive. Free disk space is checked first.
- **verify** recomputes the size and SHA-256 of every installed file, and reports missing files, files that are not regular files and files the manifest does not list. It exits 1 when anything differs.
- **compose** places the files of installed packages in a scientific root; see [Using installed packages](#using-installed-packages).
- **remove** renames the package directory away, then deletes it. Files that a composed root still links keep their space until the root's links are deleted; `remove` says how many there are.

## Building packages (maintainers)

```bash
eeglayoutlab data build --root /path/to/scientific/root --out packages/ \
  --archive base --archive head-ixi002
```

`build` finds the packages of a root with the checks the application applies:

- `base`: every file of `data/manifest.json`, with the size and SHA-256 recorded there;
- tables: the pointer's `manifest_sha256` must match the table manifest;
- heads: all six package files must exist, `package.json` must name the head and record the hashes of its four arrays, and `table.json` must match its table.

A head that is incomplete is listed in the report with the reason and gets no manifest. `build` writes:

- one manifest per complete package;
- the archives asked for with `--archive`, each file checked against its manifest while it is written;
- `catalog.json`;
- `report.md`, with exact archive sizes (written archives are measured; the others are computed from the manifest) against the Zenodo record limits.

The report also names every JSON file that contains a path in a home directory (`/Users/…`, `/home/…`). Such paths are published as they are or the package is rebuilt; editing the file would change the package's identity and its table's.

## Using installed packages

The service and the workers do not read the data directory. They read files at root-relative paths under the scientific root. The root also holds the code and the configuration: it is a checkout, or, in an application installed with conda, the tree the package installs at `$PREFIX/share/eeglayoutlab/root` ([design 0002](design/0002-installed-scientific-root.md)). `compose` puts the files of installed packages at their paths in that root:

```bash
eeglayoutlab data compose                       # every installed package, into the default root
eeglayoutlab data compose head-ixi002 --root R  # one head and the packages it needs, into R
```

- **Root.** `--root`, else `EEG_REPOSITORY_ROOT`, else the checkout that holds the package, else the installed root of the environment, as for the service. The root must contain `configs/`.
- **Writable root.** The root, and `results/v2` (or `results`) when it exists, must be writable; records are written there too. Otherwise `compose`, like `serve`, exits 2 before it compares or writes anything. An installation the user cannot write is not supported: the message says to create a user environment, for example with Miniforge or micromamba in the home directory.
- **Packages.** Every installed package, or the ones named plus the installed packages they need. A package that needs one that is not installed is reported.
- **Hard links.** Each file is a hard link to the installed file when the data directory and the root are on one file system, so the data takes no extra space. Otherwise, or with `--copy`, the file is copied, checked against its size and SHA-256 and renamed into place.
- **Read-only.** Installed files and their links are read-only. A program that rewrote one in place would fail instead of changing the installed package. One that writes a new file and renames it over the old one replaces only the link.
- **Conflicts.** Nothing is written while any path conflicts: a path that holds different bytes, a directory or a symbolic link, or a path below a symbolic link. A file already in place with the manifest's bytes is left alone, such as the tracked `data/SOURCES.md` or the files of an earlier run. Running `compose` again therefore completes an interrupted run. `--dry-run` reports the counts and conflicts and writes nothing.
- **Checks.** `compose` checks the size of each installed file. `verify` checks the SHA-256; for a hard-linked file that is also a check of the file in the root.

Because packaging never changes a file, a result computed from a composed root has the same identity as one computed from the original files. A code release does not yet declare the package versions it accepts; for now the package side's `accepts_code` is the only version check.

## Licences

| Package | Data licence |
| --- | --- |
| `base`, `scalp-node-table`, `scalp-node-table-<scenario>`, `head-ernie_xh` | Derived from the SimNIBS example dataset v4.1 (Ernie): CC BY-NC 4.0, © SimNIBS developers 2024. `data/SOURCES.md` in `base` is the project's own declaration |
| `head-ixi…` | The head (segmentation, scalp, sources, admissibility and table) is derived from one IXI subject: CC BY-SA 3.0. `mapping.npz` maps Ernie scalp positions onto that head and is Ernie-derived: CC BY-NC 4.0 |

Each manifest records these terms per file. The IXI head packages combine ShareAlike (IXI) with NonCommercial (Ernie) terms in one package. A licence for the published package, or a split of `mapping.npz` into a separate package, is to be decided before the IXI heads are published. The code that produced the files is GPL-3.0-only; the files carry the data licences.

## Sizes and publication

Zenodo accepts 50 GB and 100 files per record by default; higher quotas are granted on request (Zenodo's [upload documentation](https://help.zenodo.org/docs/deposit/create-new-upload/) and [policies](https://about.zenodo.org/policies/)). The sizes of the packages of the maintainer's installation (built on 2026-11-23):

| Packages | Archive size |
| --- | ---: |
| `base` (21 files) | 0.41 GB |
| `scalp-node-table` | 1.40 GB |
| `scalp-node-table-skull_x0.5`, `scalp-node-table-skull_x2` | 1.40 GB each |
| `head-ernie_xh` | 1.40 GB |
| `head-ixi002`, `012`, `013`, `015`, `017`, `019`, `020`, `035`, `230`, `231` | 1.11–1.27 GB each, 11.94 GB together |
| All 15 packages | 17.93 GB in 30 files with their manifests |

The largest package is 2.8 % of a record, and all 15 together are 36 % of one record and 30 of its 100 files. Each package can therefore be its own Zenodo record (one version, one DOI), or a data release can put every package in one record. On the Mac, the archives of `base` and `head-ixi002` were installed with `eeglayoutlab data install` and passed `verify`. After one byte of an installed array was changed, `verify` reported that file and exited 1. On a physical Linux machine, the archives of `base`, `scalp-node-table` and the eleven heads of example 3 were installed and verified. `compose` then placed their 134 files in a checkout without data as hard links, in 0.07 s. The examples matched their expected scores ([source installation](source-installation.md#on-a-physical-machine-2026-11-23)). Except for timings, the 19,520 numbers in their results were identical to those of a root whose data had been copied in. Heads `ixi014` and `ixi016` are incomplete and were not packaged.

Head packages built before 2026-11-23 recorded the absolute path of a build input in the maintainer's home directory in `package.json` (`inputs`; three paths for `head-ernie_xh`, one for each IXI head). All eleven heads were rebuilt with their inputs recorded by path under the root. Only the recorded paths, code hashes, build timings, the package SHA-256 and the table ID changed; every table's `rows.npy` and `index.npz` is byte-identical to the earlier build. `build` on the rebuilt heads reports no home-directory path in any package. Those eleven packages were installed with `--from-root`, composed into the root of a conda environment and verified there, and example 3 matched `expected.json` exactly ([recipe draft](../packaging/conda-forge/eeglayoutlab/README.md)). Packages for publication are built from the rebuilt heads.
