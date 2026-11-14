# Research projects and deliveries

Projects use `research-project/1`. They store research annotations and immutable copies of validated scientific results independently of computation receipts. The existing scientific request schemas, cache identities and numerical result formats are unchanged.

## Access

`POST /api/projects` accepts `{title, owner_name, notes?}` and returns `{project, role: "owner", access_key}`. The server generates the project UUID and a random 32-byte credential, encoded as 64 hexadecimal characters. Only its hash is stored on the server. There is no public project-list endpoint.

Subsequent project requests carry `X-EEG-Project-Key`. Write requests also require the configured origin policy and `X-EEG-Compute-Token`. The computation token grants neither project access nor operator access. Credentials and API parameters must not be put in a project API query string.

The project owner can create or revoke a separate read-only credential. Project lead names are annotations, not authenticated researcher accounts. Public layout-library records retain their existing shared visibility even when a copy is attached to a private project.

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
