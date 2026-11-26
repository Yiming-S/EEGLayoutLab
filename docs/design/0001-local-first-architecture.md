# 0001 — Local-first application with a Python service

- **Status:** proposed; phase 0 complete ([results](#phase-0-results)); phases 1 and 2: the interface runs on the Python service (slices 1 to 10 of the [phase 2 plan](0001-phase-2-plan.md)), and the phase 2 exit is still open ([phase 2 results](0001-phase-2-plan.md#phase-2-results))
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

The minimum macOS version follows the dependency wheels; cortech 0.1 is built for `macosx_11_0_arm64`, and the draft conda-forge recipe was built in phase 0 with the same deployment target, 11.0.

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

The package lives at `src/eeglayoutlab`, beside `src/compact_eeg`.

**The science code stays at `src/compact_eeg` until 1.0.** Scientific identities hash repository-relative paths such as `src/compact_eeg/metrics.py`, so moving the files would change every cache key. The new `eeglayoutlab` package imports `compact_eeg`. Moving it into `eeglayoutlab/core` is a deliberate identity change reserved for 1.0. Old records stay readable; only cache reuse is lost (see decision 8).

### 4. One definition of each contract

- **Python schemas are the only source.** Request and result formats are defined once in `eeglayoutlab/schemas`. The OpenAPI document and the TypeScript types used by the interface are generated from them, so a mismatch in shape or in a set of allowed values fails type checking instead of surfacing at run time. Cross-field rules, coordinate and spacing checks and digit limits are checked only by the service.
- **The fixtures become parity tests.** The shared fixtures in `contracts/fixtures/` stay. During migration they and generated variants (below) check that the Python normalizers produce exactly the canonical JSON of the Node normalizers.
- **The command line uses the same schemas,** as do any notebook API built on them.

**Web stack: Pydantic 2 for schemas and FastAPI on Uvicorn for the service** (confirmed in phase 0). OpenAPI 3.1 generation comes with them. In phase 0 the design-evaluation request and the `design-submission/1` envelope matched Node on the 20 design-evaluation cases of the shared fixtures and on about 1,300 generated request texts. Requests that Node accepts gave its canonical JSON byte for byte, and requests that Node rejects were rejected. The generated texts were also sent through FastAPI's test client ([schema parity](../../tests/schema_parity/README.md)).

Until the Node host is retired, every request schema follows these rules:

- **JavaScript semantics.** Request JSON is parsed and written with JavaScript's rules, implemented in `eeglayoutlab.schemas.jsjson`:
  - every JSON number is a double, as in `JSON.parse`, so `1e400` and very long integers become `Infinity`; the literals `NaN` and `Infinity` are rejected;
  - numbers are written as ECMAScript `Number::toString` writes them (`1`, `1e-7`, `0.000001`, `1e+21`);
  - `Math.hypot` follows V8 bit for bit; Python's `math.hypot` can differ in the last bit, which changes the outcome of the 4 − 1e-7 mm spacing check;
  - string lengths and slices count UTF-16 units, lone surrogates are escaped as `JSON.stringify` does, and `trim` uses JavaScript's whitespace set.

  Numbers and integers are checked by before-validators with `typeof` and `Number.isInteger` semantics. String lengths are checked in after-validators, because Pydantic's `max_length` and `pattern` reject lone surrogates that Node accepts. Pydantic's own JSON parser and type coercion are not used for requests.
- **Explicit canonical form.** Each format has a `canonical()` builder in Node's key order that omits defaults exactly as Node does. Canonical JSON is never derived from `model_dump`.
- **Generated variants.** Each format has a generator that runs the real Node normalizer over generated request texts. The shared fixtures alone are not enough: when single rules were replaced by the plain Python version, the fixtures caught only the change to number spelling. Errors in `Math.hypot`, UTF-16 slicing, string quoting, parsing and `trim` passed every fixture.
- **Generated TypeScript.** Types are generated with `openapi-typescript --default-non-nullable false`, so request fields with defaults stay optional. The interface's parameter types are narrowed to the generated ones; for design evaluation this is done in phase 1, and `designSubmission` takes and returns the generated types (`webapp/lib/api-types.ts`).
- **Errors.** FastAPI's 422 `{detail}` responses are replaced by 400 `{error, code}`, in the OpenAPI document as well as at run time, and the 413 and 415 checks of the Node route that serves submissions (`communityMiddleware`) are added: the body is limited, as received, to that route's limit for the request kind (65,536 bytes for design evaluation, 32,768 for electrode editing, 4,096 for the others) and decoded as a whole.

A request key is the SHA-256 of `JSON.stringify({request, identity})`, so phase 2 also writes the identity object with `jsjson`. After the Node host is retired, the generated variants can no longer run, but `jsjson`, the validators and the `canonical()` builders stay, so request keys do not change.

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
- **Data commands.** `eeglayoutlab data install`, `list`, `verify`, `compose` and `remove` manage them, showing progress and checking SHA-256 after each download. Data is published on Zenodo so that each version has a DOI.

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
| cortech 0.1 (GPL-3.0) | Not on PyPI or conda-forge. GitHub release wheels exist for CPython 3.11 and 3.12 only. Builds from the v0.1 source tag without patches for CPython 3.11–3.13 on both platforms (phase 0). Used only through `cortech.Surface(...).project_points(...)` in `cortical_fem.py`, `scalp_node_table.py`, `design_evaluation.py` and `scripts/check_environment.py` | Keep the conda-forge recipe built from source ([draft](../../packaging/conda-forge/cortech/README.md)) and submit it in coordination with the SimNIBS maintainers. Stay on 0.1 until a later release reproduces the current projections. Evaluate an own implementation of the projection, accepted only if it reproduces the current projections within the existing checks; `project_points` is about 150 lines of numpy and scipy. cortech's installed files enter the scientific identities, so adopting an own implementation is an identity change (decision 8) even when the projections are equal |
| SimNIBS 4.6 | Large; needed only for FEM, table and head building | Optional, author side |
| numba, numpy, scipy, openblas | Available on conda-forge for both platforms | Pinned per release. The cortech projection is computed by numpy and scipy, and phase 0 compared projections only with the runtime's numpy 2.3.0 and scipy 1.17.1, so an upgrade needs its own projection check |

**Distribution.** conda-forge is the main installation channel, because it ships the binary dependencies for both platforms. A PyPI package follows once every dependency installs from PyPI. cortech now builds for Python 3.11–3.13; Python support widens from 3.11 to 3.11–3.13 once the test suite passes on 3.12 and 3.13 on both platforms.

### 11. Testing and release

- **Every push** runs unit, schema-parity and contract tests on macOS arm64 and Linux x86_64. While the Node host is in service, schema-parity tests include the variants generated by the Node normalizers (decision 4).
- **Data tests** run with the data packages restored from the CI cache. They include the numerical regression against frozen results and the examples with expected scores.
- **Browser tests** run the key workflows against the Python service: design, evaluation, import, comparison, reception, studies and deliveries.
- **A tag** builds the conda package, the interface bundle, the showcase site and the versioned documentation.

macOS runners cost more minutes on a private repository; making the repository public removes that cost.

## Migration

Each phase ends with the application fully usable.

| Phase | Work | Exit criteria |
| --- | --- | --- |
| 0. Prerequisites (complete) | Build the interface as static files without the Node host. Build cortech from source on both platforms. Confirm the web stack | All pages render from the static build behind a plain Python static server. cortech imports and projects on both platforms |
| 1. Schemas | Create the `eeglayoutlab` package and its schemas, starting from the phase 0 design-evaluation schema. Port every request format with its generator of variants. Generate the TypeScript types and use them in the interface. Run the parity tests in CI, with Pydantic, FastAPI and httpx installed so that they do not skip. The Node host remains in service, unchanged | For every fixture and generated variant, the Python normalizer gives exactly the Node canonical JSON. The interface type-checks against generated types |
| 2. Python service | Implement the API: design, evaluation, editing, import, comparison, reception, studies, workspace and deliveries. Implement the queue and the identity. Switch the interface to the Python service | For the same requests on the same installation, Python request keys equal Node request keys. All browser workflows pass against the Python service. Every Node test is ported or mapped to a Python test |
| 3. Distribution | Data package commands, conda-forge packages (including cortech), CI on both platforms, documentation site, public repository, static showcase | On a fresh Mac and a fresh Linux machine: install from conda-forge, `eeglayoutlab data install`, run the examples, and match the expected scores |
| 4. Retirement | Remove the Node host and its tests. Publish the plugin API. Decide the 1.0 identity change | The repository contains one service implementation. The plugin API has documented examples |
| Later | Server edition | Deployed when an institution or collaborator needs it |

Phase 2 is planned in slices in [0001-phase-2-plan.md](0001-phase-2-plan.md). Where the scientific root lies in an application installed from conda-forge (phase 3) is decided in [0002](0002-installed-scientific-root.md). The 1.0 identity change of phase 4 is decided in [0003](0003-identity-at-1.0.md).

### Phase 0 results

Completed on 2026-11-22. Both exit criteria are met, and the web stack is confirmed.

**Static interface.** With `output: 'export'`, all 15 routes are written as static pages (about 26 MB, of which about 20 MB are model files). A Python static server that maps `/name` to `name.html` renders every page. Only the API requests and the browser's automatic `/favicon.ico` request fail. The interface links to `/design`, not `/design.html`, so the Python service needs the same mapping. The Node host serves the same build unchanged.

- The root layout chose the language on the server from cookies and request headers, which prevents static export. The pages are now rendered in English, and the browser switches to the saved or preferred language after loading.
- Nine API requests fail on page load: community records, design-evaluation health, electrode-editor parents and records, local-compute health and library, robustness studies, and source-reception health and layouts.
  - These are among the first endpoints the Python service needs, but not all of them. Requests sent only after another request succeeds do not appear. One example is the header's `/api/community/heartbeat`, posted every 15 seconds once local-compute health answers.
  - Both community endpoints belong to the retired anonymous queue. The Python service needs workspace equivalents for them, or the interface drops them.
- Left for later phases:
  - the English text shown before hydration for Chinese users;
  - the Geist fonts, which are downloaded at build time and must be included in the source before offline and conda-forge builds;
  - the `.br` and `.gz` files that `npm run build` writes beside the model binaries and text assets, which were not checked. The Python service must serve them by content negotiation, or the build must stop writing them;
  - the development server, whose API is the Node service mounted in Vite by `localComputePlugin`. Development against the Python service needs a proxy instead;
  - static stand-ins for the showcase, whose home and library pages read `/api/local-compute/library`, `/api/electrode-editor/records` and `/api/community/records`. The other requests need a clear "no local service" state.

**cortech from source.** cortech 0.1 builds from the v0.1 source tag for CPython 3.11, 3.12 and 3.13 on macOS arm64 and Linux x86_64. The six source builds used the runtime's numpy 2.3.0 and scipy 1.17.1. Each projects bit-identically to the release wheel on the same platform on 6,745 points: the 64 standard positions, the 5,387 bank candidates and displaced candidates. A draft recipe is in [`packaging/conda-forge/cortech/`](../../packaging/conda-forge/cortech/README.md); it builds and passes its tests on both platforms.

- No source patches are needed. Two build settings are: a `cgal.pc` file for pkg-config and `-Dcpp_std=gnu++17`. They can be removed once upstream's `meson.build` handles both.
- Submission to conda-forge waits on the cortech maintainers' agreement and on the licence as an SPDX expression (`GPL-3.0-only` or `GPL-3.0-or-later`). EEGLayoutLab is compatible with either. `THIRD_PARTY_NOTICES.md` does not list cortech yet; it needs an entry before cortech is distributed with EEGLayoutLab.
- Not yet tested: conda-forge's current compiler and sysroot pins (gcc 15, glibc 2.17), Python 3.14, and cross-compiled macOS builds.
- Upstream issues found that do not affect the project's meshes:
  - a crash in `points_inside_surface` on the Ernie scalp; the project does not call it;
  - an `IndexError` in `project_points`, raised through `get_triangle_neighbors`, on meshes in which every vertex has the same number of triangles, such as a single triangle.

**Web stack.** Pydantic 2 and FastAPI on Uvicorn are confirmed with the rules in decision 4. The phase 0 schema covers the design-evaluation request and the `design-submission/1` envelope. The envelope's `source_metadata` is accepted without checks for now; it is ported in phase 1.

- Phase 0 took Node's body handling from an older handler in `design-evaluation-server.mjs`, which decodes the body chunk by chunk and counts the decoded length. That handler is not reached: the route that serves submissions (`communityMiddleware`) counts the bytes received and decodes the whole body once. The phase 1 service follows that route, so the body is decoded as in Node and there is no exception to equal request keys.
- The generated OpenAPI 3.1 keeps the allowed values of the contract, for example `radius_mm: 3 | 6 | 10`.
- `designSubmission` in the interface does not type-check against the generated types in six places:
  - three parameters are wider than the contract;
  - two string literals are widened to `string`;
  - the envelope's `request` inherits these.

  A copy with the generated parameter types type-checks without casts.
- Validation in Python takes about 3 ms per design request, against 0.1 ms in Node. This is small next to an evaluation of about a second.

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
- **Other Python schema libraries.** msgspec, attrs with cattrs, or JSON Schema first with datamodel-code-generator would need the same JavaScript number and string rules (decision 4). Pydantic expressed every rule of the design request, including discriminated unions, nullable required fields and cross-field checks. Litestar is the alternative host if FastAPI's dependency changes become a problem for conda-forge packaging.

## Open questions

- **Rename at 1.0.** Whether to move `compact_eeg` into `eeglayoutlab/core` at 1.0, accepting the identity change.
- **Plugin options in the interface.** How extensions declare options that the interface can render generically.
- **cortech.** Whether its maintainers publish packages, or the project keeps its own recipe; and whether its licence is `GPL-3.0-only` or `GPL-3.0-or-later`.
- **Linux aarch64.** Support depends on every binary dependency building there.
