# Security Policy

## Local-First Security Model

EEG Layout Lab runs on the user's own machine and binds its HTTP service exclusively to the IPv4 loopback address (`127.0.0.1`) on an ephemeral port. Every session generates fresh launch, cookie, and CSRF tokens, refuses cross-origin writes and non-loopback peers, never executes shell strings from client payloads, and verifies SHA-256 digests on all model data packages and research deliveries before loading them.

Full details of the local access boundary, workspace file permissions (`0700` / `0600`), and dependency pinning are documented in [docs/security.md](docs/security.md).

## Supported Versions

| Version | Supported |
| --- | --- |
| `0.2.x` | Yes |
| `< 0.2.0` | No (upgrade to `0.2.x`; legacy hosted Node deployments stay pinned at `node-host-freeze` until Phase 4 retirement) |

## Reporting a Vulnerability

Please **do not** open a public issue for suspected security vulnerabilities (such as loopback authentication bypass, CSRF token leakage, path traversal in coordinate/delivery readers, or archive extraction escapes).

Instead, report vulnerabilities privately through the `Yiming-S/EEGLayoutLab` repository's **GitHub Security Advisories** ("Report a vulnerability" under the Security tab). Include:

1. Affected version or commit hash and operating system (`macOS arm64` or `Linux x86_64`).
2. Minimal reproduction steps or proof-of-concept request/file.
3. Expected vs. observed security boundary behavior.

Reports are acknowledged within 7 days, and a fix and coordinated advisory are prepared before public disclosure.
