"""The layout key of design 0004 is computed by the interface, the Node host and the Python service: the three must
spell every number the same way, so equal coordinates give equal keys."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from eeglayoutlab.schemas import jsjson
from eeglayoutlab.schemas.layout_key import layout_key

from .key_parity_support import needs_node

ROOT = Path(__file__).resolve().parents[2]
CASES = [
    ([[1.0, -0.0, 1e-7], [0.1 + 0.2, 123456789.123, 5e21]], [0, 1]),
    ([[-71.2345678901234, 12.5, 1e-21], [100.0, 0.000001, -3.4]], [0.0, 2.0]),
]

NODE = """
import { createHash } from 'node:crypto';
import { layoutKeyText } from %s;
const cases = JSON.parse(process.argv[1]);
console.log(JSON.stringify(cases.map(([xyz, regions]) => createHash('sha256').update(layoutKeyText(xyz, regions)).digest('hex'))));
"""


@needs_node
def test_node_and_python_give_one_key():
    text = jsjson.stringify(CASES)
    script = NODE % json.dumps(str(ROOT / 'webapp/contracts/layout-key.mjs'))
    out = subprocess.run(['node', '--input-type=module', '-e', script, text], capture_output=True, text=True,
                         check=True).stdout
    python = [layout_key(*case) for case in jsjson.parse(text)]
    assert json.loads(out) == python
    assert len(set(python)) == len(CASES)


def test_key_is_the_digest_of_the_design_members_in_order():
    xyz, regions = [[1.5, 2.0, 3.25]], [0.0]
    assert layout_key(xyz, regions) == jsjson.sha256_hex({'xyz_mm': xyz, 'region_indices': regions})
    assert jsjson.stringify({'xyz_mm': xyz, 'region_indices': regions}) == '{"xyz_mm":[[1.5,2,3.25]],"region_indices":[0]}'
