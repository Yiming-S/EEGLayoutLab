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
python -m pip install -e '.[dev,service]'
python -m pytest -m 'not data_bundle and not native_runtime' -q
cd webapp
npm ci
npm run typecheck
npm run lint
npm run test:fast
npm run build
```

The `service` extra installs Pydantic, FastAPI and Uvicorn for the request schemas in `src/eeglayoutlab`. Without it the schema parity tests are skipped; CI sets `EEG_REQUIRE_SCHEMA_PARITY=1`, which makes them required. After changing a request schema, regenerate the files in `contracts/generated/` ([contracts](contracts/README.md#generated-request-types)).

For full local checks after installing the matching data and native environment:

```sh
python3 scripts/data_bundle.py verify
.runtime/simnibs-4.6.0/bin/python scripts/check_environment.py
.runtime/simnibs-4.6.0/bin/python -B -m pytest tests -q -p no:cacheprovider
cd webapp
npm run test:unit
```

The managed runtime targets Apple Silicon macOS. Linux x86_64 has its own lock without SimNIBS (`.runtime/compute-linux-64/bin/python` in the commands above; see [source installation](docs/source-installation.md#linux-x86_64)). Any other platform needs its own installation lock and environment qualification.

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

The Python service that replaces the Node host ([phase 2 plan](docs/design/0001-phase-2-plan.md)) runs beside it on its own loopback port, with the same scientific root and its own workspace directory, and gains endpoints slice by slice; keep using the Node host for real work until slice 10. It serves the built interface. From the repository root:

```sh
python -m pip install -e '.[service]'   # also installs the eeglayoutlab command
(cd webapp && npm run build)
eeglayoutlab serve /absolute/path/to/workspace --no-browser
```

It prints `http://127.0.0.1:<port>/open?token=<launch token>`. Opening that address sets the session cookie, which every other request needs; writes also need the token from health. The cookie belongs to the host name, so a page opened on `localhost` instead gets a 401 page. Without `--no-browser` it opens the address once the service answers, through the private page `<workspace>/.eeglayoutlab/open.html`, so that the token is not on the browser's command line, which other local users can read (macOS's default browser gets the address itself). A browser that cannot read files in that directory, such as a snap package outside the home directory, shows an error; open the printed address instead. `--root`, `--static` and `--port` choose another root, export and port. `--docs` chooses the built documentation site that the service serves under `/docs/` (default `R/site`, what `mkdocs build` writes); until it is built, `/docs/` answers 503 and the interface links to the documentation on GitHub; running the command again on the same workspace prints the running instance's address. SIGINT or SIGTERM stops it. Radius searches, coordinate evaluations, electrode edits and signal simulations run in the workspace's queue (`<workspace>/.eeglayoutlab/queue.json`) and write their records under the root's `results/v2`, which two workspaces of one checkout share, one computation at a time; the signal records (`/api/community/records`) are the receipts of that workspace's queue; do not compute on the Python service while the Node host computes on the same checkout. Electrode names and source declarations imported with coordinates are kept in the workspace, in `<workspace>/annotations/electrode-names/`, never in the shared records. `--cache-only` serves stored results and refuses new computations (health reports `maintenance: true`). `--clear-interrupted` releases a task whose worker start a crash interrupted, which otherwise blocks the queue until the next reboot, and a recorded worker pid that still names a live process; use it once no worker of the earlier run is computing (the service log says when the queue waits). A `queue.json` that cannot be read stops `serve` and is kept as it is. A workspace whose `.eeglayoutlab` state cannot be made private, on a FAT, exFAT, NTFS or SMB mount that ignores chmod, is refused; choose one on a local disk.

To run the HTTP check against it, name the workspace's runtime file; `scripts/helpers/service-session.mjs` exchanges the launch token at `/open` for the cookie and reads the token:

```sh
EEG_SERVICE_RUNTIME=/absolute/path/to/workspace/.eeglayoutlab/runtime.json npm run test:integration
```

`EEG_SERVICE_TOKEN=<launch token>` with `EEG_TEST_URL` does the same without the file. Both, and `EEG_API_TARGET` below, take `http://127.0.0.1:<port>` only, never `localhost`: Node would connect to `[::1]` first, where another local user could listen on the same port. The check passes health, its page routes, the cookie check, the library, a radius job with its cached replay and bundle, and an electrode edit, a coordinate evaluation and a signal simulation of that layout with their cached replays; `--native` adds a native evaluation of new coordinates and v2 signal simulations of it, which solve the head model. `scripts/check-local-compute-live.mjs`, `check-local-library-live.mjs` and `check-radius-recovery-live.mjs` take the same variables, plus `EEG_REPOSITORY_ROOT` for the root the service serves. The first and the last run real computations, so run them against a copy of the installation (`cp -cR` on APFS) with the Node host stopped. So do `scripts/check-design-evaluation-live.mjs` and `scripts/check-electrode-editor-live.mjs`, which take `EEG_SERVICE_RUNTIME` or `EEG_SERVICE_TOKEN` too (without them they talk to the Node host at `EEG_TEST_URL`, by default `http://127.0.0.1:3000`). The first one's `--native` evaluation of new coordinates solves the head model, which takes a few minutes and about 10 GB of memory. The editor check edits a two-region layout of the `PL` and `PR` regions from the library; the one `check-local-compute-live.mjs` computes will do. `scripts/check-source-reception-live.mjs` takes the same variables and `EEG_REPOSITORY_ROOT`; it runs a v1 signal simulation of the first two-region `AL` and `AR` 35 mm layout of the library and writes its report under the root's `webapp/outputs`, so run it on a copy too. `scripts/check-workflows-browser.mjs` gives its browser the session cookie from the same variables; it needs a current `AL` and `AR` 35 mm layout (the one `npm run test:integration` computes) and runs a v2 signal simulation of it and a cancelled one. `scripts/check-coordinate-names-browser.mjs` and `check-coordinate-review-browser.mjs` take the same variables and `EEG_REPOSITORY_ROOT` against `eeglayoutlab serve --cache-only`; they need the stored evaluation of the golden request `artifacts/productization/2026-11-13/scientific-baseline/design-request.json` under that root, and until projects arrive (slice 9) they stop at their first project request. The review check makes that request last, so its imports, cached evaluations, refusals and reopening run first (after its project writes it checks the stored record again); the names check makes it before its evaluations. Run the cache half of the library check from a workspace that did not compute those results; in the workspace that computed them, a lookup returns that workspace's own receipt, which the check does not expect. For interface work, `EEG_API_TARGET=http://127.0.0.1:<service port> npm run dev` forwards `/api` and `/open` to the service instead of mounting the Node API; open `/open?token=<launch token>` once on the Vite port to get the cookie there.

`scripts/check-viewer-assets.mjs` covers shared model downloads, version changes, cancellation, retry, eviction and independent scene arrays. `scripts/check-model-loading-browser.mjs` measures actual signal-page model requests and transfers across first load, viewer remount and reload using an existing cached experiment. Run it with `EEG_TEST_URL`, `EEG_BROWSER_EXECUTABLE`, `EEG_SIGNAL_FIXTURE` and `EEG_QA_OUTPUT` set: `node scripts/check-model-loading-browser.mjs --expect-shared`.

For the current deferred viewer, add `--expect-deferred` together with `--expect-shared`. Use an exact cached result from the target QA server as `EEG_SIGNAL_FIXTURE`; a missing cache fails the check without submitting a job. After `npm run build` and a fresh server start, verify the actual compressed HTTP bytes from the host checkout's `webapp/` directory:

```sh
EEG_TEST_URL=http://127.0.0.1:3101 \
EEG_SIGNAL_FIXTURE=/absolute/path/to/qa-signal-result.json \
EEG_COMPRESSION_REPORT="$PWD/../artifacts/qa-candidate/http-compression.json" \
node scripts/check-compression-live.mjs
```

This check compares decoded models with the host's original model files and cached JSON with the supplied result. It checks encoding negotiation, HEAD, conditional requests, byte ranges and API access headers without submitting work. `scripts/check-workflows-browser.mjs` separately exercises actual layout, signal, playback, download and cancellation controls; it writes jobs and requires the isolated queue to be resumed. Unit coverage for runtime invalidation, shared forward archives, deferred loading, hidden-page playback and compression is included in `npm run test:unit` and the Python suite.

## Review and release

Research projects and their delivery format are documented in [project formats](contracts/project-formats.md). Project metadata is separate from numerical identities. Check owner/viewer access, optimistic revisions, independent archived replay and exact snapshot bytes when changing this layer. The opt-in `scripts/check-productization-browser.mjs` covers project recovery/sharing; `scripts/check-project-workflow-browser.mjs --with-delivery` covers the complete research workflow and verified downloads. Both require an isolated host and project-local `EEG_QA_OUTPUT`; the latter also needs an existing cached signal fixture via `EEG_SIGNAL_FIXTURE`.

The local stylesheet under `webapp/styles/vendor/shadcn/` retains the original CSS and MIT license; the unused component-generator CLI is excluded from runtime dependencies. The lockfile narrowly overrides `satori@0.33.5` to use the patched `fflate@0.7.5`. Review that override when updating its parent and repeat application build, image/font checks and browser regressions. Do not use a forced audit fix across unrelated dependency branches.

Describe the resulting behavior, relevant checks and unrun tiers. For scientific changes, identify the inputs/runtime and compare matched conditions. Use [web operations](docs/web-operations.md) for release identity, durable maintenance, backup and restore. Target-server deployment and public-URL acceptance are separate from local verification; see [server deployment](docs/server-deployment.md).

## Building the documentation

The documentation site is built with [MkDocs](https://www.mkdocs.org/) 1.6 and [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/) 9.8 from the repository's own Markdown, read unchanged: `README.md` is the home page and `nav` in `mkdocs.yml` sets the order. Write links as they work on GitHub. `docs/mkdocs_hooks.py` resolves them on the site and sends links to source files and directories to GitHub. The generator is pinned in `docs/requirements.txt`, apart from the application's dependencies. From the repository root, with Python 3.11 or newer:

```sh
python -m pip install -r docs/requirements.txt
mkdocs build                 # strict: a broken link, anchor or navigation entry fails the build
mkdocs serve --no-strict     # live preview on http://127.0.0.1:8000 while writing
```

The site is written to `site/`, which Git ignores. Add each new page to `nav`; a Markdown file outside `docs/` becomes a page only through `nav`, and links to other files go to GitHub. `.github/workflows/docs.yml` builds the site in strict mode on every push and keeps it as the `documentation-site` artifact for 14 days. `.github/workflows/pages.yml` publishes it on every push to `main` at <https://eeglayout.org/docs/>, under the [read-only showcase](docs/showcase.md) at the root, with `DOCS_SITE_URL` set to that address; local builds leave `site_url` unset, so the service can serve the same site under `/docs/`.

Material for MkDocs announces its end of life for May 5, 2027 at every build (`NO_MKDOCS_2_WARNING=1` hides the notice). Its successor, Zensical, reads `mkdocs.yml` but not the hooks, so a move is a separate change.

Versioned documentation for tags (design 0001, decision 11) is planned with [mike](https://github.com/jimporter/mike) and not yet wired. A release tag `vX.Y.Z` would publish its site as version `X.Y` with the alias `latest`, `main` would publish as `dev`, and `extra.version.provider: mike` in `mkdocs.yml` would show Material's version selector. The build sets `DOCS_SOURCE_REF` to the tag, so source links match the release. The versions would go under `/docs/` of the website, beside the showcase; mike's `--deploy-prefix` can place the documentation in a subdirectory of the Pages branch.

## Licensing

© 2026 Yiming Shen. Original source code and accompanying documentation are licensed under [GPL-3.0-only](LICENSE). Third-party terms remain in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
