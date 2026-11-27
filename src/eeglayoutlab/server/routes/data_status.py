"""``GET /api/data-status``: local model-data readiness for browser onboarding notices.

Reports whether ``base`` and ``scalp-node-table`` are composed under the scientific root, whether the native
compute interpreter has ``simnibs`` installed on disk (without importing ``simnibs`` or starting MPI), and which
optional head or conductivity-scenario tables are present.

Excluded from OpenAPI (``include_in_schema=False``) so ``contracts/generated/openapi.json`` and existing
``/api/<kind>/health`` and ``/api/community/status`` responses stay byte-for-byte unchanged.
No stdlib ``json`` import (``test_guards.py``).
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
from typing import TYPE_CHECKING, Any, Optional

from fastapi import FastAPI, Response

from ...cli.quickstart import inspect_data_readiness
from ...jobs import nodepath
from ...jobs.runtime import installed_form, native_python_path, runtime_config
from ..app import json_response

if TYPE_CHECKING:
    from ..app import ServiceConfig
    from .compute import ComputeHost


def _prefix_has_simnibs(prefix: Path) -> bool:
    candidates = [
        *prefix.glob('lib/python*/site-packages/simnibs/__init__.py'),
        prefix / 'Lib' / 'site-packages' / 'simnibs' / '__init__.py',
    ]
    return any(item.is_file() for item in candidates)


def has_direct_fem(root: str, native_python: Optional[str] = None) -> bool:
    """Fast filesystem check for ``simnibs`` in the native worker environment (zero subprocess or MPI init)."""
    managed_native = Path(native_python_path(root))
    if managed_native.exists() and _prefix_has_simnibs(managed_native.parent.parent):
        return True

    target = native_python or runtime_config(root).native_python
    resolved = target if os.path.isabs(target) else (shutil.which(target) or '')
    if not resolved or not os.path.exists(resolved):
        return False

    exe_dir = Path(resolved).parent
    prefix = exe_dir.parent
    if _prefix_has_simnibs(prefix):
        return True

    # Handle virtual environments created from a SimNIBS runtime with include-system-site-packages = true.
    pyvenv = prefix / 'pyvenv.cfg'
    if pyvenv.is_file():
        try:
            lines = pyvenv.read_text(encoding='utf-8', errors='replace').splitlines()
        except OSError:
            return False
        values: dict[str, str] = {}
        for line in lines:
            key, sep, val = line.partition('=')
            if sep:
                values[key.strip().lower()] = val.strip()
        if values.get('include-system-site-packages', '').lower() == 'true' and values.get('home'):
            home_prefix = Path(values['home']).parent
            if _prefix_has_simnibs(home_prefix):
                return True
    return False


def build_data_status(config: 'ServiceConfig', compute: Optional['ComputeHost'] = None) -> dict[str, Any]:
    readiness = inspect_data_readiness(config.root)
    bank_exists = os.path.exists(nodepath.join(config.root, 'results/v2/current_multiregion_bank.json'))
    base_ready = bool(readiness.base_ready and bank_exists)
    rt = config.runtime
    if rt is None and compute is not None and callable(getattr(compute, 'runtime', None)):
        rt = compute.runtime()
    if rt is None:
        rt = runtime_config(config.root)
    direct_fem = has_direct_fem(config.root, rt.native_python)
    return {
        'schema': 'eeglayoutlab-data-status/1',
        'installed_form': installed_form(config.root),
        'cache_only': bool(config.cache_only),
        'base_ready': base_ready,
        'base_present': readiness.base_present,
        'base_total': readiness.base_total,
        'scalp_node_table_ready': readiness.table_ready,
        'direct_fem_available': direct_fem,
        'coordinate_evaluation_ready': bool(base_ready and (readiness.table_ready or direct_fem)),
        'heads': list(readiness.heads),
        'scenarios': list(readiness.scenarios),
    }


def add_routes(app: FastAPI, config: 'ServiceConfig', compute: Optional['ComputeHost'] = None) -> None:
    async def endpoint() -> Response:
        return json_response(200, build_data_status(config, compute))

    app.add_api_route('/api/data-status', endpoint, methods=['GET'], include_in_schema=False, name='data_status')
