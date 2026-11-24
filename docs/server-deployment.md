# Server deployment preparation

The local web host includes project archives, research workflow metadata, scientific delivery bundles, explicit proxy policy, operational monitoring, durable maintenance and recovery tools. These require acceptance on the target platform. **The application has not been deployed publicly.** The target server's operating system, runtime, access policy and public URL are still to be confirmed.

The full application supports browsing, new layout calculations, editing/import, comparisons, reception simulations and downloads. This guide covers server installation, domains, HTTPS, process supervision and backups. Local browser development uses the macOS scientific runtime. A Linux x86_64 server uses the [Linux runtime](source-installation.md#linux-x86_64), which has no SimNIBS and computes from published scalp-node tables.

## Deployment shape

```text
Browser -> HTTPS reverse proxy -> Node on 127.0.0.1
        -> persistent FIFO / one execution slot -> Python (Linux: table runtime; Mac: SimNIBS)
        -> verified inputs and persistent scientific records
```

Use a dedicated subdomain and link to it from an existing website. APIs and model assets use root-relative paths; subdirectory hosting has not been implemented. The full service requires Node and a qualified scientific runtime alongside the built frontend. One owner is permitted for each queue directory. Keep that queue and its `projects/` tree on persistent private storage.

## Configuration and proxy contract

Copy [`configs/deploy/server.env.example`](../configs/deploy/server.env.example) to a private path outside the checkout. Set the host's actual paths and load the file explicitly; `npm start` does not read this file automatically:

```sh
cd webapp
npm ci
npm run build
cd ..
node --env-file=/absolute/path/server.env webapp/server/start.mjs
```

Production always binds to `127.0.0.1`; `PORT` defaults to `3000`. Keep public TLS at the reverse proxy. The access policy has two modes:

| Configuration | Behavior |
| --- | --- |
| No public origin or trusted proxies | Local Host/Origin/Fetch Metadata checks; forwarded headers do not identify visitors |
| `EEG_PUBLIC_ORIGIN=https://eeg.example.org` plus explicit `EEG_TRUSTED_PROXIES` IPs | Requests from a listed proxy must match the configured host and HTTPS origin; anonymous cookies use Secure, HttpOnly and SameSite=Strict |

The trusted proxy must **overwrite**, rather than append or pass through, these values:

- `Host`: the configured public hostname, including its port if configured.
- `X-Forwarded-Proto`: exactly `https`.
- `X-Forwarded-For`: exactly one actual client IP address. Forwarding chains are rejected.

Incoming `Origin`, when present, must equal the configured HTTPS origin. Cross-site Fetch Metadata is rejected. Local loopback requests remain available for operator health checks. The policy does not trust `X-Forwarded-Host` or infer a proxy from arbitrary headers. Keep the backend port inaccessible from external interfaces. Block `/api/operations/status` at the public proxy; operator status is only for a direct local request without Origin, Fetch Metadata or forwarding headers.

This boundary and Secure-cookie behavior have local HTTP tests. The final proxy configuration, browser cookies and client-IP limits must also be checked over the real public URL.

The result library lists every visitor's records, including the names visitors gave their coordinate files, to everyone. Remove a record with `npm run library:moderate -- --queue-directory <dir> remove <id> --reason "…"` from `webapp/`; see [shared library visibility](anonymous-queue.md#shared-library-visibility), which also describes the optional `EEG_LIBRARY_SCOPE=owner` mode.

## Source, science and persistent state

The running checkout supplies web code and `webapp/dist/`. `EEG_REPOSITORY_ROOT` can point it to an existing scientific snapshot containing Python code, configuration, data, runtime and results. It defaults to the host checkout. `EEG_QUEUE_DIRECTORY` separately selects an absolute queue-state directory; its default is `<scientific root>/results/web-service`.

Scientific paths remain checkout-relative inside that root; no startup migration occurs. Preserve the verified inputs and generated `results/v2/*_jobs/` and `results/v2/reception_forward/` directories. The release manifest checks scientific source agreement between the host and selected root. Historical results retain their original identities; path/runtime changes can invalidate current cache reuse. Projects are stored under `<queue directory>/projects/`, including immutable scientific copies. Moving or cleaning task receipts does not remove these project records.

`EEG_COMPUTE_PYTHON` selects the ordinary worker interpreter. Native services prefer the managed runtime: `<scientific root>/.runtime/simnibs-4.6.0/bin/python` when it exists, otherwise `<scientific root>/.runtime/compute-linux-64/bin/python`. Check and record both selections. The macOS runtime cannot be transferred to Linux as an executable environment. On Linux, install `.runtime/compute-linux-64` with `python3 scripts/bootstrap_runtime.py --execute` from [`manifest-linux-64.json`](../configs/runtime/manifest-linux-64.json). Research deliveries then name that lock. `scripts/release_manifest.py --python` reads the SimNIBS reception identity and does not work with the Linux runtime yet (`inspect_reception_runtime.py` stops because SimNIBS is not installed); run it without `--python` there. Without `--python` it records the macOS lock `configs/runtime/manifest.json` as the runtime lock, also on Linux; record the Linux lock `manifest-linux-64.json` separately.

## Memory and the scalp-node table

Without a table, every new-coordinate evaluation factorizes the full head model; on the reference Mac its measured peak was about 9.5 GiB, so such a host needs 16 GB of RAM. With a published scalp-node table the same evaluation memory-maps a 1.3 GiB row file (40,024 nodes × 4,352 sources, float64) and reads only the rows it needs; the table determines which path runs (see [architecture](architecture.md)). Measured on the reference Mac (2026-11-20, `check-app-live.mjs --native`): new-coordinate evaluation peaked at 0.39 GiB and 1.3 s, its reception at 0.45 GiB, and the whole service process tree at 0.85 GiB. Building the table there took 22 minutes with four workers (about 10 GiB each).

Measured on Linux (2026-11-21, Docker `linux/amd64` emulated with Rosetta on the reference Mac, Linux runtime, [examples](../examples/README.md)): an evaluation worker peaked at 442 MiB and the radius search at 737 MiB. The scores matched the Mac within 1e-6 (largest difference 4.1e-14). On a physical host (2026-11-23, Ubuntu 26.04.1 LTS, Intel Core i9-14900K, 123 GiB RAM, the same runtime lock and the same examples), an evaluation worker peaked at 375 MiB, the radius search at 699 MiB and the whole process tree at 831 MiB; the examples took 30 s, and the scores matched the Mac run of the same code within 3.5e-14 (see [source installation](source-installation.md#linux-x86_64)). A Linux server without the table cannot evaluate new coordinates, because its runtime has no SimNIBS.

Build the table on a host with the qualified native runtime. Preview first; each worker needs about 10 GiB:

```sh
.runtime/simnibs-4.6.0/bin/python scripts/build_scalp_node_table.py --jobs 4
.runtime/simnibs-4.6.0/bin/python scripts/build_scalp_node_table.py --jobs 4 --execute
```

The builder verifies the superposed standard64 reference against a direct FEM solve (`1e-9`) and the bank (`1e-8`), then publishes atomically. To install it on a server, copy `results/v2/current_scalp_node_table.json` and `results/v2/scalp_node_table/<table_id>/` into the scientific root with the service stopped, then rehash the rows and check their identity:

```sh
.runtime/compute-linux-64/bin/python scripts/build_scalp_node_table.py --verify
```

Add `--head <id>` to check a head package's table. Both checks passed on the Linux runtime.

A table only matches the bank, head model, sources, admission mask and vertex rule it was built from. After any of those change, rebuild it or remove the pointer; evaluation refuses a mismatched table.

Optional protocols add their own tables, built the same way on the Mac and copied with the service stopped:

- Each conductivity scenario (`--conductivity-scenario skull_x0.5`, `skull_x2`) adds about 1.3 GiB under `results/v2/scalp_node_table_scenarios/<name>/`.
- Each head package adds its package files plus a table under `results/v2/heads/<id>/`. The table size depends on that head's admissible scalp nodes; count about 1–2 GiB per head.
- Evaluation memory per job stays at the table path's level (under 0.5 GiB), because only the requested rows are read.
- A request for a scenario or head whose table is absent is rejected; nothing is computed on the server.

## Building head packages

Head packages and their tables are built on the Mac. The server only reads packages and tables; it does not run `charm` or the builders.

```sh
.runtime/simnibs-4.6.0/bin/python scripts/build_head_package.py --head-id <id> \
  --t1 <T1.nii.gz> --t2 <T2.nii.gz> --dataset IXI --subject <subject> --execute
.runtime/simnibs-4.6.0/bin/python scripts/build_scalp_node_table.py --head <id> --jobs 4 --execute
```

- `charm` calls SimNIBS's bundled x86_64 tools (`CAT_Surf2Sphere`, `CAT_WarpSurf`, `meshfix`, `mmg3d`). On Apple silicon these need Rosetta 2. The builder checks for it before starting `charm` and, if it is missing, stops and names `softwareupdate --install-rosetta --agree-to-license`.
- Measured `charm` peak memory was 34–38 GB (IXI002 surfaces and mesh resume: 36.0 GB peak footprint). Run one `charm` at a time.
- A package records the SHA256 of the code each stage ran. A package rebuilt with changed code has a new SHA256, and its table must be rebuilt.
- Input folders stay under the repository root: `charm` writes to `data/external/heads/<id>/`, and the Ernie m2m folder is `data/external/simnibs4_examples/m2m_ernie`. A link there to a folder elsewhere is fine. `package.json` records the path under the root, never the link's target; the builder refuses an input outside the root.
- An existing m2m folder without a builder record is used only with `--charm-resume`, which asserts that it came from the given scans. A finished folder is adopted as is (`charm_action: "adopt"`). An unfinished folder is continued with `charm <id> --surfaces --mesh` only when `charm` has written its label image (after the MNI warps) and has not yet run spherical registration; otherwise `charm` reruns with `--forcerun`. A folder recorded for other scans or another SimNIBS version is refused. `package.json` records `charm_resumed` and `charm_action`.
- `charm` refuses scans whose qform and sform header matrices differ. `--charm-forceqform` passes `--forceqform` to it. Use it only after checking that the two matrices differ by rounding.
  - The option is part of the recorded `charm` inputs. Every later build of that head must pass the same setting; otherwise the build stops and names the option.
  - When `charm` has refused the headers, rerun the same build with `--charm-forceqform`. The builder reruns `charm` with `--forceqform --forcerun`, which replaces the folder the refusal left. This happens only when the recorded attempt has no label image and no mesh.
  - A folder that `charm` got further with is never deleted automatically. To rebuild it with the other setting, move it aside first.

## Decisions required before launch

| Area | Information and acceptance needed |
| --- | --- |
| Platform | OS/version and installation permissions. A Linux x86_64 lock without SimNIBS exists and has been qualified in emulation and on one physical x86_64 host (above); qualify it again on the deployment host |
| Capacity | CPU, RAM, persistent disk and measured uncached-job resource use |
| Access | Computation still uses anonymous signed sessions; decide whether the hosted entry needs an additional invited-user boundary |
| Sharing | Project archives use owner/read-only credentials. The result library is public to all visitors; decide who handles removal requests and how quickly |
| Web | Domain, HTTPS, proxy ownership and final-URL browser checks |
| Operations | Supervisor, operator contact, storage retention, backup destination and recovery responsibility |

Install the archive matching [`data/manifest.json`](../data/manifest.json) and verify it using `python3 scripts/data_bundle.py verify`. Preserve the [third-party notices](../THIRD_PARTY_NOTICES.md) and [data terms](../data/SOURCES.md). Install dependencies and build on the chosen platform; recorded dependency identities are separate from numerical qualification.

## Launch acceptance

1. Qualify the platform/runtime and verify every model input.
2. Run the applicable [fast, data, native and browser checks](../CONTRIBUTING.md), including real uncached native work and exact replay.
3. Exercise both languages, layouts, editing/import, comparisons, reception and downloads over the final HTTPS origin.
4. Check independent-browser task ownership, cancellation, refresh recovery and rate limits. Restore a project on another browser, read its full scientific snapshots, revoke a shared credential, and verify that read-only access cannot modify it. Confirm the original layout library remains shared as documented.
5. Rehearse maintenance, stopped-service backup, fresh-directory restoration and version rollback using [web operations](web-operations.md).
6. Run the local operator probe, inspect resource thresholds and log alerts, and record measured queue wait, calculation duration, peak worker memory and storage growth. Node RSS monitoring alone does not measure worker peak memory.
7. Record the deployed version, public URL and operator contact with the installation record.


## Resource and operations preparation

The environment template sets `EEG_MIN_FREE_DISK_MB=512`, `EEG_MAX_HOST_RSS_MB=0` and `EEG_OPERATIONS_LOG_MB=5`. Units are MiB. The disk floor covers both scientific and queue filesystems. The optional memory threshold measures the current Node process only; it is disabled at zero and does not enforce an operating-system limit or cover Python/native worker memory. Resource failures reject new work while result reading and cancellation remain available. Establish target-platform capacity before setting a nonzero memory threshold or increasing concurrency.

From the host checkout, inspect the paused candidate through direct loopback:

```sh
node webapp/scripts/probe-service.mjs \
  --url http://127.0.0.1:3000 --allow-paused \
  --output artifacts/deployment/candidate-probe.json
```

The probe performs one read-only raw HTTP request. It never submits or cancels work, changes maintenance, or consumes a browser/project credential. Remove `--allow-paused` for normal ready-to-compute checks. Exit codes are documented in [operations](web-operations.md).

[`eeglayoutlab.service.example`](../configs/deploy/eeglayoutlab.service.example) is an optional Linux systemd template with placeholder paths and a service account. The template requires target-platform qualification before use. Choose a qualified platform/runtime first, replace every placeholder, and keep the private environment file readable only by the service account.
