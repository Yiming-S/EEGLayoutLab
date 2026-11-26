"""``eeglayoutlab examples run [--root DIR] [--out-dir DIR] [--skip-cross-head] [--update-expected]``
(``examples/run-examples.mjs``, phase 3 slice 7; decision U14).

Runs the 13 reproducible example steps in process and compares their 24 scores against ``R/examples/expected.json``
within ``1e-6``. In a checkout the default output directory is ``R/examples/outputs``; in the installed form it is
``./eeglayoutlab-examples`` and any ``--out-dir`` inside ``R`` (or ``--update-expected``) is refused with exit 2.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Any, Optional, Sequence

from ..jobs import nodepath
from ..jobs.runtime import checkout_root, installed_form, repository_root
from ..schemas import jsjson
from . import science as science_cli

__all__ = ['TOLERANCE', 'EXPECTED_SCHEMA', 'run_examples_cli', 'run_examples']

TOLERANCE = 1e-6
EXPECTED_SCHEMA = 'eeglayoutlab-examples-expected/1'
_EVALUATION_KEYS = ('field_relative', 'sensitivity_tail', 'localization_relative', 'median_mm', 'p90_mm')
_SEARCH_KEYS = ('field_relative', 'sensitivity_tail', 'localization_relative', 'conditional_global')


def _error_exit(message: str) -> int:
    sys.stderr.write(f'error: {message}\n')
    sys.stderr.flush()
    return 2


def _pick(mapping: dict[str, Any], keys: Sequence[str]) -> dict[str, Any]:
    return {key: mapping.get(key) for key in keys}


def _evaluation_scores(path: str) -> dict[str, Any]:
    nominal = science_cli.read_json(path)['result']['nominal']
    return _pick(nominal, _EVALUATION_KEYS)


def _inside_root(candidate: str, root: str) -> bool:
    real_candidate = os.path.realpath(candidate)
    real_root = os.path.realpath(root)
    return real_candidate == real_root or real_candidate.startswith(real_root + os.sep)


def _fmt_value(value: Any) -> str:
    if jsjson.is_number(value):
        return jsjson.number_to_string(jsjson.to_number(value))
    if value is None:
        return 'undefined'
    return str(value)


def run_examples(
    *,
    explicit_root: Optional[str] = None,
    explicit_out_dir: Optional[str] = None,
    python_override: Optional[str] = None,
    skip_cross_head: bool = False,
    update_expected: bool = False,
) -> int:
    try:
        root = repository_root(nodepath.resolve(explicit_root) if explicit_root else None)
    except ValueError as error:
        return _error_exit(str(error))

    in_checkout = checkout_root() is not None and not installed_form(root)
    if update_expected and not in_checkout:
        return _error_exit('--update-expected is only available in a source checkout')

    examples_dir = nodepath.join(root, 'examples')
    if not os.path.isdir(examples_dir):
        return _error_exit(f'{examples_dir} does not exist')

    if explicit_out_dir:
        out_dir = nodepath.resolve(explicit_out_dir)
    elif in_checkout:
        out_dir = nodepath.join(examples_dir, 'outputs')
    else:
        out_dir = nodepath.resolve('eeglayoutlab-examples')

    if not in_checkout and _inside_root(out_dir, root):
        return _error_exit(
            f'output directory {out_dir} is inside the installed scientific root {os.path.realpath(root)}; '
            'choose an --out-dir outside the environment'
        )

    def ex(name: str) -> str:
        return nodepath.join(out_dir, name)

    def run_step(*parameters: str) -> None:
        cmd = list(parameters)
        cmd.extend(['--root', root])
        if python_override and parameters[0] in ('evaluate', 'search', 'study'):
            cmd.extend(['--python', python_override])
        print(f"$ eeglayoutlab {' '.join(cmd)}", flush=True)
        status = science_cli.run_science(cmd)
        if status != 0:
            raise RuntimeError(f'command failed: {parameters[0]}')

    try:
        scores: dict[str, Any] = {}

        # 1. Standard 64-electrode reference from its 10-05 names: exports and nominal evaluation.
        ex1 = ex('01-standard64')
        design1 = nodepath.join(ex1, 'design.json')
        run_step(
            'design', nodepath.join(examples_dir, '01-standard64/standard64-labels.tsv'),
            '--name', 'standard64', '--out', design1,
        )
        for fmt in ('bids', 'mne', 'eeglab', 'svg'):
            run_step('export', design1, '--format', fmt, '--out-dir', nodepath.join(ex1, 'files'))
        run_step('evaluate', '--design', design1, '--radius', '6', '--seed', '42', '--out-dir', ex1)
        scores['01-standard64'] = _evaluation_scores(nodepath.join(ex1, 'request.result.json'))

        # 2. Compact two-region layout from a radius search, then evaluated as fixed coordinates.
        ex2 = ex('02-compact-search')
        search_result_path = nodepath.join(ex2, 'search.result.json')
        design2 = nodepath.join(ex2, 'design.json')
        run_step('search', nodepath.join(examples_dir, '02-compact-search/search.json'), '--out-dir', ex2)
        search_res = science_cli.read_json(search_result_path)['result']
        run_step('design', search_result_path, '--name', 'compact 2 regions 30 mm', '--out', design2)
        run_step('export', design2, '--format', 'svg', '--out-dir', nodepath.join(ex2, 'files'))
        run_step('evaluate', '--design', design2, '--radius', '6', '--seed', '42', '--out-dir', ex2)
        scores['02-compact-search'] = {
            'search': {
                **_pick(search_res['metrics'], _SEARCH_KEYS),
                'union_area_cm2': search_res['geometry']['union_area_cm2'],
            },
            'evaluation': _evaluation_scores(nodepath.join(ex2, 'request.result.json')),
        }

        # 3. Same compact layout across eleven heads (one shared noise seed).
        heads = science_cli.read_json(nodepath.join(examples_dir, '03-cross-head/heads.json'))
        missing = [
            entry['head_id']
            for entry in heads['cases']
            if not os.path.exists(nodepath.join(root, 'results/v2/heads', entry['head_id'], 'table.json'))
        ]
        not_run: dict[str, str] = {}
        if skip_cross_head:
            not_run['03-cross-head'] = 'skipped with --skip-cross-head'
        elif missing:
            not_run['03-cross-head'] = f"head packages without a published table: {', '.join(missing)}"

        if '03-cross-head' in not_run:
            print(f"\nExample 3 not run: {not_run['03-cross-head']}", flush=True)
        else:
            ex3 = ex('03-cross-head')
            study_file = nodepath.join(ex3, 'study-input.json')
            Path(ex3).mkdir(parents=True, exist_ok=True)
            Path(study_file).write_text(
                jsjson.stringify({**heads, 'design': science_cli.read_json(design2)}, indent=2) + '\n',
                encoding='utf-8',
            )
            run_step('study', study_file, '--out-dir', ex3)
            aggregation = science_cli.read_json(nodepath.join(ex3, 'study.json'))['aggregation']
            group = aggregation['groups'][0]
            scores['03-cross-head'] = {
                'completed_cases': aggregation['completed_cases'],
                'field_relative': group['nominal']['field_relative'],
                'localization_relative': group['nominal']['localization_relative'],
            }
    except Exception as error:  # noqa: BLE001
        return _error_exit(str(error))

    expected_path = nodepath.join(examples_dir, 'expected.json')
    if update_expected and not_run:
        sys.stderr.write(f"\n--update-expected needs every example; not run: {', '.join(not_run)}\n")
        sys.stderr.flush()
        return 1
    if update_expected:
        Path(expected_path).write_text(
            jsjson.stringify(
                {'schema': EXPECTED_SCHEMA, 'tolerance': TOLERANCE, 'scores': scores},
                indent=2,
            ) + '\n',
            encoding='utf-8',
        )
        print(f'\nwrote {expected_path}', flush=True)
        return 0

    expected = science_cli.read_json(expected_path)['scores']
    differences: list[str] = []

    def compare(want: Any, got: Any, path: str) -> None:
        if jsjson.is_number(want):
            want_f = jsjson.to_number(want)
            if not jsjson.is_number(got) or abs(want_f - jsjson.to_number(got)) > TOLERANCE:
                differences.append(f'{path}: expected {_fmt_value(want)}, got {_fmt_value(got)}')
        elif isinstance(want, dict):
            for key in want:
                sub = got.get(key) if isinstance(got, dict) else None
                compare(want[key], sub, f'{path}.{key}')

    skipped: list[str] = []
    for name in expected:
        if name in scores:
            compare(expected[name], scores[name], name)
        elif name in not_run and skip_cross_head:
            skipped.append(name)
        else:
            differences.append(f"{name}: not run ({not_run.get(name, 'no scores')})")

    compared = len(expected) - len(skipped)
    tol_str = jsjson.number_to_string(TOLERANCE)
    if differences:
        print(f'\n{len(differences)} differences:\n' + '\n'.join(differences), flush=True)
        return 1
    suffix = f" Not compared: {', '.join(skipped)}." if skipped else ''
    print(f'\nAll scores of {compared} of {len(expected)} examples match expected.json within {tol_str}.{suffix}',
          flush=True)
    return 0


def run_examples_cli(args: argparse.Namespace) -> int:
    return run_examples(
        explicit_root=args.root,
        explicit_out_dir=args.out_dir,
        python_override=getattr(args, 'python', None),
        skip_cross_head=bool(args.skip_cross_head),
        update_expected=bool(args.update_expected),
    )
