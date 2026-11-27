"""Unit and integration tests for ``eeglayoutlab quickstart``, ``eeglayoutlab doctor`` and ``scripts/setup_local.py``."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import subprocess
import sys

from eeglayoutlab.cli import main as cli_main
from eeglayoutlab.cli import quickstart as quickstart_cli
from eeglayoutlab.data import cli as data_cli
from eeglayoutlab.schemas import jsjson
from eeglayoutlab.server.workspace import Workspace

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / 'tests/service') not in sys.path:
    sys.path.insert(0, str(ROOT / 'tests/service'))
from installed_support import MAIN, fake_prefix, needs_non_root, read_only  # noqa: E402
from service_support import static_export  # noqa: E402


def _write_synthetic_packages_mirror(root: Path, mirror: Path) -> None:
    """Creates synthetic ``base`` and ``scalp-node-table`` archives + ``packages.json`` in ``root/data``."""
    src_root = mirror.parent / 'source-root'
    (src_root / 'configs').mkdir(parents=True, exist_ok=True)
    (src_root / 'data/external/simnibs4_examples_partial/m2m_ernie').mkdir(parents=True, exist_ok=True)
    (src_root / 'results/v2/scalp_node_table/tbl_demo').mkdir(parents=True, exist_ok=True)

    sources_bytes = b'# Data sources\n'
    mesh_bytes = b'synthetic-msh-payload'
    bank_bytes = b'{"bank":"ok"}\n'
    (src_root / 'data/SOURCES.md').write_bytes(sources_bytes)
    (src_root / 'data/external/simnibs4_examples_partial/m2m_ernie/ernie.msh').write_bytes(mesh_bytes)
    (src_root / 'results/v2/current_multiregion_bank.json').write_bytes(bank_bytes)

    files_list = []
    for rel, raw in (
        ('data/SOURCES.md', sources_bytes),
        ('data/external/simnibs4_examples_partial/m2m_ernie/ernie.msh', mesh_bytes),
        ('results/v2/current_multiregion_bank.json', bank_bytes),
    ):
        files_list.append({
            'path': rel,
            'size_bytes': len(raw),
            'sha256': hashlib.sha256(raw).hexdigest(),
            'role': 'test',
            'source_id': 'ernie_derived',
            'original_bytes': True,
        })

    manifest_obj = {
        'schema_version': 'eeglayoutlab-data-bundle/1',
        'bundle_id': 'eeglayoutlab-data-v1',
        'total_size_bytes': sum(f['size_bytes'] for f in files_list),
        'sources': [
            {'id': 'ernie_derived', 'license': 'CC-BY-NC-4.0', 'name': 'Ernie derived'},
        ],
        'files': files_list,
    }
    manifest_text = jsjson.stringify(manifest_obj, indent=2) + '\n'
    (src_root / 'data/manifest.json').write_text(manifest_text, encoding='utf-8')
    (root / 'data').mkdir(parents=True, exist_ok=True)
    (root / 'configs').mkdir(parents=True, exist_ok=True)
    (root / 'data/manifest.json').write_text(manifest_text, encoding='utf-8')

    tbl_manifest = b'{"table": "demo"}'
    tbl_digest = hashlib.sha256(tbl_manifest).hexdigest()
    (src_root / 'results/v2/scalp_node_table/tbl_demo/manifest.json').write_bytes(tbl_manifest)
    (src_root / 'results/v2/scalp_node_table/tbl_demo/rows.npy').write_bytes(b'r' * 3000)
    (src_root / 'results/v2/scalp_node_table/tbl_demo/index.npz').write_bytes(b'i' * 100)
    (src_root / 'results/v2/current_scalp_node_table.json').write_text(
        jsjson.stringify({
            'manifest_path': 'results/v2/scalp_node_table/tbl_demo/manifest.json',
            'manifest_sha256': tbl_digest,
        }) + '\n',
        encoding='utf-8',
    )

    mirror.mkdir(parents=True, exist_ok=True)
    rc = data_cli.main([
        'data', 'build',
        '--root', str(src_root),
        '--out', str(mirror),
        '--only', 'base',
        '--only', 'scalp-node-table',
        '--archive', 'base',
        '--archive', 'scalp-node-table',
    ])
    assert rc == 0
    (root / 'data/packages.json').write_bytes((mirror / 'packages.json').read_bytes())


def test_default_workspace_path_avoids_turning_home_into_a_workspace(tmp_path: Path) -> None:
    fake_home = tmp_path / 'home'
    fake_home.mkdir()
    (fake_home / 'Documents').mkdir()

    assert quickstart_cli.default_workspace_path(str(fake_home), None, home=str(fake_home)) == str(
        fake_home / 'eeglayoutlab-workspace'
    )

    existing_ws = tmp_path / 'my-study'
    Workspace.open(str(existing_ws)).close()
    assert quickstart_cli.default_workspace_path(str(existing_ws), None, home=str(fake_home)) == str(existing_ws)

    custom = tmp_path / 'custom-ws'
    assert quickstart_cli.default_workspace_path(str(fake_home), str(custom), home=str(fake_home)) == str(custom)


def test_quickstart_installs_composes_and_reuses_store_across_environments(tmp_path: Path, monkeypatch, capsys) -> None:
    mirror = tmp_path / 'mirror'
    env1 = tmp_path / 'env1-root'
    _write_synthetic_packages_mirror(env1, mirror)
    data_store = tmp_path / 'user-data-store'
    fake_home = tmp_path / 'user-home'
    fake_home.mkdir()

    served_calls: list[argparse.Namespace] = []
    monkeypatch.setattr(cli_main, 'serve', lambda ns: served_calls.append(ns) or 0)
    monkeypatch.setenv('HOME', str(fake_home))
    monkeypatch.chdir(fake_home)

    rc = cli_main.main([
        'quickstart',
        '--root', str(env1),
        '--data-dir', str(data_store),
        '--from', str(mirror),
        '--no-browser',
    ])
    assert rc == 0
    assert len(served_calls) == 1
    assert served_calls[0].workspace == str(fake_home / 'eeglayoutlab-workspace')
    readiness = quickstart_cli.inspect_data_readiness(str(env1))
    assert readiness.base_ready and readiness.base_present == 3 and readiness.table_ready

    capsys.readouterr()
    rc2 = cli_main.main([
        'quickstart',
        '--root', str(env1),
        '--data-dir', str(data_store),
        '--no-browser',
    ])
    out2 = capsys.readouterr().out
    assert rc2 == 0 and 'Model data ready (base, scalp-node-table).' in out2

    env2 = tmp_path / 'env2-root'
    (env2 / 'data').mkdir(parents=True)
    (env2 / 'configs').mkdir(parents=True)
    (env2 / 'data/manifest.json').write_bytes((env1 / 'data/manifest.json').read_bytes())
    (env2 / 'data/packages.json').write_bytes((env1 / 'data/packages.json').read_bytes())
    rc3 = cli_main.main([
        'quickstart',
        '--root', str(env2),
        '--data-dir', str(data_store),
        '--no-browser',
    ])
    assert rc3 == 0
    readiness2 = quickstart_cli.inspect_data_readiness(str(env2))
    assert readiness2.base_ready and readiness2.table_ready


def test_quickstart_in_source_checkout_proceeds_with_verified_base_before_zenodo(tmp_path: Path, capsys) -> None:
    mirror = tmp_path / 'mirror'
    checkout = tmp_path / 'checkout'
    _write_synthetic_packages_mirror(checkout, mirror)
    data_store = tmp_path / 'store'
    assert data_cli.main([
        'data', '--data-dir', str(data_store),
        'install', 'base',
        '--from', str(mirror),
        '--root', str(checkout),
        '--compose',
    ]) == 0
    empty_store = tmp_path / 'empty-store'
    rc = quickstart_cli.ensure_quickstart_data(
        str(checkout),
        data_dir=str(empty_store),
        mirror=None,
    )
    out = capsys.readouterr().out
    assert rc == 0 and 'Model data ready (base).' in out


@needs_non_root
def test_quickstart_and_doctor_refuse_read_only_installed_prefix(tmp_path: Path) -> None:
    prefix = fake_prefix(tmp_path / 'P', public=())
    with read_only(prefix.root):
        q_res = prefix.run(MAIN, 'quickstart', '--no-browser', cwd=tmp_path)
        assert q_res.returncode == 2 and 'create a user environment' in q_res.stderr

        d_res = prefix.run(MAIN, 'doctor', cwd=tmp_path)
        assert d_res.returncode == 1 and '[FAIL] Scientific root:' in d_res.stdout


def test_doctor_reports_ready_root_data_and_static_export(tmp_path: Path, capsys) -> None:
    mirror = tmp_path / 'mirror'
    root = tmp_path / 'root'
    _write_synthetic_packages_mirror(root, mirror)
    static_dir = static_export(tmp_path / 'static')
    data_store = tmp_path / 'store'
    assert data_cli.main([
        'data', '--data-dir', str(data_store),
        'install',
        '--from', str(mirror),
        '--root', str(root),
        '--compose',
    ]) == 0

    capsys.readouterr()
    simnibs_py = ROOT / '.runtime/simnibs-4.6.0/bin/python'
    rc = cli_main.main([
        'doctor',
        '--root', str(root),
        '--static', str(static_dir),
        '--python', str(simnibs_py) if simnibs_py.is_file() else sys.executable,
    ])
    out = capsys.readouterr().out
    if simnibs_py.is_file():
        assert rc == 0, out
        assert '[ OK ] Base model data: ready (3/3 files)' in out
        assert '[ OK ] Scalp-node table: ready' in out
        assert '[ OK ] Web interface: ready' in out


def test_setup_local_plan_mode_runs_read_only_with_system_python() -> None:
    res = subprocess.run(
        [sys.executable, str(ROOT / 'scripts/setup_local.py'), '--plan'],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert res.returncode == 0, res.stderr
    assert 'EEGLayoutLab local source setup' in res.stdout
    assert 'Plan complete (--plan: no files were modified).' in res.stdout
