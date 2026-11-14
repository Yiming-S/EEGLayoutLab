# Contributing

Start with [source installation](docs/source-installation.md), [architecture](docs/architecture.md) and [model definitions](docs/model-and-metrics.md). EEGLayoutLab is maintained as a web application. The native Mac wrapper and packaging tools are retired.

## Change boundaries

Routes compose feature workspaces. Keep interaction state in `webapp/features/`, common task transport in `webapp/client/`, rendering in `webapp/viewer/`, and HTTP/execution/storage in `webapp/server/`. Scientific code belongs in `src/compact_eeg/`. Browser modules must not import server code; automated boundary checks enforce this rule. Shared layout types and cross-language examples live in `contracts/`.

Preserve worker entry points, request normalization, frozen inputs and recorded provenance during structural changes. Changes to numerical assumptions require an explicit protocol/identity decision. File bytes and runtime paths participate in scientific cache keys; moving code can affect reuse without changing numerical outputs. Check numerical behavior, historical reading and current identity generation separately. Coordinate changes must preserve units, reference frame and channel/region order. Imports require coordinates registered to the Ernie subject.

Use `server/host/` for framework startup, `server/jobs/` for worker lifecycle and `server/storage/` for record access. A new workflow must share the execution slot and retain its own validation and resource limits. Keep scientific dependency upgrades separate from UI upgrades and structural refactors.

Git contains application source, display assets, configuration, documentation and tests. Large scientific payloads, installed environments, records, credentials and captures remain outside Git. Put local deliverables in the project's `artifacts/`. The root `.gitignore` allowlist must be updated when adding a new project directory. Preserve third-party attribution.

## Verification tiers

| Tier | Inputs and scope | Commands |
| --- | --- | --- |
| Fast | Source, packaged browser assets and synthetic fixtures; no external scientific bundle or native runtime | Commands below; also `.github/workflows/checks.yml` |
| Data | Verified frozen bundle and an isolated scientific workspace | Full unit/Python checks and real-data HTTP integration |
| Native | Qualified Python/SimNIBS environment and native inputs | Environment check plus integration with `--native` |
| Browser | Running production host and Chromium | Viewer checks and complete bilingual user workflows |

The fast workflow has been exercised locally on a source copy without scientific payloads or an installed native runtime. A remote GitHub Actions run has not been performed. Data/native cases are explicitly skipped or deselected in that tier; passing it does not run a FEM solve.

From the repository root:

```sh
python -m pip install -e '.[dev]'
python -m pytest -m 'not data_bundle and not native_runtime' -q
cd webapp
npm ci
npm run typecheck
npm run lint
npm run test:fast
npm run build
```

For full local checks after installing the matching data and native environment:

```sh
python3 scripts/data_bundle.py verify
.runtime/simnibs-4.6.0/bin/python scripts/check_environment.py
.runtime/simnibs-4.6.0/bin/python -B -m pytest tests -q -p no:cacheprovider
cd webapp
npm run test:unit
```

The managed runtime currently targets Apple Silicon macOS. A server on another platform needs its own installation lock and environment qualification.

## Isolated integration and browser checks

A different port does not isolate records. Prepare a new QA workspace before write-producing checks. The helper defaults to preview and writes only beneath the source project's `artifacts/`:

```sh
python3 scripts/prepare_verification_workspace.py \
  --output "$PWD/artifacts/qa-candidate" \
  --runtime-source "$PWD/.runtime/simnibs-4.6.0" \
  --link-node-modules --copy-dist
```

Inspect the plan, then repeat with `--execute`. The helper copies verified model inputs and current source, excludes accumulated historical caches, and can copy the installed runtime and existing build. `--link-node-modules` shares dependencies for local QA only. A copied Conda environment is not a portable distribution; embedded prefixes are retained and the interpreter must be checked at its new path.

Start the QA checkout's built host on an unused loopback port. From its `webapp/` directory:

```sh
PORT=3101 npm start
```

In another terminal, from the same QA `webapp/`:

```sh
EEG_TEST_URL=http://127.0.0.1:3101 npm run test:integration
EEG_TEST_URL=http://127.0.0.1:3101 npm run test:integration -- --native
npm exec playwright install chromium
VIEWER_QA_URL=http://127.0.0.1:3101/ npm run test:viewer
```

The HTTP check exercises record loading, layout design, editor evaluation, coordinate evaluation, source reception and exact cache replay. `--native` adds uncached native-coordinate and single/multi-source cases and can take several minutes. Browser tests exercise rendering and interaction separately. Save evidence under the project; `EEG_QA_OUTPUT` selects the viewer capture directory.

`scripts/check-viewer-assets.mjs` covers shared model downloads, version changes, cancellation, retry, eviction and independent scene arrays. `scripts/check-model-loading-browser.mjs` measures actual signal-page model requests and transfers across first load, viewer remount and reload using an existing cached experiment. See the [performance report](docs/web-performance.zh-CN.md) for the reproducible command and measurement conditions.

For the current deferred viewer, add `--expect-deferred` together with `--expect-shared`. Use an exact cached result from the target QA server as `EEG_SIGNAL_FIXTURE`; a missing cache fails the check without submitting a job. After `npm run build` and a fresh server start, verify the actual compressed HTTP bytes from the host checkout's `webapp/` directory:

```sh
EEG_TEST_URL=http://127.0.0.1:3101 \
EEG_SIGNAL_FIXTURE=/absolute/path/to/qa-signal-result.json \
EEG_COMPRESSION_REPORT="$PWD/../artifacts/qa-candidate/http-compression.json" \
node scripts/check-compression-live.mjs
```

This check compares decoded models with the host's original model files and cached JSON with the supplied result. It checks encoding negotiation, HEAD, conditional requests, byte ranges and API access headers without submitting work. `scripts/check-workflows-browser.mjs` separately exercises actual layout, signal, playback, download and cancellation controls; it writes jobs and requires the isolated queue to be resumed. Unit coverage for runtime invalidation, shared forward archives, deferred loading, hidden-page playback and compression is included in `npm run test:unit` and the Python suite. The [optimization record](docs/performance-optimization-progress.zh-CN.md) lists the numerical comparison scope.

## Review and release

Research projects and their delivery format are documented in [project formats](contracts/project-formats.md). Project metadata is separate from numerical identities. Check owner/viewer access, optimistic revisions, independent archived replay and exact snapshot bytes when changing this layer. The opt-in `scripts/check-productization-browser.mjs` covers project recovery/sharing; `scripts/check-project-workflow-browser.mjs --with-delivery` covers the complete research workflow and verified downloads. Both require an isolated host and project-local `EEG_QA_OUTPUT`; the latter also needs an existing cached signal fixture via `EEG_SIGNAL_FIXTURE`.

The local stylesheet under `webapp/styles/vendor/shadcn/` retains the original CSS and MIT license; the unused component-generator CLI is excluded from runtime dependencies. The lockfile narrowly overrides `satori@0.33.5` to use the patched `fflate@0.7.5`. Review that override when updating its parent and repeat application build, image/font checks and browser regressions. Do not use a forced audit fix across unrelated dependency branches.

Describe the resulting behavior, relevant checks and unrun tiers. For scientific changes, identify the inputs/runtime and compare matched conditions. Use [web operations](docs/web-operations.md) for release identity, durable maintenance, backup and restore. Target-server deployment and public-URL acceptance are separate from local verification; progress is recorded in [the refactor log](docs/web-refactor-progress.zh-CN.md).

## Licensing

© 2026 Yiming Shen & Yi Wang. Original source code and accompanying documentation are licensed under [GPL-3.0-only](LICENSE). Third-party terms remain in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
