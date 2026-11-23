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
- `test_nodefs.py` compares `nodefs.realpath_sync` and `nodefs.realpath` with Node's `fs.realpathSync` and
  `fs.promises.realpath` (`parity/fs.mjs`) on a tree of links, loops and misspelled paths. On macOS the two
  differ: the first keeps the spelling it is given, the second returns the on-disk case and normalization.

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
  `jsjson`; every design and editor cache, and every batch `request.json` with an identity, re-derives its key.

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
  `serve` during the shutdown starts anew), and a `BROWSER` command that does not return gets the open page while
  the service answers.

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
  follow links: B8), `radius_identity` and `RadiusCache.read_cache`.
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
  check-local-data-library.mjs (the lookup and submit halves of :83, :102 and :144 come with the queue in
  slice 4).
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
