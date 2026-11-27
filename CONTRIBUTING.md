# Contributing

Start with [source installation](docs/source-installation.md), [architecture](docs/architecture.md) and [model definitions](docs/model-and-metrics.md). EEGLayoutLab is maintained as a web application. The native Mac wrapper and packaging tools are retired.

## Change boundaries

Routes compose feature workspaces. Keep interaction state in `webapp/features/`, common task transport in `webapp/client/` and rendering in `webapp/viewer/`. HTTP, execution and storage belong to the Python service in `src/eeglayoutlab/`. `webapp/server/` is the legacy Node host, which the parity tests in `tests/service` run as the reference until phase 4; change it only together with its Python port. Scientific code belongs in `src/compact_eeg/`. Browser modules must not import server code; automated boundary checks enforce this rule. Shared layout types and cross-language examples live in `contracts/`.

Preserve worker entry points, request normalization, frozen inputs and recorded provenance during structural changes. Changes to numerical assumptions require an explicit protocol/identity decision. File bytes and runtime paths participate in scientific cache keys; moving code can affect reuse without changing numerical outputs. Check numerical behavior, historical reading and current identity generation separately. Coordinate changes must preserve units, reference frame and channel/region order. Imports require coordinates registered to the Ernie subject.

In the service, `server/` holds the HTTP application, access, static files and the workspace stores, and `jobs/` the queue, the worker lifecycle (`jobs.worker`, `jobs.slot`) and record access (`jobs.records`). A new workflow must share the execution slot and the installation lock, and retain its own validation and resource limits. Keep scientific dependency upgrades separate from UI upgrades and structural refactors.

Git contains application source, display assets, configuration, documentation and tests. Large scientific payloads, installed environments, records, credentials and captures remain outside Git. Put local deliverables in the project's `artifacts/`. The root `.gitignore` allowlist must be updated when adding a new project directory. Preserve third-party attribution.

## Verification tiers

| Tier | Inputs and scope | Commands |
| --- | --- | --- |
| Fast | Source, packaged browser assets and synthetic fixtures; no external scientific bundle or native runtime | Commands below; also `.github/workflows/checks.yml` on Linux x86_64 and macOS arm64 |
| Data | Verified default data packages (`base` + `scalp-node-table`) composed into a clean checkout | `.github/workflows/data.yml` on Linux x86_64 and macOS arm64 (`data verify`, `data compose`, `pytest -m data_bundle`, real-root key parity and examples 1–2) |
| Package | Locally built `cortech` and `eeglayoutlab` conda packages installed into a fresh environment outside any checkout | `.github/workflows/package.yml` on Linux x86_64 and macOS arm64 (`rattler-build`, `data install --examples`, `data verify` and examples 1–3) |
| Native | Qualified Python/SimNIBS environment and native inputs | Environment check plus integration with `--native` (manual on Apple Silicon macOS) |
| Browser | Running `eeglayoutlab serve` and Chrome | Viewer checks and complete bilingual user workflows |

The fast tier needs Python 3.11 and Node.js 22.18.0 or newer. On macOS every command below has run with Node.js 26.5.0; with 24.22.3 only `typecheck` and `test:fast` have, because the 24.22.3 binary at hand (arm64, with library validation) refuses the native modules of `lint` and `build` (oxlint, rolldown); CI is the first to lint and build with 24.22.3. Data/native cases are explicitly skipped or deselected in that tier; passing it does not run a FEM solve. From the repository root:

```sh
cd webapp
npm ci
npm run typecheck
npm run lint
npm run test:fast
npm run build
cd ..
python -m pip install -e '.[dev,service]'
EEG_REQUIRE_SCHEMA_PARITY=1 python -m pytest -m 'not data_bundle and not native_runtime' -q
```

The `service` extra installs Pydantic, FastAPI and Uvicorn for the request schemas in `src/eeglayoutlab`. The schema and key parity tests compare with Node, the static parity imports vinext from `webapp/node_modules` and `tests/service/test_static.py` also serves the built interface, which is why the interface comes first. Without the extra, Node or `npm ci` these tests skip. `EEG_REQUIRE_SCHEMA_PARITY=1`, which CI sets, turns a missing extra or Node into an error and requires vinext for the range-request parity, but not the other two: without a build `test_the_real_export` still skips, and without `npm ci` the content types are not compared with vinext. CI therefore checks, before pytest, that `webapp/dist/client/index.html` and vinext's `static-file-cache.js` exist. After changing a request schema, regenerate the files in `contracts/generated/` ([contracts](contracts/README.md#generated-request-types)).

`.github/workflows/checks.yml` runs these commands in two jobs, each on its own runner and with its own time limit: the interface checks (20 minutes; `test:fast` alone 8 minutes) and the Python tests (75 minutes), which install the web dependencies and build the interface first. Both run on `ubuntu-24.04` with Node.js 24.22.3 and 26.5.0 and on `macos-15` (arm64) with 24.22.3, all with Python 3.11. The labels fix the operating system versions and Node.js is pinned exactly, but GitHub still updates the image behind each label (about weekly) and `setup-python` takes the newest 3.11 patch: a run's log names its image version (step "Set up job") and its Python version (the Python setup step). Linux runs on every push and pull request. While the repository is private, macOS runs only on pull requests to `main`, pushes to `main` and by hand (`workflow_dispatch`); once it is public, on every run. Each job first checks that no `results`, `data/external` or `.runtime` is present. The workflow parses locally (PyYAML) and the commands pass on macOS with Node.js 26.5.0; it has not run on GitHub yet, so the Linux runs and the macOS runner are untested there.

`.github/workflows/data.yml` runs the data tier on pushes to `main`, nightly and by hand (`workflow_dispatch`). It restores the default package set (`base` and `scalp-node-table`, 1.80 GB) from `actions/cache`, keyed by the exact manifest SHA-256 digests in `data/packages.json`, verifies and composes the packages into the clean checkout, runs `pytest -m 'data_bundle and not native_runtime'` and the real-root key parity suite (`EEG_KEY_PARITY_ROOT`), and runs `eeglayoutlab examples run --skip-cross-head` against `examples/expected.json`. On Linux (`ubuntu-24.04`) it builds `.runtime/compute-linux-64` from `configs/runtime/manifest-linux-64.json`; on macOS (`macos-15`), which has no lock without SimNIBS, it builds `cortech` locally with `rattler-build` and creates a micromamba environment with design 0002's pinned numerical versions. Until the Zenodo data release is published, run `workflow_dispatch` on `data.yml` once with `seed_cache=true` and `release_tag=<tag>` (a private pre-release holding the manifests and `.tar` archives) to populate the Actions cache.

`.github/workflows/package.yml` runs on `v*` tags and by hand (`workflow_dispatch`). It builds `cortech` (`linux-64` and `osx-arm64`) and `eeglayoutlab` (`noarch: python`) into a local conda channel with `rattler-build` (executing each recipe's `run_test.py` and fast checks), installs both into a brand-new micromamba environment outside any checkout, installs and verifies the data packages (`--examples` across all 13 example packages when `data_release_tag` or the Zenodo release is available, or `--skip-cross-head` from the cached default set), and runs `eeglayoutlab examples run` with no `--root` and no `EEG_COMPUTE_PYTHON`.

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

Inspect the plan, then repeat with `--execute`. The helper copies verified model inputs and current source, excludes accumulated historical caches, and can copy the installed runtime and existing build. `--link-node-modules` shares dependencies for local QA only. A copied Conda environment is not a portable distribution; embedded prefixes are retained and the interpreter must be checked at its new path. On APFS, `cp -cR` of an installation without `.git`, `node_modules` and `.runtime` is a quicker copy, whose workers run with `EEG_COMPUTE_PYTHON` set to the installation's interpreter; its coordinate-evaluation identities differ from the installation's, so the installation's stored evaluations and v2 signal results do not hit on it.

### The local service

`eeglayoutlab serve` ([design 0001](docs/design/0001-local-first-architecture.md), [phase 2](docs/design/0001-phase-2-plan.md)) is the application's host. Install it into a Python 3.11 environment of your own, not the managed runtime under `.runtime`. It serves the checkout it was installed from (`--root` or `EEG_REPOSITORY_ROOT` names another root, such as a QA copy) and that root's built interface:

```sh
python -m pip install -e '.[service]'   # also installs the eeglayoutlab command
(cd webapp && npm run build)
eeglayoutlab serve /absolute/path/to/workspace --no-browser
```

It prints `http://127.0.0.1:<port>/open?token=<launch token>`. Opening that address sets the session cookie, which every other request needs; writes also need the token from health. The cookie belongs to the host name, so a page opened on `localhost` instead gets a 401 page. Each start has a new port and new tokens, so a tab from an earlier run reaches no service (a new port) or gets 401 (the same port, `--port`), and the interface asks to run the command again: at once on the page's next request, in a notice at the foot of the window. Without `--no-browser` it opens the address once the service answers, through the private page `<workspace>/.eeglayoutlab/open.html`, so that the token is not on the browser's command line, which other local users can read (macOS's default browser gets the address itself). A browser that cannot read files in that directory, such as a snap package outside the home directory, shows an error; open the printed address instead. `--root`, `--static` and `--port` choose another root, export and port. `--docs` chooses the built documentation site that the service serves under `/docs/` (default `R/site`, what `mkdocs build` writes); until it is built, `/docs/` answers 503 and the interface links to the documentation on GitHub. Running the command again on the same workspace prints the running instance's address. SIGINT or SIGTERM stops it.

Radius searches, coordinate evaluations, electrode edits and signal simulations run in the workspace's queue (`<workspace>/.eeglayoutlab/queue.json`) and write their records under the root's `results/v2`, which the workspaces of one checkout share, one computation at a time; the signal records (`/api/community/records`) are the completed signal tasks of that workspace. Do not compute with the service while a legacy Node host computes on the same checkout. Electrode names and source declarations imported with coordinates are kept in the workspace, in `<workspace>/annotations/electrode-names/`, never in the shared records. Robustness studies and research projects are kept in the workspace too, in `<workspace>/studies/` and `<workspace>/projects/`; the project page lists them, no access key is needed, and a project delivery describes the Python service as its export host. `--cache-only` serves stored results and refuses new computations (health reports `maintenance: true`). `--clear-interrupted` releases a task whose worker start a crash interrupted, which otherwise blocks the queue until the next reboot, and a recorded worker pid that still names a live process; use it once no worker of the earlier run is computing (the service log says when the queue waits). A `queue.json` that cannot be read stops `serve` and is kept as it is. A workspace whose `.eeglayoutlab` state cannot be made private, on a FAT, exFAT, NTFS or SMB mount that ignores chmod, is refused; choose one on a local disk.

### Data from the Node host

The earlier Node host (`npm start` in `webapp/`, with `EEG_REPOSITORY_ROOT` and `EEG_QUEUE_DIRECTORY` as in [server configuration](docs/server-deployment.md)) is kept as a legacy host until phase 4; hosted deployments stay at the tag `node-host-freeze`. The current interface no longer opens its projects, which need project keys. The projects, robustness studies and completed signal records it saved stay in its queue directory (`R/results/web-service`) until they are copied into a workspace, with the Python service stopped on that workspace:

```sh
eeglayoutlab workspace import-legacy /absolute/path/to/workspace --dry-run
eeglayoutlab workspace import-legacy /absolute/path/to/workspace
```

The command only reads the queue directory (`--queue-directory` chooses another one, `--root` another root), which is never a workspace: the command and `serve` refuse it, or a directory inside it, as one. It checks every record as the Node host reads it, copies it byte for byte with its identifier, and prints what it imported, what the workspace already held and what it refused, and exits 1 when it refused something. A project or study the workspace already holds with other bytes is refused, and the workspace's copy kept. Signal records whose result is not stored under `R/results/v2` are listed but cannot be downloaded. Stop the Node host first. Running the command again copies only records that are new and changes nothing else, so a project or study the Node host changed after the first run is refused then, and the workspace keeps the copy of the first run.

### Live and browser scripts

The opt-in scripts in `webapp/scripts` run from `webapp/` against a running service. They find it through `scripts/helpers/service-session.mjs`, with no default address:

- `EEG_SERVICE_RUNTIME=/absolute/path/to/workspace/.eeglayoutlab/runtime.json` signs the script in as the service's launched browser: the helper exchanges the launch token at `/open` for the cookie and reads the token from health. `EEG_SERVICE_TOKEN=<launch token>` with `EEG_TEST_URL` does the same without the file. `EEG_TEST_URL` may also name a Vite proxy in front of the service. These take `http://127.0.0.1:<port>` only, never `localhost`: Node would connect to `[::1]` first, where another local user could listen on the same port.
- With `EEG_TEST_URL` alone, a script that still supports the legacy Node host checks the Node host there.
- `EEG_REPOSITORY_ROOT` names the root the service serves (default this checkout); `EEG_BROWSER_EXECUTABLE` the Chrome binary of the Playwright scripts; `EEG_QA_OUTPUT` where evidence goes (by default below the root's `artifacts`).
- A script that must not start work requires `eeglayoutlab serve --cache-only` with nothing queued or running (health `maintenance` and `drained`). A script that computes writes records under the root: run it against a copy of the installation, with any Node host on that root stopped.

```sh
export EEG_SERVICE_RUNTIME=/absolute/path/to/workspace/.eeglayoutlab/runtime.json
npm run test:integration
npm run test:integration -- --native
npm exec playwright install chromium
npm run test:viewer
```

The scripts and what they need:

- `npm run test:integration` (`scripts/check-app-live.mjs`) passes health, its page routes, the cookie check, the library, a radius job with its cached replay and bundle, and an electrode edit, a coordinate evaluation and a signal simulation of that layout with their cached replays; `--native` adds a native evaluation of new coordinates and v2 signal simulations of it, which solve the head model. It computes.
- `scripts/check-local-compute-live.mjs` runs real radius searches. `check-radius-recovery-live.mjs` checks a recovered radius search; its fixed original record exists on no current installation, so it fails until it gets a new fixture. `check-local-library-live.mjs` checks the library and, for every compatible cache row, that a lookup hits with the row's key: run that half from a workspace that did not compute those results, since in the workspace that computed them a lookup returns that workspace's own receipt, which the check does not expect.
- `scripts/check-design-evaluation-live.mjs` evaluates stored coordinates; its `--native` evaluation of new coordinates solves the head model, which takes a few minutes and about 10 GB of memory. `scripts/check-electrode-editor-live.mjs` edits a two-region layout of the `PL` and `PR` regions from the library; the one `check-local-compute-live.mjs` computes will do. Both compute.
- `scripts/check-source-reception-live.mjs` runs a v1 signal simulation of the first two-region `AL` and `AR` 35 mm layout of the library, checks the signal records and the saved download, and writes its report under the root's `webapp/outputs`. It computes.
- `scripts/check-compression-live.mjs` (`EEG_SIGNAL_FIXTURE`, an exact cached signal result of that root; `EEG_COMPRESSION_REPORT`, the report) submits no work. The service serves identity encoding only, so against it every response must carry the original bytes uncompressed, with encoding negotiation, `HEAD`, conditional requests, byte ranges and API access headers checked; against a legacy Node host the same checks expect its compression.
- `scripts/check-key-parity-live.mjs --node http://127.0.0.1:<port>` (or `EEG_NODE_URL`) compares the service with a legacy Node host on the same root (`--root`, else `EEG_REPOSITORY_ROOT`, else the service's root), with lookups only, by status, `hit`, `job.key` and `job.request`: both libraries, row by row; 18 fixed lookups (radius searches, coordinate evaluations with each option, perturbations, the editor's preparation, signal simulations v1 and v2); the stored request of every completed coordinate evaluation, electrode edit and signal simulation under the root's `results/v2`, which must hit with its own key and request; and every compatible cache row of the library, whose lookup must hit with its id on both. Only a lookup that hits on both hosts compares a key: a miss carries none, so a lookup that misses on both is reported as not compared, and the run fails as incomplete unless each kind (radius search, coordinate evaluation, electrode editor, signal simulation v1 and v2) has a compared key. Compute one request of a missing kind on the root first, or pass `--allow-incomplete`. Run both hosts cache-only on that root: `eeglayoutlab serve --cache-only`, and the Node host with `EEG_REPOSITORY_ROOT`, a temporary `EEG_QUEUE_DIRECTORY` and `EEG_MAINTENANCE=1` (its lookup hits write receipts there). It exits 1 on any mismatch.
- `npm run test:viewer` (`scripts/check-head-viewer.mjs`) checks the 3D viewer of the layout page and saves captures to `EEG_QA_OUTPUT`.
- `scripts/check-model-loading-browser.mjs --expect-shared` (add `--expect-deferred` for the current deferred viewer) measures the signal page's model requests and transfers across first load, viewer remount and reload, using `EEG_SIGNAL_FIXTURE`, an exact cached result of the target root; a missing cache fails the check without submitting a job.
- `scripts/check-workflows-browser.mjs` exercises actual layout, signal, playback, download and cancellation controls. It needs a current `AL` and `AR` 35 mm layout (the one `npm run test:integration` computes), runs a v2 signal simulation of it and a cancelled one, and so computes.
- `scripts/check-coordinate-names-browser.mjs` and `check-coordinate-review-browser.mjs` check the service only, with `--cache-only`. They need the stored evaluation of the golden request `artifacts/productization/2026-11-13/scientific-baseline/design-request.json` under that root. After its imports, cached evaluations, refusals and reopening, the review check saves a project snapshot and then checks the stored record again; the names check creates its project first, saves each named evaluation to it and reopens the names from the layout page's link.
- `scripts/check-project-workflow-browser.mjs` (`--with-delivery` adds the delivery) and `check-research-workflow-browser.mjs --stage2` and `--stage3` check the service only, with `--cache-only` (stage 1 runs on either host). They need a stored v2 signal simulation: `EEG_SIGNAL_FIXTURE` names a JSON file with its `result` exactly as the service returns it, whose request carries `region_definition: "dk40-six-roi-v1"`, as the signal page sends it, and whose layout (`request.record_id`) is one of the two library layouts they save; `EEG_SECOND_LAYOUT_ID` names the other. The research stages also need the golden request's stored evaluation, and stage 3 a completed electrode edit (`EEG_EDITOR_RECORD_KEY`) and an older delivery holding a layout, an electrode edit and a signal entry at `artifacts/productization/2026-11-13/stage4-browser/owner-research-delivery.json` under the root. They write their reports under the root's `artifacts/productization/2026-11-13` and `artifacts/research-workflow/2026-11-14` (or `EEG_QA_OUTPUT`).
- `scripts/check-robustness-browser.mjs` runs against `eeglayoutlab serve --cache-only` (or a legacy Node host at `EEG_TEST_URL` in maintenance). It reads the inputs of its two studies and the canonical request of each of their 8 cases from `tests/service/fixtures/robustness`, so those 8 coordinate evaluations must be stored under that root first (compute them on a copy without `--cache-only`), with at least one geometry-rejected trial among the grid cases and one grid case without a valid trial. It writes its report under the root's `artifacts/research-workflow/2026-11-14/stage5-browser` (or `EEG_QA_OUTPUT`).
- `scripts/check-workspace-projects-browser.mjs` checks the service only (`--cache-only` is enough): it creates a project, saves a completed library layout to it (`EEG_LAYOUT_ID`, by default the first one listed), renames and annotates it, reopens it in fresh browsers from the workspace's project list and by `/projects?project=<id>`, and checks that no credential, sharing control or job submission appears.

The default fixture paths of these scripts name files of an earlier installation; on another root, compute the fixtures on a copy first and name them with the variables above. `scripts/check-viewer-assets.mjs` covers shared model downloads, version changes, cancellation, retry, eviction and independent scene arrays; it and the unit coverage for runtime invalidation, shared forward archives, deferred loading, hidden-page playback and compression run in `npm run test:unit` and the Python suite.

### Interface development

`npm run dev` in `webapp/` serves the interface with Vite and forwards `/api` and `/open` to a running service. Name the service with `EEG_WORKSPACE=/absolute/path/to/workspace`, whose `.eeglayoutlab/runtime.json` gives its port (read again for every request, so a restarted service is followed), or with `EEG_API_TARGET=http://127.0.0.1:<service port>`. Then open `/open?token=<launch token>` once on the Vite port to get the cookie there; the token is in the address the service prints. Without either variable the dev server does not start; while the workspace's service is not running it answers 503 with a hint. `EEG_NODE_API=1 npm run dev` mounts the legacy Node API instead, as before phase 2.

## Review and release

Research projects and their delivery format are documented in [project formats](contracts/project-formats.md). Project metadata is separate from numerical identities. Check optimistic revisions, independent archived replay and exact snapshot bytes when changing this layer. The opt-in `scripts/check-workspace-projects-browser.mjs` covers creating, listing and reopening workspace projects; `scripts/check-project-workflow-browser.mjs --with-delivery` covers the complete research workflow and verified downloads. Both run against `eeglayoutlab serve` with a project-local `EEG_QA_OUTPUT`; the latter also needs an existing cached signal fixture via `EEG_SIGNAL_FIXTURE`.

The local stylesheet under `webapp/styles/vendor/shadcn/` retains the original CSS and MIT license; the unused component-generator CLI is excluded from runtime dependencies. The lockfile narrowly overrides `satori@0.33.5` to use the patched `fflate@0.7.5`. Review that override when updating its parent and repeat application build, image/font checks and browser regressions. Do not use a forced audit fix across unrelated dependency branches.

Describe the resulting behavior, relevant checks and unrun tiers. For scientific changes, identify the inputs/runtime and compare matched conditions. [Web operations](docs/web-operations.md) (release identity, durable maintenance, backup and restore) and [server deployment](docs/server-deployment.md) describe the legacy Node host, whose hosted deployments stay at the tag `node-host-freeze`.

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
