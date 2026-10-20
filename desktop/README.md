# EEG Layout Lab for macOS

Version 0.1.1 (build 2). Project collaborators: Yiming Shen, PhD and Yi Wang, PhD.

The desktop application contains the interface, Node.js, the Python/SimNIBS
runtime, the frozen model data, and the supplied result library. End users do
not install Node.js, Python, Conda, or a separate data archive.

## Open the application

1. Obtain the complete Apple Silicon desktop archive from the maintainer.
2. Extract the ZIP and move **EEG Layout Lab.app** into **Applications**, or use
   the Applications shortcut in the DMG.
3. Open **EEG Layout Lab**. On first launch, wait while its offline workspace is
   prepared. Subsequent launches reuse the installed workspace and saved results.
4. Quit using **EEG Layout Lab → Quit EEG Layout Lab** or **Command + Q**.

Use an Apple Silicon Mac with macOS 14 or newer. No network connection is needed
to install the bundled scientific workspace or run the included simulations.

This first test build uses an ad-hoc signature, not a Developer ID signature or
Apple notarization. If macOS reports an unidentified developer, confirm the file
came from the maintainer, attempt to open it, then use **System Settings →
Privacy & Security → Open Anyway** for this application. A damaged-app or malware
warning requires investigation; do not disable Gatekeeper globally. See
[Apple's opening instructions](https://support.apple.com/en-us/102445).

## User data

Saved calculations, caches, and logs are stored under:

```text
~/Library/Application Support/EEG Layout Lab/
```

The signed application bundle is not modified while running. Workspaces are
versioned by the bundled payload SHA-256. Installing another payload preserves
older workspaces; it does not silently merge scientific versions. Replacing the
App alone does not delete saved calculations.

The native window includes **Open Data Folder** and **Open Logs** menu actions.
The embedded interface retains English and Simplified Chinese language selection.

## Build from source (maintainers)

Build on Apple Silicon with Xcode command-line tools. Complete the
[source checkout installation](../docs/source-installation.md) first. The builder reads the frozen
data manifest and builds only into a new output directory.

1. Obtain the official Node archive specified in `release.json`. Its SHA-256 is
   checked against the pinned value before extraction.
2. Run from the repository root:

```sh
.runtime/simnibs-4.6.0/bin/python desktop/build.py \
  --node-archive /path/to/node-v24.21.0-darwin-arm64.tar.gz \
  --output releases/desktop-0.1.1-build2 \
  --dmg
```

The output contains the `.app`, ZIP, optional DMG, checksums, and build report.
`build-work/` is staging, not a file to share. A repeated build must use a new
output directory. The source runtime and frozen scientific inputs are not
modified. Do not commit the output or runtime to Git.

`desktop/runtime/stage_runtime.py` copies the complete scientific environment,
converts installation-specific library references and Python launchers to
relative paths, and records its changes. It verifies native imports, MUMPS,
surface projection, loaded-library locations, and the unchanged source runtime.
Its explicit optional-plugin exclusion is recorded in the audit.

### Update the desktop shell without rebuilding model data

After changing only `desktop/*.mjs` or the native Swift shell, reseal a completed
build into a **new** export directory:

```sh
.runtime/simnibs-4.6.0/bin/python desktop/finalize.py \
  --input releases/desktop-0.1.1-build2 \
  --output releases/desktop-0.1.1-export1 \
  --rebuild-shell \
  --dmg
```

Omit `--rebuild-shell` when only the bootstrap scripts changed. The input build
is read only. The copied app keeps the original scientific payload bytes, so its
installed workspace identity and saved calculations remain unchanged. The
finalizer checks the input signature and manifest, updates bootstrap hashes,
applies an ad-hoc signature, verifies it, and creates fresh archives, checksums,
and a build report. English and Simplified Chinese `START_HERE` guides are placed
beside the archives and in the DMG. Changes to application web code, scientific code, runtime, or model data
require a full build instead.

## Checks

The [desktop verification report](VERIFICATION.md) records runtime relocation,
native-window checks, full numerical integration, and post-install cache replay.

```sh
node --test desktop/tests/*.test.mjs
.runtime/simnibs-4.6.0/bin/python -B -m pytest -q \
  tests/test_desktop_runtime.py tests/test_desktop_build.py tests/test_desktop_finalize.py
```

The native shell accepts `--smoke-test` when launched from Terminal: it opens
the actual UI, reports DOM and WebGL2 checks, and quits. `EEG_DESKTOP_USER_DATA`
selects a separate test directory so that QA does not touch a user's workspace.
The HTTP integration script can then exercise actual layout, electrode-editing,
coordinate, and source-simulation jobs against the desktop server.

Keep the runtime audit and `BUNDLED_COMPONENTS.json` with each release. Third-party
license texts remain in the packaged environment; root `THIRD_PARTY_NOTICES.md`
and the bundled notices describe the software and Ernie data separately. A
public binary release also needs its corresponding-source and license review,
Developer ID signing, and notarization. None is implied by an ad-hoc build.
