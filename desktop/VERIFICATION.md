# Desktop build verification

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

