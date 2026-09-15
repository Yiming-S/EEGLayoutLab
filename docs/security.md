# Local execution and dependency status

## Execution boundary

This collaboration release runs on the user's own computer. Both the development
host and the production start script bind to `127.0.0.1` by default. The local
computation API checks the connecting address, HTTP Host, Origin and Fetch
Metadata. Mutating requests also require the current session token. Worker
requests use bounded schemas and a shared execution slot.

Anonymous browser cookies now isolate queue receipts and cancellation rights;
completed scientific records remain in the existing shared results library.
See [anonymous visitors and scheduling](anonymous-queue.md) for storage,
rate limits, IP retention and restart behavior.

Do not expose the local server through port forwarding, a public tunnel or a
shared network interface. Public proxy, HTTPS and origin configuration remain
a separate deployment step; the current connection checks remain local-only.
Do not commit environment files, certificates, runtime installations or user jobs.

## Dependency audit recorded on 2026-09-10

`npm audit --json` reported **5 high-severity affected dependency entries** in the
locked web environment. This count is not a count of five independently
exploitable application flaws; one entry is the parent dependency that introduces
another affected package. They remain unresolved in this migration so that the
framework and scientific functionality can be validated separately from upgrades.

| Dependency | Reported issue | Upstream advisory |
| --- | --- | --- |
| `image-size` | Malformed image parsing can loop indefinitely. | [ICNS](https://github.com/advisories/GHSA-w3rx-r6r6-pgpr), [JXL/HEIF](https://github.com/advisories/GHSA-5p2g-fcmc-qvqq) |
| `react-server-dom-webpack` | Resource exhaustion in Server Functions. | [Server Functions denial of service](https://github.com/advisories/GHSA-wx67-qw84-cm4g) |
| `undici` | Multiple proxy, header, cache and WebSocket issues. | [Proxy certificate validation](https://github.com/advisories/GHSA-vmh5-mc38-953g), [cache disclosure/crash](https://github.com/advisories/GHSA-4cwx-7wf7-3272) |
| `vinext` | Affected through its `image-size` dependency. | Same image-parser advisories above. |
| `vite` | Windows development-server path handling issues. | [File-deny bypass](https://github.com/advisories/GHSA-fx2h-pf6j-xcff), [UNC path handling](https://github.com/advisories/GHSA-v6wh-96g9-6wx3) |

Audit the exact installed lock file again before distribution. A public service
requires a separate dependency update, regression pass and deployment security
review. The current local-only setting narrows network exposure; it does not
remove the reported dependency issues or establish a clean security audit.

```sh
cd webapp
npm audit
```

The project has no automatic dependency upgrades in its installation scripts.
Review targeted updates and their lockfile changes rather than using an
unreviewed forced framework upgrade.
