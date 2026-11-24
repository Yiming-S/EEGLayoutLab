"""The job routes under test (test_compute_routes.py, tests/service/README.md): a synthetic root whose radius worker
is a fake, the service started with its lifespan, and Node's composed service over the same root.

``FAKE_WORKER`` replaces ``scripts/run_local_radius_compute.py``. It reads the request on stdin, as the real worker
does, and plays the step of ``R/fake-radius-plan.json`` for it (keyed ``<region_count>/<radius_mm>/<mode>``):
stdout lines, a stderr text, a wait (``hold`` seconds, until it is stopped), then a result line and an exit status.
A result echoes the request it was given unless the step is ``stale``. Both hosts run the same script with the
same interpreter, so the records they write can be compared.

``compute_root`` builds the root: the radius code (``library_support.code_tree``), the fake worker, the forward
inputs and the plan; the results it plans carry a provenance that ``InputIntegrity.verify`` accepts and whose
``code_sha256`` is the root's code identity. ``serving`` starts ``create_app`` with its lifespan on a workspace (a
TestClient used as a context manager runs the ASGI lifespan, so the queue starts and recovers; leaving it stops the
running worker and writes the queue once more).

``run_node`` runs ``parity/compute_routes.mjs`` (its header documents the steps) over a root; ``run_python`` runs the
same steps through the Python application; ``masked`` puts both answers in the compared form.
"""
from __future__ import annotations

import contextlib
import dataclasses
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any, Iterator, Optional

from eeglayoutlab.jobs.radius import WORKER_SCRIPT, RadiusCache, code_identity
from eeglayoutlab.jobs.runtime import runtime_config
from eeglayoutlab.schemas import jsjson
from eeglayoutlab.server.app import Service, create_app

from .key_parity_support import NODE_ENV
from .library_support import code_tree, forward_inputs, radius_result, write
from .service_support import TOKENS, loopback_client, service_config

ROOT = Path(__file__).resolve().parents[2]
DRIVER = ROOT / 'tests/service/parity/compute_routes.mjs'
PLAN = 'fake-radius-plan.json'
SETTLE = 30.0  # seconds a job may take to settle under load before a test fails
HOLD = 120  # seconds a held worker waits; it is always stopped before that

FAKE_WORKER = r'''import json
import os
import sys
import time

request = json.loads(sys.stdin.read())
with open(os.path.join(os.getcwd(), 'fake-radius-plan.json'), encoding='utf-8') as handle:
    plan = json.load(handle)
step = plan['%s/%s/%s' % (request['region_count'], request['radius_mm'], request['mode'])]
for line in step.get('stdout', []):
    sys.stdout.write(line + '\n')
    sys.stdout.flush()
if step.get('stderr'):
    sys.stderr.write(step['stderr'])
    sys.stderr.flush()
if step.get('hold'):
    time.sleep(step['hold'])
if 'result' in step:
    result = step['result']
    if not step.get('stale'):
        result['request'] = request
    sys.stdout.write(json.dumps({'type': 'result', 'result': result}, ensure_ascii=False) + '\n')
    sys.stdout.flush()
sys.exit(step.get('exit', 0))
'''

# The planned requests: a completed layout with progress, no layout, a crash, a held worker, a result for another
# request.
REQUESTS = {
    'done': {'region_count': 2, 'radius_mm': 35, 'mode': 'preset', 'mask_codes': ['PL', 'PR']},
    'none': {'region_count': 1, 'radius_mm': 15, 'mode': 'whole_surface'},
    'crash': {'region_count': 3, 'radius_mm': 50, 'mode': 'whole_surface'},
    'hold': {'region_count': 4, 'radius_mm': 50, 'mode': 'whole_surface'},
    'stale': {'region_count': 2, 'radius_mm': 40, 'mode': 'preset', 'mask_codes': ['PL', 'PR']},
    'second-hold': {'region_count': 6, 'radius_mm': 50, 'mode': 'whole_surface'},
}
TERMINAL = ('completed', 'no_layout', 'failed', 'cancelled', 'timeout')


def plan_key(request: dict) -> str:
    return f"{request['region_count']}/{request['radius_mm']}/{request['mode']}"


def progress(value: float, stage: str, message: str) -> str:
    return jsjson.stringify({'type': 'progress', 'progress': value, 'stage': stage, 'message': message})


def compute_root(root: Path) -> dict:
    """Builds the root; returns the provenance of its planned results."""
    code_tree(root)
    write(root, WORKER_SCRIPT, FAKE_WORKER)
    provenance = {**forward_inputs(root), 'code_sha256': code_identity(str(root))}
    hold = {'stdout': [progress(0.25, 'geometry', '构建候选区域')], 'hold': HOLD}
    steps = {
        'done': {'stdout': [progress(0.25, 'geometry', '构建候选区域'), 'plain log line',
                            progress(0.75, 'optimize', '优化布局')],
                 'stderr': 'warning: 中文\n', 'result': radius_result(REQUESTS['done'], provenance)},
        'none': {'result': radius_result(REQUESTS['none'], provenance, status='no_layout')},
        'crash': {'stderr': 'Traceback: boom\n', 'exit': 1},
        'hold': hold,
        'second-hold': hold,
        'stale': {'result': radius_result(REQUESTS['done'], provenance), 'stale': True},
    }
    write(root, PLAN, {plan_key(REQUESTS[name]): step for name, step in steps.items()})
    return provenance


def key_of(root: Path, request: dict) -> str:
    """The radius key of ``request`` on ``root`` (the service's identity: code files, threads, runtime)."""
    from eeglayoutlab.jobs.radius import normalize_request

    return RadiusCache(str(root), sys.executable).identity_for(normalize_request(request))[1]


def json_body(response: Any) -> Any:
    return jsjson.parse(response.text)


@contextlib.contextmanager
def serving(root: Path, workspace: Path, *, cache_only: bool = False, clear_interrupted: bool = False,
            radius_options: Optional[dict] = None, queue_options: Optional[dict] = None,
            csrf: bool = True) -> Iterator[tuple[Service, Any]]:
    """The application on ``root`` and ``workspace`` with its lifespan running, and a loopback client that holds
    the session cookie (and sends the CSRF token unless ``csrf`` is false)."""
    config = dataclasses.replace(service_config(root, None, workspace),
                                 runtime=runtime_config(str(root), sys.executable, env={}),
                                 cache_only=cache_only, clear_interrupted=clear_interrupted)
    app = create_app(config)
    app.compute.radius_options.update(radius_options or {})
    app.compute.queue_options.update(queue_options or {})
    client = loopback_client(app, csrf=csrf)
    with client:
        yield app, client


def post(client: Any, path: str, body: Any = None, **headers: str) -> Any:
    data = body if isinstance(body, (bytes, str)) or body is None else jsjson.stringify(body)
    return client.post(path, content=data, headers={'content-type': 'application/json', **headers})


def poll(client: Any, id: str, statuses: tuple[str, ...] = TERMINAL, limit: float = SETTLE,
         kind: str = 'local-compute') -> dict:
    """The receipt's view once its status is one of ``statuses``."""
    deadline = time.monotonic() + limit
    while True:
        response = client.get(f'/api/{kind}/jobs/{id}')
        assert response.status_code == 200, response.text
        job = json_body(response)['job']
        if job['status'] in statuses:
            return job
        if time.monotonic() > deadline:
            raise AssertionError(f'the job did not reach {statuses}: {job}')
        time.sleep(0.02)


def wait_for(check: Any, limit: float = SETTLE) -> None:
    deadline = time.monotonic() + limit
    while not check():
        if time.monotonic() > deadline:
            raise AssertionError('the service did not settle')
        time.sleep(0.02)


def queue_file(workspace: Path) -> dict:
    return jsjson.parse((workspace / '.eeglayoutlab/queue.json').read_text(encoding='utf-8'))


def write_queue(workspace: Path, state: dict) -> None:
    (workspace / '.eeglayoutlab/queue.json').write_text(jsjson.stringify(state), encoding='utf-8')


def jobs_tree(root: Path) -> dict[str, str]:
    """``R/results/v2/local_app_jobs`` as ``{relative path: text}``."""
    base = root / 'results/v2/local_app_jobs'
    if not base.exists():
        return {}
    return {str(path.relative_to(base)): path.read_text(encoding='utf-8')
            for path in sorted(base.rglob('*')) if path.is_file()}


# --- Parity with Node's composed service --------------------------------------------------------------------------

# The steps both hosts run (parity/compute_routes.mjs documents them). {N} in a path is the id of the N-th receipt
# (by first appearance) of the answers so far.
STEPS: list[dict] = [
    {'method': 'GET', 'path': '/api/local-compute/health'},
    {'method': 'GET', 'path': '/api/community/status'},
    {'method': 'POST', 'path': '/api/local-compute/lookup', 'body': REQUESTS['done']},
    {'method': 'POST', 'path': '/api/local-compute/jobs', 'body': REQUESTS['done']},
    {'method': 'GET', 'path': '/api/local-compute/jobs/{0}', 'until': TERMINAL},
    {'method': 'POST', 'path': '/api/local-compute/jobs', 'body': REQUESTS['done']},
    {'method': 'POST', 'path': '/api/local-compute/lookup', 'body': REQUESTS['done']},
    {'method': 'POST', 'path': '/api/local-compute/jobs', 'body': REQUESTS['none']},
    {'method': 'GET', 'path': '/api/local-compute/jobs/{1}', 'until': TERMINAL},
    {'method': 'POST', 'path': '/api/local-compute/jobs', 'body': REQUESTS['crash']},
    {'method': 'GET', 'path': '/api/local-compute/jobs/{2}', 'until': TERMINAL},
    {'method': 'POST', 'path': '/api/local-compute/jobs', 'body': REQUESTS['stale']},
    {'method': 'GET', 'path': '/api/local-compute/jobs/{3}', 'until': TERMINAL},
    {'method': 'POST', 'path': '/api/local-compute/jobs', 'body': REQUESTS['hold']},
    {'method': 'GET', 'path': '/api/local-compute/jobs/{4}', 'until': ('running',), 'progress': True},
    {'method': 'POST', 'path': '/api/local-compute/jobs', 'body': REQUESTS['hold']},
    {'method': 'POST', 'path': '/api/local-compute/lookup', 'body': REQUESTS['hold']},
    {'method': 'POST', 'path': '/api/local-compute/jobs', 'body': REQUESTS['second-hold']},
    {'method': 'GET', 'path': '/api/local-compute/health'},
    {'method': 'POST', 'path': '/api/local-compute/jobs/{5}/cancel'},
    {'method': 'POST', 'path': '/api/local-compute/jobs/{4}/cancel'},
    {'method': 'GET', 'path': '/api/local-compute/jobs/{4}', 'until': TERMINAL},
    {'method': 'POST', 'path': '/api/local-compute/jobs/{4}/cancel'},
    {'method': 'GET', 'path': '/api/local-compute/jobs/{0}'},
    {'method': 'GET', 'path': '/api/local-compute/jobs/{0}?annotation_id=' + 'a' * 64},
    {'method': 'GET', 'path': '/api/local-compute/jobs/{0}?other=1'},
    {'method': 'GET', 'path': '/api/local-compute/jobs/{0}?annotation_id=ABC'},
    {'method': 'GET', 'path': '/api/local-compute/jobs/00000000-0000-4000-8000-000000000000'},
    {'method': 'POST', 'path': '/api/local-compute/jobs/00000000-0000-4000-8000-000000000000/cancel'},
    {'method': 'POST', 'path': '/api/local-compute/lookup', 'body': {**REQUESTS['none'], 'AR': 0.9}},
    {'method': 'POST', 'path': '/api/local-compute/lookup', 'raw': '{"region_count":'},
    {'method': 'POST', 'path': '/api/local-compute/lookup', 'raw': '{}', 'type': 'text/plain'},
    {'method': 'POST', 'path': '/api/local-compute/jobs', 'raw': ' ' * 4097},
    {'method': 'POST', 'path': '/api/local-compute/jobs', 'body': REQUESTS['none'], 'token': False},
    {'method': 'POST', 'path': '/api/local-compute/jobs/{0}/cancel', 'token': False},
    {'method': 'GET', 'path': '/api/local-compute/library'},
    {'method': 'GET', 'path': '/api/community/status'},
]
_ID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
_TIME = re.compile(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z')
# The members only Node has, its public-service machinery: the visitor count of the status, and the public library's
# ``visibility`` (on rows) and ``library_scope`` (test_library_parity.py removes them the same way).
_NODE_ONLY = ('online_visitors', 'visibility', 'library_scope')


def _ids(text: str, ids: list[str]) -> None:
    for id in _ID.findall(text):
        if id not in ids:
            ids.append(id)


def _strip(value: Any) -> Any:
    if isinstance(value, dict):
        return {name: _strip(member) for name, member in value.items() if name not in _NODE_ONLY}
    if isinstance(value, list):
        return [_strip(member) for member in value]
    return value


def masked(answers: list[dict], token: str) -> list[dict]:
    """Receipt and job ids numbered by first appearance, times and the CSRF token masked, Node's visitor count
    dropped; bodies re-serialized with ``JSON.stringify`` so that member order still counts."""
    ids: list[str] = []
    for answer in answers:
        _ids(answer['body'], ids)
    out = []
    for answer in answers:
        text = answer['body'].replace(token, '<token>')
        try:
            text = jsjson.stringify(_strip(jsjson.parse(text)))
        except Exception:  # noqa: BLE001 - a body that is not JSON is compared as it is
            pass
        text = _ID.sub(lambda match: f'<id{ids.index(match.group(0))}>', text)
        text = _TIME.sub('<time>', text)
        out.append({**answer, 'body': text})
    return out


def masked_tree(tree: dict[str, str]) -> dict[str, str]:
    """A record tree with batch and job ids and times masked; keys are kept."""
    ids: list[str] = []
    for path in tree:
        _ids(path, ids)
    out = {}
    for path, text in tree.items():
        name = _ID.sub(lambda match: f'<id{ids.index(match.group(0))}>', path)
        out[name] = _TIME.sub('<time>', _ID.sub('<job>', text))
    return out


def run_node(root: Path, scratch: Path, steps: list[dict] = STEPS) -> dict:
    """Node's composed service (``createLocalComputeService``) over ``root`` with its state in ``scratch``."""
    spec = scratch / 'spec.json'
    out = scratch / 'out.json'
    spec.write_text(json.dumps({'root': str(root), 'queueDirectory': str(scratch / 'queue'),
                                'python': sys.executable, 'owner': 'parity-owner', 'steps': steps,
                                'terminal': list(TERMINAL), 'settle_ms': SETTLE * 1000}), encoding='utf-8')
    subprocess.run(['node', str(DRIVER), str(spec), str(out)], check=True, env=NODE_ENV, timeout=300)
    return json.loads(out.read_text(encoding='utf-8'))


def _target(path: str, ids: list[str]) -> str:
    return re.sub(r'\{(\d+)\}', lambda match: ids[int(match.group(1))], path)


def run_python(root: Path, workspace: Path, steps: list[dict] = STEPS) -> dict:
    """The same steps through the Python application, as the driver sends them: ``{N}`` is the N-th distinct id
    in the bodies so far, POSTs carry the CSRF token unless the step says ``token: false``, a step with ``until``
    is repeated until its job reaches one of those statuses (with ``progress``, a progress above 0)."""
    answers: list[dict] = []
    ids: list[str] = []
    with serving(root, workspace, csrf=False) as (app, client):
        for step in steps:
            target = _target(step['path'], ids)
            headers = {}
            if step['method'] == 'POST':
                headers['content-type'] = step.get('type', 'application/json')
                if step.get('token', True):
                    headers['x-eeg-compute-token'] = TOKENS.csrf
            data = step['raw'] if 'raw' in step else jsjson.stringify(step['body']) if 'body' in step else None
            deadline = time.monotonic() + SETTLE
            while True:
                response = client.request(step['method'], target, content=data, headers=headers)
                body = response.text
                until = step.get('until')
                if until is None:
                    break
                job = jsjson.parse(body)['job']
                if job['status'] in until and (not step.get('progress') or job['progress'] > 0):
                    break
                if time.monotonic() > deadline:
                    raise AssertionError(f'{target} did not settle: {body}')
                time.sleep(0.02)
            _ids(body, ids)
            answers.append({'method': step['method'], 'path': step['path'], 'status': response.status_code,
                            'type': response.headers.get('content-type'), 'body': body})
    return {'answers': answers, 'token': TOKENS.csrf, 'tree': jobs_tree(root), 'queue': queue_file(workspace)}
