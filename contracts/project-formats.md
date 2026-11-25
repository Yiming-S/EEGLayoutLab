# Research projects and deliveries

Projects use `research-project/1`. They store research annotations and immutable copies of validated scientific results independently of computation receipts. The existing scientific request schemas, cache identities and numerical result formats are unchanged.

## Access

`POST /api/projects` accepts `{title, owner_name, notes?}` and returns `{project, role: "owner", access_key}`. The server generates the project UUID and a random 32-byte credential, encoded as 64 hexadecimal characters. Only its hash is stored on the server. There is no public project-list endpoint.

Subsequent project requests carry `X-EEG-Project-Key`. Write requests also require the configured origin policy and `X-EEG-Compute-Token`. The computation token grants neither project access nor operator access. Credentials and API parameters must not be put in a project API query string.

The project owner can create or revoke a separate read-only credential. Project lead names are annotations, not authenticated researcher accounts. Attaching a copy to a private project does not change who sees the original record in the library lists; that follows the library scope described in `docs/anonymous-queue.md`.

## Endpoints

| Method and path | Behavior |
| --- | --- |
| `GET /api/projects/:id` | Read project metadata with owner or viewer access |
| `PATCH /api/projects/:id` | Change `title`, `owner_name`, `notes` or `workflow`; requires current `revision` |
| `POST /api/projects/:id/share` | Rotate the viewer credential; requires current `revision` |
| `POST /api/projects/:id/revoke-share` | Revoke viewer access; requires current `revision` |
| `POST /api/projects/:id/entries` | Attach a verified completed result; requires current `revision` |
| `GET /api/projects/:id/entries/:entryId` | Read entry metadata and its archived scientific snapshot |
| `PATCH /api/projects/:id/entries/:entryId` | Change entry `title` or `notes`; requires current `revision` |
| `DELETE /api/projects/:id/entries/:entryId` | Detach an entry using body `revision` or `If-Match`; retain its scientific file |
| `GET /api/projects/:id/export` | Download a verified `eeg-research-delivery/1` bundle with owner or viewer access |

Stale revisions return `409`; read-only writes return `403`. Source attachments require an owned completed task receipt, not a caller-provided scientific payload. Invalid, missing or corrupted scientific records do not become project snapshots.

## Saved entries

An attachment has `kind: "layout" | "editor" | "source"`. Layout and editor attachments supply a scientific `record_id`; source attachments supply `receipt_id`. Titles and notes are optional. The server resolves, validates and copies the underlying result.

Each entry records its own UUID, scientific record identifier, title, notes, creation time, protocol summary, snapshot byte count and SHA-256. A snapshot uses `research-project-snapshot/1` and contains `kind`, `record_id` and `payload`:

- Layout payload: the established layout reproducibility bundle.
- Editor payload: the saved editor record and validated evaluation cache.
- Source payload: the complete signal result, including requests, provenance, quality checks, conditions and waveforms.

Snapshot checksums cover the exact UTF-8 `JSON.stringify(snapshot)` text. Project or entry renaming does not change that text. Metadata and scientific copies are written atomically beneath `<queue directory>/projects/` and included in stopped-service backup/restore. Physical detached copies still count toward storage limits.

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

## Repeated studies

Repeated studies use separate `eeg-robustness-study/1` and `eeg-robustness-study-export/1` schemas. The Node host stores them under the configured queue's `studies/` tree, owned by the existing browser session; the Python service stores them in its workspace, `<workspace>/studies/`, for its one local user. Each case retains a normalized original `design-evaluation/1` request, scientific key, receipt reference, outcome and verified cache copy. Export includes `cache_json`, the original UTF-8 cache text, and `source_sha256`, its checksum. The parsed `cache` is supplied for reading the values.

See `docs/robustness-studies.md` for protocols, case-level summaries and recovery. These study wrappers keep the original scientific evaluation and its default trial/noise counts.
