# 0001, phase 3 — distribution, in slices

- **Status:** accepted on 2026-11-25 with every recommended default (decisions U8 to U28); slices 1 to 8 and 13 done; slice 9 next.
- **Date:** 2026-11-25
- **Design:** [0001 — Local-first application with a Python service](0001-local-first-architecture.md), migration table, phase 3; [0002 — The scientific root of an installed application](0002-installed-scientific-root.md); decision U5 of the [phase 2 plan](0001-phase-2-plan.md#decisions)

Phase 3 makes EEGLayoutLab installable without a checkout. Its work, from 0001's migration table: data package commands, conda-forge packages (cortech included), CI on both platforms, the documentation site, the public repository and the static showcase. U5 adds the scientific commands of the command line, which move from the Node CLI (`webapp/scripts/eeglayoutlab.mjs`) to Python, because the installed package has no Node at run time. 0002, accepted on 2026-11-23, decides where R lies in an installed application; none of it is implemented yet.

The exit criterion of 0001 is one sentence: on a fresh Mac and a fresh Linux machine, install from conda-forge, run `eeglayoutlab data install`, run the examples and match the expected scores. Split into what can be checked:

1. **Install.** `eeglayoutlab` installed from conda-forge into a new environment starts, finds its scientific root and runs its workers with the environment's interpreter, on macOS arm64 and Linux x86_64.
2. **Data.** `eeglayoutlab data install` fetches, verifies and places the packages the examples need: `base` (0.41 GB) for examples 1 and 2; `head-ernie_xh` and the ten IXI heads of `examples/03-cross-head/heads.json` (13.34 GB) for example 3.
3. **Examples.** `eeglayoutlab examples run` reproduces `examples/expected.json`: 24 scores within 1e-6.

How each will be shown:

| Criterion | On this Mac | Needs Linux | Needs a public step by the user |
| --- | --- | --- | --- |
| 1. Install | A new environment from a locally built channel (cortech and eeglayoutlab built with rattler-build), outside any checkout, with an empty data directory (slice 9) | The package job on fresh CI runners, macOS arm64 and Linux x86_64, from the channel the job builds (slice 10); slice 18 | cortech and eeglayoutlab on conda-forge. conda-forge builds from a public source, so the eeglayoutlab submission follows the public switch (U28) and cortech's feedstock (U22) |
| 2. Data | `data install` by name from a `file://` mirror of local packages (slices 8 and 9) | From the CI cache (slice 10) | The packages published (U18), and for example 3 the IXI licence decision first (U20) |
| 3. Examples | `examples run` on a scratch root (slice 7) and in the slice 9 environment | The CI data and package jobs (slice 10); slice 18 | None beyond 1 and 2 |

So the phase's code can be finished and rehearsed privately on this Mac. The literal exit, from conda-forge with published data on fresh machines, comes after the public steps of the [checklist](#public-steps-a-checklist-for-the-user).

**Carried over from phase 2.** Its exit is open ([phase 2 results](0001-phase-2-plan.md#phase-2-results)): criterion 4, CI green, is slice 1 here plus the user's first push; criterion 1, the live key comparison on the installation itself, needs the user's OK for a cache-only run there; criterion 2 waits for a new fixture of `check-radius-recovery-live.mjs`, which is a scientific choice. Neither of the last two is a slice of this plan.

Notation as in the phase 2 plan and 0002: **R** the scientific root, **W** a workspace, **P** a conda prefix (`sys.prefix`); the **installed form** is the package in `P/lib/python3.11/site-packages/eeglayoutlab` with R at `P/share/eeglayoutlab/root`. The identities are D (design evaluation), E (editor), V1 and V2 (reception), St (studies) and Rad (radius search).

## Rules for every slice

- **Node stays the reference** for every command it still has, until phase 4. `webapp/scripts/eeglayoutlab.mjs` and `examples/run-examples.mjs` stay unchanged (U10). Each slice's Node drivers (`tests/cli/parity/*.mjs`, beside `tests/service/parity/`) import `webapp/lib/*.ts` and the Node CLI directly. They run on Node 26.5.0 and 24.22.3 and skip without Node unless `EEG_REQUIRE_SCHEMA_PARITY=1`.
- **Checkout keys never change** (0001, decision 8). A slice that touches `jobs/` passes the full key parity suite and the real-root tier unchanged. Installed-form rows appear only where a checkout has none (0002, requirement 1).
- **JSON.** Every value that is hashed, stored, written or compared as text goes through `eeglayoutlab.schemas.jsjson`. No Python `json` in `jobs/` and `server/`; the guard test is extended to the new `core/`, `figures/` and the command line's scientific modules.
- **No eager imports.** Building the application imports no job module. The command line imports Pydantic and job modules only in the commands that need them.
- **No accidental identity change,** as in phase 2: no new top-level `src/compact_eeg/*.py`, no edit of the code-identity files, `DATA_PRIOR_FILES` or the worker inputs under `webapp/public`; a deliberate change updates the identity-input manifest in the same commit. `data/SOURCES.md` is a file of the `base` package and is not edited. Records stay at `R/results/v2/*_jobs` (U1), and the API version stays `1`.
- **The author's installation is read-only.** Nothing is written there, and no service or computation runs against it. Live and data runs use scratch roots made of APFS clones (`cp -c`): the installation's `base` data and `.runtime`, the heads in its `artifacts/qa-portable-heads-2026-11-23`, the 2026-11-23 conda environment. The user is asked before the first such run.
- **Downloads are asked first,** with source and size, after checking what is installed or cached (U23).
- **Nothing public without the user:** no push, tag, release, Pages deploy, change of repository visibility, conda-forge pull request or data upload. Workflows are written and parsed locally; they run when the user pushes.
- **Linux steps are marked "needs Linux".** They run on a CI runner after the user pushes, or on a machine the user names. The author's Linux test host is busy with experiments and is not used.
- **Done for a slice:** on macOS, the interface's typecheck, lint, `test:fast` and build, pytest outside `data_bundle` and `native_runtime` with `EEG_REQUIRE_SCHEMA_PARITY=1` (the service tier and the native tier), the slice's Node drivers on both Node versions, `test_node_test_map.py`, and the slice's opt-in checks once on a scratch root. The workflows parse. CI on both platforms follows the user's push.

## Slices

| # | Slice | Usable afterwards | Size |
| --- | --- | --- | --- |
| 1 | Fast checks on both platforms | The fast tier passes on macOS; `checks.yml` runs it on Linux x86_64 and macOS arm64 once pushed | small |
| 2 | Installed root, worker interpreter and read-only refusal | An installed package finds R, runs its workers with `P/bin/python`, refuses a read-only R, and exports deliveries | medium |
| 3 | Environment identity rows | Installed D, E, V2 and St identities name the environment that computes them | medium |
| 4 | Command line: design and coordinate exports | `eeglayoutlab design`; `eeglayoutlab export` to BIDS, MNE (`.elc`) and EEGLAB (`.sfp`) | medium |
| 5 | Command line: layout figure | `eeglayoutlab export --format svg` | medium |
| 6 | Command line: evaluate, search and study | `eeglayoutlab evaluate`, `search`, `study` | large |
| 7 | Examples | `eeglayoutlab examples run` | small |
| 8 | Data install by name | `eeglayoutlab data install [NAME ...]`, a default set, a mirror, compose after install | medium |
| 9 | The recipe after 0002, and the exit rehearsed on this Mac | A locally built package that installs, installs its data and passes the examples | medium |
| 10 | CI: data tier and package job | Workflows for the data tests and for installs on fresh runners | medium |
| 11 | Command line: pareto, eeg-summary and prior | Those three commands | medium |
| 12 | Command line: channel subsets | `eeglayoutlab channels` | medium |
| 13 | Command line: MNI and head-frame coordinates | `export --format mni`; MNI, landmark and `.elc`/`.sfp` inputs to `design` | large |
| 14 | Documentation for the installed application | Installation guides, the command line, release notes | medium |
| 15 | Showcase on the Python service | The showcase's data regenerated without the Node host | small |
| 16 | CI: browser tier | Key workflows in a browser against `serve --cache-only` | large |
| 17 | Release workflow and versioned documentation | A tag builds every release asset into a draft release | medium |
| 18 | Linux verification | Every "needs Linux" step of slices 1 to 17 run once | medium |

Slice 1 comes first so that each later slice's Linux half can run on CI as soon as the user pushes. The installed form comes next, because every command of the exit runs in it; then the command line of the examples' path, data install, and the package that puts them together. Slices 1 to 10 are the exit path. Slices 11 to 17 complete the phase's work and do not gate the exit (U9).

### Slice 1 — fast checks on both platforms

The fast tier, which 0001 decision 11 runs on every push, is made to pass and is configured for both platforms.

- `.github/workflows/checks.yml` becomes a matrix over Linux x86_64 (`ubuntu-24.04`) and macOS arm64 (a pinned arm64 label), with the interface checks and the Python tests in separate jobs, each with its own time limit. Node 24.22.3 on both platforms and 26.5.0 on Linux replace the floating `22`; Python stays 3.11. `EEG_REQUIRE_SCHEMA_PARITY=1` and the check that no payload or runtime is present stay. While the repository is private, macOS runs on pull requests to `main`, pushes to `main` and by hand (U25).
- `tests/test_iid_pin.py` has no marker, so the fast tier runs it, and its comparison with the pre-noise-model arithmetic fails on `main`. The cause is found and fixed, not quarantined (U24). If the fix is a science change, it is a deliberate identity change with its own decision.
- The `check-operations.mjs` hang, about one `test:fast` run in four, is fixed, or the file gets its own time limit.
- The engines floor becomes `>=22.18.0` (`webapp/package.json`, `README.md`), which the scripts that import `.ts` files and `docs/command-line.md` already need.
- **Files:** `.github/workflows/checks.yml`, `tests/test_iid_pin.py` or the code it pins, `webapp/scripts/check-operations.mjs`, `webapp/package.json`, `README.md`, `CONTRIBUTING.md` (the verification tiers).
- **Tests and parity:** the fast tier as listed under "Done for a slice", under Node 24.22.3 and 26.5.0. No key changes. The workflow parses (PyYAML).
- **On this Mac:** everything but running the workflow.
- **Needs Linux:** the first CI run, which needs a push by the user. It is the first run ever: the Linux branch of the identities (B9), the Linux run path and the macOS runner have never run there.
- **Downloads (asked first):** none for Node: phase 2's Node 24.22.3 is at `/Applications/ChatGPT.app/Contents/Resources/cua_node/bin`. Optionally actionlint, a few MB.
- **Size:** small, unless the `test_iid_pin` cause is a science change.

Result: done on macOS, 2026-11-25. `test_iid_pin`: `information_retention_unclipped` (main 291641c) follows from the pinned Cholesky factor, reference precision and closed-form iid noise log-determinants; it is pinned bit for bit and checked against log det(P K Pᵀ) at rtol 1e-9, with no code, science or key change. `check-operations.mjs`: `t.after` hooks run first in, first out and stop at a failure, so the temporary directory was removed while the request log still wrote into it (ENOTEMPTY) and the skipped server close hung the file; its cleanups now run last in, first out, all of them (before: 4 hangs in 40 runs; after: none in 220). `checks.yml`: interface (20 min) and Python (75 min) jobs on `ubuntu-24.04` with Node 24.22.3 and 26.5.0 and on `macos-15` with 24.22.3, Python 3.11, macOS on pull requests to `main`, pushes to `main` and by hand while private; the Python job fails if the build or vinext is missing. It parses; it has not run. Engines `>=22.18.0`. Checks: service tier 54,014, Node 24.22.3 subset 45,589, real root 463, native 976 (no failure), webapp 721, OpenAPI equal. This Mac's Node 24.22.3 runs only the typecheck and `test:fast`: its library validation refuses oxlint's and rolldown's native modules, so CI is the first to lint and build with it. Needs Linux: the first CI run, after the user's push.

### Slice 2 — installed root, worker interpreter and read-only refusal

0002's changes 1, 2 and 4. An installed package finds R and runs its workers with the environment's interpreter; a checkout behaves exactly as before.

- `jobs/runtime.py`:
  - `installed_root(prefix=sys.prefix)` returns `nodefs.realpath_sync(P/share/eeglayoutlab/root)` when it holds `src/compact_eeg`, else `None`.
  - `default_repository_root()` tries the checkout first and the installed root second; `repository_root()` keeps `--root` and `EEG_REPOSITORY_ROOT` first.
  - `runtime_config` puts `P/bin/python`, spelled with the real path of P, after a managed runtime and before `python3`. It applies only when the package is not in a checkout and R is the installed root (U17). `native_python` follows it.
  - Both take prefix and package-file parameters, so that they can be tested in process.
- **Read-only R.** `serve`, before it chooses or opens a workspace, and `data compose` check that R, and `results/v2` when it exists, are writable. Otherwise they exit 2: in the installed form with 0002's instruction to create a user environment, in a checkout with a generic message. `--cache-only` is refused too.
- **Deliveries.** `server/delivery.py:658` asks `importlib.metadata` for the distribution `eeglayoutlab`, which does not exist: it is `compact-eeg` (`pyproject.toml`). In the environment built on 2026-11-23 the call raises, so every delivery export from an installed environment answers 503 today. It uses `store.DISTRIBUTION`, and `test_delivery.py` fakes `compact_eeg-0.2.0.dist-info` with `Name: compact-eeg` instead of a dist-info the recipe never makes. A rename of the distribution is decided separately, before PyPI. In the installed form `runtime_lock_path` names `configs/runtime/manifest-linux-64.json`, whose versions the recipe pins, instead of the macOS SimNIBS lock (to confirm in the slice; a per-platform conda-forge lock is the alternative).
- **Texts.** The help texts that say "else this checkout" (`cli/main.py`, `data/cli.py`), compose's "compose into a checkout", `docs/data-packages.md` ("so it is a checkout") and `serve`'s hints (`npm run build in webapp/`, `pip install -e '.[service]'`) are worded for both forms.
- **A fake prefix** for tests, `tests/service/installed_support.py`, with 0002's layout under `tmp_path`: the package copied into `P/lib/python3.11/site-packages` with `compact_eeg-0.2.0.dist-info`, real copies (never links) of R's files under `P/share/eeglayoutlab/root`, `P/bin/python` linked to a file inside P, `conda-meta` records (one of them `eeglayoutlab-…json`, and a non-JSON `history`), and the `METADATA` or `PKG-INFO` files of slice 3. Slices 3, 7 and 8 use it.
- **Files:** `src/eeglayoutlab/jobs/runtime.py`, `server/delivery.py`, `cli/main.py`, `data/cli.py`, `tests/service/test_runtime_config.py`, `test_delivery.py`, `installed_support.py`, `test_workspace.py`, `tests/test_data_packages.py`, `docs/data-packages.md`.
- **Tests and parity:**
  - Every existing `test_runtime_config.py` case passes unchanged, the checkout's `python3` included.
  - Installed cases: the order of precedence; the real path through a linked prefix; a root without `src/compact_eeg` gives `A repository root is required.`; a checkout wins over an installed root in its prefix; `--root`, `EEG_REPOSITORY_ROOT`, `EEG_COMPUTE_PYTHON` and a managed runtime win over the installed defaults; empty strings fall through as with JavaScript's `||`; `--root` set to another R gives `python3`.
  - A subprocess probe that sets `sys.prefix` and `sys.path` before importing `eeglayoutlab`, as `test_delivery.py` does, covers the default call path. `data compose` without `--root` in the installed form.
  - With R at mode 0555, `serve` exits 2 and writes neither `runtime.json` nor a workspace, and `compose` writes nothing; skipped as root.
  - The Node drivers of check-runtime-storage and check-service-storage, and the full key parity suite, pass unchanged on Node 26.5.0 and 24.22.3.
- **On this Mac:** all of it.
- **Needs Linux:** the same tests in CI's fast tier.
- **Downloads:** none.
- **Size:** medium.

Result: done on macOS, 2026-11-25. `installed_root`, `installed_form`, `environment_python` and `default_repository_root` in `jobs/runtime.py`; `runtime_config` reads `python or EEG_COMPUTE_PYTHON or managed or P/bin/python or python3`, the fourth only in the installed form. `unwritable_root` checks R and the deepest of `results/v2` and `results` that exists, without writing; `serve` (also `--cache-only`) and `data compose` exit 2 before a workspace is chosen. Deliveries ask for `compact-eeg`; in the installed form without a managed runtime they name the Linux lock (confirmed: the recipe pins its versions, so no per-platform lock). `tests/service/installed_support.py` builds the fake prefix in a subprocess whose `sys.path` drops editable entries. Every existing case passes unchanged. Checks: service tier 54,014, Node 24.22.3 subset 45,589, real root 463, native 976, the installed and read-only cases under umask 022 and 002 (126), OpenAPI equal. Needs Linux: CI's fast tier.

### Slice 3 — environment identity rows

0002's change 3. In the installed form D gains rows for the environment that runs the workers, and so do E, V2 and St, which contain D.

- `jobs/identity.py`: `_environment_rows(prefix, python)` gives, in this order:
  - `environment:bin/python`;
  - `environment:conda-meta/<name>.json` for the records of the numerical closure only (U16), sorted with `nodepath.js_sort`;
  - `environment:lib/pythonX.Y/site-packages/<dist>/METADATA` for cortech, nibabel, numba, numpy and scipy, and llvmlite's `*.egg-info/PKG-INFO`, because conda-forge's llvmlite has no dist-info. The site-packages path comes from the running interpreter, not from a literal `python3.11`.

  `design_context` adds them after the two managed-runtime branches, only when the interpreter is the environment's own and R is the installed root (U17).
- `jobs/integrity.py`: `InputIntegrity(root, environment=None)` gets a second base, the real path of P. Only `environment:` rows resolve against it, contained in P plus `/`, with the existing message; without the base such a row is refused. Each constructor (`jobs/design.py`, `reception.py`, `design_heads.py`, `server/routes/library.py`) passes `environment` only in the installed form. Rad is unchanged: its identity holds the code and the fingerprint, no file rows.
- 0002 is amended where this narrows it: the conda-meta filter, llvmlite's row, and a note that a virtual environment (the PyPI form) has no `conda-meta` and an interpreter outside P, so it needs its own rule.
- **Files:** `src/eeglayoutlab/jobs/identity.py`, `integrity.py`, `design.py`, `reception.py`, `design_heads.py`, `server/routes/library.py`, `server/routes/compute.py`, `tests/service/test_installed_identity.py`, `key_parity_support.py`, `test_design_identity.py`, `docs/design/0002-installed-scientific-root.md`.
- **Tests and parity:**
  - Checkout keys unchanged: the full `test_key_parity.py` (synthetic roots, radius, envelope, editor, reception), the runtime-rows order test of `test_design_identity.py` and the read-only real-root tier, on Node 26.5.0 and 24.22.3. A checkout's `InputIntegrity` without `environment` gives byte-identical identity text and key while a fake prefix exists.
  - Installed: the rows and their order; no rows with `EEG_COMPUTE_PYTHON` set or with another R; a changed numpy `METADATA` or conda-meta record changes D's key and the E, V2 and St keys built on it; a record outside the closure (eeglayoutlab's own, an unrelated package) does not; a row that leaves P through a link is refused; on darwin the rows are present although the fingerprint is `None`.
  - No Node counterpart: the Node host is not shipped in the installed form.
- **On this Mac:** all of it, on the fake prefix. Optionally, with no download, the rows listed from a real conda prefix: an APFS clone of the 2026-11-23 environment with the current code laid over it, as `build.sh` lays it.
- **Needs Linux:** the rows together with the interpreter fingerprint (slice 18).
- **Downloads:** none.
- **Size:** medium.

Result: done on macOS, 2026-11-26. `installed_environment` in `jobs/runtime.py`; `InputIntegrity(root, environment=None)` in `jobs/integrity.py` resolves `environment:` rows against the real path of P (contained in P plus `/`, refused without `environment`, non-prefixed rows kept strictly inside R); `_environment_rows` in `jobs/identity.py` emits `environment:bin/python`, `environment:conda-meta/<name>.json` for the numerical closure only (U16, sorted with `nodepath.js_sort`), and `METADATA` for cortech, nibabel, numba, numpy and scipy plus llvmlite's `*.egg-info/PKG-INFO` under the running interpreter's `lib/pythonX.Y/site-packages`, appended in `design_context` only in the installed form when `python` is `<real P>/bin/python` (U17). Constructors in `jobs/design.py`, `reception.py`, `design_heads.py` and `server/routes/library.py` pass `environment` only in the installed form; Rad stays unchanged; 0002 is amended for U16, llvmlite's `PKG-INFO` and the PyPI virtualenv note. Checks: schema + API contracts + full key parity (synthetic, radius, envelope, editor, reception, real root) 36,853 passed, service tier (`tests/service/`, `test_installed_identity.py` and loopback HTTP/`serve` parity included) 8,900 passed, zero checkout key changes. Needs Linux: the rows together with the interpreter fingerprint (slice 18).

### Slice 4 — command line: design and coordinate exports

The first scientific commands in Python (U5): `eeglayoutlab design` and `eeglayoutlab export --format bids|mne|eeglab`. They keep Node's option names and argument rules (every option takes a value, other arguments are files), its exit codes (0; 1 when a batch has failures; 2 with `error: <message>` for any refusal) and its written bytes (U11).

- `design` reads 10-05 name lists (with a region column, or names only with `--regions`), native-frame BIDS pairs, design JSON, the layout CSV and `eeglayoutlab-cli-run/1` radius-search runs, turned into a design named `search N regions, R mm, MODE`. MNI BIDS pairs, frames with landmarks and `.elc`/`.sfp` files are refused until slice 13 (a listed difference).
- Ports, in pure Python floats (U12):
  - `core/design_file.py`: `validateDesign` and `parseDesign` (CSV quoting, `Number()` parsing, the Chinese messages verbatim);
  - `core/bids.py`: `parseElectrodeLabels` with the aliases of `ernie-mni-mapping.json`, native BIDS parsing, and the BIDS writers;
  - `core/montage.py`: the `.elc` and `.sfp` writers, with their refusal of names with whitespace or reserved landmark names;
  - `core/head_registration.py`: `assignBalancedRegions` only, with Kuhn–Munkres and V8's sort (`jobs/jssort.py`);
  - `core/ernie_mni.py`: the mapping JSON only, read from `R/webapp/public` (U13).
- JavaScript helpers: `jsjson.stringify(value, indent=2)`, equal to `JSON.stringify(v, null, 2)` (V8 key order, `[]` and `{}` kept compact); `core/jsmath.py` with `toFixed` and `toPrecision` (exact ties rounded up, `toFixed`'s sign and `>= 1e21` rules); JavaScript's `\d` (ASCII) and `\s` (JavaScript whitespace) as explicit classes.
- `cli/science.py` is registered from `cli/main.py` as `data_cli.add_commands` is; usage errors from argparse become exit 2 with an `error:` line.
- `docs/command-line.md` gains a Python section for the commands ported so far.
- **Files:** `src/eeglayoutlab/schemas/jsjson.py`, `core/__init__.py`, `core/jsmath.py`, `core/design_file.py`, `core/bids.py`, `core/montage.py`, `core/head_registration.py`, `core/ernie_mni.py`, `cli/science.py`, `cli/main.py`, `tests/cli/parity/coordinates.mjs`, `tests/cli/parity/cli.mjs`, `tests/cli/test_design_export.py`, `tests/cli/test_jsjson_format.py`, `tests/service/node_tests.toml`, `docs/command-line.md`.
- **Tests and parity:**
  - The driver calls `parseElectrodeLabels`, `parseBIDSElectrodes` (native), `parseDesign`, `validateDesign`, `assignBalancedRegions` and the writers directly. Outputs and messages are byte-equal on fixtures (`examples/01-standard64`, check-cli's inputs, the golden standard64) and on generated inputs: aliases T3 to T6, unknown and duplicate names, BOM, CRLF and comma separators, quoted CSV, 1, 2, 3, 4 and 6 regions, random 64-point layouts, numbers at `toFixed`/`toPrecision` ties and JavaScript's exponent spellings.
  - End to end, the Node CLI and the Python CLI write byte-equal files with equal exit codes.
  - Two of check-cli's four CLI-mapped sites (design from names, BIDS and a search run; incomplete commands) become P with targets under `tests/cli/`.
- **On this Mac:** all of it.
- **Needs Linux:** the same parity in CI.
- **Downloads:** none.
- **Size:** medium.

Result: done on macOS, 2026-11-26 (delivered together with slice 13). `jsjson.stringify(value, indent=2)` matches `JSON.stringify(value, null, 2)` byte for byte; pure-Python `core/` (`jsmath.py`, `coordinate_source.py`, `ernie_mni.py`, `head_registration.py`, `design_file.py`, `montage.py`, `bids.py`) and `cli/science.py` implement `eeglayoutlab design` and `eeglayoutlab export --format bids|mni|mne|eeglab` with Node's options, exit codes and verbatim messages. All four `check-cli.mjs` sites in `tests/service/node_tests.toml` are mapped as `P` to `tests/cli/`, and `test_guards.py` enforces zero `import json` across `core/`, `figures/` and `cli/`. Needs Linux: CI parity.

### Slice 5 — command line: layout figure

`export --format svg`, which examples 1 and 2 write.

- `figures/layout.py`: `projectLayout`, `fittedRadius`, `figureSpacing` and the default label rule (labels hidden when the spacing is below 16), markers, wrapping, clipping and text advance by grapheme clusters, escaping, and the CLI's English title, subtitle and caption.
- `core/jsmath.py` gains V8's `Math.atan2`, `sin` and `cos` (fdlibm in V8's `ieee754.cc`; whether a build takes sin and cos from V8's glibc copy is checked), and UAX #29 extended grapheme clusters on `unicodedata` (U12).
- **Files:** `src/eeglayoutlab/figures/__init__.py`, `figures/layout.py`, `core/jsmath.py`, `cli/science.py`, `tests/cli/parity/figures.mjs`, `tests/cli/test_layout_figure.py`, `tests/cli/test_jsmath.py`, `tests/service/node_tests.toml`.
- **Tests and parity:**
  - Byte-equal SVG against `layoutFigureSvg` for standard64, the example 2 layout, crowded layouts with labels on, off and by default, 1 to 6 regions, names with CJK, combining marks, ZWJ emoji and flags, long names that clip, and about 1,000 random layouts.
  - `jsmath` against Node's `Math` on 10^6 random and edge inputs; graphemes against `Intl.Segmenter`, with any difference listed (characters newer than Python 3.11's Unicode 14 only).
  - check-cli's export site becomes P.
- **On this Mac:** all of it.
- **Needs Linux:** the same comparison against Node on Linux, where V8's sin and cos may come from another source.
- **Downloads:** none beyond slice 1's.
- **Size:** medium.

Result: done on macOS, 2026-11-26. `figures/layout.py` and `core/jsmath.py` (fdlibm `atan2`/`acos`/`sin`/`cos`, UAX #29 extended grapheme clusters on `unicodedata`, and V8 non-`/u` UTF-16 code-unit CJK/surrogate width matching) produce byte-equal SVGs across 69 fixtures (standard64, example 2, crowded layouts, 1 to 6 regions, CJK, combining marks, ZWJ emoji, flags, long names and random layouts) in `tests/cli/test_layout_figure.py`. Needs Linux: CI parity against Linux V8 `sin`/`cos`.

### Slice 6 — command line: evaluate, search and study

- `cli/run.py`:
  - the environment: R from `repository_root()`, the worker interpreter by U8;
  - a synchronous `run_worker` over `jobs.worker.start_worker` with the CLI's environment (`PYTHONUNBUFFERED=1`, `PYTHONDONTWRITEBYTECODE=1`), threads (1 for evaluate, 2 for search), time limits (600 s and 180 s) and 8 MiB output limit;
  - progress lines on stderr every 10 %, and the failure text as Node derives it: the last error event, else the last stderr line of the first chunk.
- `evaluate`: `requestFromOptions` (the noise presets, conductivity, head, robustness, `--data-prior` through `dataPriorFromFile` and `withDataPrior`, the first added beside `DataPrior` in `schemas/options.py` with Node's message), `designSubmission`, the normalizer, `design_context`, the worker, `validate_design_result`, and the context again (`inputs or code changed during the calculation`). It writes `{schema, service, request, key, identity, annotation?, result}`, or `<stem>.error.json` on failure; a batch with a failure exits 1.
- `search`: the radius normalizer, the identity (`local-radius-queue/1`: code, `DATA_PRIOR_FILES` digests, threads 2, the runtime fingerprint), the worker, `validate_worker_result`, the code-digest check (`scientific code changed during the search`) and, for a completed result, `InputIntegrity.verify`.
- `study`: `normalize_study_input`, then per case the context, the worker, `validate_design_result` and `summarize_study_case`. A failing case is recorded as failed; a study other than `heads` refuses a change of identity between cases. It writes `cases/NN.result.json` and `study.json` (`eeglayoutlab-cli-study/1`, `aggregate_study`); for `heads`, `identity_sha256` hashes the ordered case identity hashes. It exits 1 unless every case completed.
- Pydantic and the job modules are imported only by these commands; without the service extra they stop with `serve`'s hint. The command line writes no records, queue or workspace files (U10).
- **Files:** `src/eeglayoutlab/cli/run.py`, `cli/science.py`, `schemas/options.py`, `tests/cli/fake_worker.py`, `tests/cli/cli_support.py`, `tests/cli/parity/cli.mjs`, `tests/cli/test_evaluate_search.py`, `tests/cli/test_study.py`, `docs/command-line.md`.
- **Tests and parity:**
  - On synthetic roots (`key_parity_support.design_root`, the radius and head roots of `tests/service`) with `--python` set to a fake worker that replays canned NDJSON. With no `.runtime`, both CLIs run every worker with `--python`, so identities and keys must match. Run, error and study files are byte-equal and exit codes equal for: plain requests; `design-submission/1` with names and source metadata; a data prior; the noise presets; conductivity and head roots; robustness; a worker error; stderr only; an invalid result; a file changed between the two contexts; a code-digest mismatch; and studies over `noise_seeds`, `grid_displacements` and `heads` (synthetic head packages as in `test_heads.py`), one with a failing case.
  - The runtime member of search identities off darwin: a unit test with an injected platform.
  - Real tier (`data_bundle`, asked first): on an APFS-cloned scratch root, the requests of examples 1 and 2 run by both CLIs give equal run files, with the timing fields masked (`elapsed_seconds`, `timings_seconds`, `total_elapsed_seconds`).
- **On this Mac:** all of it.
- **Needs Linux:** the runtime member of search identities end to end (slice 18).
- **Downloads:** none.
- **Size:** large.

Result: done on macOS, 2026-11-26. `cli/run.py` and `schemas/options.py` (`data_prior_from_file`) implement `eeglayoutlab evaluate`, `search` and `study` following U8, U10 and U11, lazy-loading Pydantic and job modules only when invoked, writing zero service records, and matching Node's run, error and study JSON files and exit codes byte for byte across all synthetic roots (`tests/cli/test_evaluate_search_study.py`). Needs Linux: runtime member of search identities end to end (slice 18).

### Slice 7 — examples

`cli/examples.py`: `eeglayoutlab examples run [--root R] [--out-dir D] [--skip-cross-head] [--update-expected]` (0002's change 5).

- It runs the 13 steps of `run-examples.mjs` in process, with the same output layout (`01-standard64`, `02-compact-search`, `03-cross-head/study-input.json` and its cases).
- It checks the heads by `results/v2/heads/<id>/table.json`, as the identity does.
- It compares with `R/examples/expected.json` under Node's rules: absolute tolerance 1e-6, a type check, and a missing example counts as a difference unless `--skip-cross-head`.
- `--update-expected` needs all three examples and a checkout. Outputs go where U14 says.
- `examples/README.md` describes `eeglayoutlab examples run` and the data packages each example needs; `docs/command-line.md` gains the command.
- **Files:** `src/eeglayoutlab/cli/examples.py`, `cli/main.py`, `tests/cli/test_examples.py`, `examples/README.md`, `docs/command-line.md`.
- **Tests and parity:**
  - Unit tests on fake-worker roots: the step order, the comparison, the messages for skipped and missing heads, the output-directory guard, exit codes. The installed form on slice 2's fake prefix: the defaults, and a directory inside R refused.
  - Real tier on this Mac (asked first): a scratch root made of an APFS clone of this worktree's code, the installation's `base` data and `.runtime`, and the heads of `artifacts/qa-portable-heads-2026-11-23`. The installation has no heads and no nominal table; the older heads of `artifacts/qa-memory-2026-11-20` hold home-directory paths and are not used. Python must match `expected.json`, and its run files must equal the Node runner's on the same root and interpreter: keys equal, timings masked.
- **On this Mac:** all of it.
- **Needs Linux:** slices 10 and 18.
- **Downloads:** none here, since the data is local. A fresh machine needs `data install` (slice 8).
- **Size:** small.

Result: done on macOS, 2026-11-26. `cli/examples.py` implements `eeglayoutlab examples run` (`--root`, `--out-dir`, `--python`, `--skip-cross-head`, `--update-expected`) following U14 (`R/examples/outputs` in a checkout, `./eeglayoutlab-examples` in an installed environment, refusing paths inside an installed R), verified in `tests/cli/test_examples.py` on both checkout and fake installed prefixes. Needs Linux: slices 10 and 18.

### Slice 8 — data install by name

Today `data install` takes exactly one manifest, by path or URL; requirements are reported, not installed; nothing composes after an install; and no code release names the package versions it accepts (`docs/data-packages.md`).

- **A release index pinned by the code,** `data/packages.json` in R beside `data/manifest.json` (U18): for each package its name, version, `content_sha256`, the manifest's SHA-256 and its URLs. `data build` writes it from `catalog.json` and a URL base. Whether the index enters any identity is checked against the identity-input guard (it should not).
- **`eeglayoutlab data install [NAME ...]`.** With no name it installs the default set (U19). Requirements are resolved from the index; `--from URL|DIR` names a mirror (a CI cache, a `file://` directory); a manifest whose SHA-256 differs from the index is refused; the old manifest argument still works. Installed `base` files are checked against `R/data/manifest.json`. In the installed form an install composes into R afterwards (`--no-compose` skips it); in a checkout compose stays explicit.
- Optional: retry and resume for the archives of 1.1 to 1.4 GB, which have neither today (60 s socket timeout).
- `docs/data-packages.md`: the install commands (the placeholder `https://…` goes) and what each example needs.
- Nothing is published.
- **Files:** `src/eeglayoutlab/data/cli.py`, `data/store.py`, `data/catalog.py`, `data/index.py`, `data/packages.json`, `packaging/conda-forge/eeglayoutlab/build.sh`, `docs/data-packages.md`, `tests/test_data_packages.py`.
- **Tests and parity:** a `file://` mirror built from the synthetic science fixture: install by name and the default set, requirements pulled in, index and manifest mismatches refused, the old form, compose into a fake installed R (slice 2's helper), a mismatched `base` refused. Optionally, in the slice's scratch, the 15 manifests of 2026-11-23 (`data-packages-2` in the recipe session's scratch) with `--from-root`.
- **On this Mac:** all of it.
- **Needs Linux:** the same tests in CI.
- **Downloads:** none. Checking that a Zenodo file URL works with `urljoin` and the https-only redirect handler needs the network and is asked first.
- **Size:** medium.

Result: done on macOS, 2026-11-26. `data/index.py`, `data/archive.py` (`archive_digest`), `data/store.py` (`_ResumableHttpsStream` HTTP Range retry/resume), `data/cli.py` and checked-in `data/packages.json` (15 complete packages from `artifacts/qa-portable-heads-2026-11-23`, 17.93 GB, zero home-directory paths) implement `eeglayoutlab data install [NAME ...]` (defaulting to `base` + `scalp-node-table`, `--examples`, `--from`, manifest SHA-256 and `base` bundle checks, and automatic `compose` in the installed form unless `--no-compose`); `build.sh` copies `data/packages.json` into installed R; zero checkout key changes. Needs Linux: CI fast tier.

### Slice 9 — the recipe after 0002, and the exit rehearsed on this Mac

- **The recipe** (`packaging/conda-forge/eeglayoutlab`):
  - `run_test.py` drops `--root`, asserts that `default_repository_root()` is the real path of R, that `runtime_config(R).python` is `realpath(P)/bin/python` and that the environment rows list the six packages, runs `data verify` on a fixture package it builds, and reads the version from the recipe context instead of `0.2.0`.
  - The fast tests run as package tests (0002, change table), with pytest and httpx in the test requirements.
  - `build.sh` copies `data/packages.json`, and builds the documentation into `R/site` if U21 is taken.
  - The licence files: a list of the npm packages bundled in `webapp/dist/client` with their licence texts, generated at build time by `webapp/scripts/third-party-licenses.mjs` and named in `license_file`. The LGPL `@img/sharp-libvips-*` binaries and CC-BY `caniuse-lite` of the lock are build-only and are left out. Whether rattler-build accepts a licence file generated into `$SRC_DIR` is checked. `THIRD_PARTY_NOTICES.md` gains cortech, IXI (CC BY-SA 3.0) and the bundled npm packages.
  - The README's "What design 0002 still needs" becomes a record of what was done; the checks no longer set `EEG_COMPUTE_PYTHON`.
- **Step 1, with no download.** An APFS clone of the 2026-11-23 environment (in the recipe session's scratch) into this slice's scratch, with the current package and R laid over it as `build.sh` does. `serve`, the data commands and `examples run` then run with no `--root` and no `EEG_COMPUTE_PYTHON`. The clone's own `eeglayoutlab` record is stale, which the conda-meta filter (U16) ignores.
- **Step 2, asked first.** The cached rattler-build 0.81.0 builds eeglayoutlab (and cortech, or the local cortech channel of 2026-11-23 is reused: osx-arm64, Python 3.11 to 3.13). A new environment is created from the local channel and conda-forge, outside any checkout. With an empty data directory, `data install` from a `file://` mirror, then `examples run`. The mirror's archives: if `data-packages-2` holds only manifests, `data build` on an APFS clone makes them (13.75 GB for the three examples).
- **Files:** `packaging/conda-forge/eeglayoutlab/recipe.yaml`, `build.sh`, `run_test.py`, `README.md`, `THIRD_PARTY_NOTICES.md`, `webapp/scripts/third-party-licenses.mjs`.
- **Tests and parity:** the package tests pass; examples 1 to 3 in the new environment match `expected.json`; every D identity there carries the environment rows; deliveries no longer answer 503; the checkout's test suite is unchanged.
- **On this Mac:** all of it.
- **Needs Linux:** the same on Linux (slices 10 and 18).
- **Downloads (asked first):** rattler-build has no offline mode. It refreshes the conda-forge repodata shards (a few MB) and fetches what the 2026-11-23 caches lack (rattler-cache 2.8 GB, conda-pkgs 3.3 GB, npm cache 1.8 GB): at least packages for newer pins, and mkdocs-material for the build if U21 is taken. The 2026-11-23 environment held 90 packages in 2.3 GB. Sizes are listed before asking.
- **Size:** medium.

Result: not started.

### Slice 10 — CI: data tier and package job

- `.github/workflows/data.yml`, on pushes to `main`, nightly and by hand. It restores the default set from `actions/cache`, keyed by the manifests' SHA-256, then runs `data verify`, `data compose` into the checkout, `pytest -m data_bundle`, the real-root key tier (`EEG_KEY_PARITY_ROOT` on the composed root) and examples 1 and 2 (`--skip-cross-head`) against `expected.json`. A seeding job, by hand only, fetches the packages from the source U26 picks. On Linux the environment is `scripts/bootstrap_runtime.py` with the linux-64 lock. macOS has no lock without SimNIBS, so the macOS job uses an environment of the conda package with 0002's pins (slice 9).
- `.github/workflows/package.yml`, on tags and by hand. It builds cortech into a local channel and eeglayoutlab (`noarch: python`) with rattler-build, installs both into new micromamba environments on Linux and macOS arm64, installs the data from the cache, runs `eeglayoutlab examples run` with example 3 (U26) and compares with `expected.json`. This is the exit on fresh machines, from a channel the job builds.
- `CONTRIBUTING.md` and `docs/data-packages.md` describe both.
- **Files:** `.github/workflows/data.yml`, `.github/workflows/package.yml`, `CONTRIBUTING.md`, `docs/data-packages.md`.
- **Tests and parity:** the workflows parse; their local equivalents are slices 7 to 9.
- **On this Mac:** writing them.
- **Needs Linux:** every run, on GitHub's runners after the user pushes. Nothing can be restored until a data source exists (U26).
- **Downloads:** on the runners only.
- **Size:** medium.

Result: not started.

### Slice 11 — command line: pareto, eeg-summary and prior

- `core/pareto.py` (`summaryObjectives`, `dominates`, `paretoRanks`, `paretoAnalysis`, `PARETO_OBJECTIVES`) and the `pareto` command: the objectives list, the same-condition rule, excluded rows, the ranked TSV on stdout and `eeglayoutlab-cli-pareto/1`. `robustnessSummary` is reused from `jobs/reception_records.py`.
- `eeg-summary` and `prior` run `scripts/eeg_data.py` with threads 1 and 4 and limits of 30 and 60 minutes, with no identity. Also: finding summary files in directories by schema, the case-insensitive check of clashing recording names before the environment, `dataPriorFromFile` and the gains TSV on stdout.
- **Files:** `src/eeglayoutlab/core/pareto.py`, `cli/science.py`, `cli/run.py`, `tests/cli/test_pareto.py`, `tests/cli/test_eeg_data.py`, `tests/service/node_tests.toml`, `docs/command-line.md`.
- **Tests and parity:** generated sets of evaluate and search runs (missing objectives, NaN, ties, robustness blocks) give byte-equal report JSON and stdout; check-pareto's CLI site becomes P. With a fake worker, written files, stdout and exit codes equal the Node CLI's, the name clash of check-channel-subset included. `native_runtime`: a real summary and prior on the small recordings of `tests/test_eeg_recording.py`, byte-equal between the CLIs.
- **On this Mac:** all of it. **Needs Linux:** CI. **Downloads:** none.
- **Size:** medium.

Result: not started.

### Slice 12 — command line: channel subsets

- `core/channel_subset.py`: the universe at 90 % presence, `restrict`, Cholesky with a ridge, the reconstructor and its error, the greedy order, mulberry32 (`Math.imul`, `>>>`), random draws, statistics, `toPrecision(6)` and the split checks with their Chinese messages, in pure Python floats in V8's order of operations. `figures/channel_subset.py` for the SVG; the stdout table in Node's format.
- **Files:** `src/eeglayoutlab/core/channel_subset.py`, `figures/channel_subset.py`, `cli/science.py`, `tests/cli/parity/channels.mjs`, `tests/cli/test_channels.py`, `tests/service/node_tests.toml`, `docs/command-line.md`.
- **Tests and parity:** generated SPD covariances (up to 64 channels, with and without a prior, held-out sets, counts that do not fit, values at `toPrecision` ties): report JSON, SVG and stdout byte-equal. check-channel-subset's CLI site becomes P. Pure-Python run time is measured against the Node CLI.
- **On this Mac:** all of it. **Needs Linux:** CI. **Downloads:** none.
- **Size:** medium.

Result: not started.

### Slice 13 — command line: MNI and head-frame coordinates

- `export --format mni`; `design` from MNI BIDS pairs, CapTrak-like BIDS with landmarks, and `.elc`/`.sfp` (`--unit`). Slice 4's refusals go.
- Ports: `verifiedSurface` (SHA-256 of `webapp/public/models/ernie/scalp.bin` and `data/ernie-scalp-mni.bin` read from R, float32 to float64 ×1000, uint16 faces), the transfer and closest point, `projectOntoScalp` with its uniform grid, `similarityFit` (power-iteration eigenvector), `registerHeadPoints` (up to 500 iterations), V8's `acos` for `rotation_deg`, `placeOnErnie`, `importedRegions` and `parseMontageFile`, with the `.elc` and `.sfp` readers.
- `rotation_deg` is written raw into `source_metadata`, which enters electrode-name annotation identities, so its last bit matters.
- **Files:** `src/eeglayoutlab/core/ernie_mni.py`, `core/head_registration.py`, `core/head_frame.py`, `core/bids.py`, `core/montage.py`, `core/jsmath.py`, `tests/cli/parity/coordinates.mjs`, `tests/cli/test_mni_head_frame.py`, `tests/service/node_tests.toml`.
- **Tests and parity:** byte-equal designs (with `source_metadata`) and MNI exports on the fixtures of check-coordinate-interop and check-head-registration (whose own checks stay N) and check-cli's montage site, which becomes P; on generated head frames (random similarity transforms, noise, units, landmark aliases, 1 to 6 regions, refusals off the scalp); and on tampered buffers. A time budget for registration in pure Python (500 iterations × 67 projections at most).
- **On this Mac:** all of it. **Needs Linux:** CI. **Downloads:** none.
- **Size:** large.

Result: done on macOS, 2026-11-26 (delivered together with slice 4). `core/ernie_mni.py`, `core/head_registration.py` (500-iteration similarity ICP with power-iteration eigenvector and fdlibm `acos` matching `rotation_deg` to the last bit), `core/montage.py` and `core/bids.py` implement `export --format mni` and `design` from MNI BIDS pairs, digitized head frames with landmarks, and `.elc`/`.sfp` montages (`--unit`), verified byte for byte in `tests/cli/test_design_export.py`. Needs Linux: CI parity.

### Slice 14 — documentation for the installed application

- `docs/installation.md` and `docs/installation.zh-CN.md`: `conda create` from conda-forge, `data install`, `serve`, `examples run`; that records live in the environment and `conda env remove` deletes them (0002, decision 1); that reception v2 needs SimNIBS and is not available in the installed form; the refusal of a read-only prefix.
- The navigation: installation first, source installation second, and the Node host's pages in a group "Legacy Node host (until phase 4)".
- `docs/command-line.md` describes the Python commands only (U8's rule, no Node needed) and points to the Node CLI as the legacy reference; `README.md` points to the installation page.
- `CHANGELOG.md` as the release notes, since an identity change must be announced there (0001, decision 8).
- `server/static.py`: the 503 for an unbuilt site gives installed-form advice instead of "run mkdocs build at the top of the repository".
- The private-repository wording stays until the switch (checklist).
- **Files:** `docs/installation.md`, `docs/installation.zh-CN.md`, `mkdocs.yml`, `README.md`, `docs/command-line.md`, `examples/README.md`, `CHANGELOG.md`, `src/eeglayoutlab/server/static.py`, `tests/service/test_static.py`.
- **Tests and parity:** `mkdocs build --strict` (a venv with the exact pins of `docs/requirements.txt` in another session's scratch built this branch cleanly at 6bdfd43: 37 pages, 5.7 MB, no warning); the static tests for the new message. No identity input is touched.
- **On this Mac:** all of it. **Needs Linux:** none (`docs.yml` builds on CI).
- **Downloads:** none while that venv exists; otherwise `pip install -r docs/requirements.txt`, about 15 MB (estimate), asked first.
- **Size:** medium.

Result: not started.

### Slice 15 — showcase on the Python service

- `webapp/scripts/build-showcase-data.mjs` signs in through `helpers/service-session.mjs` (`EEG_SERVICE_RUNTIME`). Today every request it makes to `eeglayoutlab serve` gets 401, so only the frozen Node host can regenerate the showcase's data.
- Its stub of the signal records writes `scope: 'workspace'`, as the Python service answers.
- `SHOWCASE_INSTALL_URL` (`webapp/lib/showcase.ts`) points to the site's installation page; the GitHub README it names today is a 404 while the repository is private, and describes the source installation.
- `docs/showcase.md` describes regeneration from `serve --cache-only`. The committed data in `webapp/showcase/api` is not regenerated unless the user asks, and then only on an APFS clone.
- **Files:** `webapp/scripts/build-showcase-data.mjs`, `webapp/lib/showcase.ts`, `webapp/components/showcase-banner.tsx`, `webapp/scripts/check-showcase.mjs`, `docs/showcase.md`.
- **Tests and parity:** `test:fast` (check-showcase; check-i18n if the banner text changes), `npm run build:showcase`, `serve-showcase.mjs` and a pass in Chrome; none of these has run since phase 2's slice 10.
- **On this Mac:** all of it. **Needs Linux:** none. **Downloads:** none.
- **Size:** small.

Result: not started.

### Slice 16 — CI: browser tier

- A fixture builder (`webapp/scripts/build-browser-fixtures.mjs`, or a subcommand of the Python command line) computes the records the cache-only scripts need on a composed root: the golden design request, the AL + AR 35 mm layout, the 8 cases of `tests/service/fixtures/robustness`, a v1 signal simulation, and a stored v2 signal result.
- `.github/workflows/browser.yml` runs `eeglayoutlab serve --cache-only` and the key-workflow scripts: check-head-viewer, check-workspace-projects-browser, the two coordinate checks, check-robustness-browser, check-research-workflow-browser `--stage2` and `--stage3`, check-project-workflow-browser `--with-delivery`, and check-workflows-browser without its v2 computation. It sets `EEG_SERVICE_RUNTIME` and `EEG_BROWSER_EXECUTABLE` to the runner's Chrome, and uploads `EEG_QA_OUTPUT`.
- Reception v2 computation, `--native` and check-radius-recovery-live stay manual on the Mac (U26).
- **Files:** the fixture builder, `.github/workflows/browser.yml`, `webapp/scripts/check-*-browser.mjs` (fixture variables only), `CONTRIBUTING.md`.
- **Tests and parity:** locally, on an APFS clone with Chrome, every selected script passes against `serve --cache-only`.
- **On this Mac:** the builder and the scripts. **Needs Linux:** the CI run, headless WebGL through SwiftShader included.
- **Downloads:** none locally (Chrome is installed); the runner's preinstalled Chrome in CI.
- **Size:** large. It needs slice 10's data source.

Result: not started.

### Slice 17 — release workflow and versioned documentation

- `.github/workflows/release.yml`, on `v*` tags: the slice 10 package build, the interface bundle (`webapp/dist/client`) as a tarball with its SHA-256, the `showcase-dist` tarball, `mike deploy X.Y` with the alias `latest` (and `dev` from `main`) under the `docs/` prefix of a storage branch, and a draft GitHub release holding the assets, which only the user publishes.
- `pages.yml` assembles the showcase at the root with the documentation versions from the storage branch (U27). It deploys only after the checks pass, and its `configure-pages` step gets `pages: read` or is dropped.
- `mike` goes into `docs/requirements.txt`, and `extra.version.provider: mike` into `mkdocs.yml`.
- Release metadata: `CITATION.cff`, `.zenodo.json` and `SECURITY.md`.
- **Files:** `.github/workflows/release.yml`, `pages.yml`, `docs.yml`, `docs/requirements.txt`, `mkdocs.yml`, `CONTRIBUTING.md`, `CITATION.cff`, `.zenodo.json`, `SECURITY.md`.
- **Tests and parity:** `mkdocs build --strict`; `mike deploy` into a throwaway local repository in scratch, never pushed, to check the version selector and the 404 page; the workflows parse. The real run needs a tag pushed by the user.
- **On this Mac:** all of it but the run. **Needs Linux:** the run on CI.
- **Downloads (asked first):** mike and its pinned dependencies from PyPI, well under 1 MB (estimate).
- **Size:** medium.

Result: not started.

### Slice 18 — Linux verification (needs Linux)

Every "needs Linux" step of slices 1 to 17 in one run, on a CI runner after the user pushes or on a machine the user names:

- the fast tier, the parity suites of slices 4 to 13 (V8's sin and cos on Linux against the port), and the runtime fingerprint in search identities end to end;
- the noarch package built and installed from a linux-64 cortech channel, `data install`, `examples run` against `expected.json`;
- in that environment, D keys that carry both the fingerprint and the environment rows.
- **Files:** `.github/workflows/checks.yml` if a run needs it, `packaging/conda-forge/eeglayoutlab/run_test.py`, the results in both recipe READMEs.
- **Downloads:** runner packages and data packages, listed with sizes at that time.
- **Size:** medium.

Result: not started.

## Public steps: a checklist for the user

These are not slices: each one makes something public, and only the user takes it.

- **When.** The repository goes public at the SoftwareX or JNE submission or preprint, not before (U28). Until then the work above continues privately. Check whether `pages.yml` has already deployed the method pages to the showcase's domain (`docs/showcase.md` says it is hosted).
- **Before the switch** (prepared privately in slices 9, 14 and 17): `THIRD_PARTY_NOTICES.md` with cortech, IXI and the bundled npm packages; `CITATION.cff`, `.zenodo.json`, `SECURITY.md`, `CHANGELOG.md`; third-party actions pinned to commit SHAs with dependabot updates, which needs network lookups.
- **Wording that names the private repository:** `README.md:58`, `data/README.md:18`, `docs/data-and-reproducibility.md:15` and `:29`, `docs/source-installation.md:16` and `:27`, and 0001's note on macOS runner minutes.
- **History.** Publish it as it is: rewriting breaks the tags v0.1.1 to v0.2.0 and `node-host-freeze` and the release links. Four early commits (73559b4, ec0602e, 069e922, 36c052f) carry wording that later commits corrected, and the commits use two email addresses. Do not push the local branches `claude/charming-mccarthy-451647` and `claude/web-app-deployment-plan-3ee36e`: six of their commits carry attribution trailers, and none of them is on `origin` or in `HEAD`.
- **Licences.** The CC BY-NC Ernie display data tracked in git and its history becomes downloadable; its attribution is in place and the NonCommercial terms apply. The IXI decision (U20) comes before any head package is published.
- **After the switch:** macOS CI on every push (U25); the `SHOWCASE_CNAME` variable for `pages.yml`; the data release (U18); cortech on conda-forge after the upstream agreement and an SPDX licence (U22), then eeglayoutlab from a release tarball; then the exit on a fresh Mac and a fresh Linux machine with nothing local.

## Not in phase 3

- **Python 3.12 and 3.13** (0001, decision 10): `<3.12` stays in `pyproject.toml` and the recipe until the suite passes on both versions on both platforms and the Linux lock moves; cortech already builds and projects bit-identically there. Widening changes the interpreter digests, and so the keys, of new installations.
- **The Node CLI, the Node host and their tests** leave in phase 4, with the plugin API and the 1.0 identity decision (0003).
- **Searches with fewer than 64 electrodes** in the command line (U15).
- **The open decisions of phase 2's slice 9** (the legacy import's scope and collisions).

## Where byte equality can break

The command line's written files and the installed form's identities can differ from the reference in these places.

| # | Break point | Rule in Python | Slice |
| --- | --- | --- | --- |
| C1 | `JSON.stringify(v, null, 2)`: spacing, V8 key order, compact `[]` and `{}` | `jsjson.stringify(indent=2)` | 4 |
| C2 | `toFixed` and `toPrecision` ties, sign and exponent spellings | `core/jsmath.py` | 4, 12 |
| C3 | `Number()` parsing of text fields | the port in `jobs/identity.py` | 4 |
| C4 | JavaScript's `\d`, `\s`, `trim`, `toUpperCase` and `toLowerCase` | explicit classes and `js_trim` | 4 |
| C5 | V8's `Array.prototype.sort` in region assignment | `jobs/jssort.py` | 4 |
| C6 | V8's `Math.atan2`, `acos`, `sin`, `cos`, last bit | fdlibm ported, compared on 10^6 inputs | 5, 13 |
| C7 | `Intl.Segmenter` grapheme clusters (ICU's Unicode against Python 3.11's Unicode 14) | UAX #29 on `unicodedata`; differences listed | 5 |
| C8 | mulberry32 (`Math.imul`, `>>>`) | 32-bit masks | 12 |
| C9 | The worker interpreter per command | U8 | 6 |
| C10 | The failure text of a worker | the last error event, else the last stderr line of the first chunk | 6 |
| C11 | Worker timings in real runs | masked in comparisons | 6, 7 |
| C12 | Environment rows | installed form only; a checkout is byte-identical | 3 |

## Decisions

The user accepted the recommended default of each on 2026-11-25.

| # | Question | Recommended default | Reason |
| --- | --- | --- | --- |
| U8 | Worker interpreter of the Python command line (U5; 0002, "CLI interpreter") | Follow the service: `search` runs and fingerprints the compute interpreter (`--python`, else `EEG_COMPUTE_PYTHON`, else the managed runtime, else the installed `P/bin/python`, else `python3`); `evaluate`, `study`, `eeg-summary` and `prior` use the native interpreter | `docs/command-line.md` promises the web service's key, and `--python` then means what the help says. It departs from the Node CLI only off macOS, with a managed runtime and `EEG_COMPUTE_PYTHON` or `--python` set; the docs say so |
| U9 | Which commands move to Python in phase 3 | All nine scientific commands and `examples run`. Only design, export, evaluate, search, study and the examples (slices 4 to 7) gate the exit; pareto, eeg-summary, prior, channels and the MNI and head-frame inputs (slices 11 to 13) may follow it | The conda package has no Node at run time, so a command left in Node is lost to installed users |
| U10 | The Node CLI and `run-examples.mjs` | Kept unchanged as the parity reference until phase 4, with the docs pointing to `eeglayoutlab …`. Like Node's, the Python command line writes no records, queue or workspace files | Node stays the reference while it exists; the command line's documentation promises it writes nothing of the service's |
| U11 | Parity bar of the command line | Written files, stdout tables and exit codes byte-equal with the Node CLI on fixtures and generated inputs; the shared validators' messages verbatim; Node's option names, with usage errors as exit 2 and an `error:` line; progress on stderr free | Phase 2's bar; stderr carries no science |
| U12 | V8 numerics and graphemes | Port V8's `atan2`, `acos`, `sin` and `cos`; UAX #29 on `unicodedata`; accept a difference only for characters newer than Python's Unicode, and document it. Pure Python floats in `core/` and `figures/`, no numpy | The SVG (`toFixed(2)`) and `rotation_deg` are visible in bytes; numpy reorders sums |
| U13 | Where design and export read the Ernie mapping and surface | `R/webapp/public` from `repository_root()`, so `--root` applies to them too | The installed form has `webapp/public` only in R; Node reads its own code folder, which is R in a checkout |
| U14 | Where `examples run` writes | In a checkout `R/examples/outputs`, as Node. In the installed form `./eeglayoutlab-examples` unless `--out-dir`, and never inside R. `--update-expected` only in a checkout | 0002 says outputs go to a directory the user names; package files must not change |
| U15 | Searches with fewer than 64 electrodes in the command line | Keep Node's behaviour (design refuses them; the figure's subtitle says 64) and fix both later | Parity first; variable electrode counts came with `main` 8fdbffd, and the Node CLI was not updated |
| U16 | Which conda-meta records become identity rows | Only the numerical closure (python, numpy, scipy, numba, llvmlite, nibabel, cortech, the BLAS packages, and their dependencies from the records' `depends`), never eeglayoutlab's own record or service-only packages; 0002 is amended | 0002's literal `conda-meta/*.json` changes every D, E, V2 and St key at each release and at any unrelated `conda install`, against 0002's requirement 5 |
| U17 | When the environment interpreter and rows apply | Only when the package is installed, not in a checkout, and R is the installed root; P spelled as its real path | `eeglayoutlab --root <checkout>` from an environment then keeps the checkout's rules and keys; integrity compares real paths |
| U18 | Where the data packages are published, and how the code names them | One Zenodo record per data release, holding all 15 manifests and archives side by side (36 % of one record, 30 files, one DOI), and the index `data/packages.json` in R with URLs and digests. A `file://` mirror until then; nothing is published without the user | 0001, decision 7; private release assets need a sign-in; an archive must sit beside its manifest |
| U19 | `eeglayoutlab data install` with no argument | `base` and `scalp-node-table` (1.8 GB); `--examples` adds the eleven heads of example 3 (13.34 GB). In the installed form it composes into R afterwards (`--no-compose`); a checkout composes explicitly | The installed form has no FEM, so new coordinates need the table; the heads are large and their licence is open; the exit names only `data install` and the examples |
| U20 | The IXI licence and example 3 | Decide the IXI head licence, or move `mapping.npz` into its own package, before any head is published; until then example 3 runs only from a local mirror or the CI cache | Example 3 needs ten IXI heads under combined CC BY-SA and CC BY-NC terms |
| U21 | Documentation in the installed package | Build the site at package time into `R/site` (about 5.7 MB), and change the 503 text in either case. The installation inventory proposed not building it; this plan prefers shipping it | `serve` serves `/docs/` from `R/site`, offline and matching the installed version. Cost: mkdocs-material in the recipe's build requirements |
| U22 | cortech on conda-forge | The user contacts the SimNIBS maintainers now (an upstream agreement, the SPDX licence, a stable source); rehearsals use a local cortech channel; eeglayoutlab is submitted after cortech's feedstock exists | The exit says conda-forge, and cortech's feedstock waits on people, not code |
| U23 | Local builds and downloads | Reuse what is on disk: rattler-build 0.81.0 with its caches and the local cortech channel (2026-11-23 scratch), `~/miniforge3`, the docs venv, Chrome. Ask before each download with source and size: the conda-forge repodata and missing packages (slice 9), the docs pins if the venv is gone (slice 14), mike (slice 17), optionally actionlint | Those caches live in other sessions' temporary scratch, which a reboot can remove; rattler-build has no offline mode |
| U24 | `test_iid_pin`, which fails on `main` | Find and fix the cause before CI is enabled, not mark it expected to fail | It pins the iid arithmetic bit for bit; quarantining it would hide a science regression, and leaving it keeps CI red on both platforms |
| U25 | CI runners and versions | `ubuntu-24.04` and a pinned macOS arm64 label; Node 24.22.3 on both and 26.5.0 on Linux, engines `>=22.18.0`; Python 3.11 only; macOS on pull requests to `main`, pushes to `main` and by hand while private, on every push once public | Fixed OS versions and exact Node versions, so that a toolchain change cannot look like a science change (a hosted label still gets a new image about weekly, and the run log names it); phase 2's parity ran on exactly these Node versions; macOS minutes cost more while private |
| U26 | Data and browsers in CI | The cache is seeded from a private pre-release holding the package archives (each at most 1.40 GB), made by the user, until the Zenodo release. Examples 1 and 2 on pushes to `main` and nightly (1.81 GB cached); example 3 only in the package job or by hand. Browser tier: cache-only scripts with fixtures computed in the job; reception v2, `--native` and radius recovery stay manual | Works while private with the job's token; the Actions cache holds 10 GB per repository by default and all examples need about 15 GB; native runs need about 10 GB; the radius fixture is a scientific choice |
| U27 | What the website follows | The showcase and the documentation's `latest` follow the latest release tag, `dev` follows `main`; mike writes versions to a storage branch that `pages.yml` copies under the showcase | Visitors see what conda-forge installs; the versions survive each artifact deploy |
| U28 | When the repository goes public | At the SoftwareX or JNE submission or preprint, not before; history published as it is | The methods are unpublished. conda-forge needs a public source, so the literal exit follows this switch |

## Risks

- **The literal exit waits on public steps:** the public repository (U28), cortech's feedstock (U22), the data release and the IXI decision (U18, U20), and a push for every Linux run. Until then the exit is shown only as rehearsals.
- **The first CI run is the first ever.** Linux B9, the Linux run path and the macOS runner never ran there, so several failures may come at once. The 20-minute limit was never timed on runner hardware, and the `check-operations.mjs` hang can make `test:fast` flaky.
- **Last-bit numerics.** A port of V8's `atan2`, `acos`, `sin` and `cos` can still differ from the reference build in the last bit; after `toFixed(2)` that rarely shows in the SVG, but `rotation_deg` is written raw into `source_metadata`. `toFixed` and `toPrecision` ties differ from Python's formatting (for example 0.5078125 to 6 digits).
- **Unicode versions.** `Intl.Segmenter` follows ICU in Node 26 and 24, Python 3.11 has Unicode 14; JavaScript's regular expressions and case mapping differ from Python's. A literal translation passes the fixtures and fails generated names, as `trim` did in phase 2.
- **Pure-Python speed** (a guess until measured): registration runs up to 500 iterations of 67 projections, and channel subsets draw about 200 random sets per count. Expect seconds to minutes where Node takes under a second; numpy would break bit parity.
- **Real-run comparisons** must mask worker timings, and the radius search's 135 s soft deadline can make a search's result depend on load.
- **The interpreter rule.** Whichever rule U8 picks, the two command lines differ in one configuration (a managed runtime with `EEG_COMPUTE_PYTHON` or `--python`). On macOS keys carry no runtime member, so another interpreter changes results without changing keys; the service has the same gap today.
- **Pydantic is only in the service extra.** `evaluate`, `search` and `study` need it; the recipe must keep it a run dependency.
- **No Node counterpart for the installed form.** Its root, interpreter and rows rest on Python tests alone, while checkout keys must stay byte-identical against Node.
- **Shared hard links.** Composing a data file into a second environment changes its inode's ctime, which invalidates the integrity memo; a request being hashed at that moment fails once with `输入文件正在变化`.
- **Local builds are fragile.** rattler-build is not offline, its binary and caches sit in another session's temporary scratch, and the 2026-11-23 package and environment predate phase 2's slices 8 to 10.
- **conda-forge review** may object to exact pins in a noarch recipe (0002, decision 2) and to `npm ci` during the build; cortech's source is a GitHub tag archive whose SHA-256 is not guaranteed to stay stable.
- **Data volume.** Archives of 1.1 to 1.4 GB, about 15 GB for all examples with the table, without resume or retry and with a 60 s timeout. The Actions cache holds 10 GB by default and runner disks have about 14 GB free.
- **Documentation toolchain.** Material for MkDocs reaches end of life on 2027-05-05 and Zensical does not run the hooks; mike's branch model conflicts with artifact deploys. The strict build relies on a venv in another session's scratch.
- **Licences.** The NonCommercial Ernie data in git becomes downloadable with the public switch; the IXI ShareAlike plus NonCommercial combination is unresolved; the notices lack cortech, IXI and the npm packages until slice 9.
- **Node 24.22.3** is not on `PATH`: phase 2 ran it from `/Applications/ChatGPT.app/Contents/Resources/cua_node/bin`, an application's bundled copy that an update of that application can replace.
- **The Node test map.** Each CLI-mapped site must become P in the slice that adds its Python target, or `test_node_test_map.py` fails.
- **Users must be told** that reception v2 is not available in the installed form and that `conda env remove` deletes the environment's records.
