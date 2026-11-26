"""Shared helpers for CLI parity tests against Node (``webapp/scripts/eeglayoutlab.mjs``)."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, Mapping, Optional, Sequence

import pytest

from eeglayoutlab.cli import main as py_cli
from eeglayoutlab.schemas import jsjson

ROOT = Path(__file__).resolve().parents[2]
NODE_CLI = ROOT / 'webapp/scripts/eeglayoutlab.mjs'
REQUIRED = os.environ.get('EEG_REQUIRE_SCHEMA_PARITY') == '1'


def node_executable() -> Optional[str]:
    found = shutil.which('node')
    if found:
        return found
    for fallback in ('/opt/homebrew/bin/node', '/usr/local/bin/node'):
        if os.path.isfile(fallback) and os.access(fallback, os.X_OK):
            return fallback
    if REQUIRED:
        raise RuntimeError('EEG_REQUIRE_SCHEMA_PARITY=1 but Node is not available')
    return None


NODE = node_executable()
needs_node = pytest.mark.skipif(NODE is None, reason='Node is required to run the Node CLI parity reference')


def run_node_driver(driver: Path, spec: dict[str, Any], scratch: Path) -> dict[str, Any]:
    assert NODE is not None
    spec_path = scratch / f'{driver.stem}-spec.json'
    out_path = scratch / f'{driver.stem}-out.json'
    spec_path.write_text(jsjson.stringify(spec), encoding='utf-8')
    subprocess.run(
        [NODE, str(driver), str(spec_path), str(out_path)],
        check=True,
        cwd=ROOT,
        env={**os.environ, 'UV_THREADPOOL_SIZE': '1'},
    )
    return json.loads(out_path.read_text(encoding='utf-8'))


def run_node_cli(args: Sequence[str], *, cwd: Optional[Path] = None,
                 env: Optional[Mapping[str, str]] = None) -> subprocess.CompletedProcess[str]:
    assert NODE is not None
    return subprocess.run(
        [NODE, str(NODE_CLI), *args],
        cwd=cwd or ROOT,
        env={**os.environ, **(env or {})},
        capture_output=True,
        text=True,
    )


def run_python_cli_subprocess(args: Sequence[str], *, cwd: Optional[Path] = None,
                              env: Optional[Mapping[str, str]] = None) -> subprocess.CompletedProcess[str]:
    merged = {**os.environ, **(env or {})}
    src = str(ROOT / 'src')
    existing = merged.get('PYTHONPATH', '')
    merged['PYTHONPATH'] = f'{src}:{existing}' if existing else src
    return subprocess.run(
        [sys.executable, '-m', 'eeglayoutlab.cli.main', *args],
        cwd=cwd or ROOT,
        env=merged,
        capture_output=True,
        text=True,
    )


def run_python_cli_inproc(args: Sequence[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    capsys.readouterr()
    code = py_cli.main(list(args))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def tree_bytes(directory: Path) -> dict[str, bytes]:
    if not directory.exists():
        return {}
    return {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in sorted(directory.rglob('*'))
        if path.is_file()
    }
