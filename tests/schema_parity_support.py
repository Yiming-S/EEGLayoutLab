"""Shared setup for the schema parity tests (tests/schema_parity/README.md).

The Node corpus is generated once per test session by ``tests/schema_parity/generate.mjs``.

Without Pydantic, FastAPI or Node the parity tests are skipped, so the native runtime suite runs unchanged.
With ``EEG_REQUIRE_SCHEMA_PARITY=1`` (set in CI) a missing dependency is an error instead.
"""
from __future__ import annotations

import base64
import importlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = os.environ.get('EEG_REQUIRE_SCHEMA_PARITY') == '1'


def require(module: str) -> ModuleType:
    """Import a dependency of the parity tests, or skip the module (an error when parity is required)."""
    if REQUIRED:
        return importlib.import_module(module)
    return pytest.importorskip(module)


def _node_corpus() -> dict[str, Any] | None:
    # Without the service extra every consumer of the corpus skips, so it is not generated: a failure of the
    # generator must not stop the native runtime suite, which has no Pydantic.
    if not REQUIRED and importlib.util.find_spec('pydantic') is None:
        return None
    if shutil.which('node') is None:
        if REQUIRED:
            raise RuntimeError('EEG_REQUIRE_SCHEMA_PARITY=1 but Node is not on PATH')
        return None
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'corpus.json'
        subprocess.run(['node', str(ROOT / 'tests/schema_parity/generate.mjs'), str(path)], check=True, cwd=ROOT)
        return json.loads(path.read_text(encoding='utf-8'))


CORPUS = _node_corpus()
needs_node = pytest.mark.skipif(CORPUS is None, reason='Node is required to run the reference normalizers')
FORMATS: dict[str, list[dict[str, Any]]] = {name: entry['variants'] for name, entry in (CORPUS or {}).get('formats', {}).items()}
CASES = [(name, variant) for name, variants in sorted(FORMATS.items()) for variant in variants]


def case_id(case: tuple[str, dict[str, Any]]) -> str:
    return f'{case[0]}/{case[1]["name"]}'


def body_bytes(variant: dict[str, Any]) -> bytes:
    """The request body as sent: raw bytes, or the text in UTF-8. Unpaired surrogates appear in texts only as
    escapes; a raw one has no UTF-8 form and is sent as bytes instead."""
    if 'bytes' in variant:
        return base64.b64decode(variant['bytes'])
    return variant['text'].encode('utf-8')


def body_text(variant: dict[str, Any]) -> str:
    from eeglayoutlab.schemas import jsjson

    return jsjson.decode_body(base64.b64decode(variant['bytes'])) if 'bytes' in variant else variant['text']
