# 0003 — The identity change at 1.0

- **Status:** proposed
- **Date:** 2026-11-23
- **Design:** [0001 — Local-first application with a Python service](0001-local-first-architecture.md), decisions 3, 7, 8 and 9, phase 4; [0002 — The scientific root of an installed application](0002-installed-scientific-root.md), option D

## Question

0001 keeps scientific cache keys unchanged until 1.0. It reserves the move of `compact_eeg` into `eeglayoutlab/core` for 1.0 as a deliberate identity change (decision 3), but leaves open whether to make the move (open question "Rename at 1.0"). It also stores results in a per-user cache directory (decision 7), which phase 2 postponed to 1.0 ([phase 2 plan](0001-phase-2-plan.md), U1). 0002 deferred one more part to 1.0: identities that do not depend on the layout of the files (its option D). This note designs that change as one change, so that 1.0 breaks cache reuse once and never again by accident.

## The identity today

A design-evaluation key is `sha256(JSON.stringify({request, identity}))`. The identity is:

```text
{ schema: "design-evaluation-cache/1",
  digests: { "<root-relative path>": "<sha256>", ... },   in a fixed order
  python:  "<interpreter string>",
  threads: 1,
  runtime: { ... } }                                       off macOS: python version, system, machine, numpy, scipy
```

The other identities (radius search, editor, reception v1 and v2, studies) follow the same pattern or contain this one. The [0002 inventory](0002-installed-scientific-root.md#what-r-holds-today) lists every input. Seven properties tie keys to one installation and one layout:

| # | Property | Effect |
| --- | --- | --- |
| P1 | Code enters by root-relative path (`src/compact_eeg/metrics.py`) in hand-kept lists (`project-paths.mjs`, `DATA_PRIOR_FILES`, the reception code map), or as every top-level file (radius) | Moving or renaming a file changes keys. A module missing from a list is not hashed. A new top-level file changes radius keys |
| P2 | Data enters by pointer file (`results/v2/current_*.json`), whose contents are paths used verbatim as digest keys | The same data at another path is a different identity |
| P3 | The runtime enters as rows only when the interpreter is exactly `R/.runtime/<name>/bin/python` (B5, B6). Otherwise it enters as the interpreter string and, off macOS, a five-field fingerprint (B9). 0002 adds environment rows for the installed form | Three rules for one question. The rows hash every `conda-meta` record, so an unrelated package update changes keys. On macOS outside a managed runtime nothing of the runtime enters, so a numpy or scipy update keeps the keys ([recipe draft](../../packaging/conda-forge/eeglayoutlab/README.md)) |
| P4 | Absolute paths enter as the interpreter path (`python`), V2's numerical-runtime digest and the workers' forward-cache keys | Two installations never share a key, even with identical code, data and runtime |
| P5 | Records live in `R/results/v2/*_jobs` (U1), and record paths are literal strings inside the E and V2 identities (B20) | Records cannot move without changing keys |
| P6 | Workers find R from their own file location | Code, data and records must be one tree (0002) |
| P7 | Hashes of JSON text, file bytes and plain strings are mixed under one map (B23) | Each kind needs its own helper to stay equal |

## Requirements

1. **Same numbers.** Every scientific number of 0.x and 1.0 is identical for the same request, code logic, data and runtime on the same platform.
2. **Keys change once, in planned ways only.** After 1.0 a key depends only on:
   - the normalized request;
   - the code that computes it;
   - the data it reads;
   - the numerical runtime;
   - the platform.

   It never depends on where these are installed.
3. **Nothing is missed.** A change to any file a calculation executes or reads changes its key, and a test enforces this.
4. **Old results stay readable** (decision 8). Nothing is rewritten.
5. **Extensions follow the same rules** (decision 9).

## Design

### 1. Code: by module, from the import closure

| Option | Rule | Assessment |
| --- | --- | --- |
| a | Hand-kept lists, as today, with module names instead of paths | Keeps P1's risk of a missing module |
| b | One digest over every file of `eeglayoutlab.core` and the worker modules | Never misses a module, but any change anywhere invalidates every cache, editor fixes included |
| c | Per workflow, the import closure within the project's packages, computed at build time and recorded in a generated manifest shipped with the package; a test fails when the recorded closure differs from the computed one | Fine-grained and complete; the guard of B11, made mechanical |
| d | Hashes from the installed distribution's `RECORD` or conda's `paths.json` instead of reading files | Absent or stale in checkouts and editable installs; can be edited. Not trusted for identity |

**Recommendation: c.**
- The code identity of a workflow is `{module name: sha256 of its bytes}`, sorted by module name. It covers every module of `eeglayoutlab` (including `eeglayoutlab.core`, the former `compact_eeg`) that the workflow's worker imports, directly or indirectly.
- Third-party modules belong to the runtime (section 3), not here.
- Reading the files at service start costs a few milliseconds; the digests are memoized per file size and modification time.
- **Extensions.** An extension enters as its distribution name and version plus its own module closure and its declared data files, under its entry-point name.

### 2. Data: by package content

| Option | Rule | Assessment |
| --- | --- | --- |
| a | File digests under package-relative paths | Exact, but repeats per request what the package manifest already states |
| b | `{package name: content_sha256}` for every package the calculation reads | The manifest's `content_sha256` already covers every file's path, size and SHA-256 |
| c | Package name and version | A version label can be reused for different bytes. Not an identity |

**Recommendation: b.**
- The data identity is `{"base": "<content_sha256>", "scalp-node-table": "…", "head-ixi002": "…"}`, listing only the packages the request uses.
- A scenario table is `scalp-node-table-<scenario>` and a head is `head-<id>`: the request field selects the package, and its content hash enters.
- The version label stays out, so republishing identical files under a new version keeps the keys.
- The service checks each installed package against its manifest once, keyed by device, inode, size and modification time of every file. It refuses a package that does not match, as `verify` does.
- Pointer files remain inside the packages. Their bytes are covered by the content hash, and they no longer supply digest keys (P2).

### 3. Runtime: by distribution, version and build

| Option | Rule | Assessment |
| --- | --- | --- |
| a | Every `conda-meta` record, as the managed-runtime rows hash today | Any unrelated update (`openssl`, `ca-certificates`) changes keys |
| b | The distributions the science code imports, with version and build string, plus the BLAS and OpenMP libraries and Python's version | Captures what can change numbers; independent of paths and unrelated packages |
| c | Digests of every compiled extension and shared library | Exact, but slow (hundreds of megabytes) and tied to how the files were installed |

**Recommendation: b.** It is one rule for a checkout, a managed runtime and a conda environment. It replaces B5, B6 and B9 and 0002's environment rows.
- The runtime identity is `{distribution: "version build"}` for numpy, scipy, numba, llvmlite, nibabel, cortech, matplotlib, threadpoolctl, `libblas` / `libopenblas` (or the MKL equivalents), `llvm-openmp` or `libgomp`, and Python.
- SimNIBS and MUMPS are added for the workflows that solve FEM.
- Builds come from `conda-meta` when the interpreter's prefix has it, else from the distribution metadata (`version` and the wheel tag).
- An editable or locally modified distribution (`direct_url.json` with `editable` or a local file URL) enters with the digests of its files instead.
- The thread count stays in the identity, because BLAS reductions depend on it.

### 4. Absolute paths leave the keys

After 1.0 no absolute path enters any key. The interpreter path is replaced by the runtime identity of section 3. V2's numerical-runtime digest and the forward-cache keys use the same runtime identity.

**Decision for the user: does the platform (`osx-arm64`, `linux-64`) enter the key?**
- Today the Mac and Linux give the same scores up to 3.5e-14 ([source installation](../source-installation.md#on-a-physical-machine-2026-11-23)).
- With the platform in the key, a cached result is reused only on the platform that computed it. The numbers then reproduce bit for bit, at the price of no reuse across platforms.
- Without it, a shared or published result is reused across platforms, and its numbers can differ in the last digits.
- **Recommended:** in the key. Different numbers should never share a key.

With paths gone, a key computed on one installation is valid on another with the same code, data, runtime and platform. A result record can therefore be checked against a recomputation elsewhere, and shared result libraries become possible. Publishing such a library is a separate decision.

### 5. Records and caches

| Item | 0.x | 1.0 |
| --- | --- | --- |
| Records | `R/results/v2/<kind>_jobs/<key>/…` | `<data dir>/results/<kind>/<key>/…`, with the same files: `cache.json` (key, identity, result and its SHA-256), and `request.json` and `job.json` under each job id |
| Worker caches | `R/results/v2/reception_forward/…` | `<data dir>/cache/reception-forward/…`, keyed by the runtime identity |
| References between records (`provenance.file`, `design_result`) | Root-relative path and SHA-256 of the bytes | `{kind, key, sha256}` of the referenced record |
| Data | Composed into R | Read from the installed packages in `<data dir>/packages/…` directly; `compose` is no longer needed |

- **Location.** `<data dir>` is the user data directory of [data packages](../data-packages.md), not an operating-system cache directory. Users browse the library, and a radius search takes minutes to recompute. Removing the `results` directory still never removes workspace snapshots (decision 7).
- **Old records stay readable, without being rewritten.**
  - 1.0 reads 0.x records from a checkout's or environment's `results/v2/*_jobs` through a read-only legacy reader. The library lists them as 0.x results.
  - They can be opened, compared, exported and cited.
  - They are never cache hits for 1.0 requests, because their identity cannot be recomputed under the new rules without the old files.
- **Old results are found again by recomputation only.** An index from old keys to new keys would need the old code bytes, and the move changes every module's bytes (section 6), so no old result can be proven equal under the new identity.

### 6. Moving `compact_eeg` into `eeglayoutlab/core`

The move edits the imports of every module, so every code digest changes whatever the identity rules are. Doing the move separately from sections 1–5 would mean two identity changes. Under today's path rules it would also change every key a second time. **Recommendation: one change, in one release.** After it:
- the workers run as modules (`python -m eeglayoutlab.workers.<name>`);
- `scripts/` holds only maintainer tools;
- R stops existing as a concept for users: code is in `site-packages`, data in the store and records in the data directory;
- 0002's `share/eeglayoutlab/root` is no longer installed.

### 7. Migration, tests and release

- **When.** In phase 4, after the Node host is removed: no Node parity is needed then, and the B1–B25 rules can be dropped. It comes before the plugin API is published, because extensions follow section 1. It is released as 1.0.
- **Schemas.** Every identity schema moves to `/2` (`design-evaluation-cache/2`, …). Result and record formats keep their own versions (decision 8); each one that embeds an identity or a record reference also moves to its next version.
- **Tests.**
  - *Same numbers.* The examples and a fixed request suite (evaluation, radius search, editor, reception v1, studies) run under the last 0.x and under 1.0 on both platforms. Every scientific number must be identical bit for bit on the same platform and runtime.
  - *Key behaviour.* A matrix test computes keys while varying one thing at a time. Keys must stay equal when only these vary:
    - the installation path;
    - checkout versus installed form;
    - an unrelated package in the environment;
    - a data package's version label.

    Keys must change for each of these:
    - one byte of any module in a workflow's closure;
    - one byte of a data file;
    - a numerical distribution's version or build;
    - the thread count;
    - the platform.
  - *Closure guard.* The generated module manifest equals the closure computed from the code.
- **What a user of 0.x sees.**
  - Workspaces open unchanged.
  - The library shows the earlier results as 0.x results.
  - The first request of each kind computes again.
  - Data packages stay installed, and their content hashes are their identities.
- **Release-note text (draft).**

  > 1.0 changes how calculations are identified. Keys no longer depend on where EEGLayoutLab is installed: they depend on the request, the code, the model data packages, the numerical libraries and the platform. Results computed with 0.x stay readable and are listed as 0.x results, but are not reused; each calculation runs again once. Scientific results are unchanged.

## Decisions for the user

1. **The platform enters keys** (section 4). Recommended: yes.
2. **The runtime is identified by named distributions, versions and builds** (option 3b), not by every `conda-meta` record. Recommended: yes.
3. **Records move to the user data directory** (`<data dir>/results`), not to an operating-system cache directory. Recommended: yes.
4. **No reuse of 0.x results under 1.0;** they are readable only. Recommended: yes.
5. **`compact_eeg` moves into `eeglayoutlab/core`** (0001's open question "Rename at 1.0"), **in the same release as the identity change**, in phase 4 (section 6). Recommended: yes.
6. **A data package's version label stays out of keys** (section 2). Recommended: yes.
