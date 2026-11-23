"""``GET /api/<kind>/health`` (phase 2 slice 2): the same bytes as Node's real service on the same synthetic root,
except the token value (``parity/health.mjs``)."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess

import pytest

from .key_parity_support import needs_node, require

require('fastapi')
require('httpx')

from eeglayoutlab.server.routes.health import KINDS, MASK_CODES  # noqa: E402

from .service_support import TOKENS, loopback_client, make_app, synthetic_root  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DRIVER = ROOT / 'tests/service/parity/health.mjs'
TOKEN = re.compile(r'"token":"[0-9a-f]{64}"')
COMPARED_HEADERS = ('content-type', 'cache-control', 'x-content-type-options', 'cross-origin-resource-policy',
                    'x-eeg-api-version')


def masked(body: str) -> str:
    assert len(TOKEN.findall(body)) == 1, body
    return TOKEN.sub('"token":"<token>"', body)


def tree(path: Path) -> dict[str, bytes]:
    return {entry.relative_to(path).as_posix(): entry.read_bytes()
            for entry in sorted(path.rglob('*')) if entry.is_file()}


def node_health(root: Path, scratch: Path) -> dict:
    queue, out = scratch / 'node-queue', scratch / 'node-health.json'
    env = {name: value for name, value in os.environ.items() if not name.startswith('EEG_')}
    subprocess.run(['node', str(DRIVER), str(root), str(queue), str(out)], check=True, cwd=ROOT, env=env, timeout=120)
    return json.loads(out.read_text(encoding='utf-8'))['kinds']


@needs_node
@pytest.mark.parametrize('available', [True, False])
def test_health_matches_node_byte_for_byte_except_the_token(tmp_path, available):
    root = synthetic_root(tmp_path / 'root', available=available)
    before = tree(root)
    node = node_health(root, tmp_path)
    assert tree(root) == before, 'the Node driver must only read the root'
    client = loopback_client(make_app(root))
    assert sorted(node) == sorted(KINDS)
    for kind in KINDS:
        response = client.get(f'/api/{kind}/health')
        assert response.status_code == node[kind]['status'] == 200
        assert {name: response.headers.get(name) for name in COMPARED_HEADERS} == node[kind]['headers']
        assert masked(response.text) == masked(node[kind]['body'])
        assert response.json()['available'] is available
        assert response.json()['token'] == TOKENS.csrf


def test_health_body_in_nodes_member_order(tmp_path):
    client = loopback_client(make_app(synthetic_root(tmp_path / 'root')))
    for kind in KINDS:
        assert client.get(f'/api/{kind}/health').text == (
            '{"available":true,"local_only":true,"token":"' + TOKENS.csrf + '","max_concurrent_jobs":1,"threads":2,'
            '"timeout_seconds":180,"supported_masks":' + json.dumps(MASK_CODES, separators=(',', ':')) +
            ',"active_job":null,"maintenance":false,"drained":false}')


def test_mask_codes_are_nodes():
    text = (ROOT / 'webapp/server/local-compute-server.mjs').read_text(encoding='utf-8')
    match = re.search(r'export const MASK_CODES = (\[[^\]]*\]);', text)
    assert match and json.loads(match.group(1).replace("'", '"')) == MASK_CODES


def test_availability_is_read_per_request(tmp_path):
    root = synthetic_root(tmp_path / 'root', available=False)
    client = loopback_client(make_app(root))
    assert client.get('/api/local-compute/health').json()['available'] is False
    (root / 'scripts').mkdir()
    (root / 'scripts/run_local_radius_compute.py').write_text('', encoding='utf-8')
    assert client.get('/api/local-compute/health').json()['available'] is False
    (root / 'results/v2').mkdir(parents=True)
    # existsSync follows links: a dangling link is absent, a link to a file present.
    (root / 'results/v2/current_multiregion_bank.json').symlink_to('missing.json')
    assert client.get('/api/local-compute/health').json()['available'] is False
    (root / 'results/v2/missing.json').write_text('{}', encoding='utf-8')
    assert client.get('/api/design-evaluation/health').json()['available'] is True


def test_health_needs_the_session_cookie(tmp_path):
    app = make_app(synthetic_root(tmp_path / 'root'))
    response = loopback_client(app, authenticate=False).get('/api/local-compute/health')
    assert response.status_code == 401 and TOKENS.csrf not in response.text
