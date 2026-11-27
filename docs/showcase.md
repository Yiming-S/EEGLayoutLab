# Read-only showcase

The showcase is the interface built as static files with no service behind it ([design 0001](design/0001-local-first-architecture.md), decision 1). Visitors can browse a curated set of results, the layout pages and the 3D head, the comparison page, the findings and the guide, choose channel subsets from their own recording summaries, and open delivery packages. No calculation is sent to a service, nothing is stored, and no visitor data is collected.

## What it shows

The top bar shows four of the five areas of the interface ([design 0004](design/0004-interface-structure.md)): Layout, Analysis, Findings and Documentation. Workspace holds the user's own tasks and projects, so the showcase leaves it out, and `/` opens the total-area study under Findings.

| Area | Page | In the showcase |
| --- | --- | --- |
| Layout | Layout List, layout page | The records listed in [`webapp/showcase/curation.json`](../webapp/showcase/curation.json): the 30 total-area layouts of the current protocol, the 30 historical area layouts and one saved coordinate evaluation. Each opens its layout page with its evaluation, scores and 3D head |
| | Region Design, Coordinate Import | Viewable; starting a calculation shows the read-only notice |
| | Electrode Editor | The curated layouts are listed; loading one into the editor needs the service, so the page shows the read-only notice instead |
| Analysis | Compare Layouts | The curated records can be compared and their reports exported |
| | Robustness studies | Viewable, with the curated layouts to start from; starting a study shows the read-only notice |
| | Signal Simulation | The curated layouts can be selected; starting a simulation shows the read-only notice |
| | Channel Subsets | As in the application: the selection runs in the browser on the visitor's own summary files, which are not uploaded |
| Findings | Total-Area Study, Historical Batches | As in the application; these pages read files under `webapp/public/data` |
| Documentation | User Guide, Models & Methods | As in the application. On the website the chapter links open the documentation site under `/docs/`; a showcase built alone has none, so they open the Markdown on GitHub |
| — | Research Projects (`/projects`), delivery reader (`/deliveries`) | Not in the top bar; opened by their address. Creating a project shows the read-only notice; a delivery package is read in the browser, as in the application |

Every page carries a strip that names the read-only showcase and links to the installation notes.

## Downloaded display copies

The curated coordinate evaluation offers **Redacted display copy JSON**. Its schema is `eeg-showcase-display-copy/1`, and its filename ends in `-display-copy.json`. The download contains the displayed record, saved result, request, search information and redacted runtime context. Coordinates and scientific numbers retain their saved values. Home-directory prefixes are replaced with `~`.

The file distinguishes two kinds of checksum:

- `integrity.result_sha256`, `integrity.display_record_sha256` and `integrity.payload_sha256` verify the included result, display record and complete display payload. The payload is every top-level field except `integrity`. Each digest uses SHA-256 over UTF-8 `JSON.stringify(value)`, preserving object member order; download indentation and trailing newlines are excluded.
- `source_reference` identifies the undisclosed original source file, result and scientific cache key. These are references to the original installation. A redacted identity cannot reproduce its original cache key, and the builder does not assign a new scientific key to it.

The export menu and experiment-history panel verify display-copy checksums before offering the file. The coordinates page verifies a display copy before opening its coordinates as an unevaluated draft. Full local `eeg-reproducibility-bundle/1` downloads retain their original format and recovery path. The separate **Importable layout JSON** remains the format for importing coordinates; the delivery reader accepts research-project delivery packages.

To check a downloaded display copy with the source checkout:

```bash
cd webapp
node --input-type=module - /path/to/eeg-record-display-copy.json <<'JS'
import { readFile } from 'node:fs/promises';
import { verifyShowcaseDisplayCopy } from './lib/showcase-display-copy.ts';
const copy = await verifyShowcaseDisplayCopy(JSON.parse(await readFile(process.argv[2], 'utf8')));
console.log(copy.schema, copy.integrity.payload_sha256);
JS
```

These checks detect changes to the included content; they do not authenticate the undisclosed original files. **Display record JSON** exports the curated summary and its redacted provenance fields, without claiming to be the original computation cache.

## How it works

A showcase build sets `EEG_SHOWCASE=1`; the root layout, rendered at build time, marks the page with `<html data-showcase="1">`. In such a page [`webapp/lib/showcase-api.ts`](../webapp/lib/showcase-api.ts) answers every `/api` and `/open` request in the browser:

- A `GET` whose path is listed in `showcase-api/index.json` reads the JSON file written for it.
- Every other request gets `403 {"error": …, "code": "showcase_read_only"}`. The existing error displays show its message, in the page's language.

The health endpoints are published as a service that cannot compute (`available: false`, no session token), so pages stay usable and a calculation request reaches the read-only notice instead of a connection error. No request for a missing file is sent, so the browser console stays clean.

## Rebuilding the data

The data in `webapp/showcase/api` is generated from the maintainer's installation on an APFS scratch clone through the Python service in cache-only mode and committed:

```bash
eeglayoutlab --root /path/to/installation serve /path/to/workspace --cache-only --no-browser
cd webapp
EEG_SERVICE_RUNTIME=/path/to/workspace/.eeglayoutlab/runtime.json npm run showcase:data
```

`build-showcase-data.mjs` signs in through `scripts/helpers/service-session.mjs` using `EEG_SERVICE_RUNTIME` (or `--runtime <workspace>/.eeglayoutlab/runtime.json`); `--from` alone remains supported for the legacy Node host until phase 4.

Only `GET` requests are sent. Catalogs that list layouts (editor parents, reception layouts) are filtered to the curated records, so every listed entry opens. Paths under a home directory are written as `~/…`, and the script fails if any other local path remains. Selected experiment bundles are converted to display copies after checking the original result checksum; their new payload checksums are calculated after redaction. This conversion is deterministic and leaves the original files untouched. Records not in the curation, electrode-name annotations, editor results, signal records, studies and head packages are not published. To change what is shown, edit `curation.json` and run the script again.

## Building and checking

```bash
cd webapp
npm run build:showcase                # writes showcase-dist/ (about 26 MiB); dist/ is kept
node scripts/serve-showcase.mjs       # http://127.0.0.1:3332, served as GitHub Pages serves it
```

`npm run test:fast` includes `scripts/check-showcase.mjs`, which checks the curation, redaction, request handling, published display-copy checksums and coordinate-draft recovery. It rejects changed results, invalid checksums, private paths and attempts to restore a display copy as an original calculation. `scripts/check-layout-exports.mjs` checks both download formats and their bilingual labels.

## Hosting

The showcase is online at <https://eeglayout.org>, with the documentation site under <https://eeglayout.org/docs/>.

The site must be served at the root of its domain: the interface links to `/design`, `/data/…` and `/models/…` with absolute paths, so a project page under `https://<user>.github.io/EEGLayoutLab/` does not work. Use a custom domain or another static host at a root path.

[`.github/workflows/pages.yml`](../.github/workflows/pages.yml) builds the showcase, builds the documentation into its `docs/` directory and deploys both to GitHub Pages, on every push to `main` and when started by hand. It needs:

- Pages enabled for the repository, with "GitHub Actions" as the source and the custom domain set in the Pages settings;
- the same domain as the repository variable `SHOWCASE_CNAME` (`eeglayout.org`) and in the DNS records.

The showcase publishes Ernie-derived display models and results, which keep the CC BY-NC 4.0 terms in [third-party notices](../THIRD_PARTY_NOTICES.md); the footer links to them on every page.

## Not covered

- The showcase opens in English whatever the browser language; the language switch keeps a visitor's choice. (The application follows the browser language.)
- Fonts other than Latin, including CJK, come from the visitor's system fonts.
