"""Byte-parity tests for ``design`` and ``export`` (phase 3 slices 4 & 13) and ports of ``check-cli.mjs``."""
from __future__ import annotations

import math
from pathlib import Path
import random

from eeglayoutlab.core.bids import (
    export_bids_electrodes, export_mni_bids_electrodes, parse_bids_electrodes, parse_electrode_labels,
)
from eeglayoutlab.core.design_file import design_csv, parse_design
from eeglayoutlab.core.ernie_mni import load_mapping, verified_surface
from eeglayoutlab.core.head_registration import assign_balanced_regions
from eeglayoutlab.core.montage import export_eeglab_sfp, export_mne_elc, parse_montage_file
from eeglayoutlab.schemas import jsjson

from .cli_support import (
    ROOT, needs_node, run_node_cli, run_node_driver, run_python_cli_inproc, tree_bytes,
)

COORDINATES_DRIVER = ROOT / 'tests/cli/parity/coordinates.mjs'


@needs_node
def test_design_builds_the_same_design_from_a_name_list_its_bids_export_and_a_search_run(
    tmp_path: Path, capsys
) -> None:
    """Port of ``check-cli.mjs::design builds the same design from a name list, its BIDS export and a search run``."""
    golden = load_mapping()['golden']['standard64']
    names = golden['names']
    labels = tmp_path / 'labels.tsv'
    labels.write_text(
        'name\tregion\n' + '\n'.join(f'{name}\t{idx % 2}' for idx, name in enumerate(names)) + '\n',
        encoding='utf-8',
    )

    py_design = tmp_path / 'py-design.json'
    node_design = tmp_path / 'node-design.json'
    assert run_python_cli_inproc(['design', str(labels), '--name', 'standard64', '--out', str(py_design)], capsys)[0] == 0
    assert run_node_cli(['design', str(labels), '--name', 'standard64', '--out', str(node_design)]).returncode == 0
    assert py_design.read_bytes() == node_design.read_bytes()

    base = jsjson.parse(py_design.read_text(encoding='utf-8'))
    assert base['name'] == 'standard64'
    assert all(
        math.hypot(*(base['xyz_mm'][i][axis] - golden['xyz_mm'][i][axis] for axis in range(3))) < 1e-9
        for i in range(64)
    )

    py_bids_dir, node_bids_dir = tmp_path / 'py-bids', tmp_path / 'node-bids'
    assert run_python_cli_inproc(['export', str(py_design), '--format', 'bids', '--out-dir', str(py_bids_dir)], capsys)[0] == 0
    assert run_node_cli(['export', str(node_design), '--format', 'bids', '--out-dir', str(node_bids_dir)]).returncode == 0
    assert tree_bytes(py_bids_dir) == tree_bytes(node_bids_dir)

    bids_files = [str(py_bids_dir / name) for name in ('electrodes.tsv', 'coordsystem.json', 'electrodes.json')]
    py_from_bids, node_from_bids = tmp_path / 'py-from-bids.json', tmp_path / 'node-from-bids.json'
    assert run_python_cli_inproc(['design', *bids_files, '--out', str(py_from_bids)], capsys)[0] == 0
    assert run_node_cli(['design', *bids_files, '--out', str(node_from_bids)]).returncode == 0
    assert py_from_bids.read_bytes() == node_from_bids.read_bytes()
    from_bids = jsjson.parse(py_from_bids.read_text(encoding='utf-8'))
    assert [from_bids['xyz_mm'], from_bids['region_indices'], from_bids['electrode_names']] == [
        base['xyz_mm'], base['region_indices'], base['electrode_names'],
    ]

    search = tmp_path / 'search.result.json'
    search.write_text(
        jsjson.stringify({
            'schema': 'eeglayoutlab-cli-run/1',
            'service': 'radius-search',
            'request': {'region_count': 2, 'radius_mm': 30, 'mode': 'whole_surface'},
            'result': {'status': 'completed', 'layout': {'xyzMm': base['xyz_mm'], 'regionIndices': base['region_indices']}},
        }),
        encoding='utf-8',
    )
    py_from_search, node_from_search = tmp_path / 'py-from-search.json', tmp_path / 'node-from-search.json'
    assert run_python_cli_inproc(['design', str(search), '--out', str(py_from_search)], capsys)[0] == 0
    assert run_node_cli(['design', str(search), '--out', str(node_from_search)]).returncode == 0
    assert py_from_search.read_bytes() == node_from_search.read_bytes()
    from_search = jsjson.parse(py_from_search.read_text(encoding='utf-8'))
    assert from_search['name'] == 'search 2 regions, 30 mm, whole_surface'


@needs_node
def test_design_reads_elc_and_sfp_montages_and_assigns_regions_on_request(tmp_path: Path, capsys) -> None:
    """Port of ``check-cli.mjs::design reads .elc and .sfp montages and assigns regions on request``."""
    names = load_mapping()['golden']['standard64']['names']
    labels = tmp_path / 'labels.tsv'
    labels.write_text('name\tregion\n' + '\n'.join(f'{n}\t0' for n in names) + '\n', encoding='utf-8')
    design = tmp_path / 'design.json'
    assert run_python_cli_inproc(['design', str(labels), '--out', str(design)], capsys)[0] == 0
    assert run_python_cli_inproc(['export', str(design), '--format', 'mne', '--out-dir', str(tmp_path)], capsys)[0] == 0
    assert run_python_cli_inproc(['export', str(design), '--format', 'eeglab', '--out-dir', str(tmp_path)], capsys)[0] == 0

    base = jsjson.parse(design.read_text(encoding='utf-8'))
    elc, sfp = tmp_path / 'electrodes.elc', tmp_path / 'electrodes.sfp'
    out_py, out_node = tmp_path / 'montage-py.json', tmp_path / 'montage-node.json'

    code, _, err = run_python_cli_inproc(['design', str(elc), '--out', str(out_py)], capsys)
    assert code == 2 and 'region' in err
    code, _, err = run_python_cli_inproc(['design', str(sfp), '--regions', '4', '--out', str(out_py)], capsys)
    assert code == 2 and '单位' in err
    code, _, err = run_python_cli_inproc(['design', str(elc), '--regions', '5', '--out', str(out_py)], capsys)
    assert code == 2 and '--regions must be' in err

    for extra in ([str(elc), '--regions', '4'], [str(sfp), '--regions', '4', '--unit', 'mm']):
        assert run_python_cli_inproc(['design', *extra, '--out', str(out_py)], capsys)[0] == 0
        assert run_node_cli(['design', *extra, '--out', str(out_node)]).returncode == 0
        assert out_py.read_bytes() == out_node.read_bytes()
        montage = jsjson.parse(out_py.read_text(encoding='utf-8'))
        assert [montage['xyz_mm'], montage['electrode_names']] == [base['xyz_mm'], base['electrode_names']]
        assert montage['source_metadata']['region_assignment'] == {'method': 'balanced-spatial/1', 'region_count': 4}
        assert [montage['region_indices'].count(r) for r in range(4)] == [16, 16, 16, 16]


@needs_node
def test_the_command_line_rejects_incomplete_commands_before_starting_a_calculation(capsys) -> None:
    """Port of ``check-cli.mjs::the command line rejects incomplete commands before starting a calculation``."""
    code, out, _ = run_python_cli_inproc(['help'], capsys)
    assert code == 0 and 'evaluate --design' in out
    for args in (
        ['evaluate', 'request.json'],
        ['search'],
        ['study', 'a.json', 'b.json', '--out-dir', 'x'],
        ['unknown', '--out-dir', 'x'],
        ['unknown'],
        ['export', 'd.json', '--out-dir', 'x'],
        ['design', 'x.tsv'],
        ['design', 'x.tsv', '--regions'],
    ):
        p_code, _, p_err = run_python_cli_inproc(args, capsys)
        n_res = run_node_cli(args)
        assert p_code == 2 and n_res.returncode == 2, args
        assert p_err.startswith('error: '), p_err
        # First line of error matches Node's error message verbatim.
        assert p_err.splitlines()[0] == n_res.stderr.splitlines()[0], (args, p_err, n_res.stderr)


def test_version_prints_the_package_version(capsys) -> None:
    from eeglayoutlab.cli.main import main
    from eeglayoutlab.data.store import code_version
    for flag in ('--version', '-V', 'version'):
        assert main([flag]) == 0
        assert capsys.readouterr().out == f'eeglayoutlab {code_version()}\n'


def test_export_supports_sparse_and_adaptive_search_runs_across_all_formats(tmp_path: Path, capsys) -> None:
    """Verifies U15: variable-K (8–64) and adaptive-quota radius-search runs export to BIDS, MNI, MNE, EEGLAB and SVG."""
    golden = load_mapping()['golden']['standard64']
    xyz24 = [list(pt) for pt in golden['xyz_mm'][:24]]
    adaptive_run = tmp_path / 'sparse24.result.json'
    adaptive_run.write_text(
        jsjson.stringify({
            'schema': 'eeglayoutlab-cli-run/1',
            'service': 'radius-search',
            'request': {
                'region_count': 2,
                'radius_mm': 30,
                'mode': 'preset',
                'mask_codes': ['AL', 'AR'],
                'electrode_count': 24,
                'allocation_mode': 'adaptive',
            },
            'result': {
                'status': 'completed',
                'layout': {
                    'xyzMm': xyz24,
                    'regionIndices': [0] * 8 + [1] * 16,
                },
            },
        }),
        encoding='utf-8',
    )

    out_dir = tmp_path / 'exported-24'
    for fmt in ('bids', 'mni', 'mne', 'eeglab', 'svg'):
        code, _, err = run_python_cli_inproc(
            ['export', str(adaptive_run), '--format', fmt, '--out-dir', str(out_dir)], capsys
        )
        assert code == 0, (fmt, err)

    tsv_lines = (out_dir / 'electrodes.tsv').read_text(encoding='utf-8').strip().splitlines()
    assert len(tsv_lines) == 25 and tsv_lines[1].startswith('E1\t')
    mni_lines = (out_dir / 'space-MNI152NLin6Asym_electrodes.tsv').read_text(encoding='utf-8').strip().splitlines()
    assert len(mni_lines) == 25
    elc_text = (out_dir / 'electrodes.elc').read_text(encoding='utf-8')
    assert 'NumberPositions=\t27\n' in elc_text
    sfp_lines = (out_dir / 'electrodes.sfp').read_text(encoding='utf-8').strip().splitlines()
    assert len(sfp_lines) == 27
    svg_text = (out_dir / 'layout.svg').read_text(encoding='utf-8')
    assert '24 electrodes · 2 regions · Ernie template head' in svg_text
    assert 'Region 1 (8)' in svg_text and 'Region 2 (16)' in svg_text

    # Malformed 23-electrode or unbalanced non-adaptive search runs are still strictly rejected
    bad_run = tmp_path / 'bad23.result.json'
    bad_run.write_text(
        jsjson.stringify({
            'schema': 'eeglayoutlab-cli-run/1',
            'service': 'radius-search',
            'request': {'region_count': 2, 'radius_mm': 30, 'mode': 'whole_surface'},
            'result': {'status': 'completed', 'layout': {'xyzMm': xyz24[:23], 'regionIndices': [0] * 11 + [1] * 12}},
        }),
        encoding='utf-8',
    )
    code, _, _ = run_python_cli_inproc(['export', str(bad_run), '--format', 'svg', '--out-dir', str(out_dir)], capsys)
    assert code == 2


@needs_node
def test_coordinate_parsers_registration_mni_and_csv_match_node_byte_for_byte(tmp_path: Path) -> None:
    surface = verified_surface()
    golden = load_mapping()['golden']['standard64']
    names = list(golden['names'])

    # 1. Legacy 10-20 aliases T3/T4/T5/T6, BOM, CRLF, comma-separated, names-only with --regions.
    aliased = [('T3' if n == 'T7' else 'T4' if n == 'T8' else 'T5' if n == 'P7' else 'T6' if n == 'P8' else n) for n in names]
    csv_labels = {'name': 'legacy.csv', 'text': '\ufeffname\r\n' + '\r\n'.join(aliased) + '\r\n'}
    bad_labels = {'name': 'bad.tsv', 'text': 'name\tregion\n' + '\n'.join(f'BAD{i}\t0' for i in range(64))}

    base_design = parse_electrode_labels(csv_labels, region_count=3)
    csv_text = design_csv({**base_design, 'electrode_names': [f'E,{i}' if i == 0 else f'E"{i}' if i == 1 else n for i, n in enumerate(names)]})
    mni_files = export_mni_bids_electrodes(base_design, surface)

    # Perturbed & scaled CapTrak-like head-frame BIDS and .sfp in cm to exercise similarityFit + 500-iter ICP + rotation_deg!
    rng = random.Random(202613)
    angle = 0.18
    ca, sa = math.cos(angle), math.sin(angle)
    scale = 0.112  # cm-like scale with 1.12x stretch

    def xform(pt: list[float]) -> list[float]:
        x, y, z = pt
        rx = ca * x - sa * y
        ry = sa * x + ca * y
        return [scale * rx + 1.4, scale * ry - 2.1, scale * z + 0.8]

    lm_native = load_mapping()['landmarks']['native_mm']
    sfp_rows = [
        ('FidNz', xform(lm_native['Nz'])),
        ('FidT9', xform(lm_native['LPA'])),
        ('FidT10', xform(lm_native['RPA'])),
        *((names[i], xform([golden['xyz_mm'][i][0] + rng.uniform(-0.4, 0.4),
                            golden['xyz_mm'][i][1] + rng.uniform(-0.4, 0.4),
                            golden['xyz_mm'][i][2] + rng.uniform(-0.4, 0.4)])) for i in range(64)),
    ]
    sfp_file = {
        'name': 'digitized.sfp',
        'text': '\n'.join(f'{lbl}\t{pt[0]:.6f}\t{pt[1]:.6f}\t{pt[2]:.6f}' for lbl, pt in sfp_rows) + '\n',
    }

    captrak_tsv_lines = ['name\tx\ty\tz\ttype']
    for i in range(64):
        p = sfp_rows[i + 3][1]
        captrak_tsv_lines.append(f'{names[i]}\t{p[0]:.6f}\t{p[1]:.6f}\t{p[2]:.6f}\tEEG')
    captrak_tsv_lines.append('ECG1\t0\t0\t0\tECG')
    captrak_tsv_lines.append('BAD\tn/a\tn/a\tn/a\tEEG')
    captrak_files = [
        {'name': 'sub-01_electrodes.tsv', 'text': '\n'.join(captrak_tsv_lines) + '\n'},
        {
            'name': 'sub-01_coordsystem.json',
            'text': jsjson.stringify({
                'EEGCoordinateSystem': 'CapTrak',
                'EEGCoordinateUnits': 'cm',
                'AnatomicalLandmarkCoordinates': {
                    'NAS': sfp_rows[0][1],
                    'LPA': sfp_rows[1][1],
                    'RPA': sfp_rows[2][1],
                },
            }),
        },
    ]

    rand_pts = [[rng.uniform(-70, 70), rng.uniform(-90, 80), rng.uniform(-20, 95)] for _ in range(64)]

    cases = [
        {'id': 'labels-alias-3', 'op': 'parseElectrodeLabels', 'file': csv_labels, 'options': {'regionCount': 3}},
        {'id': 'labels-unknown', 'op': 'parseElectrodeLabels', 'file': bad_labels},
        {'id': 'csv-quoted', 'op': 'parseDesign', 'text': csv_text, 'name': 'quoted'},
        {'id': 'mni-roundtrip', 'op': 'parseBIDSElectrodes', 'files': mni_files, 'withSurface': True},
        {'id': 'sfp-registered', 'op': 'parseMontageFile', 'file': sfp_file, 'options': {'unit': 'cm', 'regionCount': 6}},
        {'id': 'captrak-bids', 'op': 'parseBIDSElectrodes', 'files': captrak_files, 'withSurface': True, 'options': {'regionCount': 4}},
        {'id': 'assign-6', 'op': 'assignBalancedRegions', 'points': rand_pts, 'count': 6},
    ]
    node = {row['id']: row for row in run_node_driver(COORDINATES_DRIVER, {'cases': cases}, tmp_path)['results']}

    assert jsjson.stringify(base_design, indent=2) == node['labels-alias-3']['value']
    try:
        parse_electrode_labels(bad_labels)
    except ValueError as err:
        assert not node['labels-unknown']['ok'] and str(err) == node['labels-unknown']['message']
    else:
        raise AssertionError('expected ValueError')

    assert jsjson.stringify(parse_design(csv_text, 'quoted'), indent=2) == node['csv-quoted']['value']
    assert node['mni-roundtrip']['ok'], node['mni-roundtrip']
    assert jsjson.stringify(parse_bids_electrodes(mni_files, surface), indent=2) == node['mni-roundtrip']['value']
    assert node['sfp-registered']['ok'], node['sfp-registered']
    assert jsjson.stringify(
        parse_montage_file(sfp_file, surface, unit='cm', region_count=6), indent=2
    ) == node['sfp-registered']['value']
    assert node['captrak-bids']['ok'], node['captrak-bids']
    assert jsjson.stringify(
        parse_bids_electrodes(captrak_files, surface, region_count=4), indent=2
    ) == node['captrak-bids']['value']
    assert assign_balanced_regions(rand_pts, 6) == node['assign-6']['value']

    # Also check BIDS / MNE / EEGLAB export bytes directly
    export_cases = [
        {'id': 'exp-bids', 'op': 'exportBIDSElectrodes', 'design': base_design},
        {'id': 'exp-mni', 'op': 'exportMniBIDSElectrodes', 'design': base_design},
        {'id': 'exp-mne', 'op': 'exportMneElc', 'design': base_design},
        {'id': 'exp-sfp', 'op': 'exportEeglabSfp', 'design': base_design},
    ]
    exp_node = {row['id']: row['value'] for row in run_node_driver(COORDINATES_DRIVER, {'cases': export_cases}, tmp_path)['results']}
    assert export_bids_electrodes(base_design) == exp_node['exp-bids']
    assert export_mni_bids_electrodes(base_design, surface) == exp_node['exp-mni']
    assert export_mne_elc(base_design) == exp_node['exp-mne']
    assert export_eeglab_sfp(base_design) == exp_node['exp-sfp']
