"""Tests for ``GET /api/data-status`` local model-data readiness inspection."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from eeglayoutlab.schemas import jsjson
from eeglayoutlab.server.app import create_app

from .service_support import loopback_client, service_config


def _write_manifest_root(root: Path, *, with_base: bool, with_table: bool, with_simnibs: bool) -> None:
    (root / 'data').mkdir(parents=True, exist_ok=True)
    (root / 'results' / 'v2').mkdir(parents=True, exist_ok=True)
    bank_rel = 'results/v2/current_multiregion_bank.json'
    bank_bytes = b'{"ok":true}\n'
    manifest = {
        'schema': 'eeglayoutlab-data-manifest/1',
        'files': [
            {
                'path': bank_rel,
                'size_bytes': len(bank_bytes),
            },
        ],
    }
    (root / 'data' / 'manifest.json').write_text(jsjson.stringify(manifest), encoding='utf-8')
    if with_base:
        (root / bank_rel).write_bytes(bank_bytes)
    if with_table:
        (root / 'results' / 'v2' / 'current_scalp_node_table.json').write_text('{"ok":true}\n', encoding='utf-8')
    if with_simnibs:
        py = root / '.runtime' / 'simnibs-4.6.0' / 'bin' / 'python'
        simnibs_init = (
            root / '.runtime' / 'simnibs-4.6.0' / 'lib' / 'python3.11' / 'site-packages' / 'simnibs' / '__init__.py'
        )
        py.parent.mkdir(parents=True, exist_ok=True)
        simnibs_init.parent.mkdir(parents=True, exist_ok=True)
        py.write_text('#!/bin/sh\nexit 0\n', encoding='utf-8')
        py.chmod(0o755)
        simnibs_init.write_text('# stub\n', encoding='utf-8')
    else:
        py = root / '.runtime' / 'compute-linux-64' / 'bin' / 'python'
        py.parent.mkdir(parents=True, exist_ok=True)
        py.write_text('#!/bin/sh\nexit 0\n', encoding='utf-8')
        py.chmod(0o755)


def _get_status(root: Path, *, authenticated: bool = True, cache_only: bool = False) -> tuple[int, Any]:
    app = create_app(replace(service_config(root), cache_only=cache_only))
    with loopback_client(app, authenticate=authenticated) as client:
        res = client.get('/api/data-status')
        return res.status_code, jsjson.parse(res.text)


def test_data_status_requires_session_cookie(tmp_path: Path) -> None:
    _write_manifest_root(tmp_path, with_base=False, with_table=False, with_simnibs=False)
    code, body = _get_status(tmp_path, authenticated=False)
    assert code == 401
    assert body['code'] == 'authentication_required'


def test_data_status_reports_missing_base_and_table_and_simnibs_states(tmp_path: Path) -> None:
    # 1. Empty installation: neither base nor scalp-node-table installed, no SimNIBS.
    r1 = tmp_path / 'empty'
    _write_manifest_root(r1, with_base=False, with_table=False, with_simnibs=False)
    code, body = _get_status(r1)
    assert code == 200
    assert body == {
        'schema': 'eeglayoutlab-data-status/1',
        'installed_form': False,
        'cache_only': False,
        'base_ready': False,
        'base_present': 0,
        'base_total': 1,
        'scalp_node_table_ready': False,
        'direct_fem_available': False,
        'coordinate_evaluation_ready': False,
        'heads': [],
        'scenarios': [],
    }

    # 2. Base installed on Linux/Conda without SimNIBS and without scalp-node-table.
    r2 = tmp_path / 'base_only_no_fem'
    _write_manifest_root(r2, with_base=True, with_table=False, with_simnibs=False)
    code, body = _get_status(r2)
    assert code == 200
    assert body['base_ready'] is True
    assert body['scalp_node_table_ready'] is False
    assert body['direct_fem_available'] is False
    assert body['coordinate_evaluation_ready'] is False

    # 3. Base + scalp-node-table installed without SimNIBS -> coordinate evaluation ready.
    r3 = tmp_path / 'base_and_table'
    _write_manifest_root(r3, with_base=True, with_table=True, with_simnibs=False)
    (r3 / 'results' / 'v2' / 'heads' / 'ixi002').mkdir(parents=True)
    (r3 / 'results' / 'v2' / 'heads' / 'ixi002' / 'table.json').write_text('{}\n', encoding='utf-8')
    (r3 / 'results' / 'v2' / 'scalp_node_table_scenarios' / 'skull_x2').mkdir(parents=True)
    (r3 / 'results' / 'v2' / 'scalp_node_table_scenarios' / 'skull_x2' / 'table.json').write_text('{}\n', encoding='utf-8')
    code, body = _get_status(r3)
    assert code == 200
    assert body['base_ready'] is True
    assert body['scalp_node_table_ready'] is True
    assert body['direct_fem_available'] is False
    assert body['coordinate_evaluation_ready'] is True
    assert body['heads'] == ['ixi002']
    assert body['scenarios'] == ['skull_x2']

    # 4. Base + SimNIBS managed runtime without scalp-node-table -> direct FEM available, coordinate evaluation ready.
    r4 = tmp_path / 'base_with_simnibs'
    _write_manifest_root(r4, with_base=True, with_table=False, with_simnibs=True)
    code, body = _get_status(r4, cache_only=True)
    assert code == 200
    assert body['cache_only'] is True
    assert body['base_ready'] is True
    assert body['scalp_node_table_ready'] is False
    assert body['direct_fem_available'] is True
    assert body['coordinate_evaluation_ready'] is True
