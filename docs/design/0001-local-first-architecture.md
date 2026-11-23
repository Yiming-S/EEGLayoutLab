# 0001 — Local-first application with a Python service

- **Status:** proposed
- **Date:** 2026-11-22
- **Applies after:** 0.2.0
- **Current architecture:** [architecture.md](../architecture.md)

## Summary

EEGLayoutLab is to become a local-first scientific application for macOS and Linux. Users install a package, run `eeglayoutlab`, and work in the browser. A local Python service serves the prebuilt interface and runs each calculation in its own Python process. The Node HTTP host is to be replaced by this Python service in stages; existing results, delivery packages and scientific cache keys are to remain valid throughout.

The project is to be maintained over a long term and used for real work, not only as a published artifact. The decisions below favour one place to define each contract, a science core that does not depend on the service, explicit extension points and independent versioning of code, data and result formats.

## Context

At 0.2.0 the application has three stacks:

| Part | Language | Size (lines) | Role |
| --- | --- | --- | --- |
| `webapp/app`, `features`, `components`, `lib`, `viewer`, `client` | TypeScript/React | about 19,000 | Browser interface |
| `webapp/server` | JavaScript (Node) | about 6,300 | HTTP host, request checks, identity, queue, projects, deliveries |
| `src/compact_eeg`, `scripts` | Python | about 14,600 | Science and worker entry points |

Several properties of 0.2.0 make the change possible:

- Every route page is a client component, so the interface can be built as static files.
- With a published scalp-node table, new-coordinate evaluation no longer needs SimNIBS. On the reference Mac an evaluation peaked at 0.39 GiB, and on emulated Linux an evaluation worker peaked at 442 MiB and the radius search at 737 MiB ([server deployment](../server-deployment.md#memory-and-the-scalp-node-table)).
- `/deliveries` already reads a delivery package in the browser without the project or task APIs.

Two properties make it worthwhile:

- **Request checks are written twice.** The Node normalizers and the Python validators are kept in agreement by shared fixtures ([contracts](../../contracts/README.md)); no schema is generated from either side. Each wire change has to be made in two languages and two test suites.
- **Much of the Node host serves anonymous public visitors.** The community queue, signed anonymous sessions, the proxy access policy, operations logging and admission, library moderation and project credentials (about 1,100 lines in `community-queue.mjs`, `http/` and `operations/`, plus parts of `projects/` and `library/`) have no counterpart in a single-user local application.

## Decisions

### 1. Product forms

| Form | Now | Later |
| --- | --- | --- |
| Local application (macOS, Linux) | Main line | Main line |
| Static showcase (read-only, no computation) | Build | Keep examples current |
| Server edition (accounts, computation) | Reserve interfaces only | Deploy when an institution or collaborator needs it |
| Public anonymous computing service | Not built | Not built |

- **Public anonymous service.** It would carry permanent costs for hosting, security updates, abuse control and removal requests. Its one execution slot would also queue visitors under load. Its requirements would shape the core service around strangers rather than the people who use the application.
- **Static showcase.** It is built from the same frontend in a read-only mode and hosted on static hosting such as GitHub Pages. It shows a curated example library, the 3D head, scores and method pages, and opens delivery packages. It stores no visitor data and runs no calculation.
- **Server edition.** It is the same Python service with accounts, per-user workspaces and HTTPS behind a reverse proxy. Only its interfaces are reserved now (see decision 6).

### 2. Platforms

- **Supported:** macOS on Apple Silicon and Linux x86_64.
- **Not supported:** Windows and Intel Macs.
  - macOS 26 is the last macOS release for Intel Macs.
  - GitHub's last hosted Intel macOS runner, `macos-15-intel`, is expected to retire in 2027. After that, the platform could not be tested on every change.
  - cortech publishes no Intel macOS build.
- **Later:** Linux aarch64 can be added once every binary dependency builds there.

The minimum macOS version follows the dependency wheels; cortech 0.1 is built for `macosx_11_0_arm64`.

### 3. Package structure

The Python distribution `eeglayoutlab` contains the service, the command line and the prebuilt interface. Planned layout:

```text
eeglayoutlab/
  core/       science: geometry, metrics, priors, robustness (no HTTP, no queue)
  forward/    forward-field backends: lead-field bank, scalp-node table, FEM
  schemas/    the single definition of request and result formats
  jobs/       scientific identity, cache, queue, one process per job
  server/     HTTP API (local mode; accounts added for the server edition)
  cli/        command line
  data/       data packages: download, verification, versions
  plugins/    extension registries
  static/     built interface (generated, not edited)
frontend/     React source of the interface
```

**The science code stays at `src/compact_eeg` until 1.0.** Scientific identities hash repository-relative paths such as `src/compact_eeg/metrics.py`, so moving the files would change every cache key. The new `eeglayoutlab` package imports `compact_eeg`. Moving it into `eeglayoutlab/core` is a deliberate identity change reserved for 1.0. Old records stay readable; only cache reuse is lost (see decision 8).

### 4. One definition of each contract

- **Python schemas are the only source.** Request and result formats are defined once in `eeglayoutlab/schemas`. The OpenAPI document and the TypeScript types used by the interface are generated from them, so a mismatch between interface and service fails type checking instead of surfacing at run time.
- **The fixtures become parity tests.** The shared fixtures in `contracts/fixtures/` stay. During migration they check that the Python normalizers produce exactly the canonical JSON of the Node normalizers.
- **The command line uses the same schemas,** as do any notebook API built on them.

The proposed web stack is Pydantic for schemas and FastAPI on Uvicorn for the service, because OpenAPI generation comes with them. The choice is confirmed in phase 0 (see migration).

### 5. Science core and forward backends

- **`core` does not import the service.** The browser, the command line and notebooks call the same `core` functions.
- **Forward fields come from three backends behind one interface:** bank, table and FEM. The backend is chosen exactly as today, and a mismatched table is still an error, never a silent fallback to FEM.
- **FEM and builders are author-side only.** FEM needs SimNIBS, which is an optional dependency installed only where tables and head packages are built. User installations compute from bank and table data.

### 6. Local service

- **Process per job.** Each calculation runs in its own Python process, as the current workers do. An evaluation from the table takes about a second, so a long-lived kernel would save little. Starting each job from a clean process keeps results reproducible and isolates crashes.
- **One queue and one execution slot per workspace.** The queue is kept on disk. Cache lookups do not take the slot.
- **Access.** The service listens on 127.0.0.1 only and generates a random token at start. The opened URL carries the token and exchanges it for an HttpOnly cookie. Host and Origin checks stay to prevent DNS rebinding.
- **Instance reuse.** A lock file and runtime file per workspace let a second `eeglayoutlab` call open the running instance instead of starting another.
- **Reserved for the server edition.** Every request carries a user context, and storage paths are resolved from it. In local mode the context is the single local user.

### 7. Workspace, cache and data

- **Workspace.** The user chooses a workspace directory (`eeglayoutlab ~/my-study`). It holds projects, saved layouts, notes, comparison settings and immutable result snapshots as readable files. It can be backed up, kept in git, or sent to a collaborator. Sharing happens through delivery packages; the owner and read-only credentials of 0.2.0 are not carried over.
- **Cache.** Calculation results are stored by scientific identity in a per-user cache directory shared by all workspaces. Removing the cache never removes workspace snapshots.
- **Data packages.** The base bundle, the scalp-node tables, the conductivity-scenario tables and each head package are separate packages with their own version and SHA-256 manifest. They live in the user data directory (`~/Library/Application Support/EEGLayoutLab` on macOS, `$XDG_DATA_HOME/eeglayoutlab` on Linux).
- **Data commands.** `eeglayoutlab data install`, `list`, `verify` and `remove` manage them, showing progress and checking SHA-256 after each download. Data is published on Zenodo so that each version has a DOI.

### 8. Versions and compatibility

There are three independent version lines.

| Line | Rule |
| --- | --- |
| Code | Semantic versioning. 0.x until the Python service and plugin API are stable; 1.0 then |
| Data packages | Own version and manifest per package; a code release declares the package versions it accepts |
| Result and file formats | Schema names with versions (`…/1`, `…/2`). Every released version stays readable |

Guarantees during migration:

- **Results stay valid.** Existing result records and delivery packages stay readable, and scientific cache keys stay unchanged until 1.0.
- **Identity changes are planned.** An identity change is announced in the release notes. It never rewrites existing records.

### 9. Extension points

Extensions register through Python entry points. Planned groups:

| Group | Adds |
| --- | --- |
| `eeglayoutlab.noise_models` | Noise covariance models |
| `eeglayoutlab.metrics` | Layout metrics |
| `eeglayoutlab.coordinate_formats` | Coordinate importers and exporters |

New head models are data packages, not code, using the existing head package format.

An extension declares its options in its schema. The interface renders declared options generically, so adding an extension needs no interface change. Each extension's code and data enter the scientific identity of the requests that use it, as `data_prior` files do today.

The plugin API is published only after phase 4; until then the registries are internal.

### 10. Dependencies

| Dependency | Status | Plan |
| --- | --- | --- |
| cortech 0.1 (GPL-3.0) | Not on PyPI or conda-forge. GitHub release wheels exist for CPython 3.11 and 3.12 only. Used through `cortech.Surface` in `cortical_fem.py`, `scalp_node_table.py` and `design_evaluation.py` | Maintain a conda-forge recipe built from source, in coordination with the SimNIBS maintainers. Evaluate an own implementation of the projection, accepted only if it reproduces the current projections within the existing checks |
| SimNIBS 4.6 | Large; needed only for FEM, table and head building | Optional, author side |
| numba, numpy, scipy, openblas | Available on conda-forge for both platforms | Pinned per release |

**Distribution.** conda-forge is the main installation channel, because it ships the binary dependencies for both platforms. A PyPI package follows once every dependency installs from PyPI. Python support widens from 3.11 to 3.11–3.13 as cortech builds for those versions.

### 11. Testing and release

- **Every push** runs unit, schema-parity and contract tests on macOS arm64 and Linux x86_64.
- **Data tests** run with the data packages restored from the CI cache. They include the numerical regression against frozen results and the examples with expected scores.
- **Browser tests** run the key workflows against the Python service: design, evaluation, import, comparison, reception, studies and deliveries.
- **A tag** builds the conda package, the interface bundle, the showcase site and the versioned documentation.

macOS runners cost more minutes on a private repository; making the repository public removes that cost.

## Migration

Each phase ends with the application fully usable.

| Phase | Work | Exit criteria |
| --- | --- | --- |
| 0. Prerequisites | Build the interface as static files without the Node host. Build cortech from source on both platforms. Confirm the web stack | All pages render from the static build behind a plain Python static server. cortech imports and projects on both platforms |
| 1. Schemas | Create the `eeglayoutlab` package and its schemas. Generate the TypeScript types and use them in the interface. The Node host remains in service, unchanged | For every fixture, the Python normalizer gives exactly the Node canonical JSON. The interface type-checks against generated types |
| 2. Python service | Implement the API: design, evaluation, editing, import, comparison, reception, studies, workspace and deliveries. Implement the queue and the identity. Switch the interface to the Python service | For the same requests on the same installation, Python request keys equal Node request keys. All browser workflows pass against the Python service. Every Node test is ported or mapped to a Python test |
| 3. Distribution | Data package commands, conda-forge packages (including cortech), CI on both platforms, documentation site, public repository, static showcase | On a fresh Mac and a fresh Linux machine: install from conda-forge, `eeglayoutlab data install`, run the examples, and match the expected scores |
| 4. Retirement | Remove the Node host and its tests. Publish the plugin API. Decide the 1.0 identity change | The repository contains one service implementation. The plugin API has documented examples |
| Later | Server edition | Deployed when an institution or collaborator needs it |

### Retired with the Node host

- **Retired:**
  - the anonymous community queue and signed anonymous sessions;
  - the proxy access policy and request rate limits;
  - the operator status endpoint, request logs and admission thresholds;
  - the public result library and its moderation tool;
  - project owner and viewer credentials and read-only links.
- **Kept:** the delivery package format, project snapshot formats (read compatibility) and all result schemas.

The 2026-11-20 decision to keep the hosted result library public applied to the public service. It lapses with that service. The showcase library is curated by the maintainer.

## Alternatives considered

- **Keep the Node host and add a launcher.** This needs the least change. Users would still install both Node and Python, and request checks would stay duplicated.
- **Public anonymous computing service.** Rejected for the reasons in decision 1.
- **Fully in-browser computation (WebAssembly).** Pyodide limits memory to about 2 GB, has no subprocesses or threads, and has no cortech build. The table path reads only 192 rows (about 6.7 MB) for a 64-electrode evaluation, so a static computing demo is possible in principle. It would require porting the projection and the estimators; this is not planned.
- **Native desktop wrapper.** Retired in 0.2.0 and not reconsidered here.

## Open questions

- **Web stack.** Pydantic and FastAPI is proposed; confirm in phase 0.
- **Rename at 1.0.** Whether to move `compact_eeg` into `eeglayoutlab/core` at 1.0, accepting the identity change.
- **Plugin options in the interface.** How extensions declare options that the interface can render generically.
- **cortech.** Whether its maintainers publish packages, or the project keeps its own recipe.
- **Linux aarch64.** Support depends on every binary dependency building there.
