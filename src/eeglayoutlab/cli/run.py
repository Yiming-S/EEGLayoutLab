"""Worker-running scientific CLI commands: ``evaluate``, ``search`` and ``study`` (phase 3 slice 6; U8, U10, U11, U15).

Follows ``webapp/scripts/eeglayoutlab.mjs`` statement by statement while using ``jobs.runtime.runtime_config``'s
service interpreter rule (U8): ``search`` runs and fingerprints ``config.python`` (``--python``, else
``EEG_COMPUTE_PYTHON``, else managed runtime, else installed ``P/bin/python``, else ``python3``); ``evaluate`` and
``study`` use ``config.native_python``. Writes no service records, queue files or workspace state (U10), and never
imports Python's stdlib ``json`` (B21).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import importlib.util
import math
import os
import sys
from typing import Any, Optional, Sequence

from ..core import jsmath
from ..jobs import nodepath
from ..jobs.annotations import design_submission
from ..jobs.design_result import normalize_design_request, validate_design_result
from ..jobs.fingerprint import runtime_identity
from ..jobs.identity import UNDEFINED, JSTypeError, _js_string, _member, _same, design_context, js_truthy, request_key, to_number
from ..jobs.integrity import InputIntegrity
from ..jobs.radius import code_identity, normalize_request, radius_identity, validate_worker_result
from ..jobs.records import node_message
from ..jobs.runtime import installed_environment, repository_root, runtime_config
from ..jobs.studies import aggregate_study, normalize_study_input, summarize_study_case
from ..jobs.worker import WorkerError, start_worker
from ..schemas import jsjson
from .science import RUN_SCHEMA, read_json, stem, write_json

__all__ = [
    'STUDY_SCHEMA', 'CliEnvironment', 'build_environment', 'run_worker_sync',
    'with_data_prior', 'request_from_options', 'search_request_from_options',
    'evaluate_one', 'search_one', 'run_study', 'execute',
]

STUDY_SCHEMA = 'eeglayoutlab-cli-study/1'
MAX_CLI_OUTPUT_BYTES = 8 * 1024 * 1024

_NOISE_PRESETS: dict[str, Optional[dict[str, Any]]] = {
    'iid': None,
    'spatial_10': {'kind': 'spatial', 'rho': 0.5, 'length_mm': 10},
    'spatial_20': {'kind': 'spatial', 'rho': 0.5, 'length_mm': 20},
    'spatial_40': {'kind': 'spatial', 'rho': 0.5, 'length_mm': 40},
    'brain_background': {'kind': 'brain_background', 'fraction': 0.5},
}


@dataclass(frozen=True)
class CliEnvironment:
    root: str
    python: str
    inputs: InputIntegrity


def _error_text(error: BaseException) -> str:
    if isinstance(error, OSError):
        return node_message(error)
    msg = getattr(error, 'message', None)
    return msg if isinstance(msg, str) and msg else str(error)


def build_environment(command: str, options: dict[str, str]) -> CliEnvironment:
    """Builds the CLI execution environment per U8 and Slice 3."""
    explicit_root = nodepath.resolve(options['root']) if options.get('root') else None
    root = repository_root(explicit_root)
    config = runtime_config(root, options.get('python'))
    python_exe = config.python if command == 'search' else config.native_python
    inputs = InputIntegrity(config.repository_root, installed_environment(config.repository_root))
    return CliEnvironment(root=config.repository_root, python=python_exe, inputs=inputs)


async def _run_worker_async(
    env: CliEnvironment,
    script: str,
    request: Any,
    *,
    threads: int,
    timeout_ms: int,
    label: str,
) -> Any:
    terminal: list[Any] = [None]
    failure: list[Optional[str]] = [None]
    stopped: list[Optional[str]] = [None]
    last_progress = [-1]
    limit = str(threads)

    worker_env = {
        **os.environ,
        'OMP_NUM_THREADS': limit,
        'OPENBLAS_NUM_THREADS': limit,
        'MKL_NUM_THREADS': limit,
        'VECLIB_MAXIMUM_THREADS': limit,
        'PYTHONDONTWRITEBYTECODE': '1',
        'PYTHONUNBUFFERED': '1',
    }

    def on_event(event: dict[str, Any], _append: Any) -> None:
        ev_type = event.get('type', UNDEFINED)
        if _same(ev_type, 'progress'):
            num = to_number(event.get('progress', UNDEFINED))
            pct = math.floor(100.0 * (num if js_truthy(num) and math.isfinite(num) else 0.0))
            if pct >= last_progress[0] + 10 or pct == 100:
                last_progress[0] = pct
                raw_msg = event.get('message', None)
                msg_str = '' if raw_msg is None or raw_msg is UNDEFINED else _js_string(raw_msg)
                sys.stderr.write(f'  {label}: {pct}% {msg_str}\n')
                sys.stderr.flush()
        if _same(ev_type, 'result'):
            terminal[0] = event.get('result', UNDEFINED)
        if _same(ev_type, 'error'):
            failure[0] = _js_string(event.get('message', UNDEFINED))

    def on_stderr(text: str) -> None:
        if not js_truthy(failure[0]):
            trimmed = jsjson.js_trim(text)
            failure[0] = trimmed.split('\n')[-1]

    def on_error(error: WorkerError) -> None:
        failure[0] = error.message

    def on_stop(reason: str) -> None:
        stopped[0] = reason

    worker = await start_worker(
        env.python,
        ['-u', nodepath.join(env.root, script)],
        cwd=env.root,
        env=worker_env,
        input=request,
        timeout=timeout_ms / 1000.0,
        max_output_bytes=MAX_CLI_OUTPUT_BYTES,
        on_event=on_event,
        on_stderr=on_stderr,
        on_error=on_error,
        on_stop=on_stop,
        on_close=None,
    )
    outcome = await worker.wait()
    if stopped[0]:
        if stopped[0] == 'timeout':
            mins = jsjson.number_to_string(timeout_ms / 60000.0)
            raise RuntimeError(f'time limit of {mins} min reached')
        raise RuntimeError(f'stopped ({stopped[0]})')
    if outcome.code != 0 or not js_truthy(terminal[0]):
        code_text = 'null' if outcome.code is None else str(outcome.code)
        raise RuntimeError(failure[0] if failure[0] is not None else f'worker exited with code {code_text}')
    return terminal[0]


def run_worker_sync(
    env: CliEnvironment,
    script: str,
    request: Any,
    *,
    threads: int,
    timeout_ms: int,
    label: str,
) -> Any:
    return asyncio.run(_run_worker_async(env, script, request, threads=threads, timeout_ms=timeout_ms, label=label))


def with_data_prior(raw: Any, prior: Optional[dict[str, Any]]) -> Any:
    """``withDataPrior(raw, prior)`` from ``webapp/scripts/eeglayoutlab.mjs``."""
    if not prior:
        return raw
    is_sub = isinstance(raw, dict) and raw.get('schema') == 'design-submission/1'
    request = raw.get('request') if is_sub else raw
    if isinstance(request, dict) and js_truthy(request.get('noise_model')):
        raise ValueError('--data-prior replaces the noise model; remove noise_model from the request')
    merged = {**(request if isinstance(request, dict) else {}), 'data_prior': prior}
    return {**raw, 'request': merged} if is_sub else merged


def request_from_options(options: dict[str, str]) -> dict[str, Any]:
    """``requestFromOptions(options)`` from ``webapp/scripts/eeglayoutlab.mjs``."""
    design = read_json(options['design'])
    if design is None:
        raise JSTypeError("Cannot destructure property 'electrode_names' of 'design' as it is null.")
    action = options.get('action', 'evaluate')
    noise_name = options.get('noise')
    if noise_name is not None and noise_name not in _NOISE_PRESETS:
        raise ValueError(f'unknown --noise {noise_name}')
    noise_val = _NOISE_PRESETS.get(noise_name) if noise_name is not None else None
    design_dict = design if isinstance(design, dict) else {}
    electrode_names = design_dict.get('electrode_names')
    source_metadata = design_dict.get('source_metadata')
    scientific = {k: v for k, v in design_dict.items() if k not in ('electrode_names', 'source_metadata')}
    request: dict[str, Any] = {
        'action': action,
        'design': scientific,
        'radius_mm': jsmath.js_number(options.get('radius', '6')),
        'seed': jsmath.js_number(options.get('seed', '42')),
    }
    if noise_val:
        request['noise_model'] = noise_val
    if options.get('conductivity'):
        request['conductivity_scenario'] = options['conductivity']
    if options.get('head'):
        request['head_id'] = options['head']
    if options.get('robustness'):
        request['robustness'] = options['robustness']
    if js_truthy(electrode_names):
        envelope: dict[str, Any] = {
            'schema': 'design-submission/1',
            'request': request,
            'electrode_names': electrode_names,
        }
        if js_truthy(source_metadata):
            envelope['source_metadata'] = source_metadata
        return envelope
    return request


def search_request_from_options(options: dict[str, str]) -> dict[str, Any]:
    """Builds a canonical ``radius-search`` request from inline CLI flags (U15)."""
    missing = [flag for flag in ('regions', 'radius', 'mode') if flag not in options]
    if missing:
        flags = ', '.join(f'--{flag}' for flag in missing)
        raise ValueError(f'inline search needs {flags}')
    noise_name = options.get('noise')
    if noise_name is not None and noise_name not in _NOISE_PRESETS:
        raise ValueError(f'unknown --noise {noise_name}')
    noise_val = _NOISE_PRESETS.get(noise_name) if noise_name is not None else None
    request: dict[str, Any] = {
        'region_count': jsmath.js_number(options['regions']),
        'radius_mm': jsmath.js_number(options['radius']),
        'mode': options['mode'],
    }
    if 'masks' in options:
        request['mask_codes'] = [trimmed for item in options['masks'].split(',') if (trimmed := jsjson.js_trim(item))]
    if 'electrodes' in options:
        request['electrode_count'] = jsmath.js_number(options['electrodes'])
    if 'allocation' in options:
        request['allocation_mode'] = options['allocation']
    if 'objective' in options:
        obj_aliases = {
            'min_field_sensitivity20': 'default',
            'subspace_info_composite': 'composite',
        }
        request['objective_mode'] = obj_aliases.get(options['objective'], options['objective'])
    if noise_val:
        request['noise_model'] = noise_val
    return request


def evaluate_one(env: CliEnvironment, raw: Any) -> dict[str, Any]:
    """``evaluateOne(env, raw)`` from ``webapp/scripts/eeglayoutlab.mjs``."""
    submitted = design_submission(raw)
    body = submitted['request']
    electrode_names = submitted.get('electrode_names')
    source_metadata = submitted.get('source_metadata')
    request = normalize_design_request(body)
    context = design_context(env.root, env.python, env.inputs, request)
    result = run_worker_sync(
        env, 'scripts/design_evaluation.py', request, threads=1, timeout_ms=600000, label=request['action']
    )
    validate_design_result(result, request, context.admission)
    after = design_context(env.root, env.python, env.inputs, request)
    if after.key != context.key:
        raise RuntimeError('inputs or code changed during the calculation')
    out: dict[str, Any] = {
        'schema': RUN_SCHEMA,
        'service': 'design-evaluation',
        'request': request,
        'key': context.key,
        'identity': context.identity,
    }
    if electrode_names:
        ann: dict[str, Any] = {'electrode_names': electrode_names}
        if source_metadata:
            ann['source_metadata'] = source_metadata
        out['annotation'] = ann
    out['result'] = result
    return out


def search_one(env: CliEnvironment, raw: Any) -> dict[str, Any]:
    """``searchOne(env, raw)`` from ``webapp/scripts/eeglayoutlab.mjs``."""
    request = normalize_request(raw)
    runtime = runtime_identity(env.python)
    identity = radius_identity(env.root, request, code_identity(env.root), runtime)
    result = run_worker_sync(
        env, 'scripts/run_local_radius_compute.py', request, threads=2, timeout_ms=180000, label='search'
    )
    validate_worker_result(result, request)
    provenance = _member(result, 'provenance')
    code_sha = _member(provenance, 'code_sha256') if isinstance(provenance, dict) else UNDEFINED
    if isinstance(code_sha, dict):
        for path in jsjson._own_keys(code_sha):
            if identity['code'].get(path, UNDEFINED) != code_sha[path]:
                raise RuntimeError('scientific code changed during the search')
    if _member(result, 'status') == 'completed':
        env.inputs.verify(provenance)
    return {
        'schema': RUN_SCHEMA,
        'service': 'radius-search',
        'request': request,
        'key': request_key(request, identity),
        'identity': identity,
        'result': result,
    }


def run_study(env: CliEnvironment, raw_input: Any) -> dict[str, Any]:
    """``study(env, input)`` from ``webapp/scripts/eeglayoutlab.mjs``."""
    normalized = normalize_study_input(raw_input)
    heads = normalized['protocol'] == 'heads'
    cases: list[dict[str, Any]] = []
    runs: list[dict[str, Any]] = []
    requests = normalized['requests']
    total = len(requests)
    for index, request in enumerate(requests):
        if heads:
            label = str(request['head_id'])
        else:
            seed_s = jsjson.number_to_string(request['seed'])
            rad_s = jsjson.number_to_string(request['radius_mm'])
            label = f'seed {seed_s}, {rad_s} mm'
        sys.stderr.write(f'case {index + 1}/{total} ({label})\n')
        sys.stderr.flush()
        context = design_context(env.root, env.python, env.inputs, request)
        identity_sha256 = jsjson.sha256_hex(context.identity)
        if not heads and cases and identity_sha256 != cases[0]['identity_sha256']:
            raise RuntimeError('scientific identity changed between cases')
        try:
            result = run_worker_sync(
                env, 'scripts/design_evaluation.py', request, threads=1, timeout_ms=600000, label=label
            )
            validate_design_result(result, request, context.admission)
            cases.append({
                'index': index,
                'request': request,
                'key': context.key,
                'identity_sha256': identity_sha256,
                'status': 'completed',
                'error': None,
                'summary': summarize_study_case(result),
            })
            runs.append({
                'index': index,
                'run': {
                    'schema': RUN_SCHEMA,
                    'service': 'design-evaluation',
                    'request': request,
                    'key': context.key,
                    'identity': context.identity,
                    'result': result,
                },
            })
        except Exception as error:  # noqa: BLE001 - per-case failure recorded in study.json
            cases.append({
                'index': index,
                'request': request,
                'key': context.key,
                'identity_sha256': identity_sha256,
                'status': 'failed',
                'error': _error_text(error),
                'summary': None,
            })
    metadata = {k: v for k, v in normalized.items() if k != 'requests'}
    study_identity_sha = (
        jsjson.sha256_hex([entry['identity_sha256'] for entry in cases])
        if heads
        else cases[0]['identity_sha256']
    )
    study_record = {
        'schema': STUDY_SCHEMA,
        **metadata,
        'identity_sha256': study_identity_sha,
        'cases': cases,
        'aggregation': aggregate_study(normalized['protocol'], cases),
    }
    return {'runs': runs, 'study': study_record}


def execute(
    command: str,
    files: Sequence[str],
    options: dict[str, str],
    *,
    recording_names: Optional[Sequence[str]] = None,
) -> int:
    """Executes ``evaluate``, ``search``, ``study``, ``prior`` or ``eeg-summary`` and returns Node's exit code."""
    if command != 'eeg-summary' and importlib.util.find_spec('pydantic') is None:
        from .main import _service_hint
        raise ValueError(f'{command} needs pydantic; {_service_hint()}')

    if command == 'prior':
        from ..schemas.options import DATA_PRIOR_REGIONS, data_prior_from_file
        from .science import summary_files

        env = build_environment('prior', options)
        inputs = summary_files(files)
        if not inputs:
            raise ValueError('no covariance summaries found')
        sys.stderr.write(f'scientific root {env.root}\npython {env.python}\n{len(inputs)} summaries\n')
        sys.stderr.flush()
        prior_res = run_worker_sync(
            env, 'scripts/eeg_data.py', {'action': 'prior', 'files': inputs},
            threads=4, timeout_ms=3600000, label='prior',
        )
        data_prior_from_file(prior_res)
        write_json(options['out'], prior_res)
        req = prior_res['request']
        held = prior_res['fit'].get('held_out')
        lines = [
            f"{region}\t{jsjson.number_to_string(float(req['region_gain'][k]))}"
            for k, region in enumerate(DATA_PRIOR_REGIONS)
        ]
        noise_str = (
            f"rho {jsjson.number_to_string(float(req['rho']))}, L {jsjson.number_to_string(float(req['length_mm']))} mm"
            if js_truthy(req.get('rho'))
            else 'independent'
        )
        lines.append(f'noise\t{noise_str}')
        if js_truthy(held):
            lines.append(
                f"held-out\t{jsjson.number_to_string(float(held['prior_better_count']))}/"
                f"{jsjson.number_to_string(float(held['summaries']))} better than the area prior, "
                f"shrinkage {jsjson.number_to_string(float(held['selected_shrinkage']))}"
            )
        else:
            lines.append('held-out\tnot run (fewer than 3 summaries)')
        sys.stdout.write('\n'.join(lines) + '\n')
        sys.stdout.flush()
        sys.stderr.write(f"wrote {options['out']} ({len(prior_res['channels'])} channels, id {prior_res['id']})\n")
        sys.stderr.flush()
        return 0

    if command == 'eeg-summary':
        import re as _re

        band: list[Any] = (
            [1, 40]
            if 'band' not in options
            else [jsmath.js_number(x) for x in options['band'].split(',')]
        )
        epoch: Any = 2 if 'epoch' not in options else jsmath.js_number(options['epoch'])
        out_dir = nodepath.resolve(options['out-dir'])
        names = list(recording_names) if recording_names is not None else [
            _re.sub(r'\.(edf|bdf|rec|vhdr|set)$', '', os.path.basename(f), flags=_re.IGNORECASE)
            for f in files
        ]
        env = build_environment('eeg-summary', options)
        sys.stderr.write(f'scientific root {env.root}\npython {env.python}\n')
        sys.stderr.flush()
        failed = 0
        for k, file_path in enumerate(files):
            name = names[k]
            sys.stderr.write(f'{name}\n')
            sys.stderr.flush()
            try:
                summary = run_worker_sync(
                    env,
                    'scripts/eeg_data.py',
                    {
                        'action': 'summary',
                        'path': nodepath.resolve(file_path),
                        'band_hz': band,
                        'epoch_s': epoch,
                        'label': options.get('label', None),
                    },
                    threads=1,
                    timeout_ms=1800000,
                    label='summary',
                )
                target = nodepath.join(out_dir, f'{name}.summary.json')
                write_json(target, summary)
                epochs = summary.get('epochs') or {}
                sys.stderr.write(
                    f"  wrote {target} ({len(summary.get('channels') or ())} channels, "
                    f"{epochs.get('used')}/{epochs.get('analysed')} epochs)\n"
                )
                sys.stderr.flush()
            except Exception as error:  # noqa: BLE001
                failed += 1
                sys.stderr.write(f'  failed: {_error_text(error)}\n')
                sys.stderr.flush()
        return 1 if failed else 0

    from ..schemas.options import data_prior_from_file

    env = build_environment(command, options)
    out_dir = nodepath.resolve(options['out-dir'])
    sys.stderr.write(f'scientific root {env.root}\npython {env.python}\n')
    sys.stderr.flush()

    if command == 'study':
        outcome = run_study(env, read_json(files[0]))
        record = outcome['study']
        for item in outcome['runs']:
            idx_str = str(item['index'] + 1).zfill(2)
            write_json(nodepath.join(out_dir, 'cases', f'{idx_str}.result.json'), item['run'])
        study_path = nodepath.join(out_dir, 'study.json')
        write_json(study_path, record)
        completed = record['aggregation']['completed_cases']
        sys.stderr.write(f"wrote {study_path}: {completed}/{len(record['cases'])} cases completed\n")
        sys.stderr.flush()
        return 0 if completed == len(record['cases']) else 1

    prior = data_prior_from_file(read_json(options['data-prior'])) if options.get('data-prior') else None
    if command == 'evaluate' and options.get('design'):
        raw_jobs = [('request', request_from_options(options))]
    elif command == 'search' and not files:
        raw_jobs = [('search', search_request_from_options(options))]
    else:
        raw_jobs = [(stem(path), read_json(path)) for path in files]
    jobs = [(name, with_data_prior(raw, prior)) for name, raw in raw_jobs]
    failed = 0
    for name, raw in jobs:
        sys.stderr.write(f'{name}\n')
        sys.stderr.flush()
        try:
            run_record = evaluate_one(env, raw) if command == 'evaluate' else search_one(env, raw)
            out_path = nodepath.join(out_dir, f'{name}.result.json')
            write_json(out_path, run_record)
            sys.stderr.write(f"  wrote {out_path} (key {run_record['key'][:12]})\n")
            sys.stderr.flush()
        except Exception as error:  # noqa: BLE001 - batch item failure writes <name>.error.json and exits 1
            failed += 1
            err_msg = _error_text(error)
            write_json(nodepath.join(out_dir, f'{name}.error.json'), {
                'schema': RUN_SCHEMA,
                'request': raw,
                'error': err_msg,
            })
            sys.stderr.write(f'  failed: {err_msg}\n')
            sys.stderr.flush()
    return 1 if failed else 0
