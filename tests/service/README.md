# Service tests

Tests of the Python service (`src/eeglayoutlab/jobs`, `src/eeglayoutlab/server`) for phase 2 of
[design 0001](../../docs/design/0001-local-first-architecture.md). The directory is a package, so its module names
cannot collide with the top-level tests.

## Key parity

The first phase 2 exit criterion is that, on the same installation, Python request keys equal Node request keys.
`test_key_parity.py` checks it for the design-evaluation identity:

- `parity/identity.mjs` is the Node reference. For each case `{id, root, python?, env?, direct?, request}` it sets
  or deletes `EEG_COMPUTE_PYTHON`, builds Node's own `LocalComputeQueue` and `DesignEvaluationService` on that root
  (a fresh pair per case, with a scratch queue directory that is never created) and records the configured root
  and interpreters, the identity and admission texts and the key, or the error. `direct` calls
  `scientificContext` with a given interpreter string instead, to reach the exact-string rule of the
  managed-runtime rows. Usage: `node tests/service/parity/identity.mjs <spec.json> <out.json>`.
- `key_parity_support.py` builds the synthetic roots (`design_root`, a port of `designContextRoot` in
  `webapp/scripts/helpers/robustness-fixture.mjs`): the nominal scalp-node table, conductivity scenarios, head
  packages, fake SimNIBS and Linux table runtimes, raw pointer strings, a symlinked root, roots whose real path
  Node resolves in a particular way (a link target with `..` after a link, a root or link target spelled in
  another letter case or Unicode normalization, a file name that is not UTF-8), pointer bytes that are not UTF-8
  and a lone surrogate in a path, dist-info names with line terminators, and failure roots. It crosses
  them with interpreter configurations and requests (each option alone and combined, `{}`, requests the
  normalizer would refuse, and, on the base and full roots, every accepted design variant of the schema parity
  corpus), runs the driver once per session and computes the same cases with `eeglayoutlab.jobs`.
- Results must be equal. Failures compare by Node's code where the error has one (system errors, whose messages
  carry absolute paths, and `ERR_INVALID_ARG_TYPE` / `ERR_INVALID_ARG_VALUE`), by name for a `SyntaxError` (V8's
  messages are not reproduced), and otherwise by Node's message.
- Most failure roots break one thing: a missing, escaping or unreadable input, each identity check, an optional
  pointer that is a directory or cut short, a pointer with a BOM, pointer values Node's code trips over or skips
  (falsy ones). Node hashes the inputs concurrently, so which error wins between two breaks can depend on
  timing. The driver runs Node with one thread-pool worker (`UV_THREADPOOL_SIZE=1`), which runs the file requests
  strictly in order: argument errors before any I/O, then real paths, opens and reads, each stage over every
  input in list order, then the identity checks one after another. The two-break roots pin that order, and
  `InputIntegrity.digest_all` reproduces it. With the default pool of 4, failures in different stages can come
  out either way (about 1-3% of runs for an unreadable file against a directory).
- `test_nodefs.py` compares `nodefs.realpath_sync`, `nodefs.realpath`, `nodefs.readdir` and `nodefs.read_file`
  with Node's `fs.realpathSync`, `fs.promises.realpath`, `readdir` and `readFile` (`parity/fs.mjs`) on a tree of
  links, loops and misspelled paths, failures by code and by message (`records.node_message`: the syscall, and the
  path as the system received it, a lone surrogate as U+FFFD). On macOS the two real paths differ: the first keeps
  the spelling it is given, the second returns the on-disk case and normalization.

On macOS the identities have no `runtime` member; on Linux they carry the interpreter fingerprint, so CI covers
that branch.

Without Node or Pydantic the parity tests skip, so the native runtime suite runs unchanged; with
`EEG_REQUIRE_SCHEMA_PARITY=1`, as in CI, they must run. The other modules (`test_runtime_config.py`,
`test_fingerprint.py`, `test_design_identity.py`, `test_guards.py`, the rest of `test_nodefs.py`) need neither;
`test_fingerprint.py` also compares fake interpreters (a non-zero exit, more than 1 MiB of output, output on
stderr after the probe line, a file without a `#!` line) with Node's own `python-fingerprint.mjs` when Node is
available, and on Linux a bare name searched on PATH as glibc's `execvp` does (entries it cannot execute are
skipped, an empty entry is the working directory).

### On a real installation

With `EEG_KEY_PARITY_ROOT` set to a checkout that has `results/v2` and `.runtime`, the real-root tests (marked
`data_bundle`) also run:

```sh
EEG_KEY_PARITY_ROOT=/path/to/EEGLayoutLab python -m pytest tests/service -m data_bundle -q
```

In `test_key_parity.py` they are:

- the same comparison on that root with its real runtime, for several interpreter configurations, sharing one
  queue per configuration (hashing every input again for each case is slow), for the design and the radius
  identity;
- every stored cache under `results/v2/*_jobs` re-derives `result_sha256` and round-trips byte for byte through
  `jsjson`; every design and editor cache, and every batch `request.json` with an identity, re-derives its key;
- the electrode editor's context for every parent it offers and every stored editor request (see "Electrode
  editor" below);
- the context of every stored reception cache's request, its original download and its finish time; with the
  `native_runtime` marker also v2's context on the real runtime, whose inspector both hosts run (see "Signal
  reception" below).

The library modules add theirs (next section). All of them read the root only; Node runs with a scratch queue
directory that is never created. The stored-record check needs neither Node nor Pydantic.

## Service host

The HTTP service of slice 2 is tested in process with known tokens. `service_support.py` holds the helpers:

- `synthetic_root` (with or without the radius worker and its bank, which health reports as `available`) and
  `static_export` (a small export laid out as `npm run build` writes it, with sidecars, a dot directory and links
  out of it);
- `make_app`, and `loopback_client`, a `TestClient` at `http://127.0.0.1:<port>` that has already exchanged the
  launch token at `/open`, so its jar holds the session cookie (`csrf=True` also sends the CSRF token);
- `asgi_request`, one request passed to the application as uvicorn passes it, with the request target exactly as
  written (HTTP clients normalize `..` and percent-encoding) and a chosen peer, `Host` and cookie.

The modules:

- `test_access.py`: the loopback guard on every path, `/open` and the session cookie (also from the launcher's
  page, a cross-site navigation), the CSRF token on writes with each route family's Node message, Node's 404
  messages per prefix, the body limits per task kind and the generic 500; and, with Node, that
  `scripts/helpers/service-session.mjs` sends the launch token to 127.0.0.1 only. It holds the slice's ports in the
  Node test map.
- `test_health.py`: the four health routes. `parity/health.mjs` serves Node's real `createLocalComputeService` on
  the same synthetic root, with a scratch queue directory, and records each kind's status, five headers and body;
  Python must match byte for byte except for the token value, with the worker present and absent. Usage:
  `node tests/service/parity/health.mjs <root> <queueDirectory> <out.json>`.
- `test_static.py`: page routes, the 404 page, content types and cache headers, conditional and range requests,
  `HEAD`, 405, and the paths never served (traversal, encoded separators, dot files, links out of the export,
  `.br`/`.gz` sidecars, other spellings of a name). `parity/static_requests.mjs` sends the same conditional and
  range requests, as raw HTTP, to a `node:http` server that evaluates them with vinext's own functions (the Node
  host's static files), and parses the same HTTP dates; given Python's ETag, Python must answer each with the same
  status and range (the tag itself is strong here and weak in vinext: design 0001, slice 2, known differences).
  Usage: `node tests/service/parity/static_requests.mjs <cases.json> <out.json>`. The last test reads the real
  `webapp/dist/client` when `npm run build` has written it.
- `test_workspace.py`: the marker, the lock, `runtime.json`, the open page and instance reuse; a state directory
  that is a link, another user's, or holds links; and `eeglayoutlab serve` in a subprocess over a real socket: a
  second `serve` opens the running instance, SIGTERM or SIGINT removes the runtime file at once (so a second
  `serve` during the shutdown starts anew; a stop right after the file is written leaves none), a `BROWSER`
  command that does not return gets the open page while the service answers, and the flags of slice 4:
  `--cache-only` reports maintenance, `--clear-interrupted` releases an unconfirmed spawn, a corrupt
  `queue.json` makes `serve` exit 1 and is kept, Ctrl+C pressed twice during a radius job still stops its
  worker and writes its records, a stop before the compute services exist dispatches nothing, and a failed last
  write of the queue makes `serve` exit 1.

Without FastAPI, Uvicorn or httpx the tests that need them skip, unless `EEG_REQUIRE_SCHEMA_PARITY=1`; the health
and static parity also need Node, and the static parity `webapp/node_modules` (`npm ci`).

## Library and catalogs

The read-only library of slice 3 (`eeglayoutlab.jobs`: `records`, `radius`, `library`, `annotations`,
`design_result`, `reception_records`, `bundle`, `editor_records`, `design_heads`; the routes in
`server/routes/library.py`) must give Node's bytes on the same root. Every Node reference runs Node's own classes
with one thread-pool worker and a queue directory that is only resolved, never created.

- `test_radius_search.py`: `schemas.radius_search.normalize_request` gives Node's canonical text or Node's exact
  message for every variant of the `radius-search` corpus (`tests/schema_parity/formats/radius-search.mjs`), and
  the variants reach all 15 messages. Acceptance and canonical bytes through the registry and the
  `/api/normalize/radius-search` route are in the schema parity tests.
- `test_radius.py`: the worker-result validator (check-local-compute.mjs:61, and 33 cases against Node's
  `validateWorkerResult` message by message), `code_identity` (top-level `src/compact_eeg/*.py`, raw reads that
  follow links: B8), `radius_identity` and `RadiusCache.read_cache`; its run path is in the next section.
- `test_key_parity.py`: the radius identity. `parity/library.mjs` in its `identities` mode builds a fresh
  `LocalComputeQueue` per case and records `identityFor`. The `radius-*` roots of `key_parity_support.py` (managed
  runtimes, a linked root, and one break each: a code file linked out of the root, a directory, a dangling or
  unreadable code file, no `src/compact_eeg`, no worker, no data-prior module) are crossed with interpreter
  settings and requests, and the base root takes every canonical request of the `radius-search` corpus. Also the
  port of check-project-structure.mjs:30.
- `test_library.py`: `Library.list()` and `get(id)` against Node's `queue.library`. `library_support.py` builds
  the roots (every radius cache case, current and historical strict-area reports, saved coordinate evaluations
  under each evaluation condition, annotations; a linked root, a linked code file, a bare root, roots that break
  the offline datasets) and holds the inline Node driver `LIBRARY_DRIVER`. The list compares as a set of record
  texts plus the `finished_at` order, the rest as text; every record directory is read with `get`. It ports
  check-local-data-library.mjs; the lookup and submit halves of :83, :102 and :144 run on `RadiusJobs` with a
  spawn that fails the test, and the lookup endpoint of :121 is in `test_compute_routes.py`.
- `test_bundle.py`: `experiment_bundle` and `describe_search` against Node's `experimentBundle`.
  `bundle_support.py` builds the roots and stand-in interpreters for the frozen-bank export subprocess (arguments,
  environment, stream kinds, output at and over 1 MiB, invalid UTF-8, exits, signals) and holds `BUNDLE_DRIVER`;
  children whose exit status decides at the timeout or that pass the buffer (writing after SIGTERM, blocked
  writing, a process they started reading stdin after their exit) are compared with Node's promisified
  `execFile`, and saved evaluations that spell a zero as `-0` with Node's bundle. It ports check-coordinate-bundles.mjs and the bundle
  tests of check-source-upgrade.mjs.
- `test_library_messages.py`: Node's messages and orders the library reproduces, against Node (inline
  `MESSAGES_DRIVER`): `normalizeDesignRequest`'s refusals over the design-evaluation corpus and requests that
  reach each check, `util.inspect` and the NUL-path message, the `Received` part of `ERR_INVALID_ARG_TYPE`, every
  comparison of V8's `Array.prototype.sort` (`jobs/jssort`), Object.prototype members as family names and `idFor`
  of lone surrogates; then end to end through `LIBRARY_DRIVER` on roots with refused stored requests, broken
  strict-area pointers, these identifiers, and `finished_at` values that are not strings at several positions of
  lists of 3 to 12 records. Where Node releases differ, `library_support.node_generation` measures the running
  Node (V8's short-array limit: 7 on Node 26, which the service follows, 2 on Node 24; the `Received` text before
  and after nodejs/node#65607): Python sorts with that Node's limit in the comparisons (`sorting_as_node`), a
  Node before the hardened text is compared with its own text, and the lists of 3 to 7 records check Node 26's
  order without Node. The comparisons assume a Node locale whose collation orders the compared labels as UTF-16
  code units do (no `LANG`, or `en_US`).
- `test_catalogs.py` and `test_heads.py`: the editor's records and parents, the reception layouts and the head
  packages, against Node's services (inline `CATALOG_DRIVER` and `HEADS_DRIVER`; the editor sort roots include
  rows that Node 26 sorts and Node 24 does not, compared with Python sorting at the running Node's limit);
  `test_heads.py` ports check-design-decision.mjs:516.
- `test_library_parity.py`: both levels through `parity/library.mjs` (its header documents the spec): the library,
  every bundle and the four catalogs in its `roots` mode, and the HTTP routes against Node's composed
  `createLocalComputeService` (the middleware the Node host runs, its session pinned to one owner) on an ephemeral
  port. Node's `visibility` and `library_scope` members are taken out of its bodies and its `redactPayload` is
  applied to Python's. The list, the parents and the layouts compare their records as a set plus the
  `finished_at` order (Node sorts with `localeCompare`, whose collation follows the locale), and the list's
  annotations as the pinned owner's among Python's; the differences that remain by design (the visibility route,
  other owners' annotations read by id) are asserted as such. The composed service writes its state under a
  scratch `serviceDirectory`. Usage:
  `node tests/service/parity/library.mjs <spec.json> <out.json>`.
- `test_library_routes.py`: what the comparison cannot show: member order, annotation queries, Node's catch block,
  lazy construction, `EEG_COMPUTE_PYTHON`, concurrent requests, nothing written, and the HTTP half of
  check-coordinate-bundles.mjs:80.

With `EEG_KEY_PARITY_ROOT` the `data_bundle` tests of these modules run the ports of the Node data tests and
compare that installation with Node: the list and every record (the 342 offline radius, 30 strict-area and 30
historical-area records, every cache row and every saved evaluation: the parent-digest inputs, B13), the bundle of
every record (the frozen-bank coordinates exported with the installation's own interpreter; about 3 minutes), the
catalogs, and the routes for every record and a sample of bundles.

## Job engine, queue and radius jobs

Slice 4 writes: the worker transport and the execution slot, the record writes, the radius run path, the workspace
queue and the job routes. Everything that computes or writes runs on synthetic roots in `tmp_path` with stand-in
workers; the Node references write only under their case roots and scratch directories.

- `test_worker.py` (`jobs.worker`, `jobs.slot`): check-worker-lifecycle.mjs, whose fake children (`FakeChild`)
  drive the worker through its `spawn` hook, and the transport half of check-local-compute.mjs:97, :106 and :111 on
  `Runner`, a stand-in queue that holds the permit as `LocalComputeQueue` does. Then spawn errors, the stdin
  encoding, callbacks that raise, the hard bound on a run whose output or group outlives its leader, and the
  installation lock (its place beside the record trees, a holder in another process, the probe that takes nothing,
  the descriptor open for writing, the descriptor closed when the check after its `flock` fails, the lock during a
  run, links and directories out of the root, refused with `createBatch`'s message, and the root resolved with
  `realpath(3)` as `create_batch` resolves it: a link spelling the root in another case or normalization, and a
  dangling link).
  `parity/worker.mjs` runs Node's own `startPythonWorker` on 169 scripted fake children (89 written out, among
  them every cut of a 35-byte sample of valid and invalid UTF-8 through both decoders, and 80 seeded random UTF-8
  splits) and on 23 real processes (exit codes, signals, the output bound, the timeout's SIGKILL, a surviving
  descendant, stdin modes, spawn errors, a script without a `#!` line, PATH search, invalid UTF-8); every callback
  and close is compared as JSON text. Usage:
  `node tests/service/parity/worker.mjs <spec.json> <out.json>` (its header documents the spec).
- `test_storage.py` (`jobs.records`, the write side): check-runtime-storage.mjs:35 and :56, the record-store half
  of check-service-storage.mjs:12, and `publish_cache` (B16): a valid cache is never replaced, threads and
  processes racing for one key publish once, errors leave the cache as it was, a crash leaves only a `*.tmp` that
  readers ignore. `parity/records.mjs` runs Node's `RecordStore` and `atomicJson` with its `fs/promises` calls
  recorded (replaced through `syncBuiltinESMExports` before `records.mjs` is imported), on 18 cases built once per
  side; values, error messages, call traces and resulting trees (names, types, modes, link counts, link targets,
  bytes) must be equal. Usage: `node tests/service/parity/records.mjs <spec.json> <out.json>`; its ops are
  `createBatch`, `write`, `atomicJson`, `publish`, `read`, `keys`, `path` and `directory`, with `$number`
  stand-ins and `cycle` for circular values.
- `test_radius.py`, the run path (`RadiusJobs`): check-local-compute.mjs:72 (one child, the shell off, two BLAS
  threads), :86, :97, :106 and :111, driven through `radius_support.FakeChild` as Node drives its fake children;
  the permit and installation lock held until the records are written, another workspace computing, a paused slot
  and a broken lock, a cancel during the spawn, a cancelled caller, a cache published first by another workspace,
  `aclose`, the job map's bound, a real worker process, and the timeout case of the parity under a loop stalled for
  less than its timer.
  `parity/radius_run.mjs` runs Node's `LocalComputeQueue` with an injected `spawnProcess`, a pinned `Date` and
  pinned job ids on 13 cases (completed, no layout, worker failure, spawn throw, invalid result, timeout, cancel,
  stdin error, output limit, dispose and restart, store failure, normalized requests, code-root provenance); the
  `request.json`, `job.json` and `cache.json` bytes, the job states and the child's spawn arguments must be equal.
  Usage:
  `node tests/service/parity/radius_run.mjs <spec.json> <out.json>`. With `EEG_KEY_PARITY_ROOT`,
  check-lab-workflow.mjs:25 reads that installation's strict-area records (no lookup, no submit).
- `test_queue.py` (`jobs.queue`, `jobs.kinds`): with the stub adapters of check-community-queue.mjs:11-38
  (`queue_support.Stubs`), the scheduler tests of check-community-queue.mjs, the queue tests of
  check-abuse-limits.mjs and check-queue-maintenance.mjs (without the maintenance flag), check-reconciliation.mjs as
  startup recovery, check-cross-region-contract.mjs:124 and check-product-operations-integration.mjs:131. Then
  crash consistency of `queue.json`, corrupt files kept byte for byte, a failed last write at `dispose` kept for
  the service, the boot id and `clear_interrupted` (for an unconfirmed spawn and for a recorded worker pid; a clock
  set forward is no reboot), process-group liveness, the installation lock held by another workspace before the task
  is prepared or taken while it is prepared (the task stays queued, nothing is written), a record tree out of the
  root (Node's message, after the key check; a restart is not blocked), a hit's stored `finished_at` that is not a
  string, finalization from the completion callback, retention, `cache_only`, the statuses of
  `task-client.ts`, and the local-compute adapter over `RadiusJobs`. `parity/queue_views.mjs` runs Node's
  `CommunityQueue` with the same stubs on 9 scenarios; views, statistics and the maintenance status must be equal
  once `owners`, `networks` and `online_visitors` are removed and identifiers numbered in order of appearance.
  Usage: `node tests/service/parity/queue_views.mjs <spec.json> <out.json>`.
- `test_compute_routes.py` (`server/routes/compute.py`, `community.py`, the lifespan): the application with its
  lifespan over HTTP on a root whose worker is `compute_support.FAKE_WORKER`, a stand-in for
  `scripts/run_local_radius_compute.py` that plays the plan step of each request (`compute_support.serving` starts
  it on a workspace). Submit and poll, the stored receipt, joins and cancels, failure messages, the lookup endpoint
  (check-local-data-library.mjs:121), the services sharing one store and one slot (check-service-storage.mjs:12),
  two workspaces of one root computing one at a time (the waiting one writes nothing), `ComputeHost.stop_soon`
  (serve's first signal) stopping the worker while the service still answers, and before the services exist
  stopping them once built (a queued task stays queued), `--cache-only`, the 429 bound, a
  restart through a second application, an unconfirmed spawn and its log hint, Node's body, JSON, CSRF and query
  rules, and a corrupt queue file. `parity/compute_routes.mjs` serves Node's composed
  `createLocalComputeService` (its scheduler's state in a scratch directory) on the same root with the same fake
  worker; the 37 steps of `compute_support.STEPS` must give the same statuses, content types and bodies (ids,
  times and the token masked, Node's `online_visitors` dropped) and the same record tree under
  `R/results/v2/local_app_jobs`; on a root whose `results` is a link out of it, 4 steps give Node's refusal, and on
  one whose `results` link spells the root in upper case, Node's result. Usage:
  `node tests/service/parity/compute_routes.mjs <spec.json> <out.json>`.

The Node references need Node; the run path, the queue's adapter tests and the routes also need Pydantic (and the
routes FastAPI and httpx). Without them those tests skip, unless `EEG_REQUIRE_SCHEMA_PARITY=1`. The process tests
(groups, signals, the lock) are written for macOS and Linux, and they wait on events with generous bounds so that
they hold under load.

## Coordinate evaluation and electrode names

Slice 5 adds the coordinate evaluation's run path (`jobs.design`), the write side of the electrode-name annotations
(`jobs.annotations`), the design adapter (`jobs.kinds.DesignAdapter`) and its routes. As in slice 4, everything that
computes or writes runs on synthetic roots in `tmp_path`, and the Node references write only under their case roots
and scratch directories.

- `test_design.py` (`DesignJobs`):
  - Ports: check-design-decision.mjs:201 and :330 and check-design-robustness.mjs:35 (all eight corruptions) on
    the result validator. :265, :288 and :303 are driven through `radius_support.FakeChild` with that file's context
    stub (`design_support.Fixture`).
  - Then what Python adds:
    - the permit and the installation lock held until the records are written;
    - another workspace computing, a paused slot, a broken lock and a failed context;
    - a pause or a failed write while the batch is created;
    - a cancel during the spawn, the wall-clock limit and a cancelled caller;
    - a valid cache published first by another workspace (B16), and `aclose`;
    - the finish time a restart takes from `cache.json` (`stored_finish`) only after the record checks of Node's
      reconciliation: the key and checksum, the result, and the identity and request the record names. The record
      is read as the lookup reads it, so a second link (B16) or a link inside the root does not stop it (R6);
    - the queue's prepared submit and the job map's bound;
    - a subclass that overrides every member slice 6's editor overrides;
    - a real worker process on a design root. `design_support.FAKE_WORKER` stands in for
      `scripts/design_evaluation.py`.
  - `parity/design_run.mjs` runs Node's `DesignEvaluationService` over a `LocalComputeQueue` of the design roots of
    `key_parity_support.design_root`, so the scientific context is real on both sides. Spawn is injected, and
    `Date` and the service's `randomUUID` are pinned. It runs the cases of `design_support.parity_cases`: 20 on
    macOS, 19 on Linux (CI). The `managed` case runs on macOS only, since on Linux the identity probes the
    interpreter's fingerprint and its fake interpreter cannot run; so CI does not compare the managed run path, and
    the `scandir` message is compared there by `test_nodefs.py`. The `odd-bytes` case moves away a source input that
    its manifest names with a lone surrogate. Unless the superuser runs them (it reads files of mode 000), the cases
    also reach `EACCES`, and only then does the coverage test ask for it.
  - For each case these must equal Node's: the steps' records, the clock and id counts, the spawn arguments,
    environment, stdin and kills, and the `request.json`, `job.json` and `cache.json` trees. The one exception is
    B16: Python keeps a valid `cache.json` published first, and the publish-once case asserts it.
  - Usage: `node tests/service/parity/design_run.mjs <spec.json> <out.json>` (its header documents the steps).
- `test_annotations.py` (`ElectrodeAnnotations`, `design_submission`):
  - Ports of check-electrode-annotations.mjs:82, :100, :117, :135, :147 (below HTTP) and :212 (at the routes' body
    reader). They run on that file's fixture: a stub design adapter with Node's prepare, the workspace queue and
    `ElectrodeAnnotations.local` (W first, then Node's directory, owner `LOCAL_OWNER`). Owners are dropped (R1) and
    so is the resource gate (R2). The per-owner part of :135 becomes the 32,768-byte file bound.
  - Then the write side: an existing file is never rewritten, new files go to W only, and a directory that cannot
    be written is 503. Also the identity's checks in Node's order and the envelope's checks.
  - A temporary that disappears between the listing and its `lstat` is skipped by `list` and `create` (a known
    difference: the library lists in a request thread); an `<id>.json` that disappears there is Node's 409 and 503.
  - `test_twenty_variants_do_not_bound_a_receipt`: the per-owner bound of 20 is dropped (R1), so one user's receipt
    takes Node's 100 per receipt; the :135 port asserts that the 101st is refused by the per-receipt bound.
  - `parity/annotations.mjs` runs Node's `designSubmission` (2,879 envelopes) and `ElectrodeAnnotations` (1,840
    identities, 179 of them passed to `create`, 132 created) on the same inputs and owners. Node reads back the 130
    with a string key, and both hosts list their 125 distinct files; `test_parity_cases_reach_their_branches` pins
    these counts.
  - Values, ids, refusal messages and statuses, and file bytes must be equal. Each host must read the other's files
    back: Node given the owner, Python with slice 3's reader.
  - Usage: `node tests/service/parity/annotations.mjs <spec.json> <out.json>`.
- `test_key_parity.py`, the envelope:
  - Ports of check-electrode-annotations.mjs:73 and check-coordinate-review.mjs:122.
  - `key_parity_support.EnvelopeCases` runs the production adapter (`kinds.design_evaluation_adapter` over a
    `DesignJobs` of each root) over bare, named, sourced and refused submissions on the base and full synthetic
    roots. The same driver runs Node's adapter (its `prepares` mode).
  - The prepared request, key, identity, names, source declaration and worker input, or the refusal, must equal
    Node's. Names and source declarations never change the request, the worker input or the key.
- `test_compute_routes.py`, the design routes:
  - The flow of check-design-evaluation-live.mjs on a design root whose worker is the stand-in
    (`compute_support.design_compute_root`). It covers:
    - an evaluation with names whose annotation lands in W and is referenced by its receipt;
    - `?annotation_id` on job views, library records and bundles (the HTTP half of check-electrode-annotations.mjs:147),
      and an R annotation Node wrote, which the library reads;
    - a lookup miss that writes nothing, and the stored evaluation as one cached receipt;
    - joins, cancels, a restart, `stop_soon` and `--cache-only`, and an identity that changed after the close;
    - CSRF, 65,536 against 65,537 bytes, and a body sent one byte per ASGI message (`compute_support.chunked`).
  - Node's 100 variants per receipt over HTTP; a restart that promotes an interrupted evaluation whose result was
    stored, with that record's finish time, and keeps failed one whose record names another identity (Node's
    reconciliation retains it); the health of a receipt whose annotation is gone or corrupted.
  - `parity/compute_routes.mjs` runs the 63 steps of `compute_support.DESIGN_STEPS` on Node's composed service with
    its session pinned to the local owner. The answers, the design record tree and the six annotation files must be
    equal: Node writes them under R, the Python service under W. On a root whose configured mesh path has a NUL
    byte, a lookup and a submit answer Node's 500 with the generic message.

## Electrode editor

Slice 6 adds the electrode editor: its request format (`schemas.electrode_editor`), its run path
(`jobs.editor.EditorJobs`, a subclass of slice 5's `DesignJobs`, as Node's `ElectrodeEditorService` extends
`DesignEvaluationService`), its adapter (`jobs.kinds.electrode_editor_adapter`) and its routes. As in slices 4 and 5,
everything that computes or writes runs on synthetic roots in `tmp_path`, and the Node references write only under
their case roots and scratch directories.

- `test_editor_request.py`: `schemas.electrode_editor.normalize_editor_request` gives Node's canonical text or
  Node's exact message for every variant of the `electrode-editor` corpus
  (`tests/schema_parity/formats/electrode-editor.mjs`, 1,185 variants, among them the requests of
  check-electrode-editor.mjs's protocol test), and the variants reach all 5 messages. Python values follow
  JavaScript's (a bool is not a number, a tuple is an array), and the input is never changed. Acceptance and
  canonical bytes through the registry and the `/api/normalize/electrode-editor` route are in the schema parity
  tests.
- `editor_support.py` builds editor roots (`editor_root`): a design root of `key_parity_support.design_root`, so the
  design context the editor's builds on is the scientific one, with the radius code files, the editor's worker and
  workflow, and a parent of each kind the library offers. These are strict-area layouts of a current report whose
  identity names its region geometry, a historical strict-area layout, an early radius experiment, a saved
  coordinate evaluation, and radius caches with or without region patches (an empty list, no layout), under a noise
  model or a data prior, with another region geometry or surface admission, or under another code identity.
  `FAKE_WORKER` stands in for `scripts/electrode_editor.py`; `R/editor-mode.txt` makes it fail, hold or answer for
  another request.
- `test_editor.py` (`EditorJobs`):
  - Ports: check-electrode-editor.mjs:48 (the result validator, through `validate_editor_result` and the service's
    `validate`) and :68 (shared capacity, cached results and the permit kept while cancelling, driven through
    `radius_support.FakeChild` with that file's context stub; Python also checks the permit from the coordinate
    evaluation's side).
  - Then what Python adds:
    - each refusal of the context, in Node's order of checks;
    - the B17 identity (the design identity, `schema` overwritten in its first position, then `parent_digest`,
      `editor_sha256` and `editor_implementation_sha256` appended), the key and the worker input
      `{request, parent}`;
    - a library given as a factory, or whose `get` answers asynchronously;
    - a report rewritten with the same size and its times given back: the library keeps the layout it read, the
      report's digest is computed again, so the strict-area parent is refused;
    - `editor_jobs` for a runtime, the view's `parent_digest` (the context's, else the digest of the result's
      parent, else the result request's), and the catalogs of slice 3;
    - a real worker process: a preparation, an evaluation, a worker error, a stale result and a cancel.
  - `parity/editor_run.mjs`, mode `runs`, runs Node's `ElectrodeEditorService` over a `LocalComputeQueue` of editor
    roots, so the library, the design context and the digests are real on both sides. Spawn is injected, and `Date`
    and the job identifiers are pinned, as in `design_run.mjs`. Its 12 cases cover:
    - preparations and evaluations that complete, and every parent refusal;
    - a worker failure, a spawn throw, and every `validateEditorResult` message (V8's `TypeError` among them);
    - the editor's code, the parent or the report changed before the close. The `tamper` step rewrites a file with
      as many bytes and gives back its times; Node sets times in milliseconds, so the report's are whole seconds;
    - a timeout, a cancel, the output bound, publish once, and lookups that hit and miss.
  - The views, refusals, spawn arguments and stdin, and the record tree under `R/results/v2/electrode_editor_jobs`
    must equal Node's, except B16 in the publish-once case.
  - Usage: `node tests/service/parity/editor_run.mjs <spec.json> <out.json>` (its header documents both modes).
- `test_key_parity.py`, the editor context:
  - The same driver, mode `contexts`, against `key_parity_support.EditorCases` on 325 cases. There are 11 editor
    roots: the base root, a nominal table, a managed SimNIBS runtime, a linked root, a report without region
    geometry, another surface admission, no editor script, no editor code, a code path that is a directory, a broken
    bank and no library datasets. The base and SimNIBS roots take each interpreter configuration. Each case is a
    preparation or an evaluation of a parent (every parent on the base root, seven elsewhere), an evaluation with a
    stale digest, or, on the base root, a value the routes never pass.
  - The identity, admission, parent and worker-input texts, the parent digest, the key and the context's member
    order, or the refusal, must equal Node's. `test_editor_variants_reach_their_branches` pins what each variant
    reaches.
  - With `EEG_KEY_PARITY_ROOT`, the installation: a preparation of every parent the editor offers and of the
    reference parent of the same-day reference keys, and every stored editor request. Python and Node must agree
    on each, and an offered parent must be prepared or refused for its region geometry or surface admission, which
    `parents()` does not check (as in Node). The test prints which offered parents are refused and which stored
    keys and reference values still hold, since inputs move on.
- `test_compute_routes.py`, the editor routes:
  - On an editor root whose three workers are stand-ins (`compute_support.editor_compute_root`; the editor's plays
    `editor-plan.json` per request: hold, fail, stale, change or reparent), it covers:
    - the flow of check-electrode-editor-live.mjs: a lookup miss that writes nothing, a preparation, an evaluation
      with the view's parent digest, the cached replay and `GET /api/electrode-editor/records`;
    - a stored edit as one cached receipt, and the catalogs;
    - the queue and the slot shared with the coordinate evaluation and the radius search;
    - each parent refusal as a 400 with Node's message, with nothing queued;
    - a restart that fails an interrupted edit and promotes one whose result was stored, with that record's
      finish time;
    - a stored edit whose code or parent changed after the close;
    - `stop_soon`, `--cache-only`, the CSRF token, 32,768 against 32,769 bytes, and the library routes' library,
      which the editor reads its parents through;
    - an edit whose parent changes while it waits, refused at dispatch with Node's message
      (`parent_change_steps`, also on Node's composed service).
  - `parity/compute_routes.mjs` runs the 79 steps of `compute_support.editor_steps` on Node's composed service. The
    answers and the record trees under `electrode_editor_jobs` and `design_evaluation_jobs` must be equal.

## Signal reception

Slice 7 adds the signal simulation, v1 and v2: its request format (`schemas.source_reception`), the runtime digest
of v2's identity (`jobs.runtime_digest`, B15), the run path (`jobs.reception.ReceptionJobs`), its adapter
(`jobs.kinds.source_reception_adapter`), its routes and the workspace's signal records (`/api/community/records`).
As in slices 4 to 6, everything that computes or writes runs on synthetic roots in `tmp_path`, and the Node
references write only under their case roots and scratch directories.

- `test_source_request.py`: `schemas.source_reception.normalize_reception_request` gives Node's canonical text or
  Node's exact message for every variant of the `source-reception` corpus
  (`tests/schema_parity/formats/source-reception.mjs`, 2,686 variants, among them the requests of the mirrored Node
  tests and the 30 source fixtures of `contracts/fixtures/requests.json`), and the variants reach all 6 messages and
  every mode of both versions. A value without `mode` takes the v1 path (`normalizeSourceRequest`), any value of
  `mode` the v2 one. Python values follow JavaScript's (a bool is not a number, `-0` is written `0`, a tuple is an
  array), and the input is never changed.
- `test_runtime_digest.py` (`RuntimeIdentityCache`, Node's `runtime/identity-cache.mjs`):
  - Ports: the 13 sites of check-runtime-identity-cache.mjs, with that file's injected inspector
    (`runtime_digest_support.Fixture`: a root with `package/numerical.py`, whose inspector hashes the file and
    observes the folder and the file).
  - Then what Python adds: Node's constants (read from `identity-cache.mjs`), `max_entries` as `Number.isInteger`
    reads it, the watch's bounds and patterns, asynchronous and synchronous reads sharing the memo and the
    inspection in flight, a caller that stops waiting, keys of other interpreters and roots that do not wait for
    each other, `close` (also of an inspector a call spawns after it), the service environment read as Node reads
    `process.env`, Node's five settings over the service's own values (the memo key is the merged environment's),
    an inspector that closes its outputs and runs on (the deadline still ends it), and the error classes the queue
    tells refusals from internal faults by.
  - `parity/runtime_digest.mjs` runs Node's `createRuntimeIdentityCache` with its own inspector runner (`execFile`
    of the root's script) on 48 case directories with a stub inspector (`runtime_digest_support.STUB`, driven by
    `R/stub/mode.json`, which counts its runs in `<case>/inspections.log`): fixed outputs, failures, the timeout,
    also of a stub that closes both outputs and runs on (the driver patches `require('timers').setTimeout` to
    shorten the 15 s timer when `inspectTimeoutMs` is given), output at and over the 8 MiB bound on either stream,
    missing and unreadable scripts, legacy output without `watch`, malformed results, stamps changed during the
    inspection, launcher chains and PATH search, environments (`PYTHONPATH` among them, and service values of the
    five settings), the entry budget and 12 simultaneous reads. Digests, inspector runs and errors must equal
    Node's. Usage: `node tests/service/parity/runtime_digest.mjs <spec.json> <out.json>`.
  - `native_runtime`: with `EEG_KEY_PARITY_ROOT`, the installation's real inspector (read only, with
    `PYTHONDONTWRITEBYTECODE=1`, as Node runs it) gives Node's digest through both hosts, and a `PYTHONPATH` that
    shadows one of the runtime's packages changes it on both in the same way. The digest is never computed in-process.
- `reception_support.py`: `fixture(request, layout)` is check-source-reception.mjs's `result()` for any canonical
  request (v1, or v2's three modes with or without the atlas definition), which the contract's validators accept;
  `FAKE_WORKER` stands in for both workers (it writes that result to `--output`, fails or holds as
  `R/stub/worker-mode.txt` says, and prints a catalog with `--catalog`). `Fixture` is the Node test's `fixture()`: a
  context stub whose `bump()` changes the key, the radius queue sharing the slot, and fake children. A fake child
  never exits by itself, so `Fixture.aclose` and the run-path driver close their services within 20 s
  (`bounded_aclose`): a step that fails while a fake worker runs is reported, chained to the cleanup's timeout,
  instead of hanging the run. `reception_root` adds the reception workflow files, scripts and two stub inspectors
  to an editor root (`editor_support.editor_root`, so the library, the design context and the digests are the
  scientific ones); `RECEPTION_VARIANTS` name what one root changes.
- `test_source.py` (`ReceptionJobs`):
  - Ports: check-source-reception.mjs:155 (the v1 result validator), :212, :242, :264, :277, :318 and :335 (driven
    through `radius_support.FakeChild` with that file's context stub) and :366 (the noise guard of both versions);
    check-cross-region-contract.mjs:94 (the v2 validator, all sixteen corruptions, and a source repeated in both
    index lists, which only the distinctness check refuses) and check-source-upgrade.mjs:183.
  - Then what Python adds: the validators' V8 `TypeError`s, the permit and the installation lock held until the
    records are written, publish once (B16), the finish time at restart read only from a record that passes the
    reconciliation's checks, `aclose` (also of a catalog run spawned after it), the queue's prepared submit, a
    cancel during the spawn, a cancelled submit caller, the v2 worker under the native interpreter with one thread
    and at least 600 s, the job map of 10, the memo of verified records (two, by file state), a real worker process,
    real workers given a variable that is not UTF-8 as Node passes it (U+FFFD), the bounded cleanup of the test
    drivers and the code identity files.
  - `parity/reception_run.mjs`, mode `runs`, runs Node's `SourceReceptionService` over a `LocalComputeQueue` of
    reception roots with an injected `spawnProcess`, a pinned `Date` and pinned job ids (as `design_run.mjs`). Its
    19 cases cover v1 and v2 runs that complete, the context's refusals, a worker failure, a spawn throw, invalid
    results (40 and 46 failing rounds with 16 distinct messages each, V8's `TypeError`s among them), result files too
    large, not JSON or a directory, an identity changed before the close, a timeout, a cancel, publish once, saved
    results, busy, the job map, dispose, a store failure, lookups and the catalog. The views, hits, saved results,
    refusals, spawn arguments and environment (both hosts run with `reception_support.NOT_UTF8`, a variable that
    is not UTF-8, which the workers must inherit as Node's `process.env` holds it), and both record trees must
    equal Node's, except B16 in the publish-once case; a `restart` only disposes the service, as Node's driver
    does; temporary names and V8's `JSON.parse` message are masked. Usage:
    `node tests/service/parity/reception_run.mjs <spec.json> <out.json>` (its header documents both modes).
- `test_key_parity.py`, the reception contexts:
  - The same driver, mode `contexts`, on 830 cases over 13 reception roots (`key_parity_support.RECEPTION_ROOTS`:
    the base root, a nominal table, a managed SimNIBS runtime, no library datasets, a broken bank or candidate
    file, no v1 worker, a v2 script or the atlas definition missing, no workflow file, the legacy inspector, an
    inspector that prints another schema and one that fails). Every parent on the base root, seven elsewhere, gets
    a v1 request and v2's three modes, each with and without the atlas definition (`single-atlas` is the
    interface's single-source request); the base root also takes the explicit interpreter configuration and values
    the routes never pass. The configuration, the record and identity texts,
    the key and the member order, or the refusal, must equal Node's; `test_reception_variants_reach_their_branches`
    pins what each case reaches. The driver deletes `EEG_COMPUTE_PYTHON` (the Python side configures with
    `env={}`), and `reception_support.run_node` exports a stray one to it, so a developer's export cannot change a
    case.
  - Ports: check-service-storage.mjs:50 (v2's injected native context and the legacy inspector) and the server
    half of check-atlas-roi-contract.mjs:26 (the ROI code, the atlas and its definition enter the code identity of
    exactly the requests with `region_definition`).
  - With `EEG_KEY_PARITY_ROOT`: every stored reception cache's request through both hosts, its original download
    and its finish time read back (`data_bundle`), and v2's context in each mode on the real runtime, where both
    hosts' `numerical_runtime_sha256` and keys agree (`native_runtime`).
- `test_queue.py`: check-community-queue.mjs:189 (the bounded signal catalog of a receipt and `records()`, the
  newest completed signal receipt per key of the workspace) and :212 (`saved_result` hands the receipt's key and
  request to the adapter and never prepares the request again), without their owners (R1).
- `test_compute_routes.py`, the reception routes and the signal records:
  - On a reception root whose two workers are stand-ins (`compute_support.reception_compute_root`; the worker
    plays `reception-plan.json` by the request's seed: hold, fail, stale or change), with a stand-in design worker
    and one stored v1 result, it covers the flow of check-source-reception-live.mjs (submit, poll, lookup hit,
    records, saved download), a lookup miss that writes nothing, a stored result as one cached receipt, the queue
    and the slot shared with the coordinate evaluation, a cancel of a finished receipt (its view, written off the
    event loop), a code change during and after a run, saved results that
    are gone or fail a check (Node's 400s, the 500 of an unreadable record, the 404s), restart promotion, the
    catalog and its 500, `stop_soon`, `--cache-only`, CSRF, 4,096 against 4,097 bytes and a chunked body.
  - `parity/compute_routes.mjs` runs the 99 steps of `compute_support.reception_steps` on Node's composed service
    (its FILE steps write or remove a root file between requests). The answers (each result over 64 KiB compared by
    the SHA-256 of its text, Node's records scope `current_browser` read as `workspace`) and the record trees under
    `source_reception_jobs`, `source_reception_v2_jobs` and `design_evaluation_jobs` must be equal.

## Node test map

Exit criterion 3 is that every Node test is ported or mapped. `node_tests.toml` has one entry per `test(` /
`dataTest(` call site in the `webapp/scripts/check-*.mjs` files that import `node:test`, keyed by file and title,
with its disposition: `P` with the Python `target`, `pending` with the `slice` and `module` that will port it,
`C` with the format-parity `mirror`, `NA`, `D` with a reason R1-R7, `N`, `E` or `CLI` (the docstring of
`test_node_test_map.py` defines them). `[scripts]` lists the opt-in live and Playwright scripts with the slice
that retargets them.

`test_node_test_map.py` reads the scripts with a small JavaScript lexer and fails on an unmapped or stale site, a
target or mirror that is not a test pytest collects (named without a parametrized `[id]`; a target in
`tests/service/`), a mirrored format still without a Node generator after its slice, and a
pending entry of a finished slice (`SLICES_DONE`). A slice changes its sites to `P` and raises `SLICES_DONE` when
it is done. `python tests/service/test_node_test_map.py` prints the counts.

## Guards

`test_guards.py` keeps Python's `json` out of `eeglayoutlab.jobs` and `eeglayoutlab.server` (except the
OpenAPI writer), keeps `os.path` out of the identity module, and compares `identity_inputs.json` with every file
in git whose bytes Node hashes into a request key. After a deliberate change to one of them, update the manifest
in the same commit:

```sh
python tests/service/test_guards.py --write
```
