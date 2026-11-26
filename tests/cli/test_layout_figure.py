"""Byte-parity tests for ``figures/layout.py`` and ``eeglayoutlab export --format svg`` (phase 3 slice 5)."""
from __future__ import annotations

from pathlib import Path
import random

from eeglayoutlab.core.ernie_mni import load_mapping
from eeglayoutlab.figures.layout import figure_spacing, layout_figure_svg

from .cli_support import (
    ROOT, needs_node, run_node_cli, run_node_driver, run_python_cli_inproc, tree_bytes,
)

FIGURES_DRIVER = ROOT / 'tests/cli/parity/figures.mjs'


def _standard64_design(regions: int = 2) -> dict:
    golden = load_mapping()['golden']['standard64']
    sizes = [64 // regions + (1 if r < 64 % regions else 0) for r in range(regions)]
    reg = [r for r, count in enumerate(sizes) for _ in range(count)]
    return {
        'schema': 'eeg-electrode-design/1',
        'coordinate_system': 'ernie_native_mm',
        'unit': 'mm',
        'name': f'standard64-r{regions}',
        'electrode_names': list(golden['names']),
        'xyz_mm': [list(pt) for pt in golden['xyz_mm']],
        'region_indices': reg,
    }


@needs_node
def test_layout_figure_svg_is_byte_equal_across_regions_crowding_and_unicode(tmp_path: Path) -> None:
    rng = random.Random(202605)
    cases = []
    for r in (1, 2, 3, 4, 6):
        cases.append({'id': f'std-r{r}', 'op': 'svg', 'design': _standard64_design(r)})

    crowded = _standard64_design(2)
    crowded['xyz_mm'] = [[-40.0 + 5.0 * (i % 8), 20.0 + 5.0 * (i // 8), 80.0] for i in range(64)]
    for mode in (None, 'yes', 'no'):
        entry = {'id': f'crowded-{mode}', 'op': 'svg', 'design': crowded}
        if mode is not None:
            entry['labels'] = mode
        cases.append(entry)

    unicode_design = _standard64_design(4)
    unicode_design['name'] = '超长脑电布局标题 · Standard 64 Layout with Combining e\u0301 & Emoji 🧪🇺🇸 <A&B> "' + ('X' * 60)
    unicode_design['electrode_names'] = [
        f'极{i + 1}_e\u0301&\'"<>' if i % 3 == 0 else (f'👩‍🔬{i}' if i % 5 == 0 else f'Ch{i + 1}')
        for i in range(64)
    ]
    cases.append({'id': 'unicode', 'op': 'svg', 'design': unicode_design, 'labels': 'yes'})

    for idx in range(60):
        r = (1, 2, 3, 4, 6)[idx % 5]
        sizes = [64 // r + (1 if k < 64 % r else 0) for k in range(r)]
        regs = [k for k, sz in enumerate(sizes) for _ in range(sz)]
        rng.shuffle(regs)
        pts = [[rng.uniform(-85.0, 85.0), rng.uniform(-100.0, 95.0), rng.uniform(-45.0, 110.0)] for _ in range(64)]
        design = {
            'schema': 'eeg-electrode-design/1',
            'coordinate_system': 'ernie_native_mm',
            'unit': 'mm',
            'name': f'rand-{idx}',
            'xyz_mm': pts,
            'region_indices': regs,
        }
        cases.append({'id': f'rand-{idx}', 'op': 'svg', 'design': design})

    node = {row['id']: row for row in run_node_driver(FIGURES_DRIVER, {'cases': cases}, tmp_path)['results']}
    for c in cases:
        want = node[c['id']]
        assert want['ok'], want
        d = c['design']
        count = max(d['region_indices']) + 1
        labels_opt = c.get('labels')
        show = figure_spacing(d) >= 16.0 if labels_opt is None else (labels_opt == 'yes')
        svg = layout_figure_svg(
            d,
            {
                'title': d['name'],
                'subtitle': f"64 electrodes · {count} region{'s' if count > 1 else ''} · Ernie template head",
                'region': lambda index: f'Region {index + 1}',
                'caption': [
                    'Head frame from the Ernie template landmarks NAS, LPA and RPA (x toward RPA, y toward NAS); '
                    'azimuthal equidistant projection by angle from the vertical axis.',
                    'The circle is the NAS–LPA–RPA plane; electrodes below it lie outside. Positions are design '
                    'positions on the template head, not measured positions.',
                ],
            },
            labels=show,
        )
        assert svg == want['svg'], c['id']


@needs_node
def test_export_writes_mne_eeglab_and_svg_files_and_hides_crowded_names_unless_asked(
    tmp_path: Path, capsys
) -> None:
    """Port of ``check-cli.mjs::export writes MNE, EEGLAB and SVG files and hides crowded names unless asked``."""
    names = load_mapping()['golden']['standard64']['names']
    labels_path = tmp_path / 'labels.tsv'
    labels_path.write_text('name\tregion\n' + '\n'.join(f'{n}\t0' for n in names) + '\n', encoding='utf-8')
    design_path = tmp_path / 'design.json'
    code, _, _ = run_python_cli_inproc(['design', str(labels_path), '--out', str(design_path)], capsys)
    assert code == 0

    py_dir, node_dir = tmp_path / 'py', tmp_path / 'node'
    for fmt, filename in (('mne', 'electrodes.elc'), ('eeglab', 'electrodes.sfp'), ('svg', 'layout.svg'), ('mni', 'space-MNI152NLin6Asym_electrodes.tsv')):
        p_code, _, _ = run_python_cli_inproc(['export', str(design_path), '--format', fmt, '--out-dir', str(py_dir)], capsys)
        n_res = run_node_cli(['export', str(design_path), '--format', fmt, '--out-dir', str(node_dir)])
        assert p_code == 0 and n_res.returncode == 0
        assert (py_dir / filename).stat().st_size > 1000
    assert tree_bytes(py_dir) == tree_bytes(node_dir)
    assert '>Cz</text>' in (py_dir / 'layout.svg').read_text(encoding='utf-8')

    crowded = _standard64_design(1)
    crowded['xyz_mm'] = [[-40.0 + 5.0 * (i % 8), 20.0 + 5.0 * (i // 8), 80.0] for i in range(64)]
    crowded_path = tmp_path / 'crowded.json'
    from eeglayoutlab.schemas import jsjson
    crowded_path.write_text(jsjson.stringify(crowded), encoding='utf-8')

    py_crowded, node_crowded = tmp_path / 'py-crowded', tmp_path / 'node-crowded'
    assert run_python_cli_inproc(['export', str(crowded_path), '--format', 'svg', '--out-dir', str(py_crowded)], capsys)[0] == 0
    assert run_node_cli(['export', str(crowded_path), '--format', 'svg', '--out-dir', str(node_crowded)]).returncode == 0
    assert '>Cz</text>' not in (py_crowded / 'layout.svg').read_text(encoding='utf-8')
    assert tree_bytes(py_crowded) == tree_bytes(node_crowded)

    py_yes, node_yes = tmp_path / 'py-yes', tmp_path / 'node-yes'
    assert run_python_cli_inproc(
        ['export', str(crowded_path), '--format', 'svg', '--labels', 'yes', '--out-dir', str(py_yes)], capsys
    )[0] == 0
    assert run_node_cli(
        ['export', str(crowded_path), '--format', 'svg', '--labels', 'yes', '--out-dir', str(node_yes)]
    ).returncode == 0
    assert '>Cz</text>' in (py_yes / 'layout.svg').read_text(encoding='utf-8')
    assert tree_bytes(py_yes) == tree_bytes(node_yes)
