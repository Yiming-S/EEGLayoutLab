# Desktop build verification

## Version 0.1.1, build 2 — 2026-10-19

The current working tree was fully rebuilt on Apple Silicon running macOS
27.0.1. The deployment target remains macOS 14. A second physical Mac and
macOS 14 were not exercised in this run.

### Build inputs and package checks

- All 316 selected source and documentation files match their recorded hashes,
  including 17 untracked additions. The build includes the updated web interface,
  scientific services, and anonymous task queue.
- The builder now includes non-ignored new source files and supplies both
  installation guides beside the archives and inside the DMG. A temporary-Git
  regression test verifies source inclusion and ignored-file exclusion.
- All 21 model-data files passed verification: 406,226,293 bytes. The installed
  library contains 402 supplied records.
- Runtime staging audited 1,060 native binaries, verified isolated imports,
  MUMPS, CGAL, and loaded-library paths, and confirmed that the original runtime
  was unchanged.
- Type checking, linting, and the production web build passed. Automated tests:
  228 web checks, 11 desktop launcher checks, and 17 Python packaging/runtime
  checks passed.
- ZIP and DMG SHA-256 values match `SHA256SUMS.txt`; the embedded payload matches
  its manifest. Deep/strict signature checks and DMG integrity verification passed.
- The application copied from the read-only DMG reports version 0.1.1 (2), arm64,
  and the macOS 14 minimum. The About panel lists Yiming Shen, PhD and Yi Wang, PhD.

### Native application checks

The DMG's application was copied to a separate test installation. Scientific
test data used `EEG_DESKTOP_USER_DATA` under the release's `qa/` directory.

- Clean first launch passed in 31.19 seconds on the build Mac. The native
  WKWebView loaded the interface, and its DOM and WebGL checks passed.
- Chinese-to-English switching worked. After a controlled Command-Q and reopen
  at the same local address, the English interface was restored.
- Brain view and the left-side orientation rendered in the native window.
- The native Save dialog exported an importable layout JSON with 64 electrodes,
  two regions, `ernie_native_mm` coordinates, and millimetre units.

### Computation and restart checks

The packaged Node binary and installed worker code exercised all 11 application
routes, the supplied library, and eight computation cases. Python workers and
numerical libraries resolved inside the installed workspace.

| Check | Initial completed calculation, seconds | After service restart, seconds |
| --- | ---: | ---: |
| Two-region layout optimization | 12.785 | 0.139 |
| Electrode editor preparation | 4.382 | 0.344 |
| Evaluation with 63 active electrodes | 2.657 | 0.143 |
| Existing-bank coordinate evaluation | 2.842 | 0.326 |
| Source simulation v1 | 7.444 | 0.388 |
| New-coordinate direct FEM evaluation | 111.368 | 0.140 |
| Native-layout single-source simulation v2 | 118.691 | 1.666 |
| Native-layout multi-source simulation v2 | 6.507 | 1.694 |

Every case also repeated its request and verified an identical cached result.
After an orderly service stop, its port closed and its running-state file was
removed. Restart reused the same installed workspace, and the complete
integration suite passed again. Requests without the write token or with an
external Origin were rejected. The table reports this Mac's integration timings,
including result handling and immediate cache replay.

An initial GUI-owned integration attempt was interrupted by an orderly
application quit before its FEM task completed. The logs do not identify the
source of that quit request. The complete rerun used the packaged supervisor
directly; both that run and the post-restart run passed. The first-attempt log
is retained separately from the successful runs.

The direct FEM result reported a reference relative difference of
`2.129876327492097e-12`, below the test's `1e-8` limit. Its maximum full-system
relative residual was `8.175825218127255e-13`, and its reciprocity difference was
`4.983733404248029e-16`. These checks establish numerical consistency for the
packaged workflow; the recorded source-qualification flags remain unchanged.

### Local deliverables and data behavior

The local release is under `releases/desktop-0.1.1-build2/`, with the application,
DMG, ZIP, installation guides, build report, checksums, and verification evidence.
The DMG is 1,257,470,888 bytes; the ZIP is 1,249,514,118 bytes. Final archive containers were recreated from the same verified signed application
after the earlier containers were missing at the final check; payload bytes were
preserved, and archive checksums were regenerated. The rebuilt
installer has not been uploaded to the shared download folder in this workflow.

This build uses an ad-hoc signature and has not been Apple-notarized. New payloads
create a new scientific workspace and preserve older workspaces; results are not
automatically migrated between versions. Temporary build staging was removed
after packaging, and test services were stopped after verification.

## Historical verification: version 0.1.0

Version: 0.1.0, arm64. Verification date: 2026-09-10.

The desktop wrapper preserves the existing scientific code, frozen model data,
and web interface. It packages the computation environment rather than replacing
the numerical methods. Verification below was performed on the build Mac running
macOS 26.6.2. The deployment target is macOS 14; a second physical Mac and macOS 14
have not been tested in this verification run.

## Packaging and runtime

- Official Node.js 24.21.0 archive checked against its pinned SHA-256; its native
  dependencies are system libraries.
- Python/SimNIBS runtime tested after two directory relocations, including a path
  containing spaces. Native imports, sparse solve, geometry routines, and runtime
  identity checks passed. No non-system loaded library came from the original
  checkout or Homebrew.
- Original scientific runtime inventory unchanged by staging.
- 21 frozen input files checked against the data manifest; 402 supplied layout
  records available in the installed app.
- 16 Python packaging/runtime tests and 11 Node launcher tests passed.
- Native Swift shell compiled for arm64/macOS 14. Ad-hoc code signature passed
  deep/strict verification before and after installation from the DMG.
- Final DMG integrity check and all published SHA-256 checks passed.

The payload contains 3,016,080,114 uncompressed file bytes, before filesystem
allocation overhead and new calculation caches. The final DMG is approximately
1.24 GB. Users need space for both the App and its extracted scientific workspace.

## Native window checks

The actual WKWebView application was opened, not only the web server.

- Clean first launch: workspace preparation and page load completed in roughly
  21 seconds on this Mac. WebGL2 was available and the document loaded.
- English/Simplified Chinese selection worked; Chinese remained selected after
  quitting and reopening the app from a different installation path.
- The anatomical head rendered; dragging rotated it and exposed the second
  region. Brain transparency and the standard 64-electrode overlay worked.
- Native Save dialog exported a 64-electrode, two-region layout JSON.
- Coordinate CSV export and native Open dialog round-trip succeeded: 64 points,
  two regions, reported minimum straight-line separation 4.15 mm.
- A second shell attached to the running server without interrupting it and
  exited successfully. Its shared-server status was explicit.
- Command-Q stopped the owned server and workers; its loopback port closed.
- The app copied from the final read-only DMG reopened the same user workspace
  and reused the same port. Its application bundle remained unchanged.

## Full computation check

The integration script was executed from the extracted workspace using the Node
binary inside the App. Python workers and reported numerical libraries resolved
inside that workspace, not the source repository.

| Check | First run, seconds | After app reinstall/reopen, seconds |
|---|---:|---:|
| Two-region layout optimization | 21.805 | 0.114 |
| Electrode editor preparation | 4.346 | 0.332 |
| Evaluation after deleting one electrode (63 remain) | 2.640 | 0.128 |
| Existing-bank coordinate evaluation | 2.318 | 0.319 |
| Source simulation v1 | 6.887 | 0.369 |
| New-coordinate direct FEM evaluation | 153.998 | 0.117 |
| Native-layout single-source simulation v2 | 117.308 | 1.480 |
| Native-layout multi-source simulation v2 | 5.033 | 1.454 |

Each check also repeated the same request and verified an identical cached result.
The second run used saved computations. Times include request/result handling and
immediate cache replay; they are not general hardware performance guarantees.
All 11 application routes responded successfully. Requests without the compute
token and with an external Origin were rejected with HTTP 403.

Direct FEM checks returned a reference relative difference of
`2.129876327492097e-12` (required maximum `1e-8`), a maximum full-system relative
residual of `8.175825218127255e-13`, and reciprocity difference of
`4.983733404248029e-16`. Five reported numerical thread pools used one thread.
These are integration/numerical consistency checks, not additional independent
head-model validation. Existing source-qualification flags were not changed.

## Distribution state

The App is a self-contained local test build with an ad-hoc signature. Developer
ID signing, Apple notarization, automatic updating, and second-physical-Mac
acceptance testing are not completed by this build. New payload versions preserve
older user workspaces; automatic cross-version result migration is not implemented.
Runtime and third-party license inventories accompany the bundle.

