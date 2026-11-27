"""First-time onboarding and health commands: ``eeglayoutlab quickstart`` and ``eeglayoutlab doctor``.

- ``quickstart`` turns first-time and repeat Conda launches into a single command:
  checks root writability, installs & composes the default model data (``base`` + ``scalp-node-table``) when
  missing (reusing any packages already cached in the user data directory without re-downloading), optionally
  runs the reproducible smoke calculation (``--verify``), selects ``~/eeglayoutlab-workspace`` by default when
  not already inside a workspace, and opens the local web application.
- ``doctor`` inspects the scientific root, compute interpreter, numerical dependencies, installed model data,
  and web interface bundle, and with ``--smoke`` executes Examples 1 & 2 in a temporary directory against
  ``examples/expected.json`` to confirm end-to-end calculation readiness.

No stdlib ``json`` import: ``test_guards.py`` enforces ``eeglayoutlab.schemas.jsjson`` across ``cli/``.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from typing import Any, Optional

from ..data import cli as data_cli
from ..data import index as data_index
from ..jobs import nodepath
from ..jobs.runtime import installed_form, repository_root, runtime_config, unwritable_root
from ..schemas import jsjson
from ..server.static import export_root
from ..server.workspace import is_workspace

__all__ = [
    'DEFAULT_WORKSPACE_NAME',
    'DataReadiness',
    'add_commands',
    'default_workspace_path',
    'inspect_data_readiness',
    'ensure_quickstart_data',
    'run_smoke_examples',
    'run_doctor',
    'run_quickstart',
]

DEFAULT_WORKSPACE_NAME = 'eeglayoutlab-workspace'


@dataclass(frozen=True)
class DataReadiness:
    base_ready: bool
    base_present: int
    base_total: int
    table_ready: bool
    heads: tuple[str, ...]
    scenarios: tuple[str, ...]


def default_workspace_path(cwd: str, explicit: Optional[str] = None, home: Optional[str] = None) -> str:
    """Chooses a clean workspace without turning ``~`` or a repository into a workspace."""
    if explicit:
        return os.path.abspath(explicit)
    if is_workspace(cwd):
        return cwd
    base_home = home if home is not None else os.path.expanduser('~')
    return os.path.abspath(os.path.join(base_home, DEFAULT_WORKSPACE_NAME))


def inspect_data_readiness(root: str) -> DataReadiness:
    """Fast filesystem check of composed model payloads under ``root``."""
    manifest_path = Path(nodepath.join(root, 'data/manifest.json'))
    base_present = 0
    base_total = 0
    base_ready = False
    if manifest_path.is_file():
        try:
            parsed = jsjson.parse(manifest_path.read_text(encoding='utf-8'))
            entries = parsed.get('files') if isinstance(parsed, dict) else None
            if isinstance(entries, list) and entries:
                base_total = len(entries)
                for entry in entries:
                    rel = entry.get('path') if isinstance(entry, dict) else None
                    size = entry.get('size_bytes') if isinstance(entry, dict) else None
                    if (
                        isinstance(rel, str)
                        and isinstance(size, (int, float))
                        and not isinstance(size, bool)
                    ):
                        candidate = Path(nodepath.join(root, rel))
                        try:
                            st = candidate.lstat()
                        except OSError:
                            continue
                        if Path(candidate).is_file() and not candidate.is_symlink() and st.st_size == int(size):
                            base_present += 1
                base_ready = base_present == base_total and base_total > 0
        except Exception:  # noqa: BLE001
            base_ready = False
    else:
        bank = Path(nodepath.join(root, 'results/v2/current_multiregion_bank.json'))
        if bank.is_file():
            base_ready = True
            base_present = base_total = 1

    table_ready = Path(nodepath.join(root, 'results/v2/current_scalp_node_table.json')).is_file()

    heads_dir = Path(nodepath.join(root, 'results/v2/heads'))
    heads = tuple(sorted(
        entry.name for entry in (heads_dir.iterdir() if heads_dir.is_dir() else ())
        if entry.is_dir() and (entry / 'table.json').is_file()
    ))
    scen_dir = Path(nodepath.join(root, 'results/v2/scalp_node_table_scenarios'))
    scenarios = tuple(sorted(
        entry.name for entry in (scen_dir.iterdir() if scen_dir.is_dir() else ())
        if entry.is_dir() and (entry / 'table.json').is_file()
    ))
    return DataReadiness(
        base_ready=base_ready,
        base_present=base_present,
        base_total=base_total,
        table_ready=table_ready,
        heads=heads,
        scenarios=scenarios,
    )


def add_commands(commands: Any, root_help: str, port_type: Any) -> None:
    """Registers ``quickstart`` and ``doctor`` on the top-level CLI parser."""
    quick = commands.add_parser(
        'quickstart',
        help='install/link missing model data if needed and open the local web application',
        description=(
            'One-command launch: checks scientific root writability, installs and composes the default model data '
            '(base + scalp-node-table) when missing, creates ~/eeglayoutlab-workspace by default, and opens the '
            'application in your browser.'
        ),
    )
    quick.add_argument(
        'workspace', nargs='?', metavar='WORKSPACE',
        help=f'workspace directory (default: current directory if already a workspace, else ~/{DEFAULT_WORKSPACE_NAME})',
    )
    quick.add_argument('--root', metavar='R', help=root_help)
    quick.add_argument('--port', type=port_type, default=0, metavar='N', help='loopback port (default: a free port)')
    quick.add_argument('--static', metavar='DIR', help='static interface (default: R/webapp/dist/client)')
    quick.add_argument('--docs', metavar='DIR', help='built documentation site served under /docs/ (default: R/site)')
    quick.add_argument('--data-dir', metavar='D', help='user data package directory (default: platform user data dir)')
    quick.add_argument('--from', dest='mirror', metavar='URL|DIR',
                       help='mirror directory or URL holding package manifests and archives')
    quick.add_argument('--from-root', metavar='R', help='copy missing package files from an existing scientific root')
    quick.add_argument('--base-only', action='store_true',
                       help='install only the base package (0.41 GB) and skip scalp-node-table (1.40 GB)')
    quick.add_argument('--examples', action='store_true',
                       help='also install the 11 head packages required by cross-head Example 3')
    quick.add_argument('--verify', action='store_true',
                       help='run a fast reproducible calculation check before opening the browser')
    quick.add_argument('--no-browser', action='store_true', help='print the address instead of opening a browser')
    quick.add_argument('--cache-only', action='store_true',
                       help='serve stored results only; skip data installation and refuse new computations')
    quick.add_argument('--clear-interrupted', action='store_true',
                       help='clear an unconfirmed interrupted task state before starting')

    doctor = commands.add_parser(
        'doctor',
        help='check installation, Python worker packages, model data and optional smoke calculation',
        description='Inspect local installation readiness and optionally run a reproducible smoke calculation.',
    )
    doctor.add_argument('--root', metavar='R', help=root_help)
    doctor.add_argument('--static', metavar='DIR', help='static interface (default: R/webapp/dist/client)')
    doctor.add_argument('--docs', metavar='DIR', help='built documentation site (default: R/site)')
    doctor.add_argument('--data-dir', metavar='D', help='user data package directory')
    doctor.add_argument('--python', metavar='PATH', help='explicit compute Python interpreter to inspect')
    doctor.add_argument('--smoke', action='store_true',
                        help='run Examples 1 & 2 in a temporary directory and verify scores against expected.json')


def ensure_quickstart_data(
    root: str,
    *,
    data_dir: Optional[str] = None,
    mirror: Optional[str] = None,
    from_root: Optional[str] = None,
    base_only: bool = False,
    examples: bool = False,
) -> int:
    """Installs and composes any missing target packages into ``root``; fast no-op when already present."""
    status = inspect_data_readiness(root)
    needed_heads: list[str] = []
    if examples:
        for pkg_name in data_index.examples_packages(Path(root)):
            if pkg_name.startswith('head-'):
                needed_heads.append(pkg_name[len('head-'):])

    missing_base = not status.base_ready
    missing_table = (not base_only) and (not status.table_ready)
    missing_heads = [hid for hid in needed_heads if hid not in status.heads]

    if not missing_base and not missing_table and not missing_heads:
        parts = ['base']
        if status.table_ready:
            parts.append('scalp-node-table')
        if status.heads:
            parts.append(f'{len(status.heads)} head(s)')
        print(f'Model data ready ({", ".join(parts)}).', flush=True)
        return 0

    index_file = Path(nodepath.join(root, 'data/packages.json'))
    if not index_file.is_file():
        print(
            f'eeglayoutlab: model data is missing under {root} and data/packages.json was not found; '
            'run eeglayoutlab data install with a manifest path.',
            file=sys.stderr,
            flush=True,
        )
        return 1

    pkg_index = data_index.load_index(index_file)
    store_obj = data_cli.Store(Path(data_dir).expanduser() if data_dir else data_cli.data_dir())

    def _source_available(pkg_name: str) -> bool:
        if mirror or from_root or store_obj.find(pkg_name) is not None:
            return True
        entry = pkg_index.by_name.get(pkg_name)
        return bool(entry and entry.urls)

    if (
        not installed_form(root)
        and not missing_base
        and missing_table
        and not missing_heads
        and not _source_available('scalp-node-table')
    ):
        print(
            'Model data ready (base). Install scalp-node-table later with '
            "'eeglayoutlab data install scalp-node-table' if table-mode coordinate evaluation is needed.",
            flush=True,
        )
        return 0

    targets = ['base'] if base_only else []
    label = 'base (0.41 GB)' if base_only else 'base + scalp-node-table (1.80 GB)'
    if examples:
        label += ' + 11 example heads (13.34 GB)'
    print(f'Preparing model data ({label})...', flush=True)

    install_ns = argparse.Namespace(
        data_command='install',
        data_dir=data_dir,
        targets=targets,
        examples=examples,
        mirror=mirror,
        index=None,
        root=root,
        from_root=from_root,
        compose=True,
        no_compose=False,
        copy=False,
        any_code_version=False,
    )
    return data_cli.run(install_ns)


def run_smoke_examples(
    root: str,
    *,
    include_cross_head: bool = False,
    python: Optional[str] = None,
) -> int:
    """Runs the reproducible CLI examples into a temporary folder and verifies scores against ``expected.json``."""
    from . import examples as examples_cli

    with tempfile.TemporaryDirectory(prefix='eeglayoutlab-smoke-') as tmp_dir:
        out_dir = os.path.join(tmp_dir, 'outputs')
        ns = argparse.Namespace(
            root=root,
            out_dir=out_dir,
            python=python,
            skip_cross_head=not include_cross_head,
            update_expected=False,
        )
        return examples_cli.run_examples_cli(ns)


_PROBE_CODE = (
    'import importlib.util, sys\n'
    'mods = ("numpy", "scipy", "cortech", "numba", "nibabel", "simnibs")\n'
    'found = [m for m in mods if importlib.util.find_spec(m) is not None]\n'
    'print(sys.version.split()[0] + "|" + ",".join(found))\n'
)


def _probe_compute_python(executable: str) -> tuple[bool, str, set[str]]:
    """Checks the compute Python interpreter and which scientific packages it can import."""
    env = {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH', 'PYTHONHOME')}
    env['PYTHONNOUSERSITE'] = '1'
    try:
        res = subprocess.run(
            [executable, '-c', _PROBE_CODE],
            capture_output=True,
            text=True,
            timeout=20,
            env=env,
        )
    except OSError as err:
        return False, str(err), set()
    except subprocess.TimeoutExpired:
        return False, 'timed out probing interpreter', set()
    if res.returncode != 0:
        detail = (res.stderr or res.stdout).strip().splitlines()
        return False, (detail[-1] if detail else f'exit code {res.returncode}'), set()
    line = res.stdout.strip().splitlines()[-1] if res.stdout.strip() else ''
    ver, _, raw_mods = line.partition('|')
    mods = {item for item in raw_mods.split(',') if item}
    return True, ver, mods


def run_doctor(args: argparse.Namespace) -> int:
    """Prints a clear readiness summary of root, compute runtime, model data, web UI and optional smoke check."""
    failures = 0
    try:
        root = repository_root(nodepath.resolve(args.root) if args.root else None)
    except ValueError as err:
        print(f'[FAIL] Scientific root: {err}', file=sys.stderr, flush=True)
        return 2

    is_installed = installed_form(root)
    form_label = 'installed Conda environment' if is_installed else 'source checkout'
    problem = unwritable_root(root)
    if problem is not None:
        print(f'[FAIL] Scientific root: {root} ({form_label}) — not writable', flush=True)
        print(f'       {problem}', flush=True)
        failures += 1
    else:
        print(f'[ OK ] Scientific root: {root} ({form_label}, writable)', flush=True)

    missing_service = [name for name in ('fastapi', 'uvicorn', 'pydantic') if importlib.util.find_spec(name) is None]
    if missing_service:
        print(f'[FAIL] Local service packages: missing {", ".join(missing_service)}', flush=True)
        failures += 1
    else:
        print('[ OK ] Local service packages: fastapi, uvicorn, pydantic ready', flush=True)

    cfg = runtime_config(root, python=args.python)
    ok_py, py_info, mods = _probe_compute_python(cfg.python)
    if not ok_py:
        print(f'[FAIL] Compute Python: {cfg.python} ({py_info})', flush=True)
        if not is_installed:
            print('       Run: python3 scripts/setup_local.py  (or python3 scripts/bootstrap_runtime.py --execute)',
                  flush=True)
        failures += 1
    else:
        missing_core = [m for m in ('numpy', 'scipy') if m not in mods]
        has_simnibs = 'simnibs' in mods
        has_table_stack = all(m in mods for m in ('cortech', 'numba', 'nibabel'))
        if missing_core or (not has_simnibs and not has_table_stack):
            need = missing_core or [m for m in ('cortech', 'numba', 'nibabel') if m not in mods]
            print(f'[FAIL] Compute Python: {cfg.python} (Python {py_info}; missing {", ".join(need)})', flush=True)
            failures += 1
        else:
            fem_note = (
                'SimNIBS available (direct FEM & source-reception/2 enabled)'
                if has_simnibs
                else 'table-mode runtime (SimNIBS not installed; source-reception/2 disabled)'
            )
            print(f'[ OK ] Compute Python: {cfg.python} (Python {py_info}; {fem_note})', flush=True)

    data = inspect_data_readiness(root)
    if data.base_ready:
        count_note = f' ({data.base_present}/{data.base_total} files)' if data.base_total else ''
        print(f'[ OK ] Base model data: ready{count_note}', flush=True)
    else:
        count_note = f' ({data.base_present}/{data.base_total} files present)' if data.base_total else ''
        print(f'[WARN] Base model data: missing{count_note}', flush=True)
        print('       Run: eeglayoutlab data install   (or eeglayoutlab quickstart)', flush=True)
        failures += 1

    if data.table_ready:
        print('[ OK ] Scalp-node table: ready (coordinate evaluation without SimNIBS enabled)', flush=True)
    elif ok_py and 'simnibs' in mods:
        print('[INFO] Scalp-node table: not installed (direct SimNIBS FEM available; install scalp-node-table for fast table evaluation)',
              flush=True)
    else:
        print('[INFO] Scalp-node table: not installed (run `eeglayoutlab data install` to evaluate custom coordinates)',
              flush=True)

    if data.heads or data.scenarios:
        print(f'[INFO] Optional data: {len(data.heads)} head package(s), {len(data.scenarios)} conductivity scenario(s)',
              flush=True)

    static_dir = os.path.abspath(args.static) if args.static else nodepath.join(root, 'webapp/dist/client')
    if export_root(static_dir) is not None:
        print(f'[ OK ] Web interface: ready ({static_dir})', flush=True)
    else:
        print(f'[WARN] Web interface: not built ({static_dir})', flush=True)
        if not is_installed:
            print('       Run: (cd webapp && npm ci && npm run build)  or  python3 scripts/setup_local.py', flush=True)
        failures += 1

    docs_dir = os.path.abspath(args.docs) if args.docs else nodepath.join(root, 'site')
    if Path(docs_dir, 'index.html').is_file():
        print(f'[ OK ] Local /docs/ site: built ({docs_dir})', flush=True)
    else:
        print('[INFO] Local /docs/ site: not built locally (method links open online documentation)', flush=True)

    if args.smoke:
        if failures:
            print('[SKIP] Smoke calculation skipped until the items above are resolved.', flush=True)
            return 1
        print('Running reproducible smoke calculation (Examples 1 & 2)...', flush=True)
        rc = run_smoke_examples(root, include_cross_head=False, python=args.python)
        if rc != 0:
            print('[FAIL] Smoke calculation did not match examples/expected.json.', flush=True)
            return 1
        print('[ OK ] Smoke calculation: Examples 1 & 2 matched examples/expected.json within 1e-6.', flush=True)

    if failures == 0:
        print('All required checks passed. Launch anytime with: eeglayoutlab quickstart', flush=True)
        return 0
    return 1


def run_quickstart(args: argparse.Namespace) -> int:
    """Ensures default model data is ready, picks ~/eeglayoutlab-workspace by default, and starts ``serve``."""
    from . import main as cli_main

    missing = [name for name in ('fastapi', 'uvicorn') if importlib.util.find_spec(name) is None]
    if missing:
        print(f'eeglayoutlab: the service needs {", ".join(missing)}; {cli_main._service_hint()}',
              file=sys.stderr, flush=True)
        return 2
    try:
        root = repository_root(nodepath.resolve(args.root) if args.root else None)
    except ValueError as err:
        print(f'eeglayoutlab: {err}', file=sys.stderr, flush=True)
        return 2
    problem = unwritable_root(root)
    if problem is not None:
        print(f'eeglayoutlab: {problem}', file=sys.stderr, flush=True)
        return 2

    if not args.cache_only:
        rc = ensure_quickstart_data(
            root,
            data_dir=args.data_dir,
            mirror=args.mirror,
            from_root=args.from_root,
            base_only=args.base_only,
            examples=args.examples,
        )
        if rc != 0:
            return rc

    if args.verify:
        print('Verifying installation with a real calculation (Examples 1 & 2)...', flush=True)
        rc = run_smoke_examples(root, include_cross_head=args.examples)
        if rc != 0:
            return rc

    chosen_workspace = default_workspace_path(os.getcwd(), args.workspace)
    serve_ns = argparse.Namespace(
        workspace=chosen_workspace,
        root=root,
        port=args.port,
        static=args.static,
        docs=args.docs,
        no_browser=args.no_browser,
        cache_only=args.cache_only,
        clear_interrupted=args.clear_interrupted,
    )
    return cli_main.serve(serve_ns)
