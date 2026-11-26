"""Byte-parity tests for ``jsjson.stringify(..., indent=2)`` and ``core.jsmath`` formatting/math."""
from __future__ import annotations

from pathlib import Path
import random

from eeglayoutlab.core import jsmath
from eeglayoutlab.schemas import jsjson

from .cli_support import ROOT, needs_node, run_node_driver

COORDINATES_DRIVER = ROOT / 'tests/cli/parity/coordinates.mjs'
FIGURES_DRIVER = ROOT / 'tests/cli/parity/figures.mjs'


@needs_node
def test_jsjson_pretty_stringify_matches_v8(tmp_path: Path) -> None:
    samples = [
        {},
        [],
        {'empty_obj': {}, 'empty_arr': [], 'nested': {'a': [1, {}, [], {'x': -0.0, '2': 'two', '0': 'zero'}]}},
        {'10': 'ten', '2': 'two', 'b': [True, False, None, 1e-7, 1e21, 0.5078125], 'a': '中文 & <svg>'},
        [{'k': i, 'vals': [] if i % 2 == 0 else [i * 0.125, -0.0]} for i in range(6)],
    ]
    cases = [{'id': f's{i}', 'op': 'stringify2', 'input': item} for i, item in enumerate(samples)]
    node = {row['id']: row['value'] for row in run_node_driver(COORDINATES_DRIVER, {'cases': cases}, tmp_path)['results']}
    for i, item in enumerate(samples):
        assert jsjson.stringify(item, indent=2) == node[f's{i}']


@needs_node
def test_to_fixed_to_precision_and_graphemes_match_node(tmp_path: Path) -> None:
    rng = random.Random(20261126)
    format_inputs = [
        [0.0, 2], [-0.0, 2], [0.5078125, 6], [1.005, 2], [2.675, 2], [-2.675, 2],
        [1e-7, 4], [9.9999e-8, 3], [1e20, 2], [1e21, 2], [-1e21, 3], [123456.789, 4],
    ]
    for _ in range(500):
        val = (rng.random() - 0.5) * (10.0 ** rng.uniform(-8, 8))
        format_inputs.append([val, rng.randint(1, 8)])

    grapheme_inputs = [
        'Cz', 'AF7', '电极12', 'e\u0301cole', 'A\u030a\u0301', '👩‍🔬', '👨‍👩‍👧‍👦', '🇺🇸🇨🇳',
        '👍🏽', '🏳️‍🌈', 'abc\r\ndef', '超长标题测试——Electrode Layout 64 (Ernie) 🧪',
    ]
    out = run_node_driver(
        FIGURES_DRIVER,
        {'cases': [
            {'id': 'fmt', 'op': 'format', 'inputs': format_inputs},
            {'id': 'grp', 'op': 'graphemes', 'inputs': grapheme_inputs},
        ]},
        tmp_path,
    )['results']
    by_id = {row['id']: row['out'] for row in out}

    for (val, digits), expected in zip(format_inputs, by_id['fmt']):
        assert [jsmath.to_fixed(val, digits), jsmath.to_precision(val, digits)] == expected

    for text, expected in zip(grapheme_inputs, by_id['grp']):
        assert jsmath.graphemes(text) == expected
