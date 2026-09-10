# Application data bundle

`manifest.json` pins the minimal frozen inputs needed by the existing local App.
It records each relative path, byte size, SHA-256, role and source attribution.
`SOURCES.md` records the data license and the boundary between upstream data and
locally derived research artifacts. Both are small, version-controlled files.

The original payload contains 20 files totaling 406,223,080 bytes (387.40 MiB).
These comprise six current/historical pointers, selected reports and arrays,
the forward-bank run manifest, and the Ernie FEM mesh. Only selected files are
included; complete campaign directories and personal computation jobs are not.
The payload under `data/external/` and `results/` is transferred separately
from Git. The App's public browser assets are part of the code checkout.

Run these commands from the repository root using Python 3.10 or newer:

```sh
python scripts/data_bundle.py verify
python scripts/data_bundle.py install /path/to/eeglayoutlab-data-v1.tar.gz
python scripts/data_bundle.py export --output /path/to/eeglayoutlab-data-v1.tar.gz
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

The tool uses only Python's standard library and makes no network requests.
Obtain the matching local archive from the collaborator who supplied this
checkout. No public data-download service is assumed.

```sh
python -m unittest discover -s tests -p test_data_bundle.py
```
