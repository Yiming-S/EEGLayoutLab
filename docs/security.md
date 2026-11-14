# Access boundaries and dependency status

The current host always listens on `127.0.0.1`. Local access validates the connecting address, Host, Origin and Fetch Metadata. An explicit HTTPS origin and trusted proxy IP configuration enables hosted access; this policy and Secure-cookie behavior have local tests. The target platform, final reverse proxy and public HTTPS URL require qualification for each installation. Follow [server deployment](server-deployment.md).

## Computation, records and projects

Anonymous signed browser sessions isolate task receipts and cancellation rights. Submission limits, bounded requests and a shared execution permit constrain work. Completed layout records remain in the established shared scientific library: a private project does not make its original layout record private.

Research projects have a separate project identifier and random access credential. The server stores credential hashes. The owner credential permits metadata changes and attaching validated scientific records; a shared credential is read-only and can be revoked or replaced. Project snapshots copy the validated scientific payload and verify its checksum independently of queue receipts. Project names and notes do not enter scientific requests or cache identities.

This is credential-based project access, not a researcher account, identity verification or organization directory. A member opens a project on another browser by manually restoring its identifier and credential or the exported access file. Anyone holding an owner credential can act as that project's owner. Keep access files separate from scientific delivery bundles; the latter contain no project access keys. Losing all owner credentials requires an explicit operator recovery procedure; no email/password recovery endpoint is implemented.

Write requests require both the configured origin policy and the current computation-session token. That token does not grant project access or operator privileges. The direct local operations endpoint rejects browser and proxy metadata and must remain unavailable through the public proxy. Operating-system access controls maintenance signals; no public maintenance-write endpoint exists.

## Operational data

Private project archives, queue state and signing secrets belong in protected server storage and private stopped-service backups. Do not publish them as source or release assets. The server's request log contains generated request identifiers, fixed route labels, status, duration and optional task identifier/status. It excludes cookies, access credentials, client query parameters, request bodies and scientific result bodies. Log size and retention are bounded; dropped or unavailable logging is visible to the local operator probe.

Disk and optional Node-memory admission checks reject new work when observations fail. These checks do not establish a hard operating-system memory limit, measure scientific worker peak memory or qualify public-service capacity. See [operations](web-operations.md) for configuration and response procedures.

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
