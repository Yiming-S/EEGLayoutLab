# Portable scientific runtime

`stage_runtime.py` prepares the existing frozen Apple Silicon runtime for the
desktop payload. It is a build-time operation; the receiver needs no Conda,
Python installation, activation, prefix rewrite, or `conda-unpack` operation.

The staged project must contain `src/` and preserve this relative layout:

```
project/
  src/compact_eeg/
  scripts/
  configs/
  data/
  results/
  .runtime/simnibs-4.6.0/
```

Invoke with explicit paths; the destination must not already exist:

```
python3 desktop/runtime/stage_runtime.py \
  --source /path/to/EEGLayoutLab/.runtime/simnibs-4.6.0 \
  --destination '/path/to/staging/project/.runtime/simnibs-4.6.0' \
  --project-root '/path/to/staging/project'
```

The script hashes the source inventory, copies regular files without hard links,
preserves symlinks and metadata, verifies the initial copy, converts the editable
project `.pth` into a relative site path, and wraps Python console entry points
with a relative shell/Python trampoline. It replaces native build-machine RPATHs
and absolute bundled-library references with loader-relative paths, then ad-hoc
signs and verifies each changed Mach-O. Existing Conda metadata and license files
are preserved. Original provenance paths in metadata remain historical records;
they are not used to locate the running interpreter.

One upstream optional binary is excluded from the staged copy:
`PyQt5/Qt5/plugins/sqldrivers/libqsqlpsql.dylib`. It depends on an unbundled Homebrew
PostgreSQL library; the WebKit desktop app and EEG workflows do not use Qt SQL.
Its original file and all upstream license material remain intact. The audit
records the exact exclusion and SHA-256. No other unbundled absolute Mach-O
dependency is accepted.

`portable-runtime-audit.json` records source/staged inventory hashes, each path
change, signature treatment, preserved metadata, and verification results.
Verification starts the staged interpreter from an unrelated working directory
with only `/usr/bin:/bin` on PATH and no inherited Python/Conda/dyld variables.
It checks project resolution through the relative `.pth`, native imports,
MUMPS sparse factorization and solve, CGAL projection, the production native
runtime identity, loaded dyld image locations, and the relocated `pip check`
console entry point. This is a bounded runtime check, not a full FEM benchmark.

For a second relocation test, move the complete staged project and invoke the
probe with its new root. The receiving launcher must set
`PYTHONDONTWRITEBYTECODE=1`, `PYTHONNOUSERSITE=1`, and single-thread BLAS/OpenMP
limits; it must not inherit `PYTHONHOME`, `PYTHONPATH`, or `DYLD_*` overrides.
Validated build-Mac relocation does not establish a second physical Mac test.

`--skip-verify` is reserved for builders that copy project sources after runtime
staging and then run `verify_runtime.py` themselves. Failed stages are retained
for inspection; the script never overwrites or deletes an existing destination.
