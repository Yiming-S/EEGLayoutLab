# Read-only showcase

The showcase is the interface built as static files with no service behind it ([design 0001](design/0001-local-first-architecture.md), decision 1). Visitors can browse a curated set of results, the 3D head, the comparison page, the method and guide pages, and open delivery packages. Nothing is computed or stored, and no visitor data is collected.

## What it shows

| Area | In the showcase |
| --- | --- |
| Overview, historical experiments, method, guide | As in the application; these pages read files under `webapp/public/data` |
| Layout records | The records listed in [`webapp/showcase/curation.json`](../webapp/showcase/curation.json): the 30 total-area layouts of the current protocol, the 30 historical area layouts and one saved coordinate evaluation |
| Compare layouts, coordinate import | The curated records can be compared and their reports exported; the saved coordinate evaluation opens with its result |
| Signal simulation | The curated layouts can be selected; starting a simulation shows the read-only notice |
| Electrode editor | The curated layouts are listed; loading one into the editor needs the service, so the page shows the read-only notice instead |
| Layout design, robustness studies, projects | Viewable; starting a calculation, a study or a project shows the read-only notice |
| Delivery reader (`/deliveries`) | Unchanged: a delivery package is read in the browser |

Every page carries a strip that names the read-only showcase and links to the installation notes.

## How it works

A showcase build sets `EEG_SHOWCASE=1`; the root layout, rendered at build time, marks the page with `<html data-showcase="1">`. In such a page [`webapp/lib/showcase-api.ts`](../webapp/lib/showcase-api.ts) answers every `/api` and `/open` request in the browser:

- A `GET` whose path is listed in `showcase-api/index.json` reads the JSON file written for it.
- Every other request gets `403 {"error": …, "code": "showcase_read_only"}`. The existing error displays show its message, in the page's language.

The health endpoints are published as a service that cannot compute (`available: false`, no session token), so pages stay usable and a calculation request reaches the read-only notice instead of a connection error. No request for a missing file is sent, so the browser console stays clean.

## Rebuilding the data

The data in `webapp/showcase/api` is generated from the maintainer's installation and committed:

```bash
cd webapp
node server/start.mjs      # with EEG_REPOSITORY_ROOT set to the installation, on a free PORT
npm run showcase:data -- --from http://127.0.0.1:<PORT>
```

Only `GET` requests are sent. Catalogs that list layouts (editor parents, reception layouts) are filtered to the curated records, so every listed entry opens. Paths under a home directory are written as `~/…`, and the script fails if any other local path remains. Records not in the curation, electrode-name annotations, editor results, signal records, studies and head packages are not published. To change what is shown, edit `curation.json` and run the script again.

## Building and checking

```bash
cd webapp
npm run build:showcase                # writes showcase-dist/ (about 26 MiB); dist/ is kept
node scripts/serve-showcase.mjs       # http://127.0.0.1:3332, served as GitHub Pages serves it
```

`npm run test:fast` includes `scripts/check-showcase.mjs`, which checks the curation, the redaction and the request handling.

## Hosting

The site must be served at the root of its domain: the interface links to `/design`, `/data/…` and `/models/…` with absolute paths, so a project page under `https://<user>.github.io/EEGLayoutLab/` does not work. Use a custom domain or another static host at a root path.

[`.github/workflows/showcase-pages.yml`](../.github/workflows/showcase-pages.yml) builds the site and deploys it to GitHub Pages. It runs only when started by hand (`workflow_dispatch`), and needs:

- Pages enabled for the repository, with "GitHub Actions" as the source;
- a custom domain, set as the repository variable `SHOWCASE_CNAME` (for example `showcase.example.org`) and in the DNS records.

The showcase publishes Ernie-derived display models and results, which keep the CC BY-NC 4.0 terms in [third-party notices](../THIRD_PARTY_NOTICES.md); the footer links to them on every page.

## Not covered

- Users whose language is Chinese see the English page until it hydrates, as in the application.
- Fonts other than Latin, including CJK, come from the visitor's system fonts.
