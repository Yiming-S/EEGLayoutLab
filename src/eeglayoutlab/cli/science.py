"""Scientific command-line subcommands: ``design``, ``export``, ``evaluate``, ``search``, ``eeg-summary``,
``prior``, ``channels``, ``pareto`` and ``study`` (``webapp/scripts/eeglayoutlab.mjs``, phase 3 slices 4-6 & 11-13;
decisions U5, U8, U10, U11, U13, U15).

No ``json`` stdlib import: all JSON parsing, formatting and hashing go through ``eeglayoutlab.schemas.jsjson`` so
written files and keys are byte-identical to the Node reference CLI. Pydantic and job modules are imported only
when ``evaluate``, ``search``, ``study`` or ``prior`` runs.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import stat as statmod
import sys
from typing import Any, Optional, Sequence

from ..core import jsmath
from ..core.bids import (
    REGION_DESCRIPTION, bids_needs_mni_surface, export_bids_electrodes, export_mni_bids_electrodes,
    parse_bids_electrodes, parse_electrode_labels,
)
from ..core.channel_subset import SUMMARY_SCHEMA, channel_subsets
from ..core.design_file import parse_design, validate_design
from ..core.ernie_mni import verified_surface
from ..core.montage import export_eeglab_sfp, export_mne_elc, parse_montage_file
from ..core.pareto import pareto_cli_report
from ..figures.channel_subset import channel_subset_figure_svg
from ..figures.layout import plot_figure_spacing, plot_figure_svg, validate_layout_plot
from ..jobs import nodepath
from ..jobs.runtime import repository_root
from ..schemas import jsjson

__all__ = [
    'RUN_SCHEMA', 'HELP', 'SCIENCE_COMMANDS', 'SEARCH_INLINE_OPTIONS', 'add_commands', 'parse_science_args',
    'read_json', 'write_json', 'stem', 'summary_files', 'design_from', 'export_files', 'run_science',
]

RUN_SCHEMA = 'eeglayoutlab-cli-run/1'
SCIENCE_COMMANDS = frozenset({
    'design', 'export', 'evaluate', 'search', 'eeg-summary', 'prior', 'channels', 'pareto', 'study', 'help',
})
SEARCH_INLINE_OPTIONS = frozenset({
    'regions', 'radius', 'mode', 'masks', 'electrodes', 'allocation', 'objective', 'noise',
})
_SEARCH_ELECTRODE_COUNTS = frozenset({8, 12, 16, 24, 32, 48, 64})
_SPARSE_REGION_DESCRIPTION = (
    'EEGLayoutLab region index (8–64 channels, balanced or adaptive regional quota), '
    'numbered continuously from zero. Supported region counts: 1, 2, 3, 4, or 6.'
)

_ALLOWED_OPTIONS: dict[str, frozenset[str]] = {
    'design': frozenset({'name', 'regions', 'unit', 'out', 'root'}),
    'export': frozenset({'format', 'labels', 'out-dir', 'root'}),
    'evaluate': frozenset({
        'design', 'radius', 'seed', 'action', 'noise', 'conductivity', 'head',
        'robustness', 'data-prior', 'out-dir', 'root', 'python',
    }),
    'search': frozenset({'data-prior', 'out-dir', 'root', 'python', *SEARCH_INLINE_OPTIONS}),
    'eeg-summary': frozenset({'band', 'epoch', 'label', 'out-dir', 'root', 'python'}),
    'prior': frozenset({'out', 'root', 'python'}),
    'channels': frozenset({'test', 'prior', 'counts', 'draws', 'seed', 'figure', 'out'}),
    'pareto': frozenset({'objectives', 'out'}),
    'study': frozenset({'out-dir', 'root', 'python'}),
}

HELP = """EEGLayoutLab command line

  eeglayoutlab quickstart [WORKSPACE] [--from URL|DIR] [--base-only] [--examples] [--verify] [--no-browser]
      First-run and daily launch: install/link missing model data, create ~/eeglayoutlab-workspace
      if needed, and open the local web application on 127.0.0.1.

  eeglayoutlab doctor [--root DIR] [--smoke]
      Check scientific root, Python worker packages, model data and web UI (--smoke runs a quick calculation).

  eeglayoutlab serve [WORKSPACE] [--root DIR] [--port N] [--no-browser] [--cache-only]
      Start the local web application on 127.0.0.1 for a workspace.

  eeglayoutlab data list | verify [NAME ...] | install [NAME ...] | compose [NAME ...] | remove NAME
      Manage verified scientific data packages in the user data directory.

  eeglayoutlab examples run [--root DIR] [--out-dir DIR] [--skip-cross-head] [--update-expected]
      Run the reproducible command-line examples and compare scores against examples/expected.json.

  eeglayoutlab design FILE... [--name NAME] [--regions 1|2|3|4|6] [--unit mm|cm|m] --out DESIGN.json
      Build a design from coordinate files: a BIDS pair (Ernie native, MNI, or a head frame
      such as CapTrak with NAS/LPA/RPA landmarks), an MNE .elc or EEGLAB .sfp file, a 10-05
      name list, the layout CSV, a design JSON, or a 64-channel balanced search run. Head-frame,
      .elc and .sfp coordinates are registered onto Ernie's scalp by their landmarks.
      --regions assigns balanced spatial regions to files without a region column;
      --unit gives the unit of an .sfp file, which declares none.

  eeglayoutlab export DESIGN_OR_SEARCH_RUN.json --format bids|mni|mne|eeglab|svg [--labels yes|no] --out-dir DIR
      Write BIDS/MNI/MNE/EEGLAB coordinate files or the 2D layout figure (SVG, English text;
      --labels yes|no, by default names are hidden where they would overlap) from a design JSON
      or any completed 8–64 channel (balanced or adaptive) search result JSON.

  eeglayoutlab evaluate REQUEST.json... --out-dir DIR
  eeglayoutlab evaluate --design DESIGN.json --radius 6 --seed 42
      [--action evaluate|perturb] [--noise iid|spatial_10|spatial_20|spatial_40|brain_background]
      [--conductivity skull_x0.5|skull_x2] [--head HEAD_ID] [--robustness standard/1]
      [--data-prior PRIOR.json] --out-dir DIR
      Score fixed coordinates, as /api/design-evaluation does. --robustness adds electrode
      dropout, unequal electrode noise and cap re-placement (evaluate on Ernie only).
      --data-prior applies a prior from the prior command (replaces --noise; Ernie only).

  eeglayoutlab search REQUEST.json... [--data-prior PRIOR.json] --out-dir DIR
  eeglayoutlab search --regions 1|2|3|4|6 --radius MM --mode whole_surface|low_hair|preset
      [--masks CODE,...] [--electrodes 8|12|16|24|32|48|64] [--allocation balanced|adaptive]
      [--objective default|composite]
      [--noise iid|spatial_10|spatial_20|spatial_40|brain_background]
      [--data-prior PRIOR.json] --out-dir DIR
      Search a layout for a region count and radius, as /api/local-compute does.

  eeglayoutlab eeg-summary RECORDING... [--band 1,40] [--epoch 2] [--label TEXT] --out-dir DIR
      Covariance summary of recorded EEG (EDF/EDF+C, BDF, BrainVision .vhdr, EEGLAB .set):
      10-05 channels on Ernie, band-pass and notch, average reference, artifact epochs removed.
      Only the summary leaves this step; the recording is read in place.

  eeglayoutlab prior SUMMARY.json|DIR... --out PRIOR.json
      Fit region source power and noise structure to summaries, with leave-one-out shrinkage
      toward the area prior when there are three or more.

  eeglayoutlab channels SUMMARY.json|DIR... [--test FILE,...|DIR] [--prior PRIOR.json]
      [--counts 8,16,24,32] [--draws 200] [--seed 1] [--figure FIGURE.svg] --out SUBSET.json
      Choose channel subsets that best reconstruct all recorded channels: greedy on the data,
      greedy on the prior's model (with --prior), the 10-20 subset and random subsets,
      scored on the training summaries and on held-out --test summaries. --figure also writes
      the error against subset size as an SVG figure.

  eeglayoutlab pareto RUN.result.json... [--objectives LIST] --out PARETO.json
      Rank evaluate and search results by Pareto dominance. LIST is comma-separated from
      field, sensitivity, localization, p90, area, dropout, impedance, replacement
      (default field,sensitivity,localization). All inputs must share one evaluation condition.

  eeglayoutlab study STUDY.json --out-dir DIR
      Run every case of a robustness study (noise_seeds, grid_displacements or heads)
      and write the same per-case summaries and aggregation as the web study page.

  Options: --root DIR (scientific root; default EEG_REPOSITORY_ROOT, checkout, or installed root)
           --python PATH (default: service interpreter rule; search uses --python/EEG_COMPUTE_PYTHON/managed/env)
"""


def add_commands(commands: Any) -> None:
    """Registers scientific and example subcommands on the top-level ``argparse`` subparsers for ``--help``."""
    commands.add_parser('help', help='show command-line usage')
    design = commands.add_parser('design', help='build an electrode design JSON from coordinate files')
    design.add_argument('files', nargs='*', metavar='FILE')
    design.add_argument('--name', metavar='NAME')
    design.add_argument('--regions', metavar='1|2|3|4|6')
    design.add_argument('--unit', metavar='mm|cm|m')
    design.add_argument('--root', metavar='DIR')
    design.add_argument('--out', metavar='DESIGN.json')

    export = commands.add_parser('export', help='export BIDS, MNI, MNE, EEGLAB or SVG layout files')
    export.add_argument('design_file', nargs='?', metavar='DESIGN_OR_RUN.json')
    export.add_argument('--format', metavar='bids|mni|mne|eeglab|svg')
    export.add_argument('--labels', metavar='yes|no')
    export.add_argument('--root', metavar='DIR')
    export.add_argument('--out-dir', metavar='DIR')

    evaluate = commands.add_parser('evaluate', help='score fixed electrode coordinates')
    evaluate.add_argument('files', nargs='*', metavar='REQUEST.json')
    evaluate.add_argument('--design', metavar='DESIGN.json')
    evaluate.add_argument('--radius', metavar='MM')
    evaluate.add_argument('--seed', metavar='N')
    evaluate.add_argument('--action', metavar='evaluate|perturb')
    evaluate.add_argument('--noise', metavar='PRESET')
    evaluate.add_argument('--conductivity', metavar='SCENARIO')
    evaluate.add_argument('--head', metavar='HEAD_ID')
    evaluate.add_argument('--robustness', metavar='standard/1')
    evaluate.add_argument('--data-prior', metavar='PRIOR.json')
    evaluate.add_argument('--root', metavar='DIR')
    evaluate.add_argument('--python', metavar='PATH')
    evaluate.add_argument('--out-dir', metavar='DIR')

    search = commands.add_parser('search', help='search a compact layout for a region count and radius')
    search.add_argument('files', nargs='*', metavar='REQUEST.json')
    search.add_argument('--regions', metavar='1|2|3|4|6')
    search.add_argument('--radius', metavar='MM')
    search.add_argument('--mode', metavar='whole_surface|low_hair|preset')
    search.add_argument('--masks', metavar='CODE,...')
    search.add_argument('--electrodes', metavar='8|12|16|24|32|48|64')
    search.add_argument('--allocation', metavar='balanced|adaptive')
    search.add_argument('--objective', metavar='OBJECTIVE')
    search.add_argument('--noise', metavar='PRESET')
    search.add_argument('--data-prior', metavar='PRIOR.json')
    search.add_argument('--root', metavar='DIR')
    search.add_argument('--python', metavar='PATH')
    search.add_argument('--out-dir', metavar='DIR')

    eeg_sum = commands.add_parser('eeg-summary', help='compute covariance summary from recorded EEG files')
    eeg_sum.add_argument('files', nargs='*', metavar='RECORDING')
    eeg_sum.add_argument('--band', metavar='LO,HI')
    eeg_sum.add_argument('--epoch', metavar='SECONDS')
    eeg_sum.add_argument('--label', metavar='TEXT')
    eeg_sum.add_argument('--root', metavar='DIR')
    eeg_sum.add_argument('--python', metavar='PATH')
    eeg_sum.add_argument('--out-dir', metavar='DIR')

    prior = commands.add_parser('prior', help='fit empirical data prior from covariance summaries')
    prior.add_argument('files', nargs='*', metavar='SUMMARY.json|DIR')
    prior.add_argument('--root', metavar='DIR')
    prior.add_argument('--python', metavar='PATH')
    prior.add_argument('--out', metavar='PRIOR.json')

    channels = commands.add_parser('channels', help='select and evaluate channel subsets from covariance summaries')
    channels.add_argument('files', nargs='*', metavar='SUMMARY.json|DIR')
    channels.add_argument('--test', metavar='FILE,...|DIR')
    channels.add_argument('--prior', metavar='PRIOR.json')
    channels.add_argument('--counts', metavar='8,16,24,32')
    channels.add_argument('--draws', metavar='N')
    channels.add_argument('--seed', metavar='N')
    channels.add_argument('--figure', metavar='FIGURE.svg')
    channels.add_argument('--out', metavar='SUBSET.json')

    pareto = commands.add_parser('pareto', help='rank evaluate and search results by Pareto dominance')
    pareto.add_argument('files', nargs='*', metavar='RUN.result.json')
    pareto.add_argument('--objectives', metavar='LIST')
    pareto.add_argument('--out', metavar='PARETO.json')

    study = commands.add_parser('study', help='run all cases of a robustness study')
    study.add_argument('files', nargs='*', metavar='STUDY.json')
    study.add_argument('--root', metavar='DIR')
    study.add_argument('--python', metavar='PATH')
    study.add_argument('--out-dir', metavar='DIR')

    examples = commands.add_parser('examples', help='run reproducible command-line examples')
    ex_sub = examples.add_subparsers(dest='examples_command', required=True, metavar='ACTION')
    ex_run = ex_sub.add_parser('run', help='run the examples and compare scores with expected.json')
    ex_run.add_argument('--root', metavar='DIR')
    ex_run.add_argument('--out-dir', metavar='DIR')
    ex_run.add_argument('--python', metavar='PATH')
    ex_run.add_argument('--skip-cross-head', action='store_true')
    ex_run.add_argument('--update-expected', action='store_true')


def parse_science_args(argv: Sequence[str]) -> tuple[Optional[str], list[str], dict[str, str]]:
    """``parseArgs(argv)`` from ``webapp/scripts/eeglayoutlab.mjs``: every ``--option`` takes one value."""
    if not argv:
        return None, [], {}
    command = argv[0]
    rest = list(argv[1:])
    files: list[str] = []
    options: dict[str, str] = {}
    index = 0
    while index < len(rest):
        value = rest[index]
        if not value.startswith('--'):
            files.append(value)
            index += 1
            continue
        name = value[2:]
        nxt = rest[index + 1] if index + 1 < len(rest) else None
        if nxt is None or nxt.startswith('--'):
            raise ValueError(f'--{name} needs a value')
        options[name] = nxt
        index += 2
    allowed = _ALLOWED_OPTIONS.get(command)
    if allowed is not None:
        unknown = next((key for key in options if key not in allowed), None)
        if unknown is not None:
            raise ValueError(f'unknown option --{unknown}')
    return command, files, options


def read_json(path: str) -> Any:
    return jsjson.parse(Path(path).read_text(encoding='utf-8'))


def write_json(path: str, value: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(jsjson.stringify(value, indent=2) + '\n', encoding='utf-8')


def stem(path: str) -> str:
    return re.sub(r'\.json$', '', os.path.basename(path), flags=re.IGNORECASE)


def summary_files(paths: Sequence[str]) -> list[str]:
    """``summaryFiles(paths)`` from ``webapp/scripts/eeglayoutlab.mjs``."""
    resolved: list[str] = []
    for path in paths:
        st = os.stat(path)
        if not statmod.S_ISDIR(st.st_mode):
            resolved.append(nodepath.resolve(path))
            continue
        names = nodepath.js_sort([name for name in os.listdir(path) if name.endswith('.json')])
        for name in names:
            candidate = nodepath.resolve(path, name)
            try:
                val = read_json(candidate)
                if isinstance(val, dict) and val.get('schema') == SUMMARY_SCHEMA:
                    resolved.append(candidate)
            except Exception:  # noqa: BLE001 - matches JS try/catch filter
                pass
    return resolved


def _trim_start(text: str) -> str:
    i = 0
    while i < len(text) and text[i] in jsjson.JS_TRIM:
        i += 1
    return text[i:]


def _resolved_root(explicit: Optional[str]) -> str:
    return repository_root(nodepath.resolve(explicit) if explicit else None)


def _exportable_layout(raw: Any) -> tuple[dict[str, Any], bool, str]:
    """Validates either a 64-point ``eeg-electrode-design/1`` or a completed 8–64-channel ``radius-search`` run."""
    if isinstance(raw, dict) and raw.get('schema') == RUN_SCHEMA and raw.get('service') == 'radius-search':
        request = raw.get('request') if isinstance(raw.get('request'), dict) else {}
        result = raw.get('result') if isinstance(raw.get('result'), dict) else {}
        if result.get('status') != 'completed':
            raise ValueError('the search found no layout')
        layout = result.get('layout') if isinstance(result.get('layout'), dict) else {}
        xyz_mm = layout.get('xyzMm')
        region_indices = layout.get('regionIndices')
        plot = validate_layout_plot({'xyz_mm': xyz_mm, 'region_indices': region_indices})
        total = len(plot['xyz_mm'])
        if total not in _SEARCH_ELECTRODE_COUNTS:
            raise ValueError('search layout electrode count must be 8, 12, 16, 24, 32, 48 or 64')
        reg_num = request.get('region_count')
        if not jsjson.is_integer(reg_num):
            raise ValueError('search request is missing region_count')
        r = int(float(reg_num))
        regs = [int(float(v)) for v in plot['region_indices']]
        if len(set(regs)) != r:
            raise ValueError('search layout region indices do not match request region_count')
        counts = [regs.count(k) for k in range(r)]
        is_adaptive = request.get('allocation_mode') == 'adaptive'
        if is_adaptive:
            if r < 2 or any(c < 4 for c in counts):
                raise ValueError('adaptive search layout requires at least 2 regions and 4 electrodes per region')
        else:
            if total < 2 * r:
                raise ValueError('balanced search layout requires at least 2 electrodes per region')
            expected = [total // r + (1 if k < total % r else 0) for k in range(r)]
            if sorted(counts, reverse=True) != expected:
                raise ValueError('balanced search layout region counts must split evenly')
        reg_str = jsjson.number_to_string(request['region_count'])
        rad_str = jsjson.number_to_string(request['radius_mm'])
        mode_str = str(request.get('mode', ''))
        doc: dict[str, Any] = {
            'schema': 'eeg-electrode-design/1',
            'coordinate_system': 'ernie_native_mm',
            'unit': 'mm',
            'name': f'search {reg_str} regions, {rad_str} mm, {mode_str}'[:100],
            'xyz_mm': [[float(v) for v in pt] for pt in plot['xyz_mm']],
            'region_indices': regs,
        }
        if total == 64 and not is_adaptive:
            return validate_design(doc), True, REGION_DESCRIPTION
        return doc, False, _SPARSE_REGION_DESCRIPTION
    return validate_design(raw), True, REGION_DESCRIPTION


def design_from(files: Sequence[str], options: dict[str, str]) -> dict[str, Any]:
    """``designFrom(files, options)`` from ``webapp/scripts/eeglayoutlab.mjs``."""
    root = _resolved_root(options.get('root'))

    def read(path: str) -> dict[str, str]:
        return {'name': os.path.basename(path), 'text': Path(path).read_text(encoding='utf-8')}

    def named(design: dict[str, Any]) -> dict[str, Any]:
        return validate_design({**design, 'name': options['name']} if options.get('name') else design)

    region_count: Optional[int] = None
    if 'regions' in options:
        parsed_regions = jsmath.js_number(options['regions'])
        if parsed_regions not in (1.0, 2.0, 3.0, 4.0, 6.0):
            raise ValueError('--regions must be 1, 2, 3, 4 or 6')
        region_count = int(parsed_regions)
    unit = options.get('unit')
    if unit is not None and unit not in ('mm', 'cm', 'm'):
        raise ValueError('--unit must be mm, cm or m')

    if len(files) == 1 and re.search(r'\.(elc|sfp)$', files[0], re.IGNORECASE):
        surface = verified_surface(root=root)
        return named(parse_montage_file(read(files[0]), surface, region_count=region_count, unit=unit, root=root))

    if len(files) == 1:
        file = read(files[0])
        trimmed = _trim_start(file['text'])
        if trimmed.startswith('{'):
            value = jsjson.parse(trimmed)
            if isinstance(value, dict) and value.get('schema') == RUN_SCHEMA and value.get('service') == 'radius-search':
                request = value.get('request') or {}
                result = value.get('result') or {}
                if result.get('status') != 'completed':
                    raise ValueError('the search found no layout')
                reg_str = jsjson.number_to_string(request['region_count'])
                rad_str = jsjson.number_to_string(request['radius_mm'])
                return named({
                    'schema': 'eeg-electrode-design/1',
                    'coordinate_system': 'ernie_native_mm',
                    'unit': 'mm',
                    'name': f"search {reg_str} regions, {rad_str} mm, {request['mode']}",
                    'xyz_mm': result['layout']['xyzMm'],
                    'region_indices': result['layout']['regionIndices'],
                })
            return named(parse_design(file['text']))
        if trimmed.startswith('#'):
            return named(parse_design(file['text'], stem(files[0])))
        return named(parse_electrode_labels(file, region_count=region_count, root=root))

    coordinate_files = [read(path) for path in files]
    if not bids_needs_mni_surface(coordinate_files):
        return named(parse_bids_electrodes(coordinate_files, None, region_count=region_count, root=root))
    return named(parse_bids_electrodes(coordinate_files, verified_surface(root=root),
                                       region_count=region_count, root=root))


def export_files(
    path: str,
    fmt: str,
    labels: Optional[str] = None,
    *,
    root_option: Optional[str] = None,
) -> list[dict[str, str]]:
    """``exportFiles(path, format, labels)`` supporting 64-point designs and 8–64-channel search runs (U15)."""
    design, is_strict_64, reg_desc = _exportable_layout(read_json(path))
    root = _resolved_root(root_option)
    if fmt == 'bids':
        return export_bids_electrodes(
            design,
            root=root,
            validate=is_strict_64,
            region_description=None if is_strict_64 else reg_desc,
        )
    if fmt == 'mni':
        return export_mni_bids_electrodes(
            design,
            verified_surface(root=root),
            validate=is_strict_64,
            region_description=None if is_strict_64 else reg_desc,
        )
    if fmt == 'mne':
        return [export_mne_elc(design, root=root, validate=is_strict_64)]
    if fmt == 'eeglab':
        return [export_eeglab_sfp(design, root=root, validate=is_strict_64)]
    if fmt == 'svg':
        count = max(design['region_indices']) + 1
        total = len(design['xyz_mm'])
        show_names = plot_figure_spacing(design, root=root) >= 16.0 if labels is None else (labels == 'yes')
        svg = plot_figure_svg(
            design,
            {
                'title': design['name'],
                'subtitle': f"{total} electrodes · {count} region{'s' if count > 1 else ''} · Ernie template head",
                'region': lambda index, *_rest: f'Region {index + 1}',
                'caption': [
                    'Head frame from the Ernie template landmarks NAS, LPA and RPA (x toward RPA, y toward NAS); '
                    'azimuthal equidistant projection by angle from the vertical axis.',
                    'The circle is the NAS–LPA–RPA plane; electrodes below it lie outside. Positions are design '
                    'positions on the template head, not measured positions.',
                ],
            },
            labels=show_names,
            root=root,
        )
        return [{'name': 'layout.svg', 'text': svg}]
    raise ValueError('--format must be bids, mni, mne, eeglab or svg')


def _csv_items(value: str) -> list[str]:
    return [trimmed for item in value.split(',') if (trimmed := jsjson.js_trim(item))]


def _run_channels(files: Sequence[str], options: dict[str, str]) -> int:
    if not files or not options.get('out'):
        raise ValueError('channels needs training summaries and --out')
    training = [read_json(p) for p in summary_files(files)]
    held = [read_json(p) for p in summary_files(_csv_items(options['test']))] if options.get('test') else []
    prior_val = read_json(options['prior']) if options.get('prior') else None
    counts_val = [jsmath.js_number(x) for x in _csv_items(options['counts'])] if options.get('counts') else None
    draws_val = jsmath.js_number(options['draws']) if 'draws' in options else None
    seed_val = jsmath.js_number(options['seed']) if 'seed' in options else None

    report = channel_subsets(
        training=training,
        test=held,
        prior=prior_val,
        counts=counts_val,
        draws=draws_val,
        seed=seed_val,
    )
    write_json(options['out'], report)

    if options.get('figure'):
        held_out = len(report['test']) > 0
        standard = report['standard_10_20']
        fig_path = Path(options['figure'])
        Path(nodepath.resolve(options['figure'])).parent.mkdir(parents=True, exist_ok=True)
        b0 = jsjson.number_to_string(float(report['band_hz'][0]))
        b1 = jsjson.number_to_string(float(report['band_hz'][1]))
        svg = channel_subset_figure_svg(
            report,
            {
                'title': 'Reconstruction error of channel subsets',
                'subtitle': ' · '.join([
                    'Mean held-out error' if held_out else 'Training error',
                    f"{len(report['universe'])} shared channels",
                    f'{b0}–{b1} Hz',
                ]),
                'xLabel': 'Channels in the subset',
                'yLabel': 'Unexplained variance (lower is better)',
                'names': {
                    'data': 'Greedy on the data',
                    'data_prior': 'Greedy on the data-prior model',
                    'area_prior': 'Greedy on the area-prior model',
                    'random': 'Random subsets, median and P10–P90',
                    'standard': f"10-20 system ({standard['count']})" if standard else '',
                },
                'channels': lambda count: f'{count} channels',
                'caption': [
                    'Error is the unexplained variance fraction of the average-referenced shared channels. '
                    'Each subset is recorded against one of its own channels; the reconstructor is fitted on '
                    'the training summaries.',
                    (
                        "Curves are the mean held-out error; the band is the P10–P90 of the random subsets' "
                        'mean held-out error over draws. The data-greedy curve includes the size of the 10-20 subset.'
                        if held_out
                        else 'Without held-out summaries the curves are training errors, optimistic for greedy '
                        "selection on the data; the band is the P10–P90 of the random subsets' training error."
                    ),
                ],
            },
        )
        fig_path.write_text(svg, encoding='utf-8')
        sys.stderr.write(f"wrote {options['figure']}\n")

    def cell(row: dict[str, Any]) -> str:
        base = jsmath.to_fixed(float(row['train_error']), 3)
        if row.get('test_error'):
            return f"{base}/{jsmath.to_fixed(float(row['test_error']['mean']), 3)}"
        return base

    method_keys = list(report['methods'].keys())
    method_vals = list(report['methods'].values())
    methods_hdr = '\t'.join(method_keys)
    sys.stdout.write(f'count\t{methods_hdr}\trandom median\n')
    for k, count in enumerate(report['counts']):
        m_cells = '\t'.join(cell(m['counts'][k]) for m in method_vals)
        r_row = report['random']['counts'][k]
        r_cell = jsmath.to_fixed(float(r_row['train_error']['median']), 3)
        if r_row.get('test_error_mean'):
            r_cell += f"/{jsmath.to_fixed(float(r_row['test_error_mean']['median']), 3)}"
        sys.stdout.write(f'{count}\t{m_cells}\t{r_cell}\n')

    standard = report['standard_10_20']
    if standard:
        extra = f"\tdata greedy {cell(standard['data_same_count'])}" if standard.get('data_same_count') else ''
        sys.stdout.write(f"10-20 ({standard['count']})\t{cell(standard)}{extra}\n")
    sys.stdout.flush()

    left_parts = [
        f'{cnt} {role} summaries lack a channel and were left out'
        for cnt, role in ((len(report['training_skipped']), 'training'), (len(report['test_skipped']), 'held-out'))
        if cnt
    ]
    left_str = f" ({'; '.join(left_parts)})" if left_parts else ''
    sys.stderr.write(
        f"wrote {options['out']}: {len(report['universe'])} channels, {len(report['training'])} training and "
        f"{len(report['test'])} held-out summaries{left_str}; errors are training/held-out\n"
    )
    sys.stderr.flush()
    return 0


def _error_exit(message: str) -> int:
    sys.stderr.write(f'error: {message}\n')
    sys.stderr.flush()
    return 2


def run_science(argv: Sequence[str]) -> int:
    """Runs any scientific command with Node's option grammar, output bytes and exit codes
    (0 ok, 1 batch/case failure, 2 usage/validation error)."""
    if not argv or argv[0] in ('help', '--help', '-h'):
        sys.stdout.write(HELP)
        sys.stdout.flush()
        return 0
    if len(argv) >= 2 and argv[1] in ('--help', '-h'):
        sys.stdout.write(HELP)
        sys.stdout.flush()
        return 0
    try:
        command, files, options = parse_science_args(argv)
        if command == 'design':
            if not files or not options.get('out'):
                raise ValueError('design needs input files and --out')
            design = design_from(files, options)
            write_json(options['out'], design)
            sys.stderr.write(f"wrote {options['out']} ({design['name']})\n")
            sys.stderr.flush()
            return 0

        if command == 'pareto':
            if len(files) < 2 or not options.get('out'):
                raise ValueError('pareto needs at least two result files and --out')
            report = pareto_cli_report([(f, read_json(f)) for f in files], options.get('objectives'))
            write_json(options['out'], report)
            for row in report['rows']:
                vals = '\t'.join(jsjson.number_to_string(float(row['values'][o])) for o in report['objectives'])
                sys.stdout.write(f"{row['rank']}\t{row['name']}\t{vals}\n")
            sys.stdout.flush()
            front_count = sum(1 for row in report['rows'] if row['rank'] == 1)
            sys.stderr.write(f"wrote {options['out']}: {front_count} of {len(report['rows'])} on the front\n")
            sys.stderr.flush()
            return 0

        if command == 'channels':
            return _run_channels(files, options)

        if command == 'prior':
            if not files or not options.get('out'):
                raise ValueError('prior needs summary files and --out')
            from . import run as cli_run
            return cli_run.execute('prior', files, options)

        if not options.get('out-dir'):
            raise ValueError(f'{command} needs --out-dir')

        if command == 'eeg-summary':
            if not files:
                raise ValueError('eeg-summary needs recording files')
            if 'label' in options and len(files) > 1:
                raise ValueError('--label applies to a single recording')
            names = [re.sub(r'\.(edf|bdf|rec|vhdr|set)$', '', os.path.basename(f), flags=re.IGNORECASE) for f in files]
            clash = next(
                (
                    name for k, name in enumerate(names)
                    if next(i for i, other in enumerate(names) if other.lower() == name.lower()) != k
                ),
                None,
            )
            if clash is not None:
                raise ValueError(
                    f'two recordings would both write {clash}.summary.json; run them into different --out-dir folders'
                )
            from . import run as cli_run
            return cli_run.execute('eeg-summary', files, options, recording_names=names)

        if command == 'export':
            if len(files) != 1 or not options.get('format'):
                raise ValueError('export takes one design file and --format')
            labels = options.get('labels')
            if labels is not None and labels not in ('yes', 'no'):
                raise ValueError('--labels must be yes or no')
            out_dir = Path(options['out-dir'])
            for item in export_files(files[0], options['format'], labels, root_option=options.get('root')):
                out_dir.mkdir(parents=True, exist_ok=True)
                target = nodepath.join(options['out-dir'], item['name'])
                Path(target).write_text(item['text'], encoding='utf-8')
                sys.stderr.write(f'wrote {target}\n')
            sys.stderr.flush()
            return 0

        if command not in ('evaluate', 'search', 'study'):
            raise ValueError(f'unknown command {command}\n\n{HELP}')
        if command == 'study' and len(files) != 1:
            raise ValueError('study takes one study file')
        if command == 'evaluate' and not files and not options.get('design'):
            raise ValueError('evaluate needs request files or --design')
        if command == 'search':
            has_inline_search = any(k in options for k in SEARCH_INLINE_OPTIONS)
            if files and has_inline_search:
                raise ValueError('search takes either request files or inline options, not both')
            if not files and not has_inline_search:
                raise ValueError('search needs request files')

        from . import run as cli_run
        return cli_run.execute(command, files, options)
    except OSError as error:
        from ..jobs.records import node_message
        return _error_exit(node_message(error))
    except Exception as error:  # noqa: BLE001 - Node CLI catches every rejection as exit 2 + error: <msg>
        msg = getattr(error, 'message', None)
        text = msg if isinstance(msg, str) and msg else str(error)
        return _error_exit(text)
