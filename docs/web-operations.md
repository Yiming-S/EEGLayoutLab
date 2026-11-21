# Web operations

These procedures manage one Node host, one persistent queue and its scientific checkout. They have local tests; each production installation requires target-platform qualification. Follow [deployment preparation](server-deployment.md) for HTTPS and access configuration.

## Configure and start

Use [`server.env.example`](../configs/deploy/server.env.example) as the template and keep the real file outside the checkout. From the host source root:

```sh
node --env-file=/absolute/path/server.env webapp/server/start.mjs
```

The host reads the current checkout's `webapp/dist/` and always binds to loopback. Build with `npm ci` and `npm run build` in `webapp/` before starting a version; do not rebuild the directory used by a running verification server.

Use the complete `npm run build` command: its final step creates lossless Brotli/gzip model variants beside the original files in `dist/client/models/`. Publish that complete build and restart the host so its static-file inventory includes the variants. Dynamic API JSON compression is handled by the host. Preserve `Content-Encoding` and `Vary: Accept-Encoding` through the reverse proxy; do not compress an already encoded response again. Verify the deployed bytes and browser behavior using the checks in [CONTRIBUTING](../CONTRIBUTING.md).

| Setting | Meaning |
| --- | --- |
| `PORT` | Loopback port; default `3000` |
| `EEG_REPOSITORY_ROOT` | Scientific code, configurations, frozen inputs, records and runtime; default host checkout |
| `EEG_QUEUE_DIRECTORY` | Absolute queue directory; default `<scientific root>/results/web-service` |
| `EEG_COMPUTE_PYTHON` | Ordinary worker interpreter; native services still prefer the scientific root's managed runtime when present |
| `EEG_MAINTENANCE` | `1` starts paused; `0` does not override a previously saved pause |
| `EEG_PUBLIC_ORIGIN`, `EEG_TRUSTED_PROXIES` | Explicit HTTPS origin and trusted proxy IPs; absent by default |
| `EEG_MIN_FREE_DISK_MB` | Minimum free disk on scientific and queue filesystems; default 512 MiB; zero disables the floor |
| `EEG_MAX_HOST_RSS_MB` | Optional current Node-host RSS admission threshold; default zero, disabled |
| `EEG_OPERATIONS_LOG_MB` | Private request log limit, 1–10 MiB per UTC day; default 5; seven-day retention |

The **source root** used below is the Git checkout containing the host and release tools. The **repository root** is the scientific snapshot used by workers. They can be identical. Queue state can be separate, but model/record paths retain their established layout inside the scientific root.

## Pause, drain and stop

The startup log prints the server PID. Send signals to that exact Node process through the operating system or its supervisor:

```sh
kill -USR2 "$EEG_SERVER_PID"
node webapp/scripts/probe-service.mjs --url http://127.0.0.1:3000 --allow-paused
```

`SIGUSR2` durably enables maintenance. It blocks new uncached work and dispatch of waiting tasks. Cache lookup, result reading, cancellation and reconciliation of completed work remain available. Queued receipt IDs and FIFO order are preserved.

Wait until health reports `maintenance: true` and `drained: true`. Drained means no active backend, held execution permit, live recorded worker or uncertain launch remains. It does not mean that queued tasks have been deleted. If a worker is active, allow it to finish or cancel it and wait for process closure.

Stop the service with its supervisor or `SIGTERM` and confirm the Node process has exited before executing a backup. Maintenance alone is insufficient: cache receipt reads can still write queue state. Other tools that write scientific records must also be stopped.

```sh
kill -TERM "$EEG_SERVER_PID"
```

On restart the saved pause remains effective. `SIGUSR1` explicitly persists the resumed state and reopens submission/dispatch:

```sh
kill -USR1 "$EEG_SERVER_PID"
```

An environment file containing `EEG_MAINTENANCE=1` forces a pause at every startup. A public API token cannot toggle maintenance; no remote write endpoint exists. Follow [queue recovery](anonymous-queue.md) if locks or uncertain worker markers prevent draining.

## Record a release identity

The tool records current Git-visible source bytes, source revision/dirty state, scientific source agreement, frozen-data identity, runtime lock and the selected installed Python/native identity. It does not install dependencies, build, or execute a scientific solve.

Set the following shell variables to verified absolute paths. Use a new output name for each run:

```sh
EEG_SOURCE_ROOT=/absolute/path/host-checkout
EEG_SCIENCE_ROOT=/absolute/path/scientific-checkout
EEG_NATIVE_PYTHON=/absolute/path/scientific-checkout/.runtime/simnibs-4.6.0/bin/python
EEG_QUEUE_PATH=/absolute/path/queue
cd "$EEG_SOURCE_ROOT"
python3 scripts/release_manifest.py \
  --source-root "$EEG_SOURCE_ROOT" \
  --repository-root "$EEG_SCIENCE_ROOT" \
  --python "$EEG_NATIVE_PYTHON" --verify-data \
  --output "$EEG_SOURCE_ROOT/artifacts/releases/candidate.json"
```

The default is preview. Inspect the output and repeat with `--execute` to create the new manifest. Preserve its reported `manifest_sha256` independently. Source, data and runtime identities are recorded separately; the manifest is not a numerical regression result. Keep source and configuration unchanged while creating release and backup inventories.

## Back up the stopped service

After maintenance, drain and confirmed shutdown:

```sh
python3 scripts/backup_service.py backup \
  --source-root "$EEG_SOURCE_ROOT" \
  --repository-root "$EEG_SCIENCE_ROOT" \
  --queue-directory "$EEG_QUEUE_PATH" \
  --python "$EEG_NATIVE_PYTHON" \
  --output "$EEG_SOURCE_ROOT/artifacts/backups/candidate"
```

This previews the inventory. Repeat with `--execute` to write it. Execution requires `--python`, acquires the queue's exclusive acquisition guard and the native forward-cache lock, verifies payloads, then rechecks inventories after copying. A live queue owner, active/uncertain receipt or native writer prevents backup.

The snapshot contains current source, generated job/forward records, `queue.json`, the browser-session signing secret and the complete private `projects/` and `studies/` trees, including scientific snapshots, study case archives and project credential hashes. Browser-held plaintext project access files are separate private recovery material and are not reconstructed from hashes. It excludes frozen model payloads, installed Python/Node environments, `node_modules`, builds, access logs, process locks and private environment files. Retain the matching data bundle, runtime installation materials and private operator configuration separately. The signing secret, receipts and private project archives make the backup private operational material, not a Git or public-release artifact.

Record the printed `manifest_sha256` independently from the snapshot. It is the SHA-256 of `backup.json`; restoration requires that expected value.

## Restore into a new directory

```sh
python3 scripts/backup_service.py restore \
  --repository-root "$EEG_SOURCE_ROOT" \
  --snapshot "$EEG_SOURCE_ROOT/artifacts/backups/candidate" \
  --manifest-sha256 "$EEG_BACKUP_MANIFEST_SHA256" \
  --output "$EEG_SOURCE_ROOT/artifacts/restores/candidate"
```

Set `EEG_BACKUP_MANIFEST_SHA256` to the independently retained hash. Preview verifies the manifest, complete file inventory, every payload hash and paused queue state. Repeat with `--execute` to create the fresh directory. Existing destinations are refused. Both backup and restore outputs must be new paths under the source project's `artifacts/`; links, unexpected entries and overlapping restore paths are rejected.

Restore writes the queue to the restored tree's `results/web-service/`, including when the original queue directory was elsewhere; project and study archives follow that restored queue directory. It never overwrites the live installation. A `.restore-incomplete` marker identifies interrupted publication; do not start such a directory.

The restored report states `ready_to_start: false`. Install the exact frozen bundle and a qualified runtime, install web dependencies, build, configure paths and verify the result before starting. Conda environments and dependency installations are not inside the snapshot. Restoring to a new path can change cache identity; retain historical records and verify exact reuse instead of editing hashes.

## Upgrade and rollback

1. Prepare the candidate checkout, locked dependencies and build; run applicable tests in a separate workspace.
2. Record source/data/runtime identities. Verify that the selected scientific root contains the matching scientific code.
3. Pause, drain and stop the old host; create and verify its backup.
4. Start the candidate in maintenance with the intended scientific root and queue directory. Never run two owners against one queue.
5. Check health, existing records and the approved user workflows; then resume explicitly.
6. If acceptance fails, stop the candidate and restore the previous host plus its compatible data/queue snapshot. Recheck before resuming.

Code rollback does not reverse an incompatible data-format change. Any future migration needs a separately reviewed conversion and recovery procedure. The current refactor preserves stored formats and does not migrate data on startup.


## Direct local operator status and probe

`GET /api/operations/status` accepts only a direct loopback request with a local Host and no Origin, Fetch Metadata or forwarding headers. A computation-session token and project credential do not grant operator access. Block this path at the public proxy. Use the provided raw HTTP probe, `curl` or another local non-browser client; Node `fetch` adds Fetch Metadata and is intentionally rejected by this boundary.

```sh
node webapp/scripts/probe-service.mjs --url http://127.0.0.1:3000
```

The command prints one JSON report without tokens, scientific payloads or private filesystem paths. It accepts `--timeout-ms` from 100 through 60000, with a five-second default absolute deadline and a 1 MiB response bound. `--output` writes only beneath this checkout's `artifacts/` directory and rejects symbolic links or traversal.

| Exit | Meaning | Operator action |
| --- | --- | --- |
| `0` | Ready; or paused and drained when `--allow-paused` was explicitly supplied | Continue the matching acceptance or normal operation procedure |
| `2` | Service responded but is not ready, or resource/logging alerts exist | Read alert codes; inspect queue state, disk, current Node RSS and logging before resuming |
| `3` | Connection, deadline, HTTP, response-size or response-format failure | Check process/port and direct local operator access; inspect supervisor logs |
| `4` | Invalid arguments or unsafe output destination | Correct the command or choose a new regular path under project artifacts |

`--allow-paused` allows a maintained and drained candidate to pass the probe; it does not resume work and does not require queued tasks to be deleted. Drained must still be true. The default probe reports maintenance as not ready for new computation. HTTP success alone does not establish that scientific jobs work; run the target-platform native and browser checks separately.

Request statistics are process-lifetime counts and durations for fixed route labels, including aborted connections. Queue state is the currently retained task state, not an all-time experiment count. Current Node RSS and free disk are direct observations; CPU load and scientific worker peak memory are not measured here. New work is refused if resource sampling fails, disk is below the configured floor or current Node RSS exceeds its enabled threshold. Existing cached results, reads and cancellation remain available. These are admission checks, not hard resource isolation or a capacity guarantee.

Private request logs use generated request identifiers and optional task identifiers for correlation. They exclude headers, query strings, bodies and scientific outputs. Files are limited per UTC day, retained for seven days and buffered through a bounded pending queue. Logging failures or excess events do not fail application responses; the status/probe reports unavailable, failed or dropped logging. Inspect permissions, free space and log pressure when these appear. Preserve an incident's relevant logs privately before retention removes them. Access logs and operations request logs are not part of the scientific/project backup; retain them separately when required.

## Project recovery and retention

Projects are private archives under the configured queue directory. They contain immutable copies of validated layouts, edits and signal results, plus separately editable research metadata. Source receipts may expire without removing the project snapshot. Project credentials are restored manually on another browser using the project identifier and key or downloaded access file; this release does not provide researcher accounts or email recovery. Keep owner access files privately backed up, separate from scientific delivery packages.

Creating a read-only share replaces the previous shared credential; revoking it stops subsequent shared reads. Project credentials do not change who sees the original records in the library lists; that follows the [library scope](anonymous-queue.md#shared-library-visibility). A record the operator removed from the shared library can be attached to a project only from a browser that owns it. A delivery bundle is an offline scientific archive: revoking a credential cannot recall files already downloaded by its holder.

The project store currently bounds entries, snapshot size and total snapshot storage. Removing an entry detaches it from the current project but preserves its immutable project copy and the original scientific record; detached copies still count toward the storage budget. Do not clean projects by deleting arbitrary files beneath `results/`. Define a separate operator retention procedure and make a verified stopped-service backup before any destructive cleanup.

## Interrupted calculations and repeated studies

Use the stopped-service [task reconciliation tool](task-reconciliation.md) to recover interrupted receipts from exact validated completed caches. Preview and apply use a separately saved plan and the original queue SHA-256; scientific outputs remain unchanged. Keep the service stopped while applying the plan.

[Repeated studies](robustness-studies.md) retain per-case requests, outcomes and exact cache copies separately from bounded queue receipts. Startup pauses further study submissions until an explicit study resume. A child previously accepted by the shared queue retains its original queue behavior. Service maintenance and study controls are separate: resuming the service allows scheduling, while resuming a study authorizes its remaining cases.
