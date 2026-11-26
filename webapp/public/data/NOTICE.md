# Licence of the files in this directory

The repository's GPL-3.0-only grant (see `LICENSE` at the repository root) covers
the project's original source code and documentation. Most files in this
directory are data derived from third-party material and are **not** covered by
that grant.

## Ernie-derived files: CC BY-NC 4.0

These files are derived from the SimNIBS example dataset v4.1, Ernie head model,
© SimNIBS developers 2024, licensed under
[CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/). Release page:
<https://github.com/simnibs/example-dataset/releases/tag/v4.1>.

| File | What it is |
| --- | --- |
| `ernie-scalp-mni.bin` | The SimNIBS nonlinear Ernie-to-MNI warp sampled at the display scalp vertices |
| `ernie-mni-mapping.json` | Bindings, Ernie's charm-placed `EEG10-20_extended_SPM12` cap positions and fiducials, and the MNI fiducials from the SimNIBS 4.6.0 `ElectrodeCaps_MNI` resources (GPL-3.0-only) |
| `single_head_optimization.json` | Frozen optimization results (204 conditions) computed on the Ernie head model |
| `fixed64_results.json` | Frozen fixed-64 layout results computed on the Ernie head model |
| `retention-example.json` | Numerical excerpt of one Ernie result, used by the retention guide |

The three result files are numerical records computed from the Ernie model and
its derived forward bank. They are treated as derived data and keep the CC BY-NC
4.0 terms.

What you may do under that licence: copy and redistribute these files, and adapt
them, **for non-commercial purposes only**. You must keep the attribution below,
link to the licence, and say what you changed. Commercial use of these files is
not permitted by the licence; replace them or obtain permission from the
rights holders first.

Attribution to keep with any copy:

> Derived from SimNIBS example dataset v4.1, Ernie head model. © SimNIBS
> developers 2024. CC BY-NC 4.0. The files are numerical derivatives (warps,
> mappings and model results); see `THIRD_PARTY_NOTICES.md` and
> `scripts/build_ernie_mni_mapping.py` for how they were made.

## Reference montage: MNE-Python, BSD-3-Clause

`biosemi64_reference.json` holds the positions of the BioSemi 64-channel cap taken
from MNE-Python 1.11.0's built-in `biosemi64` standard montage (its `source`
field says so). MNE-Python is distributed under the BSD 3-Clause licence.

## Project-authored file: GPL-3.0-only

`experiment_protocol_v2.json` is the project's own protocol description and is
covered by the repository's GPL-3.0-only grant.

The full list of third-party material is in `THIRD_PARTY_NOTICES.md` at the
repository root.
