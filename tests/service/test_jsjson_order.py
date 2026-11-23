"""``jsjson.stringify`` writes V8's own-key order (plan B1): array-index keys first, ascending, then insertion order.

The ``keyorder`` corpus (tests/schema_parity/reference.mjs) holds Node's ``JSON.stringify(JSON.parse(text))`` for
fixed and 2,000 random texts whose keys mix array indices and ordinary keys.
"""
from __future__ import annotations

import pytest

from eeglayoutlab.schemas import jsjson
from schema_parity_support import CORPUS, needs_node


@needs_node
def test_key_order_matches_json_stringify_of_json_parse():
    corpus = CORPUS['keyorder']
    assert len(corpus) > 2000
    mismatches = [(text, expected, jsjson.stringify(jsjson.parse(text))) for text, expected in corpus
                  if jsjson.stringify(jsjson.parse(text)) != expected]
    assert mismatches == []
    # The corpus exercises the rule: insertion order alone differs from Node for many of its texts. (The helper
    # recurses, so the few deeply nested texts are left out of this count.)
    shallow = [(text, expected) for text, expected in corpus if text.count('[') + text.count('{') < 500]
    assert sum(_insertion_order(jsjson.parse(text)) != expected for text, expected in shallow) > len(corpus) // 4


def _insertion_order(value):
    if isinstance(value, dict):
        return '{' + ','.join(jsjson.quote(key) + ':' + _insertion_order(child) for key, child in value.items()) + '}'
    if isinstance(value, list):
        return '[' + ','.join(_insertion_order(child) for child in value) + ']'
    return jsjson.stringify(value)


@pytest.mark.parametrize('key', ['0', '1', '9', '17', '100', '2147483647', '2147483648', '4294967294'])
def test_array_indices(key):
    assert jsjson.is_array_index(key)


@pytest.mark.parametrize('key', ['', '01', '00', '-0', '-1', '+1', '1.5', '1.0', '1e3', ' 1', '1 ', '0x1', 'NaN', 'Infinity',
                                 '4294967295', '4294967296', '9007199254740993', '\u0663', '\u00b2', '\uff11', '1\u0663', 'a',
                                 '1' + '0' * 4300, '9' * 5000])
def test_ordinary_keys(key):
    # str.isdigit accepts "01", "\u00b2" and "\u0663"; V8 treats each as an ordinary key.
    assert not jsjson.is_array_index(key)


def test_index_keys_are_written_first():
    value = {'b': 0, '2': 1, '1': 2, '01': 3, '4294967295': 4, '4294967294': 5}
    assert jsjson.stringify(value) == '{"1":2,"2":1,"4294967294":5,"b":0,"01":3,"4294967295":4}'
    # Nested objects and objects in arrays follow the same rule; the input is not changed.
    assert jsjson.stringify([{'10': 0, '9': 1, 'x': {'1': [], '0': None}}]) == '[{"9":1,"10":0,"x":{"0":null,"1":[]}}]'
    assert list(value) == ['b', '2', '1', '01', '4294967295', '4294967294']


def test_worker_results_with_integer_like_keys_hash_as_in_node():
    # src/compact_eeg/cortical_fem.py writes containing_tissue_counts in np.unique order; Node's JSON.parse moves
    # the index keys first, and result_sha256 is over that order (the stored 6a28cc63... design record).
    result = jsjson.parse('{"native_qa":{"source_qa":{"containing_tissue_counts":{"-1":4,"1":66,"2":4244,"3":38}}}}')
    text = '{"native_qa":{"source_qa":{"containing_tissue_counts":{"1":66,"2":4244,"3":38,"-1":4}}}}'
    assert jsjson.stringify(result) == text
    assert jsjson.sha256_hex(result) == jsjson.sha256_hex(jsjson.parse(text))


def test_duplicate_keys_keep_first_position_and_last_value():
    assert jsjson.stringify(jsjson.parse('{"a":1,"1":2,"a":3}')) == '{"1":2,"a":3}'


def test_digit_keys_beyond_python_s_int_limit_are_ordinary_keys():
    # int() refuses more than 4300 digits; such a key is no array index, so V8 keeps it in insertion order.
    key = '1' + '0' * 4300
    assert jsjson.stringify(jsjson.parse('{"b":1,"' + key + '":2,"1":3}')) == '{"1":3,"b":1,"' + key + '":2}'


@pytest.mark.parametrize('depth', [400, 2000, 20000])
def test_stringify_writes_any_depth_parse_accepts(depth):
    # V8 writes any depth JSON.parse returns; stringify does not recurse (parse falls back to an iterative parser).
    for text in ('[' * depth + ']' * depth, '{"a":' * depth + '{"1":[1,{"0":null}],"b":-0}' + '}' * depth):
        assert jsjson.stringify(jsjson.parse(text)) == text.replace('"b":-0', '"b":0')


def test_non_string_keys_are_refused():
    with pytest.raises(TypeError):
        jsjson.stringify({1: 'a'})
