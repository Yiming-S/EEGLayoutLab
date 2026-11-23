# Licence of the files in this directory

The repository's GPL-3.0-only grant (see `LICENSE` at the repository root) covers
the project's original source code and documentation. It does **not** cover the
Ernie data in this directory.

## Ernie-derived files: CC BY-NC 4.0

These files are derived from the SimNIBS example dataset v4.1, Ernie head model,
© SimNIBS developers 2024, licensed under
[CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/). Release page:
<https://github.com/simnibs/example-dataset/releases/tag/v4.1>.

| File | What it is |
| --- | --- |
| `scalp.bin` | Exterior scalp surface, millimetres converted to metres, rounded to float32 |
| `cortex.bin` | Largest gray-matter surface component, same conversion |
| `source-roi-cortex.bin` | Left and right central cortical surfaces, float32 metres, normals packed as int8, triangles reordered into ROI material groups |
| `manifest.json` | Inventory, hashes and transformation record of `scalp.bin` and `cortex.bin` |
| `source-roi.json` | Source checksums, material groups and source memberships of `source-roi-cortex.bin` |

What you may do under that licence: copy and redistribute these files, and adapt
them, **for non-commercial purposes only**. You must keep the attribution below,
link to the licence, and say what you changed. Commercial use of these files is
not permitted by the licence; replace them or obtain permission from the
rights holders first.

Attribution to keep with any copy:

> Derived from SimNIBS example dataset v4.1, Ernie head model. © SimNIBS
> developers 2024. CC BY-NC 4.0. Coordinates were converted from millimetres to
> metres and rounded into display buffers; see `README.md` and `manifest.json`
> for the full description of modifications.

## Project-authored file: GPL-3.0-only

`source-roi-definition.json` is the project's own grouping of Desikan–Killiany
labels into six research ROIs. It is covered by the repository's GPL-3.0-only
grant. The atlas labels it names keep their upstream FreeSurfer and SimNIBS
notices.

## Documentation

`README.md` in this directory describes the buffers and their provenance; it
inherits the licence of the files it describes.

The full list of third-party material is in `THIRD_PARTY_NOTICES.md` at the
repository root.
