# Architecture

EEGLayoutLab is a browser application with a Node HTTP host and bounded Python workers. The web application is maintained; the native Mac wrapper and packaging tools have been retired. The macOS scientific runtime remains available for local browser use.

This page describes the current structure. The planned move to a local-first application with a Python service, in stages that keep results and cache keys valid, is described in [design 0001](design/0001-local-first-architecture.md).

## Module boundaries

```text
app route -> feature workspace/controller -> client/task-client
          -> HTTP service -> durable FIFO + execution slot
          -> Python worker -> compact_eeg workflow -> verified record
```

| Location | Responsibility |
| --- | --- |
| [`contracts/`](../contracts/) | Shared layout types, documented wire formats and Node/Python request fixtures |
| [`webapp/app/`](../webapp/app/) | Route entry points that compose feature workspaces |
| [`webapp/features/`](../webapp/features/) | Overview, design, electrode editing, decisions, reception, library and historical results |
| [`webapp/client/`](../webapp/client/) | Common task transport, polling and connection recovery |
| [`webapp/viewer/`](../webapp/viewer/) | Head assets, resource lifetime, contact/source layers and camera interaction |
| [`webapp/components/`](../webapp/components/) | Shared UI and the React wrapper around the viewer |
| [`webapp/lib/`](../webapp/lib/) | Display calculations, translations, URL state and compatibility exports |
| [`webapp/server/contracts/`](../webapp/server/contracts/) | Pure server request normalization and result validation |
| [`webapp/server/http/`](../webapp/server/http/) | JSON responses, API metadata and explicit access policy |
| [`webapp/server/host/`](../webapp/server/host/) | Development/production framework adapters, configuration and operator signals |
| [`webapp/server/jobs/`](../webapp/server/jobs/) | Shared execution permit and Python process lifecycle |
| [`webapp/server/runtime/`](../webapp/server/runtime/) | Interpreter/path selection and scientific identity context |
| [`webapp/server/storage/`](../webapp/server/storage/) | Record access over the existing on-disk layout |
| [`webapp/server/projects/`](../webapp/server/projects/) | Project credentials, revisioned annotations and immutable verified scientific snapshots |
| [`webapp/server/delivery/`](../webapp/server/delivery/) | Bounded research deliveries, exact snapshot checksums and readable reports |
| [`webapp/server/operations/`](../webapp/server/operations/) | Request correlation, bounded private logs, local status and resource admission |
| [`src/compact_eeg/workflows/`](../src/compact_eeg/workflows/) | Scientific application workflows |
| [`src/compact_eeg/`](../src/compact_eeg/) | Geometry, forward modeling, reconstruction and metrics |
| [`scripts/`](../scripts/) | Worker entry points, data/runtime setup and release/recovery tools |

Browser modules do not import server implementations. Server imports are checked for cycles. Shared layout contracts have no renderer dependency. Request fixtures exercise the existing Node and Python validators; schema generation is not part of this implementation. See [API formats](../contracts/api-formats.md).

The viewer's asset loader validates atlas groups and hashes before use. A scene lifetime owns generated geometry, materials, labels, event listeners, observers and the renderer. `lib/anatomical-head-scene.ts` preserves the existing exports. Reception separates pure result projections, one shared playback timeline and paired receiver panels; display controls do not recalculate scientific scores.

Viewer instances share downloads and SHA-256 validation through `viewer/asset-cache.ts`. The cache retains at most 32 MiB and four verified binary entries, keyed by URL and checksum. Each scene receives its own position, normal and index arrays and can dispose them independently. Aborting one viewer does not cancel another viewer's download; the underlying request is canceled when its last subscriber leaves. Failed requests are removed so the next load can retry. Model indexes are revalidated on each mount, and binary URLs include their checksums so a deployment can replace a model without reusing the previous version's browser cache.

Reception loads each 3D module when its placeholder comes within 200 px of the viewport. Once activated, scrolling away preserves the camera and selection. A manual load control and an observer-free fallback cover other browsers. Playback stops its interval while the document is hidden and resumes at the saved position only if playback was already active.

## Execution and records

`community-queue.mjs` stores anonymous task receipts and FIFO order. All four scientific services share `jobs/execution-slot.mjs`. The Python runner handles progress output, output limits, cancellation, timeout and process-tree termination. A permit remains held until process closure, result validation and persistence finish. Cache lookup remains available without occupying that permit.

Radius design and in-bank editing read the frozen lead-field bank. Fixed-coordinate evaluation retains its existing `1e-7 mm` bank/reference matching checks; other qualified coordinates require native FEM, or the published scalp-node table described below. Reception reuses bank fields only at exactly identical saved coordinates. Editor and V2 reception initialization also validate native inputs and runtime identity, so a bank-backed operation alone does not establish that a minimal Python environment supports the full application.

Native coordinate evaluation also prepares reception fields using the same model instance, source operator and factorization. It preserves the original design and reception projection paths separately: repeated projection can change floating-point coordinates, so design fields are not substituted for reception fields. The verified reception matrix and QA are published atomically under `results/v2/reception_forward/shared_fields/`, keyed by exact coordinates, model/source inputs, code, runtime and thread settings. Reception still requires a valid completed design record. A failed optional preparation leaves the successful design available; identity changes, corrupt archives and cancellation remain errors. Old reception archives remain readable.

When `results/v2/current_scalp_node_table.json` exists, coordinate evaluation of non-bank points reads a precomputed scalp-node table instead of factorizing the head model. `scripts/build_scalp_node_table.py` solves, once, a unit load at every table vertex against the fixed gauge node, using the qualified MUMPS path and the same residual/current thresholds as a direct solve. The table vertices are every vertex of an exterior triangle whose three vertices pass the current surface admissibility mask, plus every admitted bank candidate vertex. An admitted candidate can sit on a vertex whose incident triangles all touch a screened vertex; its zero-weight corners are redirected to that vertex. On Ernie this adds vertex 46112, read by bank candidate 4925, for 40,024 vertices. A point electrode's load is the barycentric combination of its triangle's three node loads, so its row is the same combination of node rows: superposition of one linear operator, not interpolation between electrodes. Evaluation keeps the original cortech projection, reads three SHA256-checked rows per electrode and must reproduce the bank reference within `1e-8`. The table is bound to the bank, candidate geometry, source inputs, head hashes, admission mask and vertex rule; any difference is an error, never a fallback to direct FEM, until the table is rebuilt. Because the vertex rule is part of the table identity, the nominal table and both conductivity-scenario tables built under the earlier rule must be rebuilt. Its pointer, manifest, index and row bytes enter the shared cache identity. Results record `forward_mode: scalp_node_table` and the table ID. Reception for such a design uses the same table and fails if it has been replaced; designs evaluated with direct FEM keep their native reception path.

`runtime/identity-cache.mjs` reuses a runtime identity only while its observed filesystem state remains unchanged. The Python snapshot wrapper retains the original runtime digest algorithm and records files, directories, import paths, launchers and symlink targets. Node rechecks inode/device, type, size, nanosecond modification/change times and executable mode, coalesces pending checks and evicts failed entries. An older scientific checkout without the snapshot wrapper uses the original uncached inspection. This optimization does not change scientific cache keys.

## Research projects

Projects keep annotations and immutable scientific copies under `<queue directory>/projects/`. Owner and revocable viewer credentials are hashed on the server; names are descriptive metadata rather than authenticated accounts. A restored credential works across browsers. This access boundary does not change the existing shared original layout library.

Attaching an entry resolves a validated completed layout, editor evaluation or owned signal receipt on the server. It saves a checksummed copy of the full scientific payload. Project annotations, selected reference/candidate layouts and comparison requirements remain separate from scientific requests and identities. Optimistic project revisions prevent stale writes. Receipt pruning and cleanup of the original calculation cache do not erase these saved copies. Recognized temporary files left by interrupted atomic snapshot writes are retained and counted in storage limits, never read as completed science.

The browser retains the active project per tab and provides explicit save actions in existing tools. Archived result views read project snapshots directly. Scientific delivery bundles keep exact snapshot text, a checksum manifest, annotations, comparison settings and copied original readings. Current export-host fingerprints are separate from the original calculation identities. Delivery preparation is bounded and does not start scientific work. See [project formats](../contracts/project-formats.md).

## Local operations and admission

The outer HTTP observer generates request identifiers, correlates returned task IDs and writes bounded private logs containing route labels, status and duration. It does not log credentials, query strings, scientific inputs or response payloads. The local operator status endpoint requires a direct loopback request without browser or proxy metadata; the computation token does not grant operator access.

Filesystem free-space checks and an optional current Node RSS threshold apply before accepting uncached work, before dispatch and before project mutations. Cache lookup, existing results and cancellation remain available. Resource-blocked tasks retain their FIFO position. These operational settings do not enter scientific cache identities or change worker thread counts. Current Node memory is not scientific-worker peak memory or a hard OS resource limit. Accepted project writes and pending operational logs are flushed before releasing the queue owner during shutdown.

## Host checkout and scientific root

The **host checkout** supplies `webapp/`, dependencies and the production build. `EEG_REPOSITORY_ROOT` selects the **scientific root** containing worker scripts, `src/`, scientific configurations, installed model inputs, generated records and the managed runtime. Both roots default to the same checkout. `EEG_QUEUE_DIRECTORY` can place queue state elsewhere; its value must be absolute.

The store preserves existing paths:

- `results/v2/local_app_jobs/`, `design_evaluation_jobs/`, `electrode_editor_jobs/`, `source_reception_jobs/` and `source_reception_v2_jobs/` contain generated job records.
- `results/v2/reception_forward/` contains generated forward fields.
- `results/web-service/` is the default queue, signing-secret and operational-log directory.
- Other paths named in `data/manifest.json` remain frozen inputs or supplied records, including entries under `results/v2/`.

This configuration supports a new host checkout using an existing scientific snapshot. It does not move data, rewrite old records or introduce independently relocatable input/result roots. A release manifest verifies that the scientific source expected by the host matches the selected scientific checkout.

`EEG_COMPUTE_PYTHON` selects the ordinary worker interpreter. Native services retain their existing precedence: the scientific root's `.runtime/simnibs-4.6.0/bin/python` is preferred when present. Release checks record the interpreter actually selected.

## Compatibility and hosting

API JSON responses carry `X-EEG-API-Version: 1`; errors retain `error` and add a stable coarse `code`. Existing routes and scientific cache-key formats remain unchanged. Legacy Python entry points and Node compatibility exports remain part of the supported execution/import paths.

API JSON uses asynchronous Brotli/gzip streams when accepted, with identity fallback, `Vary: Accept-Encoding` and the existing access/cache headers. Small responses normally remain uncompressed. `npm run build` also creates beneficial `.br`/`.gz` variants of binary models in `dist/client/models/`; the host serves the negotiated variant. Original model files and decoded JSON bytes are unchanged.

Cache identities include actual code, inputs and, where applicable, runtime bytes and filesystem paths. A changed path or environment can require a new calculation. Historical results retain their original identity; no approximate-coordinate cache fallback or hash rewriting is introduced.

Production always listens on `127.0.0.1`. Default API access is local. Explicit HTTPS-origin and trusted-proxy configuration enables the tested proxy policy and Secure cookies. Public deployment and target-platform qualification remain pending. See [deployment](server-deployment.md), [queue behavior](anonymous-queue.md), [operations](web-operations.md) and [verification commands](../CONTRIBUTING.md).
