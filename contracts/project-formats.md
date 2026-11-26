# Research projects and deliveries

Projects use `research-project/1`. They store research annotations and immutable copies of validated scientific results independently of computation receipts. The existing scientific request schemas, cache identities and numerical result formats are unchanged.

The application's host, the Python service (`eeglayoutlab serve`), keeps projects in its workspace, `<workspace>/projects/<id>/project.json` with the snapshots in `snapshots/`, for its one local user. The legacy Node host keeps them under its queue directory, `<queue directory>/projects/`, behind credentials; the differences are listed under [Legacy Node host](#legacy-node-host).

## Access

Every project request needs the service's session cookie, which the `eeglayoutlab` command's launch link sets (`401` with code `authentication_required` otherwise). Write requests also require a same-origin request and `X-EEG-Compute-Token`. There is no project credential: the projects of a workspace are open to its user. API parameters must not be put in a project API query string.

`POST /api/projects` accepts `{title, owner_name, notes?}` and returns `{project, role: "owner", access_key}`. The server generates the project UUID. A new project's `owner_key_hash` hashes a random key that is never stored and `viewer_key_hash` is `null`; the returned `access_key` is stored nowhere and opens nothing, and the interface ignores it and `role`. `X-EEG-Project-Key` is accepted and ignored. Project lead names are annotations, not authenticated researcher accounts.

## Endpoints

| Method and path | Behavior |
| --- | --- |
| `GET /api/projects` | List the workspace's projects, most recently updated first: `{projects: [{id, title, owner_name, revision, created_at, updated_at, entry_count}]}` |
| `POST /api/projects` | Create a project |
| `GET /api/projects/:id` | Read project metadata |
| `PATCH /api/projects/:id` | Change `title`, `owner_name`, `notes` or `workflow`; requires current `revision` |
| `POST /api/projects/:id/entries` | Attach a verified completed result; requires current `revision` |
| `GET /api/projects/:id/entries/:entryId` | Read entry metadata and its archived scientific snapshot |
| `PATCH /api/projects/:id/entries/:entryId` | Change entry `title` or `notes`; requires current `revision` |
| `DELETE /api/projects/:id/entries/:entryId` | Detach an entry using body `revision` or `If-Match`; retain its scientific file |
| `GET /api/projects/:id/export` | Download a verified `eeg-research-delivery/1` bundle |

`POST /api/projects/:id/share` and `/revoke-share` answer `404` `Project endpoint not found.`. Stale revisions return `409`. Source attachments require a completed signal task of the workspace, not a caller-provided scientific payload. Invalid, missing or corrupted scientific records do not become project snapshots.

## Saved entries

An attachment has `kind: "layout" | "editor" | "source"`. Layout and editor attachments supply a scientific `record_id`; source attachments supply `receipt_id`. Titles and notes are optional. The server resolves, validates and copies the underlying result.

Each entry records its own UUID, scientific record identifier, title, notes, creation time, protocol summary, snapshot byte count and SHA-256. A snapshot uses `research-project-snapshot/1` and contains `kind`, `record_id` and `payload`:

- Layout payload: the established layout reproducibility bundle.
- Editor payload: the saved editor record and validated evaluation cache.
- Source payload: the complete signal result, including requests, provenance, quality checks, conditions and waveforms.

Snapshot checksums cover the exact UTF-8 `JSON.stringify(snapshot)` text. Project or entry renaming does not change that text. Metadata and scientific copies are written atomically beneath `<workspace>/projects/`. Physical detached copies still count toward storage limits.

## Research workflow

`workflow` contains `reference_entry_id`, `candidate_entry_id` and `comparison_href`; each can be `null`. Selected entries must be layouts in the same project. A saved comparison must refer to those layouts and use the existing `/decision` parameters: `a`, `b`, `ar`, `thresholdMode`, `sensitivity`, `localization`, `p90`.

The comparison page retains its established interpretation. Joint requirements use one 10–100 percent limit; optional amplitude/localization parameters must match it and no P90 limit is stored in joint mode. Custom requirements retain their independent limits. Changing these annotations does not alter scientific requests or recompute scores. Detaching a selected layout clears the affected selection and comparison link.

## Delivery bundle

`eeg-research-delivery/1` contains public project annotations, saved workflow, export-host metadata, record references and files. Each `file.content` retains the exact original scientific JSON text; SHA-256 and UTF-8 size identify that text. `README.md` provides a readable summary, original metric readings, comparison requirements and reproduction instructions. The manifest checksum covers bundle metadata and file descriptors. Checksums verify internal integrity; they are not an author signature.

The export host is identified separately from the original calculation identities inside each snapshot. Model payloads are referenced through recorded manifests and checksums. Original scientific provenance, including original calculation paths, is retained. Project access keys, credential hashes and private operator configuration are excluded.

Current limits are 16 MiB per scientific snapshot, 128 MiB of physical snapshot data and 100 snapshot files per project, 512 KiB of project metadata, and 32 MiB per serialized delivery bundle. One delivery is prepared at a time. Oversized requests return `413`; concurrent export preparation returns `429`. The browser verifies file and manifest hashes before download. Cancelling download preparation does not cancel scientific tasks or delete saved results.

## Named coordinate copies

A coordinate design can carry `electrode_names` (64 unique ordered labels) and `source_metadata` (the bounded coordinate-file declaration described in `docs/coordinate-file-interface.md`: `electrode-coordinate-source/1` for Ernie-native files, `/2` with a `conversion` record for MNI files and 10-05 name lists). The browser submits these as presentation metadata in a `design-submission/1` envelope around the original mathematical request. Bare legacy requests remain valid.

Per-electrode labels and source declarations do not enter the scientific request or cache key. The legacy overall `design.name` field retains its original request/key semantics. Two label sets can therefore reference one scientific result while retaining separate immutable annotation IDs.

A project entry may contain `annotation_id`. Its `research-project-snapshot/1` file then carries `electrode_annotation` beside `payload`. The original scientific payload remains unchanged. The outer snapshot checksum includes the annotation, so differently named copies have different snapshot checksums even when their scientific record ID is identical. Explicit annotation selection is required when reopening a named copy; an unrelated latest label set is not substituted.

## Legacy Node host

The Node host (`npm start`, kept until phase 4 of design 0001; hosted deployments stay at the tag `node-host-freeze`) writes the same `research-project/1` and `research-project-snapshot/1` bytes, keeps the same revisions, size limits and delivery bundle, and answers the endpoints above with the same statuses and messages, except:

- A project has an owner credential, a random 32-byte key encoded as 64 hexadecimal characters, whose hash alone is stored. Every project request carries it in `X-EEG-Project-Key`. The owner can create, rotate or revoke a separate read-only credential (`share`, `revoke-share`); a read-only write returns `403`. The current interface sends no project key, so it cannot open the Node host's projects.
- There is no project list: `GET /api/projects` answers `405`.
- A source attachment needs a completed task receipt that the browser owns.
- Unused projects are pruned after 30 days, and the number of projects is capped per network and in total.
- A delivery's `host` describes the Node host. The Python service's `application_version` is the version in `pyproject.toml`, and its `source_files` hash the service's project and delivery modules and `pyproject.toml` (an installed package, which has no `pyproject.toml`: its distribution's version and the four modules). So the `manifest_sha256` of the two hosts' deliveries of one project differ; the scientific files and their checksums do not.

`eeglayoutlab workspace import-legacy [WORKSPACE] [--root R] [--queue-directory Q] [--dry-run]` copies the projects, the robustness studies and the completed signal tasks of the Node host's queue directory (default `R/results/web-service`) into a workspace. It only reads the queue directory. Each project and study is checked as the Node host reads it, every snapshot against its checksum, and copied byte for byte with its identifier; a record the workspace already holds with the same bytes is reported as present, and one with other bytes is refused, keeping the workspace's copy. The signal tasks join the workspace's task list without their owners. The command prints what it imported, found and refused, and exits `1` when it refused something.

## Repeated studies

Repeated studies use separate `eeg-robustness-study/1` and `eeg-robustness-study-export/1` schemas. The Python service stores them in its workspace, `<workspace>/studies/`, for its one local user; the legacy Node host stores them under its queue's `studies/` tree, owned by the browser session. Each case retains a normalized original `design-evaluation/1` request, scientific key, receipt reference, outcome and verified cache copy. Export includes `cache_json`, the original UTF-8 cache text, and `source_sha256`, its checksum. The parsed `cache` is supplied for reading the values.

See `docs/robustness-studies.md` for protocols, case-level summaries and recovery. These study wrappers keep the original scientific evaluation and its default trial/noise counts.
