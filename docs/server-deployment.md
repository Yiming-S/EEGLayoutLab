# Server deployment preparation

**Status: planned deployment; public hosting configuration is not yet implemented.**

Yiming Shen, PhD, and Yi Wang, PhD, are preparing EEG Layout Lab for Dr. Wang's server. The target is the full application: browsing existing layouts, designing new layouts, editing and importing electrode coordinates, comparing results, running signal simulations, and downloading outputs. New numerical work will run on the server, with results stored there.

This document records the handoff and implementation work needed before launch. The current [source installation guide](source-installation.md) covers local Apple Silicon macOS use.

## Proposed first deployment

Use one application service on a dedicated subdomain, with HTTPS handled by a reverse proxy and scientific computation on the same server:

```text
Browser
  -> HTTPS reverse proxy on the application's subdomain
  -> Node application on loopback: UI + HTTP APIs
  -> persistent FIFO queue with one execution slot
  -> Python / SimNIBS workers
  -> verified model inputs + persistent results
```

The collaborator's existing website can link to the application. A dedicated subdomain preserves the application's current root-relative API and model-asset paths. Hosting under a website subdirectory requires additional path configuration and testing.

The deployable system includes the Node service and scientific runtime alongside the built interface. Use one application instance for each queue directory; the current scheduler is a single-host service.

## Server information to confirm

| Item | Required information |
| --- | --- |
| Platform | Operating system and version; CPU architecture |
| Capacity | CPU allocation, RAM, persistent disk space, and storage growth allowance |
| Access | Administrative contact, installation permissions, and private server access method |
| Web address | Application domain or subdomain, reverse proxy, and HTTPS certificate management |
| Compute access | Who can submit new work: invited collaborators, signed-in users, or anonymous visitors |
| Results | Whether records are shared across visitors or restricted to a team or individual |
| Operations | Service supervision, logs, backups, retention, and update responsibility |

Set capacity from measurements on the target server using representative cached and uncached requests. The browser interface alone does not determine the memory or storage required for native computation.

## Current implementation and required changes

| Area | Current behavior | Work before public launch |
| --- | --- | --- |
| HTTP host | [`start.mjs`](../webapp/server/start.mjs) listens on `127.0.0.1`; `PORT` defaults to `3000`. | Keep the application behind the reverse proxy and configure the approved public host and HTTPS origin. |
| Request validation | [`loopbackRequest`](../webapp/server/local-compute-server.mjs) checks the socket address, Host, Origin, and Fetch Metadata. | Implement and test an explicit trusted-proxy boundary. Ordinary external HTTPS requests do not pass the current local checks. |
| Visitor sessions | Signed anonymous cookies isolate task receipts and cancellation rights. Cookies currently use HttpOnly and SameSite=Strict. | Add Secure cookies for HTTPS and implement the selected compute-access policy. |
| Client IP | The queue uses the direct connection address and ignores `X-Forwarded-For`. | Accept client-address information only from the configured trusted proxy, so IP limits operate on the intended address. |
| Scientific runtime | The managed installer and environment checker target macOS arm64; the scientific package requires Python 3.11. | Prepare and validate the target platform's runtime. A Linux host needs separate installation locks and platform-aware environment checks. |
| Scheduling | Four scientific services share one persistent FIFO execution slot. | Retain the bounded queue for the first deployment and verify limits through the public proxy. |
| Record visibility | Completed scientific records use the shared results library. | Implement the chosen sharing policy if team or individual access is required. |

The default native interpreter is `.runtime/simnibs-4.6.0/bin/python`. `EEG_COMPUTE_PYTHON` selects the queue's interpreter; native services prefer the project runtime when it exists. Verify the interpreter used by each service on the destination server.

Full functionality requires the SimNIBS native dependencies, auditable Conda package metadata, and solver libraries. The managed runtime is specified in [`configs/runtime/`](../configs/runtime/). The existing macOS environment cannot be copied to Linux as an executable runtime.

## Handoff materials

| Material | Handoff rule |
| --- | --- |
| Application source | Select a reviewed commit or release. Include any approved local changes in that version before handoff. |
| Model data | Supply the archive matching [`data/manifest.json`](../data/manifest.json), install it at the expected checkout-relative paths, and run `python3 scripts/data_bundle.py verify`. |
| Scientific environment | Record the platform, interpreter, package versions, native libraries, and environment verification outcome. |
| Web dependencies and build | Use the checked-in npm lockfile and the Node requirement in [`webapp/package.json`](../webapp/package.json). Build on the deployment system. |
| Selected result records | Transfer the agreed records with their original inputs, IDs, hashes, and provenance. The base data bundle contains selected records, not the complete accumulated result archive. |
| Service configuration | Keep host-specific paths, proxy settings, credentials, and certificates outside Git. |
| Third-party material | Preserve [third-party notices](../THIRD_PARTY_NOTICES.md) and [data-source terms](../data/SOURCES.md) with the handoff. |

For data-bundle creation and installation commands, see [Data and reproducibility](data-and-reproducibility.md). Install dependencies on the destination; keep Mac runtime binaries, `node_modules`, and local build outputs out of the source handoff.

## Persistent storage and recovery

Preserve the checkout-relative scientific inputs, selected existing records, and these generated directories across application updates:

- `results/web-service/`: queue receipts, the session-signing secret, and private operational logs.
- `results/v2/local_app_jobs/`, `results/v2/design_evaluation_jobs/`, `results/v2/electrode_editor_jobs/`, `results/v2/source_reception_jobs/`, and `results/v2/source_reception_v2_jobs/`: requests, validated results, and calculation metadata.
- `results/v2/reception_forward/`: generated forward-field caches.

Use a consistent backup procedure for inputs, records, and queue state, and test restoration before launch. Keep the installed environment reproducible from its recorded dependencies. Reserve storage for new tasks and define retention before opening calculation access.

The queue permits one server owner per state directory. After a restart, queued tasks retain their order; running numerical work is recorded as interrupted and can be resubmitted. There is no numerical checkpoint resume. See [Anonymous visitors and the computation queue](anonymous-queue.md) for locks, limits, and recovery procedures.

Cache identities include code, numerical inputs, runtime details, and filesystem paths. A platform or path change can require new computation. Preserve historical records and validate cache reuse on the target server using the full identity.

## Build and local verification

After the destination runtime and data are ready, build and start the local production host from the repository root:

```sh
cd webapp
npm ci
npm run build
npm start
```

This starts the existing loopback service at `http://127.0.0.1:3000`. `PORT` can select another local port. Public access requires the request-validation, HTTPS, and proxy changes described above.

Run the applicable checks in [CONTRIBUTING.md](../CONTRIBUTING.md), including real-data HTTP and native-computation checks on the destination. The current environment checker must be adapted before it can verify a Linux runtime. Record the exact deployed code, data-manifest identity, runtime, checks performed, and outcomes.

## Acceptance before launch

1. Verify the model-data inventory and the target platform's scientific runtime.
2. Pass type checking, linting, unit checks, and the production build; review the current dependency audit using [the dependency-status guide](security.md).
3. Exercise the browser workflow over the final HTTPS address: existing records, 3D views, region design, coordinate import, electrode editing, comparisons, signal simulation, and downloads in both interface languages.
4. Complete representative new calculations, including a native FEM request; resubmit identical inputs and verify valid cache reuse and result provenance.
5. Verify queue ownership, cancellation, refresh, limits, and the chosen compute-access and record-visibility rules using separate browsers.
6. Restart the service with queued and running work, then verify documented interruption handling and saved-result recovery. Test backup restoration.
7. Record the public URL, operator contact, and deployment version, then update the main README's hosted-version entry.
