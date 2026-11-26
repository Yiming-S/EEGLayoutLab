# 0002 — The scientific root of an installed application

- **Status:** accepted on 2026-11-23 (recommendation A and the three decisions below), amended on 2026-11-26 for the numerical closure of `conda-meta`, `llvmlite`'s `egg-info` metadata and virtual environments ([phase 3](0001-phase-3-plan.md), U16 and slice 3). Changes 1, 2, 3 and 4 of the table below (the installed root, the environment's interpreter, the environment identity rows and the refusal of a read-only R) are implemented; the others are not yet
- **Date:** 2026-11-23
- **Design:** [0001 — Local-first application with a Python service](0001-local-first-architecture.md), migration table, phase 3

## Question

Where is the scientific root R when EEGLayoutLab is installed from conda-forge and is not run from a checkout?

Phase 3 ends when a user, on a fresh Mac and a fresh Linux machine, can:
1. install from conda-forge;
2. run `eeglayoutlab data install`;
3. run the examples and match the expected scores.

Today every part of the application takes R to be a checkout. A conda package installs Python packages into `site-packages`, where none of R's root-relative paths exist.

## What R holds today

The table below was compiled from the Node host, the CLI (`webapp/scripts/eeglayoutlab.mjs`), the workers and the Python port of phase 2 (slice 3). The identities are:
- D: design evaluation; the editor (E), reception v2 (V2) and studies (St) contain it;
- V1: reception v1;
- Rad: radius search.

| Kind | Root-relative paths | Use | In identities |
| --- | --- | --- | --- |
| Science code | `src/compact_eeg/*.py` (every top-level file, found by listing the directory), `src/compact_eeg/workflows/*.py` | Imported by the workers | Path strings and bytes: Rad (all top-level files), D, E, V1, V2 (fixed lists) |
| Worker entry points | `scripts/design_evaluation.py`, `electrode_editor.py`, `run_local_radius_compute.py`, `run_source_reception*.py`, `source_reception*.py`, `reception_forward_provider.py`, `inspect_*`, `runtime_identity_watch.py`, `export_history_coordinates.py`, `eeg_data.py` | Run as `R/scripts/<name>.py` | Path strings and bytes in D, E, V1, V2, Rad |
| Configuration | `configs/ernie_fem_point_pilot.json`, `configs/conductivity_scenarios.json`, `configs/single_head_optimization.json`; `configs/runtime/manifest*.json` and `data/manifest.json` for delivery headers | Read | D, Rad (bytes) |
| Worker inputs in the interface tree | `webapp/public/models/ernie/source-roi*.json`, `webapp/public/data/ernie-mni-mapping.json`, `webapp/public/data/single_head_optimization.json` | Read | D and Rad with a data prior; V2 with a region definition |
| Model data | `data/external/…`, `results/v2/current_*.json` and the files they point to, `results/v2/scalp_node_table*/…`, `results/v2/heads/…` | Read; pointer contents used verbatim as digest keys | D, E, V1, V2, St, Rad |
| Managed runtime | `.runtime/simnibs-4.6.0/` or `.runtime/compute-linux-64/`: `bin/python`, `conda-meta/*.json`, selected `site-packages/*.dist-info/METADATA` | Runs the workers | Rows only when the interpreter is exactly `R/.runtime/<name>/bin/python`; the absolute interpreter path is D's `python` |
| Records | `results/v2/{local_app_jobs, design_evaluation_jobs, electrode_editor_jobs, source_reception_jobs, source_reception_v2_jobs}/<key>/…`, `design_evaluation_jobs/electrode_annotations/` | Written by the hosts and workers | Record paths enter E and V2 (`provenance.file`, `design_result`) |
| Worker caches | `results/v2/reception_forward/…` | Written by the workers | Their own keys, which contain absolute runtime paths |
| Node queue | `results/web-service/` unless `EEG_QUEUE_DIRECTORY` is set | Written by Node only | None |
| Static interface | Python: `R/webapp/dist/client`; Node: `<code folder>/webapp/dist` | Served | None |

These rules decide where R can be:

- **The workers derive R from their own location.**
  - The entry points prepend `Path(__file__).resolve().parents[1] / "src"` to `sys.path`.
  - `compact_eeg/workflows/paths.py` sets `PROJECT_ROOT = Path(__file__).resolve().parents[3]`, which design evaluation and the editor use without a `--root`.
  - The code, the data and the records must therefore be one physical tree.
  - A symbolic link for `scripts` or `src` would move the data root that those workers read.
- **Every digested input must lie inside the real path of R.** Input integrity resolves each input with `realpath` and refuses any path outside R ("输入文件超出本项目", input file outside this project). An interpreter or runtime outside R therefore contributes no file rows; a symbolic link from R to it fails.
- **The absolute R reaches keys only through runtime paths.** These are D's `python` when it is the managed runtime, V2's numerical-runtime digest and the workers' forward-cache keys. Root-relative strings enter keys verbatim.
- **Nothing needs git.** Only `scripts/release_manifest.py` and the macOS runtime bootstrap call `git`. The Python service's default root, however, requires `pyproject.toml` and `src/compact_eeg`.
- **Without a managed runtime** the worker interpreter is `EEG_COMPUTE_PYTHON` or the literal `python3` from `PATH`. An `eeglayoutlab` started from an environment that is not activated would run its workers with another interpreter.

## Requirements

1. **Same rules for the same files.** A checkout keeps its keys (0001, decision 8). The installed form computes identities with the same rules, so the same files give the same file digests. It may add identity rows only where a checkout has none.
2. **The code that runs is the code that is hashed.** Since the workers find R from their own location, the hashed `src/` and `scripts/` must be the files they execute.
3. **Records stay at `R/results/v2/*_jobs`** until 1.0 ([phase 2 plan](0001-phase-2-plan.md), U1), so R must be writable.
4. **Data packages are placed with `eeglayoutlab data compose`** ([data packages](../data-packages.md)), as hard links where possible.
5. **Upgrades keep the cache** when a calculation's inputs did not change, and two installed versions never share files that one of them changes.
6. **No administrator rights** on either platform.
7. **The numerical environment is pinned and enters identities,** as the managed runtimes are today (0001, decision 10: numpy, scipy and cortech are pinned per release).

## Options

| | A. Root inside the environment | B. Per-user root with a managed runtime | C. Checkout only until 1.0 | D. Logical paths |
| --- | --- | --- | --- | --- |
| Layout | The package installs the root tree at `$PREFIX/share/eeglayoutlab/root`. The environment's own interpreter runs the workers | `eeglayoutlab setup` copies the root tree into the data directory and builds `R/.runtime/<lock>` from the lock files, as `bootstrap_runtime.py` does | `git clone` plus `bootstrap_runtime.py`, as today; conda-forge after 1.0 | Identities name files by package and module, not by root-relative path; code stays in `site-packages`; R holds only data and records |
| Checkout keys | Unchanged | Unchanged | Unchanged | All change: an identity change |
| Installed keys | Stable across `conda update`: R and the interpreter path keep their spelling | Stable while R is kept; code must be synchronised into R on upgrade | — | — |
| Runtime in identities | New rows from the environment (below), installed form only | The existing managed-runtime rows | Existing rows | To be designed |
| Downloads and disk | One conda install, about 80 MB of package beside its dependencies | The conda environment and a second runtime of 0.7–1.3 GB, downloaded at setup | Today's | — |
| Upgrades | `conda update` replaces the code; records and composed data stay | A version check, a copy of the new tree, and a runtime rebuild when the lock changes | `git pull` | — |
| Two versions side by side | Two environments, two roots; data shared read-only through the store | Needs one root per environment, so the same as A with more parts | Two checkouts | — |
| Records when the environment is removed | Removed with it | Kept | Kept | Kept |
| Fits 0001 | Phase 3 as planned | Phase 3, with an installer of its own | Moves conda-forge after phase 4 | Only at 1.0, together with moving `compact_eeg` into `eeglayoutlab/core` |

A per-user root that holds a copy of the code but uses the environment's interpreter (A's runtime with B's location) needs the same synchronisation as B, and one root per environment. It keeps records when an environment is removed, but adds an installer step that A does not need.

## Recommendation: A, the root inside the environment

### Layout

```text
$PREFIX/
  bin/python, bin/eeglayoutlab          the environment (numpy, scipy, numba, cortech, …)
  lib/python3.11/site-packages/eeglayoutlab/   the service, CLI, data commands
  share/eeglayoutlab/root/              R
    src/compact_eeg/…                   identical to the checkout of the same version
    scripts/*.py
    configs/…
    data/{manifest.json, SOURCES.md, README.md}
    webapp/public/…                     worker inputs and interface data
    webapp/dist/client/…                the built interface
    examples/…
    data/external/…, results/v2/…       placed by eeglayoutlab data compose (hard links)
    results/v2/*_jobs/…                 records, written at run time
```

- **Package contents.** The tree under `root/` is the checkout's files at the same relative paths, with nothing renamed. It is about 23 MB plus the 54 MB interface. `compact_eeg` is installed only there, not in `site-packages`, so exactly one copy exists and it is the copy that is hashed and run. The service does not import `compact_eeg`.
- **Interpreter and environment.** The `eeglayoutlab` package goes to `site-packages`. The recipe pins the numerical packages to the versions of the Linux lock (numpy 2.3.0, scipy 1.17.1, numba 0.64.0, llvmlite 0.46.0, nibabel 5.3.3, cortech 0.1) on both platforms. The Mac form has no SimNIBS, like the Linux runtime.
- **Writable environment.** A user environment (Miniforge, Mambaforge or micromamba in the home directory) is writable. Records written there are not files of the package, so `conda update` and `conda remove eeglayoutlab` leave them. `conda env remove` deletes them with the environment.
- **Read-only prefix.** When the prefix is not writable, for example a system-wide installation, `eeglayoutlab` stops with the instruction to create a user environment.

### Rules

- **`repository_root()`**: `--root`, else `EEG_REPOSITORY_ROOT`, else the checkout that contains the package, else `<sys.prefix>/share/eeglayoutlab/root` when it holds `src/compact_eeg`. The default is the real path, as for a checkout. `serve`, `data compose`, the examples and the workers all find R this way.
- **Worker interpreter.** In the installed form, when no managed runtime exists under R and `EEG_COMPUTE_PYTHON` is not set, it is `<sys.prefix>/bin/python`, the absolute path of the environment's interpreter, never `python3` from `PATH`. That string becomes D's `python`, as a managed interpreter's path does today, so it is stable across `conda update`.
- **Environment rows.** When the interpreter is the environment's own and R is the installed root (U17), the identity adds the files that the Linux managed runtime contributes, taken from the environment instead of `R/.runtime/compute-linux-64`:
  - `environment:bin/python`, the interpreter;
  - `environment:conda-meta/<name>.json` for the numerical closure only (python, numpy, scipy, numba, llvmlite, nibabel, cortech, the BLAS packages and their dependencies from `depends`; U16), never `eeglayoutlab`'s own record or service-only packages, so `conda update eeglayoutlab` and unrelated `conda install` commands keep existing D, E, V2 and St keys;
  - `environment:lib/pythonX.Y/site-packages/<dist>/METADATA` of cortech, nibabel, numba, numpy and scipy, and `llvmlite`'s `*.egg-info/PKG-INFO` (conda-forge's `llvmlite` ships an `egg-info` directory rather than `dist-info`), with `X.Y` taken from the running interpreter.

  The row keys are prefix-relative paths under `environment:`, so they cannot collide with checkout rows. Input integrity accepts these files inside the real path of `sys.prefix`, and only for `environment:` rows when the environment base is given. A checkout never produces these rows, so its keys do not change.
- **Data.** `eeglayoutlab data install` fills the data directory and `eeglayoutlab data compose` links the packages into R. Hard links work because a user environment and the data directory are normally on one file system; otherwise the files are copied. Several environments share one installed copy of the data.
- **Examples.** `eeglayoutlab examples run` (decision U5 moves the scientific commands to phase 3) reads `R/examples` and writes to a directory the user names.
- **Virtual environments (PyPI).** A wheel can install the same root tree as data files under `sys.prefix/share/eeglayoutlab/root`, giving the same R and `default_repository_root()` rule. However, a `venv` has no `conda-meta` directory and its `bin/python` resolves outside `sys.prefix` to the base interpreter, so the PyPI form needs its own environment-row and containment rule when PyPI distribution is added after phase 4.

### What changes, and where

| Change | Where | When |
| --- | --- | --- |
| Installed-root fallback in `default_repository_root` | `src/eeglayoutlab/jobs/runtime.py` | After slice 10, before the first conda build |
| Environment interpreter as the default worker interpreter in the installed form | `jobs/runtime.py` (`managed_python`, the native and compute choices) | Same |
| Environment rows and their integrity base | `jobs/identity.py`, `jobs/integrity.py`; the Node host is not shipped in the installed form, so it needs no counterpart | Same; installed form only |
| Refusal of a read-only R | `cli/main.py` (`serve`, `data compose`) | Same |
| `eeglayoutlab examples run` | `cli/` | Phase 3 (U5) |
| The recipe: build the interface (Node at build time only), install the root tree and the package, pin the numerical packages, test with `eeglayoutlab data verify` on a fixture and the fast tests | `packaging/conda-forge/eeglayoutlab/` | Phase 3 |
| CI job that installs the built package into a fresh environment on both platforms and runs the examples with data packages from the cache | `.github/workflows/` | Phase 3 (0001, decision 11) |

No change touches a checkout's keys. The installed form's keys are new because its interpreter path and environment rows are new, as every new installation's keys are today. Code digests equal a checkout's of the same version, because the files and their relative paths are the same.

### Consequences

- **Records live in the environment until 1.0.** Removing the environment removes the library of computed results and the caches, but not the workspaces, which hold the user's own copies (0001, decision 7). At 1.0 the records move to the per-user cache directory with the identity change (option D), and the environment then holds only code.
- **Reception v2 needs SimNIBS.** Its numerical-runtime digest requires a SimNIBS runtime (MUMPS and the `simnibs` package). The installed form has none, as the Linux runtime has none today, so reception v2 is not available there.
- **Hard links into the package cache.** conda links package files from its package cache. Code files under R are such links, and they are never written: the workers do not write bytecode, and records are new files. A program that rewrote a code file in place would change the cache copy, as with any conda package.

## Decisions

Confirmed on 2026-11-23:

1. **Records in the environment until 1.0** (consequence above), or a per-user root (the variant of A and B) that keeps them when the environment is removed, at the price of an installer step and synchronising code on every upgrade. Decided: in the environment.
2. **Exact pins on both platforms** to the Linux lock's versions. Decided: yes; a later upgrade gets its own projection check (0001, decision 10).
3. **Read-only prefixes are unsupported.** Decided: yes, with the error message described above.

## Findings for phase 2

The inventory found these differences between hosts or entry points. The [phase 2 plan](0001-phase-2-plan.md) does not list them:

- **CLI interpreter.** The CLI runs every worker, the radius search included, with the native interpreter, and ignores `--python` when a managed runtime exists. The server runs the radius search with the compute interpreter. Off macOS, with `EEG_COMPUTE_PYTHON` set, a CLI search and a server search can therefore get different radius keys. The Python CLI (phase 3, U5) has to pick one rule.
- **Static interface location.** Node serves `<code folder>/webapp/dist`; the Python service serves `R/webapp/dist/client`. They differ when R is not the checkout that contains the code.
- **Library listing without code.** If `R/src/compact_eeg` is missing, Node's library listing fails as a whole, because the radius code identity is computed outside the error handling in `local-data-library.mjs`.
