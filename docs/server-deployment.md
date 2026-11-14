# Server deployment preparation

The local web host includes project archives, research workflow metadata, scientific delivery bundles, explicit proxy policy, operational monitoring, durable maintenance and recovery tools. These require acceptance on the target platform. **The application has not been deployed publicly.** The target server's operating system, runtime, access policy and public URL are still to be confirmed.

The full application supports browsing, new layout calculations, editing/import, comparisons, reception simulations and downloads. This guide covers server installation, domains, HTTPS, process supervision and backups. Local browser development uses the existing macOS scientific runtime.

## Deployment shape

```text
Browser -> HTTPS reverse proxy -> Node on 127.0.0.1
        -> persistent FIFO / one execution slot -> Python / SimNIBS
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

## Source, science and persistent state

The running checkout supplies web code and `webapp/dist/`. `EEG_REPOSITORY_ROOT` can point it to an existing scientific snapshot containing Python code, configuration, data, runtime and results. It defaults to the host checkout. `EEG_QUEUE_DIRECTORY` separately selects an absolute queue-state directory; its default is `<scientific root>/results/web-service`.

Scientific paths remain checkout-relative inside that root; no startup migration occurs. Preserve the verified inputs and generated `results/v2/*_jobs/` and `results/v2/reception_forward/` directories. The release manifest checks scientific source agreement between the host and selected root. Historical results retain their original identities; path/runtime changes can invalidate current cache reuse. Projects are stored under `<queue directory>/projects/`, including immutable scientific copies. Moving or cleaning task receipts does not remove these project records.

`EEG_COMPUTE_PYTHON` selects the ordinary worker interpreter. Native services prefer `<scientific root>/.runtime/simnibs-4.6.0/bin/python` when it exists. Check and record both selections. The supplied managed runtime targets Apple Silicon macOS; it cannot be transferred to Linux as an executable environment.

## Decisions required before launch

| Area | Information and acceptance needed |
| --- | --- |
| Platform | OS/version, CPU architecture, installation permissions and native-runtime lock |
| Capacity | CPU, RAM, persistent disk and measured uncached-job resource use |
| Access | Computation still uses anonymous signed sessions; decide whether the hosted entry needs an additional invited-user boundary |
| Sharing | Project archives use owner/read-only credentials; the original layout library is still shared and is not made private by saving a project |
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

[`eeglayoutlab.service.example`](../configs/deploy/eeglayoutlab.service.example) is an optional Linux systemd template with placeholder paths and a service account. The template requires target-platform qualification before use. Choose a qualified platform/runtime first, replace every placeholder, and keep the private environment file readable only by the service account. See the [Chinese deployment checklist](productization-handoff.zh-CN.md) for the complete procedure.
