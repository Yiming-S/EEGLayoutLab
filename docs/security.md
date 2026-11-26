# Access boundaries and dependency status

The application's host is the local Python service, `eeglayoutlab serve`, for one user and one workspace ([design 0001](design/0001-local-first-architecture.md)). It listens on `127.0.0.1` only. Before any routing, every request must come from a loopback address, name the loopback interface in `Host`, and carry no foreign `Origin` or cross-site Fetch Metadata; otherwise it gets 403. Every path, pages and health included, also needs the session cookie that the command's launch link (`/open?token=…`) sets. Without it the service answers 401: a tab from an earlier run, or an address typed by hand, asks to run the command again. Each start has a new port, launch token, cookie and write token. Writes also need the write token from health in `X-EEG-Compute-Token`. Every secret is compared in constant time.

## Computation, records and projects

The workspace's queue holds the tasks of its one user; any page of the session can follow or cancel them. One computation runs at a time per installation, and every request size and the queue length stay bounded. Completed layout records remain in the shared scientific library under `results/v2`, which every workspace of the checkout reads: a project does not make its original layout record private.

Research projects and robustness studies are kept in the workspace directory (`projects/`, `studies/`). The project page lists the workspace's projects, and opening or changing one needs only the session: there are no project credentials, roles, read-only shares or access files. The service ignores an `X-EEG-Project-Key` header and answers 404 to `share` and `revoke-share`. Anyone who can read the workspace directory, or use the running session, can read and change its projects; protect the workspace with the operating system's file permissions, as for any private file. Project snapshots copy the validated scientific payload and verify its checksum independently of queue receipts. Project names and notes do not enter scientific requests or cache identities. A delivery package contains no access key.

The write token does not grant operator privileges, and the service has no remote operations or maintenance endpoint: `--cache-only` serves stored results only.

## The legacy Node host

The legacy Node host (`npm start`), which hosted deployments keep at the tag `node-host-freeze` until phase 4 of design 0001, has its own access model. It also listens on `127.0.0.1`; an explicit HTTPS origin and trusted proxy IP configuration enables hosted access, and this policy and its Secure cookies have local tests. Anonymous signed browser sessions isolate its task receipts and cancellation rights, with submission limits per browser and per network. Its research projects have a project identifier and a random access credential whose hash it stores: the owner credential permits changes, a shared credential is read-only and can be revoked or replaced, and a member opens a project on another browser by restoring its identifier and credential or an exported access file. This is credential-based access, not a researcher account; losing all owner credentials requires an explicit operator recovery. The current interface no longer offers these credentials, so it does not open the Node host's projects; `eeglayoutlab workspace import-legacy` copies them into a workspace. Its direct local operations endpoint rejects browser and proxy metadata and must remain unavailable through the public proxy. Follow [server deployment](server-deployment.md) for a hosted installation.

## Operational data

Workspaces, private project archives, the legacy host's queue state and signing secrets belong in protected storage and private backups. Do not publish them as source or release assets. The legacy Node host's request log contains generated request identifiers, fixed route labels, status, duration and optional task identifier/status. It excludes cookies, access credentials, client query parameters, request bodies and scientific result bodies. Log size and retention are bounded; dropped or unavailable logging is visible to the local operator probe. The Python service writes no request log; its messages go to the terminal that runs it.

The legacy host's disk and optional Node-memory admission checks reject new work when observations fail. These checks do not establish a hard operating-system memory limit, measure scientific worker peak memory or qualify public-service capacity. See [operations](web-operations.md) for configuration and response procedures.

## Current locked dependency audit: 2026-11-13

The first productization round ran `npm ci` from the updated lockfile and audited both the complete installed dependency graph and `--omit=dev`. Both reports contain zero known affected entries. The reports are retained locally as `artifacts/productization/2026-11-13/dependency-audit-final.json` and `dependency-audit-production-final.json`. This result applies to that lockfile and the advisory database at the time of the audit; it does not replace target-server qualification.

The installed set includes React and React DOM 19.2.9, `react-server-dom-webpack` 19.2.9, Vinext 1.0.1, Vite 8.1.6 and `@vitejs/plugin-rsc` 0.5.34. A scoped `satori@0.33.5` override selects `fflate` 0.7.5; compression round trips and the Satori-to-SVG-to-PNG path were checked. The application does not use `next/og` or `ImageResponse`; its unused framework wrapper was not qualified by those checks. The shadcn command-line dependency was removed; its existing CSS is retained unchanged with its MIT notice under `webapp/styles/vendor/shadcn/`.

The production build, application tests, real browser workflows and scientific regression were rerun with the updated installed dependencies. No Python package, model input or scientific calculation setting was changed by the dependency update.

## Historical dependency audit: 2026-09-10

The following table is an archival record of an earlier locked environment. That audit reported five high-severity affected dependency entries; it is **not a current vulnerability count** or a claim that these entries remain unresolved in the current lockfile.

| Dependency in the historical audit | Recorded issue | Upstream advisory |
| --- | --- | --- |
| `image-size` | Malformed image parsing can loop indefinitely. | [ICNS](https://github.com/advisories/GHSA-w3rx-r6r6-pgpr), [JXL/HEIF](https://github.com/advisories/GHSA-5p2g-fcmc-qvqq) |
| `react-server-dom-webpack` | Resource exhaustion in Server Functions. | [Server Functions denial of service](https://github.com/advisories/GHSA-wx67-qw84-cm4g) |
| `undici` | Proxy, header, cache and WebSocket issues. | [Proxy certificate validation](https://github.com/advisories/GHSA-vmh5-mc38-953g), [cache disclosure/crash](https://github.com/advisories/GHSA-4cwx-7wf7-3272) |
| `vinext` | Affected through its `image-size` dependency. | Image-parser advisories above. |
| `vite` | Windows development-server path handling. | [File-deny bypass](https://github.com/advisories/GHSA-fx2h-pf6j-xcff), [UNC path handling](https://github.com/advisories/GHSA-v6wh-96g9-6wx3) |

Before each distributed candidate, audit its actual lockfile, retain the dated report and assess each finding against the installed version and exposed application paths:

```sh
cd webapp
npm audit
```

An audit result, dependency upgrade and target-server acceptance are separate records. Review targeted lockfile changes and rerun applicable tests; installation does not perform forced automatic upgrades. Keep private environment files, certificates, installed runtimes and generated user records outside Git.
