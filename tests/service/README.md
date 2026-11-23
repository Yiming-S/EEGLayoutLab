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
EEG_KEY_PARITY_ROOT=/path/to/EEGLayoutLab python -m pytest tests/service/test_key_parity.py -m data_bundle -q
```

- the same comparison on that root with its real runtime, for several interpreter configurations, sharing one
  queue per configuration (hashing every input again for each case is slow);
- every stored cache under `results/v2/*_jobs` re-derives `result_sha256` and round-trips byte for byte through
  `jsjson`; every design and editor cache, and every batch `request.json` with an identity, re-derives its key.

Both read the root only. The stored-record check needs neither Node nor Pydantic.

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
