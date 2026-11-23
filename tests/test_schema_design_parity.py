"""Phase 0c: the Pydantic design-evaluation schema reproduces Node's canonical JSON byte for byte.

Node (webapp/server/design-evaluation-server.mjs) is run by
tests/schema_parity/design_variants.mjs over the shared fixtures and generated
request texts; its outputs are compared with eeglayoutlab.schemas.
"""
from copy import deepcopy
import base64
import json
import math
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile

import pytest

pytest.importorskip('pydantic')

from eeglayoutlab.schemas import jsjson  # noqa: E402
from eeglayoutlab.schemas.design_evaluation import canonical_json, normalize_design_request  # noqa: E402
from eeglayoutlab.schemas.submission import DesignEvaluationBody, canonical_submission  # noqa: E402
from pydantic import TypeAdapter  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = json.loads((ROOT / 'contracts/fixtures/requests.json').read_text(encoding='utf-8'))
DESIGN_FIXTURES = [sample for sample in FIXTURES['cases'] if sample['service'] == 'design']


def _node_corpus():
    if shutil.which('node') is None:
        return None
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'variants.json'
        subprocess.run(['node', str(ROOT / 'tests/schema_parity/design_variants.mjs'), str(path)], check=True, cwd=ROOT)
        return json.loads(path.read_text(encoding='utf-8'))


CORPUS = _node_corpus()
needs_node = pytest.mark.skipif(CORPUS is None, reason='Node is required to run the reference normalizer')
NODE_FIXTURES = {sample['name']: sample for sample in (CORPUS or {}).get('fixtures', [])}
VARIANTS = (CORPUS or {}).get('variants', [])
SUBMISSIONS = (CORPUS or {}).get('submissions', [])
BODY = TypeAdapter(DesignEvaluationBody)


def _python(text):
    """(parsed, accepted, canonical) for one request text, as the Python service would see it."""
    try:
        value = jsjson.parse(text)
    except ValueError:
        return False, False, None
    try:
        return True, True, canonical_json(value)
    except ValueError:
        return True, False, None


def _double(hex_bits):
    return struct.unpack('>d', bytes.fromhex(hex_bits))[0]


@needs_node
@pytest.mark.parametrize('sample', DESIGN_FIXTURES, ids=lambda sample: sample['name'])
def test_shared_fixture_parity(sample):
    node = NODE_FIXTURES[sample['name']]
    request = deepcopy(sample['request'])
    if sample['valid']:
        # A Python caller passing the decoded dict (ints stay ints) and the HTTP path (text) agree with Node.
        assert canonical_json(request) == node['canonical']
        assert _python(json.dumps(sample['request'], ensure_ascii=False)) == (True, True, node['canonical'])
        assert canonical_json(json.loads(node['canonical'])) == node['canonical']  # idempotent
    else:
        with pytest.raises(ValueError):
            normalize_design_request(request)
        assert not node['accepted']
    assert request == sample['request']  # not mutated


@needs_node
@pytest.mark.parametrize('variant', VARIANTS, ids=lambda variant: variant['name'])
def test_generated_variant_parity(variant):
    text = jsjson.decode_body(base64.b64decode(variant['bytes'])) if 'bytes' in variant else variant['text']
    parsed, accepted, canonical = _python(text)
    assert (parsed, accepted) == (variant['parsed'], variant['accepted']), variant.get('error')
    assert canonical == variant['canonical']
    if accepted:
        assert _python(canonical) == (True, True, canonical)


@needs_node
@pytest.mark.parametrize('variant', SUBMISSIONS, ids=lambda variant: variant['name'])
def test_design_submission_envelope_parity(variant):
    try:
        canonical = jsjson.stringify(canonical_submission(BODY.validate_python(jsjson.parse(variant['text']))))
    except ValueError:
        canonical = None
    assert canonical == variant['canonical'], variant.get('error')


@needs_node
def test_generated_set_covers_both_outcomes():
    names = {variant['name'].split('-')[0] for variant in VARIANTS}
    assert {'spacing', 'noise', 'prior', 'robustness', 'head', 'scenario', 'combo', 'name', 'bytes'} <= names
    assert 200 < sum(variant['accepted'] for variant in VARIANTS) < len(VARIANTS)


@needs_node
def test_number_spelling_matches_json_stringify():
    mismatches = [(bits, text, jsjson.number_to_string(_double(bits))) for bits, text in CORPUS['numbers']
                  if jsjson.number_to_string(_double(bits)) != text]
    assert mismatches == []
    # Python's own spelling differs for many of the same values.
    assert sum(json.dumps(_double(bits)) != text for bits, text in CORPUS['numbers']) > len(CORPUS['numbers']) // 4


@needs_node
def test_hypot_matches_v8_bit_for_bit():
    rows = [([_double(b) for b in row[:3]], _double(row[3])) for row in CORPUS['hypot']]
    assert [d for d, expected in rows if struct.pack('>d', jsjson.hypot(*d)) != struct.pack('>d', expected)] == []
    # math.hypot is correctly rounded and so differs from V8's Kahan sum in the last bit for some inputs.
    assert any(math.hypot(*d) != expected for d, expected in rows)


@needs_node
def test_significant_digit_and_rounding_rules_match():
    assert [b for b, expected in CORPUS['precision'] if jsjson.equals_to_precision(_double(b), 4) != expected] == []
    for b, expected, rounded in CORPUS['round2']:
        value = _double(b)
        assert jsjson.round_half_up(value * 100) == _double(rounded)
        assert (jsjson.round_half_up(value * 100) / 100 == value) == expected
    # Python's round() is half-even and so is not Math.round.
    assert round(0.5) != jsjson.round_half_up(0.5)


def test_utf16_slice_and_quote_follow_javascript():
    name = 'a' + '\U0001F600' * 60
    sliced = jsjson.slice_utf16(name, 100)
    assert len(sliced) == 51 and sliced[-1] == '\ud83d'  # 'a', 49 emoji, then the lone high surrogate of the 50th
    assert name[:100] != sliced
    assert jsjson.quote(sliced).endswith('\\ud83d"')
    assert jsjson.quote(' \x7f\x00\x1f"\\') == '" \x7f\\u0000\\u001f\\"\\\\"'
    with pytest.raises(ValueError):
        jsjson.parse('NaN')
    with pytest.raises(ValueError):
        jsjson.parse('﻿{}')
