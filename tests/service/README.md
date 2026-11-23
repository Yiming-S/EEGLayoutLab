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

## Guards

`test_guards.py` keeps Python's `json` out of `eeglayoutlab.jobs` and `eeglayoutlab.server` (except the
OpenAPI writer), keeps `os.path` out of the identity module, and compares `identity_inputs.json` with every file
in git whose bytes Node hashes into a request key. After a deliberate change to one of them, update the manifest
in the same commit:

```sh
python tests/service/test_guards.py --write
```
