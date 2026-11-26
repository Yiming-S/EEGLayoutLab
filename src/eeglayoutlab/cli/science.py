"""Scientific command-line subcommands: ``design``, ``export``, ``evaluate``, ``search`` and ``study``
(``webapp/scripts/eeglayoutlab.mjs``, phase 3 slices 4-6 & 13; decisions U5, U8, U10, U11, U13).

No ``json`` stdlib import: all JSON parsing, formatting and hashing go through ``eeglayoutlab.schemas.jsjson`` so
written files and keys are byte-identical to the Node reference CLI. Pydantic and job modules are imported only
when ``evaluate``, ``search`` or ``study`` runs.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import sys
from typing import Any, Optional, Sequence

from ..core import jsmath
from ..core.bids import (
    bids_needs_mni_surface, export_bids_electrodes, export_mni_bids_electrodes,
    parse_bids_electrodes, parse_electrode_labels,
)
from ..core.design_file import parse_design, validate_design
from ..core.ernie_mni import verified_surface
from ..core.montage import export_eeglab_sfp, export_mne_elc, parse_montage_file
from ..figures.layout import figure_spacing, layout_figure_svg
from ..jobs import nodepath
from ..jobs.runtime import repository_root
from ..schemas import jsjson

__all__ = [
    'RUN_SCHEMA', 'HELP', 'SCIENCE_COMMANDS', 'add_commands', 'parse_science_args',
    'read_json', 'write_json', 'stem', 'design_from', 'export_files', 'run_science',
]

RUN_SCHEMA = 'eeglayoutlab-cli-run/1'
SCIENCE_COMMANDS = frozenset({'design', 'export', 'evaluate', 'search', 'study', 'help'})

_ALLOWED_OPTIONS: dict[str, frozenset[str]] = {
    'design': frozenset({'name', 'regions', 'unit', 'out', 'root'}),
    'export': frozenset({'format', 'labels', 'out-dir', 'root'}),
    'evaluate': frozenset({
        'design', 'radius', 'seed', 'action', 'noise', 'conductivity', 'head',
        'robustness', 'data-prior', 'out-dir', 'root', 'python',
    }),
    'search': frozenset({'data-prior', 'out-dir', 'root', 'python'}),
    'study': frozenset({'out-dir', 'root', 'python'}),
}

HELP = """EEGLayoutLab command line

  eeglayoutlab serve [WORKSPACE] [--root DIR] [--port N] [--no-browser] [--cache-only]
      Start the local web application on 127.0.0.1 for a workspace.

  eeglayoutlab data list | verify [NAME ...] | install [NAME ...] | compose [NAME ...] | remove NAME
      Manage verified scientific data packages in the user data directory.

  eeglayoutlab examples run [--root DIR] [--out-dir DIR] [--skip-cross-head] [--update-expected]
      Run the reproducible command-line examples and compare scores against examples/expected.json.

  eeglayoutlab design FILE... [--name NAME] [--regions 1|2|3|4|6] [--unit mm|cm|m] --out DESIGN.json
      Build a design from coordinate files: a BIDS pair (Ernie native, MNI, or a head frame
      such as CapTrak with NAS/LPA/RPA landmarks), an MNE .elc or EEGLAB .sfp file, a 10-05
      name list, the layout CSV, a design JSON, or a search run from this tool. Head-frame,
      .elc and .sfp coordinates are registered onto Ernie's scalp by their landmarks.
      --regions assigns balanced spatial regions to files without a region column;
      --unit gives the unit of an .sfp file, which declares none.

  eeglayoutlab export DESIGN.json --format bids|mni|mne|eeglab|svg [--labels yes|no] --out-dir DIR
      Write the web page's coordinate files or the layout figure (SVG, English text;
      --labels yes|no, by default names are hidden where they would overlap).

  eeglayoutlab evaluate REQUEST.json... --out-dir DIR
  eeglayoutlab evaluate --design DESIGN.json --radius 6 --seed 42
      [--action evaluate|perturb] [--noise iid|spatial_10|spatial_20|spatial_40|brain_background]
      [--conductivity skull_x0.5|skull_x2] [--head HEAD_ID] [--robustness standard/1]
      [--data-prior PRIOR.json] --out-dir DIR
      Score fixed coordinates, as /api/design-evaluation does. --robustness adds electrode
      dropout, unequal electrode noise and cap re-placement (evaluate on Ernie only).
      --data-prior applies a prior from the prior command (replaces --noise; Ernie only).

  eeglayoutlab search REQUEST.json... [--data-prior PRIOR.json] --out-dir DIR
      Search a layout for a region count and radius, as /api/local-compute does.

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
    export.add_argument('design_file', nargs='?', metavar='DESIGN.json')
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
    search.add_argument('--data-prior', metavar='PRIOR.json')
    search.add_argument('--root', metavar='DIR')
    search.add_argument('--python', metavar='PATH')
    search.add_argument('--out-dir', metavar='DIR')

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


def _trim_start(text: str) -> str:
    i = 0
    while i < len(text) and text[i] in jsjson.JS_TRIM:
        i += 1
    return text[i:]


def _resolved_root(explicit: Optional[str]) -> str:
    return repository_root(nodepath.resolve(explicit) if explicit else None)


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
    """``exportFiles(path, format, labels)`` from ``webapp/scripts/eeglayoutlab.mjs``."""
    design = validate_design(read_json(path))
    root = _resolved_root(root_option)
    if fmt == 'bids':
        return export_bids_electrodes(design, root=root)
    if fmt == 'mni':
        return export_mni_bids_electrodes(design, verified_surface(root=root))
    if fmt == 'mne':
        return [export_mne_elc(design, root=root)]
    if fmt == 'eeglab':
        return [export_eeglab_sfp(design, root=root)]
    if fmt == 'svg':
        count = max(design['region_indices']) + 1
        show_names = figure_spacing(design, root=root) >= 16.0 if labels is None else (labels == 'yes')
        svg = layout_figure_svg(
            design,
            {
                'title': design['name'],
                'subtitle': f"64 electrodes · {count} region{'s' if count > 1 else ''} · Ernie template head",
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


def _error_exit(message: str) -> int:
    sys.stderr.write(f'error: {message}\n')
    sys.stderr.flush()
    return 2


def run_science(argv: Sequence[str]) -> int:
    """Runs a scientific command (``design``, ``export``, ``evaluate``, ``search``, ``study``, ``help``) with Node's
    option grammar, output bytes and exit codes (0 ok, 1 batch/case failure, 2 usage/validation error)."""
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

        if not options.get('out-dir'):
            raise ValueError(f'{command} needs --out-dir')

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
        if command != 'study' and not files and not (command == 'evaluate' and options.get('design')):
            suffix = ' or --design' if command == 'evaluate' else ''
            raise ValueError(f'{command} needs request files{suffix}')

        from . import run as cli_run
        return cli_run.execute(command, files, options)
    except Exception as error:  # noqa: BLE001 - Node CLI catches every rejection as exit 2 + error: <msg>
        msg = getattr(error, 'message', None)
        text = msg if isinstance(msg, str) and msg else str(error)
        return _error_exit(text)
