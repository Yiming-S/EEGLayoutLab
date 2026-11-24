# 0001, phase 2 — the Python service, in slices

- **Status:** in progress; slices 1 to 4 done, slice 5 next. Decisions U1, U2, U3 and U6 were confirmed on 2026-11-23; U4, U5 and U7 are proposed defaults.
- **Date:** 2026-11-23
- **Design:** [0001 — Local-first application with a Python service](0001-local-first-architecture.md), migration table, phase 2

Phase 2 replaces the Node HTTP host (`webapp/server`) with the Python service in `src/eeglayoutlab`. Its exit criteria are:

1. On the same installation, Python request keys equal Node request keys for the same requests.
2. Every browser workflow passes against the Python service.
3. Every Node test is ported to a Python test or mapped.

Notation: **R** is the scientific root (the checkout, holding `results/v2`, `.runtime` and `webapp/public`), **W** a workspace directory, and **Q** Node's queue directory `R/results/web-service`.

## Rules for every slice

- **Node stays the production host until slice 10.** From slice 2 the Python service runs beside it on another loopback port, with the same R and its own W, and serves the same static interface.
- **Shared files.** Both hosts read and write the record trees `R/results/v2/{local_app_jobs, design_evaluation_jobs, electrode_editor_jobs, source_reception_jobs, source_reception_v2_jobs}` and the workers' forward caches. Python never writes Q. Python publishes a `cache.json` once and never replaces a valid one. Side-by-side checks on one installation use lookups only; tests that compute against Python run with Node stopped or on a copy.
- **JSON.** Every value that is hashed, stored or compared as text goes through `eeglayoutlab.schemas.jsjson`, never through Python's `json`; a test enforces this in `jobs/` and `server/`.
- **Record locations stay fixed** at `R/results/v2/*_jobs` until 1.0 (U1). Their paths are literal strings inside some identities.
- **No accidental identity change.** No new top-level `src/compact_eeg/*.py`, and no edits to the code-identity files, the workflow lists in `webapp/server/project-paths.mjs`, `DATA_PRIOR_FILES`, the reception code map or the worker inputs under `webapp/public`. A deliberate science change updates the identity-input manifest in the same commit.
- **Request formats are ported as in phase 1:** a schema, a `REQUEST_FORMATS` entry, a Node variant generator, a `/api/normalize/<name>` route and regenerated types.
- **API version** stays `1`; any other value makes every interface request fail.
- **Done for a slice:** CI green (typecheck, lint, `test:fast`, build, and pytest with `EEG_REQUIRE_SCHEMA_PARITY=1`), the slice's Node tests mapped, and its opt-in checks run once on the author's installation (`EEG_KEY_PARITY_ROOT`, the `data_bundle` and `native_runtime` markers, the slice's live scripts against the Python port).

## Slices

| # | Slice | Usable on the Python port afterwards | Node code it replaces |
| --- | --- | --- | --- |
| 1 | Key core | Design-evaluation identity, admission and key computed in Python, equal to Node's (library code, no HTTP) | `runtime/config.mjs`, `runtime/python-fingerprint.mjs`, `local-input-integrity.mjs` (digest), `runtime/scientific-context.mjs`, the workflow lists |
| 2 | Service host beside Node | `eeglayoutlab serve`: static pages, token-to-cookie access, the four health routes, JSON conventions with per-route body limits, the Node test map | `start.mjs`, `host/*`, `http/{access-policy,responses,public-errors}.mjs`, the health route of `community-queue.mjs` |
| 3 | Read-only library and catalogs | Library, record, bundle, design heads, editor records and parents, reception layouts, all byte-equal to Node | `local-data-library.mjs`, the read side of `storage/records.mjs`, `experiment-bundle.mjs`, the radius format and identity, library reads in the reception and editor services |
| 4 | Job engine and radius search | Lookups, radius jobs, cancel, a durable workspace queue, task status | `jobs/python-worker.mjs`, `jobs/execution-slot.mjs`, record writes, the scheduler of `community-queue.mjs` without its public parts |
| 5 | Design evaluation and electrode names | Coordinate evaluation, import and the comparison test tab | `design-evaluation-server.mjs`, `annotations/electrode-names.mjs` |
| 6 | Electrode editor | Prepare and evaluate edits | `electrode-editor-server.mjs` |
| 7 | Signal reception v1 and v2 | Reception jobs, catalog and saved signal records | `source-reception-server.mjs`, `reception-v2-support.mjs`, `runtime/identity-cache.mjs`, `/api/community/records*` |
| 8 | Robustness studies | Studies stored in W | `studies/*` |
| 9 | Workspace projects and deliveries | Projects in W, delivery export, `eeglayoutlab workspace import-legacy` | `projects/*`, `delivery/*` |
| 10 | Interface switch | Python is the host; credentials and public-service UI removed; every browser workflow passes against Python | the Node host's product path (Node stays in the repository until phase 4) |

Keys come first because every later slice depends on them; the host second, so that each later slice is a set of endpoints with tests; reads before writes, because library record bytes enter the editor and reception keys.

### Slice 1 — key core

Python computes the design-evaluation identity, admission and request key for any request and root, and the bytes equal those of Node's `DesignEvaluationService.context` on the same root with the same interpreter configuration. No HTTP, workers or writes.

- `schemas/jsjson.py`: `stringify` writes object keys in V8 order (array-index keys ascending first, then insertion order) instead of refusing integer-like keys; design results contain such keys.
- New package `src/eeglayoutlab/jobs/`: `nodepath` (Node's POSIX path functions and code-unit sorting), `nodefs` (Node's path encoding, directory names and its two real-path functions), `runtime` (repository root and interpreter selection), `integrity` (input digests with containment and a stable read), `fingerprint` (the Linux runtime probe) and `identity` (the design context, statement by statement).
- Node reference: key-order and path corpora in `tests/schema_parity/reference.mjs`, and drivers `tests/service/parity/identity.mjs` (the real Node wiring on the same temporary root) and `parity/fs.mjs` (Node's real paths).
- Tests in `tests/service/`: key parity over synthetic roots (table, scenario, head, robustness, data prior, managed runtimes, interpreter spellings, odd pointers and pointer bytes, symlinked and misspelled roots, every failure and the error orders Node fixes), and an opt-in real-root mode (`EEG_KEY_PARITY_ROOT`) that also re-derives every stored cache's `result_sha256` and bytes, every design and editor cache key and every batch `request.json` key.

Result (2026-11-23): on the author's installation Python's design key for `{}` equals Node's (`e2f287c3…23dd`, 230 digests), and the real-root mode passes. Three adversarial review rounds (31 confirmed findings, each fixed or listed here) left these known differences, none of which reaches a key on a working installation:

- When two inputs fail, Node reports whichever settles first. Python reports the failure Node reports with one thread-pool worker (the earliest stage, then the first in the list); with Node's default pool of 4 the two can differ, rarely across stages and by timing within one.
- A `SyntaxError` is compared by name; Python's message is not V8's.
- `fs.realpathSync` is ported with a bound of 4,096 links (`nodefs._MAX_RESTARTS`): Node resolves a longer chain, and loops forever on a walk that repeats or keeps growing, where Python raises `ELOOP`.
- V8 converts a nested array to a string recursively and throws `RangeError` beyond a few thousand levels (about 4,500 on Node 26); Python converts any depth. Only a raw request can carry such a value: normalized requests hold strings.

The Linux branch (the `runtime` member of identities, names that are not UTF-8, `execvp`'s PATH search and `/bin/sh` fallback) is reached only in CI, and CI's Node 22 was not run locally.

### Slice 2 — service host beside Node

`eeglayoutlab serve [WORKSPACE] [--root R] [--port N] [--static DIR] [--no-browser]` (`cli/main.py`, a `[project.scripts]` entry) serves one workspace on a free 127.0.0.1 port, with new tokens at every start. It opens the browser from a thread once the service accepts connections, through the private page `W/.eeglayoutlab/open.html` that redirects to the launch URL (Jupyter's redirect file), so the token is never on a browser's command line; only macOS's default launcher, which reads the URL on standard input, gets the URL itself.

- `server/workspace.py`: the marker `eeglayoutlab-workspace.json` and `W/.eeglayoutlab/` (0700) with the `flock` lock, `runtime.json` (0600, written once the socket is bound, removed as soon as SIGINT or SIGTERM arrives while it is still the process's own) and `open.html` (0600, written only while that runtime file is there, so none outlives the process). The state directory must be a directory of this user, not a link; a looser mode is set to 0700, and a file system that keeps the directory or its files open after chmod (FAT, exFAT, NTFS, SMB mounts) is refused before a token is written; its files are opened through a descriptor of it, never through a link, and written under random names, then renamed; the reader of `runtime.json` takes only a private regular file of this user. A second `serve` on a locked W opens the running instance, or, while the holder has no runtime file (starting or stopping), retries the lock for up to 10 s; a file system without locks is refused.
- `server/access.py`, the outermost layer: Node's loopback guard on every path; then the session cookie `eeglayoutlab-<port>` that `GET /open?token=` sets (otherwise 401, JSON under `/api/` and an HTML page elsewhere); then, on `POST`, `PUT`, `PATCH` and `DELETE`, the CSRF token with each route family's Node message.
- `server/app.py`: `create_app(ServiceConfig)`, body limits per task kind, Node's 404 message per prefix and a generic 500 for any unexpected exception. `routes/health.py`: the four health routes.
- `server/static.py`: the export of `npm run build` (14 pages, the 404 page, cache headers, ETag and `Last-Modified`, `HEAD`, 405), never sidecars, dot files or links out of it, and names found exactly as spelled, also on a file system that ignores case; pages answer 503 until the interface is built (its `index.html` is there), and the export and its pages are looked up at every request, so a build made while the service runs is served without a restart. `Last-Modified` names the whole second that the preconditions compare. Conditional and range requests follow vinext's functions (304, 412, `If-Range`, single ranges, its HTTP-date parser), checked against them by `parity/static_requests.mjs`.
- In `webapp/`: the opt-in `EEG_API_TARGET` proxy in `vite.config.ts`, `scripts/helpers/service-session.mjs`, and `check-app-live.mjs` signed in through it; the helper and the proxy take `http://127.0.0.1:<port>` only, never `localhost` or `[::1]`, where another local user could listen on the service's port.
- The Node test map, with the slice's seven access sites ported to `tests/service/test_access.py`.

Result (2026-11-23): health equals Node's real service byte for byte except for the token value, with the worker present and absent, and so do its five headers; the OpenAPI document is unchanged. Against `eeglayoutlab serve` with the author's installation as root, `check-app-live.mjs` passes health, the 11 page routes and the 401 without the cookie, then stops at `GET /api/local-compute/library` (slice 3). Known differences from Node:

- Pages, static files and health need the cookie and pass the guard. Node guarded only the API and answered health to any loopback client.
- The guard lets one cross-site request through: a top-level `GET /open` navigation with the launch token, which is how a browser marks the redirect from `open.html`. It answers 200 with a page that refreshes to `/` instead of the plan's 303, because a browser sends neither the `SameSite=Strict` cookie nor a same-origin `Sec-Fetch-Site` on a redirect in a chain that a cross-site navigation started (checked in headless Chrome: the 303 ends in the guard's 403, the page in the interface). Every other `/open` still answers 303.
- The CSRF check runs before routing, so a write without the token on a path where Node answers 404 or 405 (a `PUT`, `PATCH` or `DELETE` on a compute route, a `PUT` on `/api/projects`) gets 403.
- `GET /api/<kind>/health/<36 characters>` and `.../cancel` are 404 `Unknown queue endpoint`; Node's route pattern answers them with the health body.
- A refusal raises `ApiError` with its status, and any other exception is a 500. Node turned a plain `Error` into a 400 with its message.
- JSON responses carry no `Vary: Accept-Encoding`, `X-EEG-Request-Id` or compression, and `.br`/`.gz` sidecars are 404 ("Not carried over").
- Static files carry a strong ETag, `"<mtime_ns hex>-<size hex>"`, valid because only the original bytes are served; vinext's are weak (`W/"<size>-<seconds>"`, or `W/"<hash>"` for hashed names). So `If-Range` with the file's ETag gets 206 here and the whole file from Node, where only the `Last-Modified` date allows a range. `If-None-Match` and `If-Match` compare weakly on both hosts. `parity/static_requests.mjs` compares the evaluation for Python's ETag, not how the tag is made.
- The OpenAPI document still lists only 400, 413 and 415 for the normalize endpoints, not 401 and 403.

The health and static parity ran on Node 26 only; CI's Node 22 on Linux was not run locally.

### Slice 3 — read-only library and catalogs

The library, its records and bundles, and the catalogs the editor, the signal simulation and the coordinate evaluation read are served by Python with Node's bytes on the same root: `GET /api/local-compute/library`, `.../library/<id>[?annotation_id=]`, `.../library/<id>/bundle[?annotation_id=]`, `/api/electrode-editor/records` and `/parents`, `/api/source-reception/layouts` and `/api/design-evaluation/heads`. Nothing is written under R.

- `schemas/radius_search.py`: the `radius-search` format (Node's `normalizeRequest`, its 15 messages verbatim), with its registry entry, a generator over 1,243 variants (`tests/schema_parity/formats/radius-search.mjs`), `/api/normalize/radius-search` and `RadiusSearchRequest` in the generated types.
- In `jobs/`: `records` (the read side of `storage/records.mjs`; directory names in byte order, as libuv lists them), `integrity` gains `verify`, `radius` (the worker-result validator, `codeIdentity`, which reads code files raw and follows links (B8), `identityFor` and `readCache`), `design_result` (`validateDesignResult`), `reception_records` (`designReceptionRecord`, `receptionLayouts`), `annotations` (the read side of the electrode-name annotations), `library` (`validateSavedRecord`, the offline radius and area importers, labels, `list` and `get`), `bundle` (`describeSearch` and `experimentBundle`, whose frozen-bank export runs as Node's promisified `execFile` does: argument conversion, socket-pair streams, the 10 s timeout and the 1 MiB buffer counted after decoding), `editor_records` (`validateEditorResult`, `records`, `parents`), `design_heads` (`heads`) and `jssort` (V8's `Array.prototype.sort`, which the order and failures of the list and the editor records follow).
- `server/routes/library.py`: the seven routes with Node's catch block (an annotation error keeps its status and message, any other failure is a 500 `计算记录无法读取` that names no path) and each prefix's 404 for another identifier. The library, its runtime (`ServiceConfig.runtime`, by default `runtime_config(R)`, which reads `EEG_COMPUTE_PYTHON`) and the head digests are built on first use. Electrode-name annotations are read without regard to owner, from `W/annotations/electrode-names/` first, then Node's `R/results/v2/design_evaluation_jobs/electrode_annotations/`.
- Node references: `tests/service/parity/library.mjs` (radius identities; the library, bundles and catalogs of Node's own services; the routes of Node's composed `createLocalComputeService`) and inline drivers in the library, bundle, catalog and head tests. The synthetic roots cover every radius cache case (compatible, another code identity, a bad checksum, malformed, unreadable), strict-area and historical-area reports, saved evaluations under each evaluation condition, saved searches whose export a stand-in interpreter answers, editor records, head packages and annotations, plus a linked root (B4), a linked code file (B8) and broken offline datasets.
- The slice's 24 Node test sites are ported (`test_library`, `test_bundle`, `test_radius`, `test_heads`, `test_library_routes`, `test_key_parity`), and the four format-mirrored sites that waited for `radius-search` have their generator. The lookup and submit halves of check-local-data-library.mjs:83, :102 and :144 came with the queue in slice 4, and the `assertIndependentNoiseParent` half of check-coordinate-bundles.mjs:163 with reception v2 in slice 7.

Result (2026-11-23): on the author's installation the list (411 records: 342 offline radius, 30 strict-area and 30 historical-area records, 7 cache rows and 2 saved evaluations, no warnings), every record, the bundle of every listed record (five cache rows export their frozen-bank coordinates with the installation's interpreter), the four catalogs (1 editor record, 35 parents, 37 layouts, no head package) and the radius identities equal Node's text; over HTTP so do the list, every record and a sample of bundles. None of the 7 cache rows is compatible with the installation's current code, in Node as in Python. Against `eeglayoutlab serve` with that installation as root, `check-app-live.mjs` passes the pages, the 401 without the cookie and its library check (342, 30 and 30 records, no warnings), then stops at its first job, `POST /api/local-compute/jobs` (slice 4). `check-local-library-live.mjs` has no session support; with its requests sent to the Python port by a preloaded `fetch` wrapper, its read half passes (health, the counts 342 and 30, one record of each dataset read and validated) and it stops at its first lookup (slice 4). Known differences from Node:

- The list and the editor records are sorted with V8's algorithm as Node 26 runs it (`jobs/jssort`: binary insertion alone up to 7 items, TimSort above) and Node's comparators, but texts compare in UTF-16 code units where Node's `localeCompare` uses ICU collation, which depends on the locale. So records without `finished_at` can come out in another order, and since each answer decides which records V8 compares next, a record whose `finished_at` is not a string fails the list (or the editor records) exactly when Node's sort throws only where ICU orders the compared texts as code units do: on the author's installation under `en_US` or without `LANG`, not under `zh_CN`, which puts Han before Latin. And only on Node 26: Node 24 (V8 13.6, measured) and Node 22 (V8 12.4) have no insertion-only path, so 3 to 7 such records can sort on one side and fail on the other. The parity tests, at the library level and over HTTP, compare the records as a set and the `finished_at` order separately, so they hold under any locale; on the author's installation the orders were equal. The tests that compare such lists with Node run Python's sorts with the limit measured on that Node (`library_support.sorting_as_node`), and lists of 3 to 7 records check Node 26's order without Node.
- Bodies carry no `visibility` or `library_scope`, every record is listed and readable, and the annotations of every owner are listed and read; Node filters by the session's owner. `.../library/<id>/visibility` is 404 `未知计算接口` (Node: 405 `请使用POST`).
- Warnings keep the server paths that Node's `redactPayload` replaces (path redaction is not carried over).
- A root that cannot be read answers 500 for each request; Node fails when the service is created.
- A record that is not JSON is reported with Python's parser message, not V8's. A stored design request that the phase 1 schema refuses carries `normalizeDesignRequest`'s message (`design_result.node_refusal`, compared with Node over the schema corpus and requests that reach each check).
- After a timeout or a full buffer, as in Node, both outputs are closed and the export subprocess gets SIGTERM; 2 s later it gets SIGKILL, where Node waits for it indefinitely. At the timeout, as in Node, the exit status then decides: a child that exits with 0 (one whose own child still holds an output open, or one that handles SIGTERM without writing) gives the output read until then. As Node does, the child's stdin is closed when it exits (noticed within 10 ms).
- The `Received` part of `ERR_INVALID_ARG_TYPE` (a strict-area pointer whose `report` is not a string) is Node's hardened text (nodejs/node#65607, Node 24.22 and later releases): an object is named by a non-empty string `constructor.name` only. Node 26.5 and 24.21 name it by any `name` member and, for a primitive `constructor`, fail with V8's `TypeError` from an `in` check, so such a warning differs there; `test_library_messages.py` compares with the text the running Node writes.
- Memo stamps use `st_mtime_ns`; Node's use `mtimeMs`. They never enter keys.
- As in Node, each `list` and `get` recomputes the key of every cache row and re-reads and re-validates each compatible one, so requests slow down as compatible caches accumulate: about 0.2 s per request on the synthetic parity root (13 cache rows), 13 ms for a record on the author's installation, where none is compatible.
- The OpenAPI document describes the canonical radius request; the service also accepts `null` or `{"kind": "iid"}` for `noise_model`, `null` for `data_prior` and an empty `mask_codes` in a free mode, as Node does.

The parity ran on Node 26 on macOS; the message, catalog and bundle tests also ran on Node 24.22.3 on macOS, and the export's timeout and buffer cases against Node 24.22.3's `execFile` on Linux. CI's Node 22 on Linux, where identities carry the interpreter fingerprint, was not run locally; `test_library_messages.py` measures V8's insertion-sort limit and the `Received` text on the Node it runs.

### Slice 4 — job engine, durable queue and radius search

Radius searches run on the Python service: lookups, jobs, their progress, cancellation and cache replay, with a durable workspace queue in `W/.eeglayoutlab/queue.json` and the task status of the interface's header. Records go to `R/results/v2/local_app_jobs` with Node's bytes. Only `local-compute` is wired; the design evaluation, the editor and the signal simulation get their adapters in slices 5 to 7.

- In `jobs/`:
  - `worker` ports `startPythonWorker` for asyncio. The child leads its own process group and the shell is off. NDJSON on stdout goes through a port of Node's `StringDecoder`, so split UTF-8 and a last line without a newline still count. stdout is bounded and the stderr tail is cut to 16,000 UTF-16 units. A stop, cancel or timeout sends SIGTERM to the group, then SIGKILL 2 s later. Completion waits until the whole group is gone. Spawn errors take Node's two paths (an asynchronous error with a close, or a synchronous throw).
  - `slot` holds `ExecutionSlot` (one permit per workspace, held through validation and the record writes) and the new `InstallationLock`, a non-blocking `flock` on `R/results/v2/.eeglayoutlab-execution.lock` held with the permit. Two workspaces of one installation therefore compute one at a time. `ExecutionSlot.available()` asks for both without taking either. The lock file sits outside every `*_jobs` directory and is opened for writing (read-only only when this user may not write it), since Linux NFS emulates `flock` with byte-range locks, whose exclusive form needs a descriptor open for writing. A descriptor is closed on any error after its `flock`, so a failed check cannot leave the lock held with nothing referring to it. Lookups take neither lock.
  - `records` gains the write side of `storage/records.mjs`: `create_batch` (each component created, then real-pathed inside the root), `atomic_json` (`<path>.<uuid4>.tmp` opened `wx` with mode 0600, fsync, rename, fsync of the directory, unlink in `finally`), `RecordStore.write` and `publish_cache` (B16, below). It makes Node's system calls in Node's order and gives Node's error texts (`node_message`).
  - `radius` gains the run path, `RadiusJobs`, a port of `LocalComputeQueue`. The worker is `<computePython> -u R/scripts/run_local_radius_compute.py` with cwd R and two threads for OMP, OpenBLAS, MKL and vecLib (B10). It has a 180 s timeout and an 8 MiB output bound. `request.json` is written before the spawn and `job.json` after the close. `validate_worker_result` must accept the result and its `code_sha256` must equal the queued identity. A completed or `no_layout` result becomes `cache.json` in Node's member order. Node's Chinese messages are kept verbatim.
  - `queue` holds `WorkspaceQueue`, a port of `CommunityQueue` for one local user: one FIFO across kinds, deduplication of a pending key, a cached receipt per stored result, and the identity prepared again at dispatch. The spawn intent is persisted before the spawn, and only once the permit is free: as Node's tick reads its busy slot, the queue probes the installation lock before it prepares a task and again before the intent. Startup recovery applies Node's restart rules and the reconciliation of interrupted receipts; `queue.json` records the kernel's boot id of its last write (`boot_id`) for the reboot rule below. A corrupt file is refused and kept; a hit's `finished_at`, which Node copies from the stored record unchecked, may hold any value. A failed write stops new work until a write succeeds. Retention keeps the newest 1,000 computed and 300 cached receipts, and the bound of 50 pending tasks answers 429 `queue_limited`.
  - `kinds` holds the adapter protocol of `community-adapters.mjs` (`ServiceAdapter`, `local_compute_adapter`).
- In `server/`:
  - `routes/compute.py` serves `POST /api/<kind>/lookup` (200), `POST /api/<kind>/jobs` (202), `GET /api/<kind>/jobs/<id>[?annotation_id=]` and `POST /api/<kind>/jobs/<id>/cancel` (202), with Node's body checks per kind and Node's `publicFailure`.
  - `routes/community.py` serves `GET /api/community/status`: `{queued_tasks, running_tasks, available, resource_blocked: false, recovery_blocked, maintenance, drained, jobs}`, the last 12 receipts newest first, without `online_visitors`.
  - Health adds `active_job` (the kind's first pending task without its result), `maintenance` and `drained`.
  - `ComputeHost` builds the slot, the radius search and the queue in the ASGI lifespan and shares them with the library. On shutdown it stops scheduling, stops the running worker with `server_restart`, waits for its records and writes the queue once more.
- The command line gains `eeglayoutlab serve --cache-only`, which replaces the operator maintenance mode: health and status report `maintenance: true`, hits are served, misses are refused with Node's 503 and message, and `drained` is true once nothing runs. It also gains `--clear-interrupted`, which releases an unconfirmed spawn and the recorded pid of a worker that blocks dispatch. The SIGINT and SIGTERM handlers are now installed before `runtime.json` is written, so a stop during startup leaves no runtime file (the race slice 3 noted). The first signal stops the compute services at once, as Node's `dispose` does; one that comes before they are built stops them as soon as they are, so nothing is recovered or dispatched. Every signal reaches uvicorn as SIGTERM, so Ctrl+C pressed twice still waits for the worker's records. A corrupt `queue.json` makes `serve` exit 1 with one message naming the file, after uvicorn's `Application startup failed. Exiting.`, and leaves the file as it was. A last write of the queue at shutdown that fails also makes `serve` exit 1, as Node's host exits 1 when its `dispose` throws, and keeps the file as it was: the queue logs `computation queue stopped` with its traceback, as Node's `failClosed` logs its stack, and then one line names the file.
- In `webapp/`: `components/community-status.tsx` reads `GET /api/community/status` through `community-status-model.ts` (a plain GET, no token) and shows the visitor count and its notices only when the answer has `online_visitors`. Only then, on the Node host, it also sends the visible-page heartbeat as before and shows its answer, so Node still counts the browser and logs its visit. Each request has its own 8 s limit, as health and the heartbeat had. It works on both hosts (`check-community-status.mjs`, with Node's own community routes). The live scripts `check-local-compute-live.mjs`, `check-local-library-live.mjs` and `check-radius-recovery-live.mjs` sign in to the Python service through `openServiceSession` (`EEG_SERVICE_RUNTIME` or `EEG_SERVICE_TOKEN`), read the root from `EEG_REPOSITORY_ROOT` and import `../server/` again.
- Node references in `tests/service/parity/`:
  - `worker.mjs`: `startPythonWorker` on 169 scripted fake children (89 written out, 80 seeded random UTF-8 splits) and 23 real-process cases.
  - `records.mjs`: Node's `RecordStore` and `atomicJson`, with its `fs/promises` calls recorded, on 18 cases.
  - `radius_run.mjs`: `LocalComputeQueue` with an injected `spawnProcess`, a pinned clock and pinned job ids, on 13 cases.
  - `queue_views.mjs`: `CommunityQueue` with the stub adapters of check-community-queue.mjs, on 9 scenarios.
  - `compute_routes.mjs`: Node's composed `createLocalComputeService` over HTTP, on 37 HTTP steps with the same fake worker, and on 4 steps over a root whose `results` is a link out of it and over one whose `results` link spells the root in upper case.
- The slice's 43 Node test sites are ported (`test_worker`, `test_storage`, `test_radius`, `test_queue`, `test_compute_routes`), and so are the lookup and submit halves of check-local-data-library.mjs:83, :102 and :144 that slice 3 left (`test_library`).

Result (2026-11-23):

- **Parity.** Python's results equal Node's in every reference above, on Node 26.5.0 and Node 24.22.3.
  - The worker's events, logs, stops, kills and closes.
  - The record store's results, error messages, system-call traces and resulting trees.
  - The `request.json`, `job.json` and `cache.json` bytes of the run path, with its child's arguments.
  - The queue's views, statistics and maintenance status. Node's `owners`, `networks` and `online_visitors` are removed and identifiers renumbered.
  - Every HTTP step's status, content type and masked body, and the masked record tree. Ids, times and the token are masked.
- **Checks.** The service tier passes (22,048 tests), and so do the real-root tier (460), the native tier (879) and the interface's typecheck, lint, `test:fast` and build. The OpenAPI document is unchanged: the job routes are not in it, like the library routes.
- **Mutation checks.** Each was caught by the tests: 8 mutants of `records.py`, 19 of the run path, and a swap of the worker's decoder for Python's own.
- **Linux.** The worker, the slot and the record tests, and the queue tests that need no Pydantic (the boot id read from `/proc/sys/kernel/random/boot_id` among them), passed on Linux (Ubuntu, Node 24.22.3) in a scratch directory, after reruns on that flaky host.
- **Live checks.** These ran with `eeglayoutlab serve` on a scratch workspace, against an APFS copy of the author's installation without `.git`, `.claude`, `artifacts`, `node_modules` and `.runtime`. The installation's managed interpreter ran the workers through `EEG_COMPUTE_PYTHON`.
  - **Keys.** The current keys of the 7 Node-written cache rows are equal on the installation and on its copy, by Python and by Node, so the root's path does not enter radius identities. None of the 7 equals its row's key any more (the code identity changed), so none is compatible, as slice 3 found.
  - **`check-local-compute-live.mjs` passes.** It ran 7 real radius searches (6 completed, 1 `no_layout`, 4 to 9 s each), each replayed from the cache. The invalid configuration is refused with 400, and the missing token and the foreign origin with 403. Its first run stopped at the 400 check, on both hosts: the script read the status from a member that the error body's own `code` overwrote. That is fixed.
  - **`check-local-library-live.mjs` passes** before the searches, when no row is compatible. It also passes after them from a second workspace on the same copy: the 9 cache rows the Python service wrote are hits with `source: local_cache` and resubmit to `key === row.id`, nothing new is written and the original data are unchanged. From the workspace that computed those rows it stops at `source`, because the lookup there returns the computed receipt (`local_compute`), as Node does for the browser that computed a result.
  - **`check-radius-recovery-live.mjs` stops** at its first read: its fixed original record `6135457e…` is no longer in the installation. Its other assertions, run separately, pass except one. The search completes in 5 s with 2 components of 32 electrodes each, within 25 mm and at least 4 mm apart, and the lookup hit and library record are compatible. But its provenance is `strict-radius-local/3-external-exposure`, not the script's `strict-radius-local/2`. Both of those assertions describe an older installation, and the script needs an owner for its science.
  - **`check-app-live.mjs`** passes the 11 pages, the 401 without the cookie, the library (402 supplied records), and a radius job with its cached replay, record and bundle. It stops at the first electrode-editor job (slice 6: 404 `Unknown queue endpoint`).
  - **Shutdown.** SIGTERM stopped each service with exit 0, `runtime.json` was removed and no worker was left. Nothing under the installation changed.

Known differences from Node:

- **Publish once (B16).** `publish_cache` writes the temporary, then links it to `cache.json`. When the name exists, the kind's reader decides: a valid file is kept and the job keeps its own result in `job.json`, and only an invalid one is replaced by rename. Node's rename replaces any file. So an existing `cache.json` that cannot be read (EACCES, EPERM) fails the publish where Node would replace it. On a file system without hard links the validity check runs before the rename. A crash after the link and before the unlink leaves the temporary's name as a second link to `cache.json`, which readers ignore.
- **The installation lock** is new. While another workspace of the installation computes, the queue's probe finds the lock held, as Node's tick finds its permit busy: the task stays queued, unprepared, and `queue.json` is not written, so no crash can leave a spawn intent behind. The queue looks again every second, since nothing signals that release. A lock taken between the probe and the start makes the submit busy, and the task goes back to its place, as in Node's race. Each directory between the root and the lock is resolved with `realpath(3)`, as `createBatch` resolves it, so a link that spells the root in another case or Unicode normalization (macOS) stays inside the root. One that resolves out of the root (`results` kept elsewhere through a link) is refused with `createBatch`'s message, `Record directory leaves the repository.`, after the dispatch has prepared the identity and checked the key, so the view and the status read as Node's on that root until a restart. The refusal comes before the spawn intent, where Node's comes inside `adapter.start`, after it. Node's failed receipt therefore keeps `starting: true`, and after a restart Node reports `recovery_blocked` and dispatches nothing until the receipt is repaired. Python's receipt has no intent, so a restart keeps dispatching, and each task fails with the same message. A lock that cannot be used for another reason fails the task with the generic message, where Node has no lock.
- **The worker transport** uses pipes, not libuv's socket pairs. A hard bound at the timeout plus twice the kill grace (184 s for a radius job) ends a run whose output a process outside the group keeps open, or whose group cannot empty: the group gets SIGKILL and the run completes as `escaped`. Node waits forever there. If the child exits before its input is written, the input is dropped silently, where Node may report EPIPE.
- **The spawn is awaited.** A cancel during the spawn marks the job `cancelling` at once and is applied when the worker exists. `submit` awaits the spawn under `asyncio.shield`, so a caller that goes away cannot leave a job active with the permit held. Records are read and written in worker threads.
- **Finalization** runs from the kind's completion callback, not a 250 ms poll of the service's bounded job map (jobs.md section 5.6). A non-terminal worker status at that point is recorded as `failed`.
- **Restart recovery.**
  - Liveness covers the worker's whole process group (`killpg(pid, 0)`; EPERM counts as alive), and a `worker_pid` whose group is gone is dropped from its receipt.
  - An unconfirmed spawn blocks dispatch until the machine has rebooted since the last write of `queue.json`, which came at or after every intent and pid it holds, or until `--clear-interrupted`. A `worker_pid` from before such a boot is dropped without a probe, since a live process with that pid is another one; without a reboot a live group blocks until it is gone, as in Node, or until `--clear-interrupted`. A reboot is a `boot_id` in the file that is not the kernel's boot id now (`kern.bootsessionuuid`, `/proc/sys/kernel/random/boot_id`), which changes only at a boot. The plan named the boot time (`kern.boottime`, `/proc/stat btime`) instead, but both kernels derive it from the wall clock, so a clock set forward (NTP after a long pause, a restored virtual machine) would look like a reboot and drop a live worker's pid. Without both ids nothing is resolved this way.
  - On a root whose `results` or `results/v2` resolves out of the root, the failed receipt has no spawn intent, so a restart does not block dispatch where Node's does (the installation lock, above).
  - Startup `recover()` replaces Node's offline reconciliation tool, and a promoted receipt keeps its hit's message instead of Node's reconciliation note.
  - Leftover temporaries of `queue.json` are removed at startup.
  - As in Node's `eligibleReceipt`, a cancellation interrupted by a restart becomes `failed` with the restart message, so a later restart can promote it.
- **One user.** A lookup or submit of a result this workspace computed returns its computed receipt, with `cached: true` and `source: local_compute`, as Node answers the browser that computed it. Node gives every other browser a new cached receipt (`local_cache`).
- **Admission.** A submit whose write fails takes its new receipt back. A dispatch of a kind without an adapter fails with the generic message. A lookup hit writes a cached receipt to `W/.eeglayoutlab/queue.json`, as Node writes one to Q, but never a record under R, and it takes no lock.
- **Routes.**
  - A kind without an adapter, and every kind of an application whose lifespan never ran, answers 404 `Unknown queue endpoint` before the body is read. Node applies the body limits first, and answers `任务不存在或不属于当前浏览器` for a receipt id under another kind.
  - There is no `POST /api/community/heartbeat`: Python answers 404 `Unknown community endpoint`. The interface sends it only to a host whose status counts visitors, so the Python service never gets it and the Node host's count and visit log stay as they were (R1).
- **Shutdown.** Node exits at a second Ctrl+C, after its first one has sent the worker SIGTERM. Python stops the worker at the first signal too, then ignores further signals until the graceful shutdown (up to 5 s for open requests) and the worker's records are done.
- **Not ported.** Owners, networks, visitors, their rate limits and caps, the resource gate, the custom queue directory and the operator maintenance mode (R1, R2, R6).

Node 22 on Linux, CI's Node, was not run locally. The run path, the queue's adapter over it and the routes were not run on Linux: the Linux test host has no Pydantic, which the run path needs.

## Where key equality can break

The request key is `sha256(utf8(JSON.stringify({request, identity})))`. Proof tiers: **A** CI on synthetic roots with the Node driver on the same root; **B** the opt-in real installation; **C** a live lookup comparison of both hosts.

| # | Break point | Rule in Python | Slice | Proof |
| --- | --- | --- | --- | --- |
| B1 | Object key order (V8 puts array-index keys first) | `jsjson.stringify` orders as V8 | 1 | A, B |
| B2 | Number and string spelling; absent members dropped | phase 1 `jsjson`; callers omit absent members | phase 1 | A |
| B3 | Canonical request per format | a `canonical()` builder per format | 1 (design), 3, 6–9 | A, C |
| B4 | Root string: default realpath of the checkout, explicit root only resolved | same rules; the default through `nodefs.realpath_sync` (Node's lexical `fs.realpathSync`); no extra realpath | 1, 3 | A |
| B5 | Interpreter strings: `nativePython` in design, editor and reception identities | `runtime_config` with JavaScript truthiness; the service's own interpreter never enters an identity | 1, 3 | A, B |
| B6 | Managed-runtime rows only on exact path equality; filters and code-unit sort | same test and sort | 1 | A |
| B7 | Raw pointer strings as digest keys; POSIX path joins | `jobs.nodepath`, never `os.path` for key strings | 1 | A |
| B8 | Digest semantics differ between design inputs and radius code files | separate helpers | 1, 3 | A |
| B9 | Linux runtime fingerprint (exact probe, memoized) | `jobs.fingerprint` | 1, 3 | A on Linux |
| B10 | Thread constants and worker environment | constants and spawn environment | 1, 4, 7 | A |
| B11 | Code-file sets | identity-input manifest guard | all | A, B |
| B12 | Optional rows and their order; JavaScript `$` and truthiness | `re.fullmatch`, `js_truthy`, same order | 1, 3 | A |
| B13 | Library record bytes, which enter editor and reception keys | byte port | 3 | A, B |
| B14 | Design `cache.json` bytes, whose hash enters reception v2 keys | same writer and field order | 5 | A, B |
| B15 | Reception runtime digest (inspector subprocess, memo) | same command, working directory and environment | 7 | A, B |
| B16 | Republishing a result changes keys built on it | publish once; one host computes at a time | 4, 5 | A |
| B17 | Editor identity order | copy, overwrite, append | 6 | A, B |
| B18 | Study identity hashes | same | 8 | A |
| B19 | Batch `request.json` bytes | same writer | 4–7 | A, B |
| B20 | Literal record paths inside identities | literal strings | 3, 7 | A |
| B21 | Python `json` | banned in `jobs/` and `server/` by a test | 1 | test |
| B22 | Envelope fields and discriminators never enter keys | phase 1 envelope; formats of slices 3 and 7 | 3, 5, 7 | A |
| B23 | Different hash inputs (`JSON.stringify` text, bytes, plain strings) | separately named helpers | 3 | A |
| B24 | Body decoding: bytes counted before decoding | phase 1 `read_json_body`, with a limit per route | 2 | A |
| B25 | Real paths: `InputIntegrity` resolves its root with `fs.realpathSync` (link targets lexically, spelling kept) and inputs with `realpath(3)` (physically; on macOS the on-disk case and normalization), so containment can differ from `os.path.realpath`'s | `jobs.nodefs`: a port of `fs.realpathSync` and libc's `realpath`; names decoded with U+FFFD | 1 | A, B |

## Not carried over

The Node code stays until phase 4; none of this is ported:

- anonymous visitors: the visitor cookie and session secret, per-visitor scoping, visitor counts, visit logs and the heartbeat;
- rate and quota limits per visitor, network or owner (the global queue bound and every size bound are kept);
- the hosted proxy policy and operator signals;
- operations: monitoring, request logs, the resource gate, admission thresholds, request ids, path redaction in messages and JSON compression;
- the maintenance mode, replaced by `--cache-only` (slice 4);
- library visibility and moderation;
- project credentials: owner and viewer keys, sharing and revocation, fragment links and the key vault;
- silent pruning of projects and study drafts;
- the hosted operations tools (`backup_service.py`, `reconcile_service.py` and the service probe), which keep targeting Q until phase 4;
- pre-compressed static sidecars (Python serves the original bytes).

## Interface changes

| Slice | Change |
| --- | --- |
| 2 | An opt-in development proxy to the Python service, and a session helper for scripts |
| 4 | The status component reads `GET /api/community/status`; a host that counts visitors (Node) then gets the heartbeat as before; visitor counts only when present (works on both hosts) |
| 10 | A 401 answer shows "reopen from the `eeglayoutlab` command" |
| 10 | Visitor counts, the visibility control and project credentials (keys, roles, sharing, fragment links, the vault) are removed; projects open from `GET /api/projects` |
| 10 | The development proxy targets Python by default; live and browser scripts are retargeted |

Unchanged: the `X-EEG-Compute-Token` header (health still returns the token), every job, library, study and project path, the job view and its states, and API version `1`.

## Node tests

The unit-test files in `webapp/scripts` contain 630 test sites. 184 are ported to Python (81 so far), 16 are mirrored by format parity, 332 stay in Node (19 of them adapted in slice 10), 88 are dropped with the public-service machinery, and 10 belong to the Node host's structure or the Node command line. `tests/service/node_tests.toml` maps every site to its disposition, and `tests/service/test_node_test_map.py` fails on an unmapped site, a missing Python target or a pending entry of a finished slice.

## Decisions

The plan assumes the recommended default of each. U1, U2, U3 and U6 are confirmed.

| # | Question | Recommended default | Reason |
| --- | --- | --- | --- |
| U1 | Where calculation results live during phase 2 | In the checkout at `R/results/v2/*_jobs`, shared by all workspaces as the cache; moved only with the 1.0 identity change or a later scientific-root decision | Record paths enter reception and editor keys; moving them would break exit criterion 1 and decision 8. This defers decision 7's separate per-user cache directory |
| U2 | What a workspace holds | Shared: calculation results and the library. Per workspace: task history, the signal-experiment list, electrode-name sets, projects and studies | Matches decision 7; a result from another workspace is found again by running the same request, which is a cache hit |
| U3 | `eeglayoutlab` without a workspace path | Use the current directory; ask before turning a non-empty directory into a workspace; when not interactive, require a path | Familiar from tools such as Jupyter; avoids scattering workspace files |
| U4 | Data from the Node application (projects, studies, signal receipts in Q) | An explicit `eeglayoutlab workspace import-legacy` that verifies and copies byte for byte; nothing automatic; the source is not modified | Automatic migration into whichever directory is opened first could split one person's work |
| U5 | Command line in phase 2 | Only `serve` and `workspace import-legacy`; the scientific commands move in phase 3 | Phase 3's acceptance (the examples against their expected scores) is the natural test for them |
| U6 | Port and session lifetime | A free port and a new token at every start; running the command again opens the running instance | A fixed port collides with other tools and with Node during coexistence; a persistent token weakens decision 6 |
| U7 | A hosted Node deployment that follows this repository | Tag the last commit before slice 10, stop deploying later commits, retire it in phase 4 | Slice 10 removes the credentials and visitor features a public service needs |
