# Application data bundle

`manifest.json` pins the minimal frozen inputs needed by the web application.
It records each relative path, byte size, SHA-256, role and source attribution.
`SOURCES.md` records the data license and the boundary between upstream data and
locally derived research artifacts. Both are small, version-controlled files.

The bundle contains 21 files totaling 406,226,293 bytes (387.41 MiB).
These comprise the source declaration, six current/historical pointers,
selected reports and arrays, the forward-bank run manifest, and the Ernie FEM
mesh. Complete campaign directories and personal calculation history are
excluded. The payload under `data/external/` and `results/` is distributed as a
release attachment. The browser assets are part of the code checkout.

## Download and install

Download `eeglayoutlab-data-v1.tar.gz` and `eeglayoutlab-data-v1.tar.gz.sha256` from [Release v0.2.0](https://github.com/Yiming-S/EEGLayoutLab/releases/tag/v0.2.0) into `releases/` (directly in a browser, or with [GitHub CLI](https://cli.github.com/) below; no GitHub sign-in is required), then verify and install from the matching source checkout:

```sh
mkdir -p releases
gh release download v0.2.0 --repo Yiming-S/EEGLayoutLab \
  --pattern eeglayoutlab-data-v1.tar.gz \
  --pattern eeglayoutlab-data-v1.tar.gz.sha256 \
  --dir releases
(cd releases && shasum -a 256 -c eeglayoutlab-data-v1.tar.gz.sha256)
python3 scripts/data_bundle.py install releases/eeglayoutlab-data-v1.tar.gz
python3 scripts/data_bundle.py verify
```

Use Python 3.10 or newer. Continue with the [source installation guide](../docs/source-installation.md)
to install the computation environment and web dependencies.

## Local bundle tools

Run these commands from the repository root using Python 3.10 or newer:

```sh
python3 scripts/data_bundle.py verify
python3 scripts/data_bundle.py install /path/to/eeglayoutlab-data-v1.tar.gz
python3 scripts/data_bundle.py export --output /path/to/eeglayoutlab-data-v1.tar.gz
```

Each command also accepts `--root /path/to/checkout`. The default root is the
repository containing the script. Export requires an existing output directory
and a new filename; it will not replace an existing archive. Export normalizes
archive owner, mode and timestamps and verifies all archive members before
publishing the file. It leaves source data unchanged.

Install uses this checkout's manifest as its trust anchor. The archive's copy
must be byte-identical. The complete archive and all existing destinations are
validated before any payload is installed. Matching files are retained; an
existing file with different bytes causes an error. Extra, duplicate, missing,
absolute or traversing paths and non-regular archive members are rejected.
Symlink destinations, ancestors and source files are rejected. Do not modify
the destination tree concurrently with installation. An interrupted final
placement can be resumed by running install again.

The bundle tool uses only Python's standard library and makes no network
requests. Downloading a release attachment is a separate step.

```sh
python3 -m unittest discover -s tests -p test_data_bundle.py
```
