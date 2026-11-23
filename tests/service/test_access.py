"""Access control (design 0001, decision 6; phase 2 slice 2): the loopback guard, the launch token exchanged for
the session cookie, the CSRF token on writes, and the transport answers of the API (Node's 404 messages, body
limits, the generic 500). Each Node test this ports is named in its docstring.
"""
from __future__ import annotations

import errno
import json
import logging
import os
from pathlib import Path
import re
import subprocess

import pytest

from .key_parity_support import needs_node, require

require('fastapi')
require('httpx')

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from eeglayoutlab.schemas import jsjson  # noqa: E402
from eeglayoutlab.server.access import (  # noqa: E402
    FORBIDDEN, SESSION_EXPIRED, Tokens, cookie_name, loopback_request, token_matches, write_refusal,
)
from eeglayoutlab.server.app import (  # noqa: E402
    BODY_LIMITS, INTERNAL_MESSAGE, ApiError, error_response, json_response, node_fallback, read_json_body,
)
from eeglayoutlab.server.routes import health as health_module  # noqa: E402

from .service_support import (  # noqa: E402
    HOST, PORT, TOKENS, asgi_request, loopback_client, make_app, session_cookie, static_export, synthetic_root,
)

ROOT = Path(__file__).resolve().parents[2]
NODE_SERVER = ROOT / 'webapp/server'
SESSION_HELPER = ROOT / 'webapp/scripts/helpers/service-session.mjs'
COMPUTE_REFUSED = '会话已更新，请刷新页面后重新计算'


@pytest.fixture
def app(tmp_path):
    return make_app(synthetic_root(tmp_path / 'root'), static_export(tmp_path / 'static'))


@pytest.fixture
def client(app):
    return loopback_client(app)


def scope(peer='127.0.0.1', **headers):
    return {'client': (peer, 50000) if peer else None,
            'headers': [(name.replace('_', '-').encode(), value.encode('latin-1')) for name, value in headers.items()]}


def assert_error(response, status, code, message=None):
    assert response.status_code == status
    body = response.json()
    assert list(body) == ['error', 'code'] and body['code'] == code
    if message is not None:
        assert body['error'] == message
    assert response.headers['content-type'] == 'application/json; charset=utf-8'
    assert response.headers['x-eeg-api-version'] == '1' and response.headers['cache-control'] == 'no-store'


# --- The guard ----------------------------------------------------------------------------------------------

def test_local_origin_host_and_remote_address_are_all_checked():
    """check-local-compute.mjs:53 'local origin, Host and remote address are all checked'."""
    base = {'host': 'localhost:3000', 'origin': 'http://localhost:3000'}
    assert loopback_request(scope(**base))
    assert not loopback_request(scope(**{**base, 'origin': 'https://example.org'}))
    assert not loopback_request(scope(host='attacker.example:3000'))
    assert not loopback_request(scope('192.168.1.3', **base))
    assert not loopback_request(scope(**base, sec_fetch_site='cross-site'))


@pytest.mark.parametrize('peer, headers, allowed', [
    ('127.0.0.1', {'host': '127.0.0.1:41234'}, True),
    ('::1', {'host': '[::1]:41234'}, True),
    ('::ffff:127.0.0.1', {'host': 'localhost'}, True),
    ('127.0.0.1', {'host': '127.0.0.1:41234', 'origin': 'http://127.0.0.1:41234'}, True),
    ('127.0.0.1', {'host': '127.0.0.1:41234', 'origin': ''}, True),
    ('127.0.0.1', {'host': '127.0.0.1:41234', 'sec_fetch_site': 'same-origin'}, True),
    ('127.0.0.1', {'host': '127.0.0.1:41234', 'sec_fetch_site': 'none'}, True),
    ('127.0.0.1', {'host': '127.0.0.1:41234', 'sec_fetch_site': 'same-site'}, False),
    # The Host pattern is case-sensitive, ASCII and anchored, as JavaScript's.
    ('127.0.0.1', {'host': 'LOCALHOST:41234'}, False),
    ('127.0.0.1', {'host': '127.0.0.1:³'}, False),
    ('127.0.0.1', {'host': '127.0.0.1:123456'}, False),
    ('127.0.0.1', {'host': '127.0.0.1.evil.example'}, False),
    ('127.0.0.1', {}, False),
    # Origin must equal http://<Host> exactly.
    ('127.0.0.1', {'host': '127.0.0.1:41234', 'origin': 'http://localhost:41234'}, False),
    ('127.0.0.1', {'host': '127.0.0.1:41234', 'origin': 'https://127.0.0.1:41234'}, False),
    ('127.0.0.1', {'host': '127.0.0.1:41234', 'origin': 'null'}, False),
    ('10.0.0.2', {'host': '127.0.0.1:41234'}, False),
    (None, {'host': '127.0.0.1:41234'}, False),
])
def test_guard_cases(peer, headers, allowed):
    assert loopback_request(scope(peer, **headers)) is allowed


def test_guard_joins_repeated_headers_as_node_does():
    # Node keeps the first Host and joins repeated Origin and Sec-Fetch-Site values, which then never match.
    host = [(b'host', b'127.0.0.1:1'), (b'host', b'evil.example')]
    assert loopback_request({'client': ('127.0.0.1', 1), 'headers': host})
    origins = [*host[:1], (b'origin', b'http://127.0.0.1:1'), (b'origin', b'http://127.0.0.1:1')]
    assert not loopback_request({'client': ('127.0.0.1', 1), 'headers': origins})


def test_the_guard_comes_first_on_every_path(app):
    # /open with the launch token is the one cross-site navigation let through (test_open_from_the_launchers_page).
    for path in ('/api/local-compute/health', '/design', '/favicon.svg', '/open?token=' + TOKENS.session, '/nope'):
        for headers in ([('origin', 'http://evil.example')], [('sec-fetch-site', 'cross-site')]):
            reply = asgi_request(app, 'GET', path, headers)
            assert reply.status == 403
            assert reply.body == b'{"error":"Request rejected by access policy.","code":"request_forbidden"}'
            assert 'set-cookie' not in reply.headers
        assert asgi_request(app, 'GET', path, host='example.org').status == 403
        assert asgi_request(app, 'GET', path, peer='192.168.1.3').status == 403
        # Before the cookie: an unauthenticated foreign request is refused, not asked to log in.
        assert asgi_request(app, 'GET', path, [('origin', 'http://evil.example')], cookie=False).status == 403


# --- Launch token and session cookie ------------------------------------------------------------------------

def test_open_exchanges_the_launch_token_for_the_session_cookie(app):
    client = loopback_client(app, authenticate=False)
    response = client.get(f'/open?token={TOKENS.launch}')
    assert response.status_code == 303 and response.headers['location'] == '/'
    assert response.headers['set-cookie'] == f'eeglayoutlab-{PORT}={TOKENS.session}; HttpOnly; SameSite=Strict; Path=/'
    assert response.headers['cache-control'] == 'no-store' and response.content == b''
    # The launch token stays valid for the life of the process (instance reuse opens it again), and the
    # redirect target is never built from Host.
    reply = asgi_request(app, 'GET', f'/open?token={TOKENS.launch}', host='localhost:1', cookie=False)
    assert reply.status == 303 and reply.headers['location'] == '/'
    assert client.get('/design').status_code == 200


NAVIGATION = [('sec-fetch-site', 'cross-site'), ('sec-fetch-mode', 'navigate'), ('sec-fetch-dest', 'document')]


def test_open_from_the_launchers_page(app):
    # The launcher opens W/.eeglayoutlab/open.html, whose redirect to /open a browser marks cross-site. The answer
    # is a page that refreshes to /, a same-origin navigation that sends the SameSite=Strict cookie (a redirect
    # in a chain that a cross-site navigation started would not).
    for headers in (NAVIGATION, NAVIGATION[:1]):
        reply = asgi_request(app, 'GET', f'/open?token={TOKENS.launch}', headers, cookie=False)
        assert reply.status == 200 and 'location' not in reply.headers
        assert reply.headers['set-cookie'] == f'eeglayoutlab-{PORT}={TOKENS.session}; HttpOnly; SameSite=Strict; Path=/'
        assert reply.headers['content-type'] == 'text/html; charset=utf-8' and reply.headers['cache-control'] == 'no-store'
        assert reply.headers['referrer-policy'] == 'no-referrer'
        assert b'<meta http-equiv="refresh" content="0;url=/">' in reply.body
    # Only for the launch token, as a top-level navigation by GET, and with the rest of the guard.
    refused = [
        ('GET', f'/open?token={TOKENS.session}', NAVIGATION, {}),
        ('GET', '/open', NAVIGATION, {}),
        ('GET', f'/open?token={TOKENS.launch}', [*NAVIGATION[:2], ('sec-fetch-dest', 'iframe')], {}),
        ('GET', f'/open?token={TOKENS.launch}', [NAVIGATION[0], ('sec-fetch-mode', 'no-cors')], {}),
        ('GET', f'/open?token={TOKENS.launch}', [*NAVIGATION, ('origin', 'null')], {}),
        ('GET', f'/open?token={TOKENS.launch}', NAVIGATION, {'host': 'example.org'}),
        ('GET', f'/open?token={TOKENS.launch}', NAVIGATION, {'peer': '192.168.1.3'}),
        ('GET', f'/open?token={TOKENS.launch}', [('sec-fetch-site', 'same-site')], {}),
        ('HEAD', f'/open?token={TOKENS.launch}', NAVIGATION, {}),
        ('GET', f'/design?token={TOKENS.launch}', NAVIGATION, {}),
    ]
    for method, target, headers, options in refused:
        reply = asgi_request(app, method, target, headers, cookie=False, **options)
        assert reply.status == 403 and 'set-cookie' not in reply.headers, (method, target, headers, options)


@pytest.mark.parametrize('query', [
    '', '?token=', '?token', '?token=wrong', f'?token={TOKENS.launch[:-1]}', f'?token={TOKENS.launch}0',
    f'?token={TOKENS.launch.upper()}', f'?token={TOKENS.session}', f'?token={TOKENS.csrf}',
    f'?token={TOKENS.launch}&token={TOKENS.launch}', f'?token={TOKENS.launch}&x=1', f'?x=1&token={TOKENS.launch}',
    f'?TOKEN={TOKENS.launch}', '?token=%E6%96%87',
])
def test_a_bad_open_token_is_refused_without_a_cookie(app, query):
    reply = asgi_request(app, 'GET', '/open' + query, cookie=False)
    assert reply.status == 401 and 'set-cookie' not in reply.headers
    assert reply.headers['content-type'] == 'text/html; charset=utf-8' and reply.headers['cache-control'] == 'no-store'
    assert 'eeglayoutlab'.encode() in reply.body and '127.0.0.1'.encode() in reply.body


def test_open_takes_only_get(app):
    assert asgi_request(app, 'HEAD', f'/open?token={TOKENS.launch}', cookie=False).status == 405
    reply = asgi_request(app, 'POST', f'/open?token={TOKENS.launch}', [('x-eeg-compute-token', TOKENS.csrf)])
    assert reply.status == 405 and reply.headers['allow'] == 'GET' and 'set-cookie' not in reply.headers
    # A write needs the CSRF token first, on /open too.
    assert asgi_request(app, 'POST', f'/open?token={TOKENS.launch}', cookie=False).status == 403
    # Only the path as received: an encoded spelling is not /open.
    assert asgi_request(app, 'GET', f'/%6Fpen?token={TOKENS.launch}', cookie=False).status == 401


def test_without_the_cookie_the_api_and_the_pages_answer_401(app):
    client = loopback_client(app, authenticate=False)
    for path in ('/api/local-compute/health', '/api/design-evaluation/health', '/api/openapi.json', '/api/nope'):
        assert_error(client.get(path), 401, 'authentication_required', SESSION_EXPIRED)
    for path in ('/', '/design', '/favicon.svg', '/_next/static/chunks/app-3f2a.js', '/nope'):
        response = client.get(path)
        assert response.status_code == 401 and response.headers['content-type'] == 'text/html; charset=utf-8'
        assert 'eeglayoutlab' in response.text and 'http://127.0.0.1' in response.text and 'localhost' in response.text
        assert 'set-cookie' not in response.headers
    reply = asgi_request(app, 'HEAD', '/design', cookie=False)
    assert reply.status == 401 and reply.body == b'' and int(reply.headers['content-length']) > 0
    # A write without the cookie is refused for the session first, whatever its token.
    assert_error(client.post('/api/local-compute/jobs', headers={'x-eeg-compute-token': TOKENS.csrf}), 401,
                 'authentication_required')


@pytest.mark.parametrize('cookie, allowed', [
    (session_cookie(), True),
    (f'eeg-layout-language=en; {session_cookie()}; eeg_visitor=x', True),
    (f'eeglayoutlab-{PORT}=wrong; {session_cookie()}', True),
    (f'eeglayoutlab-{PORT}=wrong', False),
    (f'eeglayoutlab-{PORT}={TOKENS.launch}', False),
    (f'eeglayoutlab-{PORT}={TOKENS.session.upper()}', False),
    (f'eeglayoutlab-{PORT}={TOKENS.session}x', False),
    (f'eeglayoutlab-{PORT + 1}={TOKENS.session}', False),
    (f'eeglayoutlab={TOKENS.session}', False),
    (f'eeg_visitor={TOKENS.session}', False),
    ('', False),
])
def test_the_session_cookie_is_named_for_the_port(app, cookie, allowed):
    reply = asgi_request(app, 'GET', '/api/local-compute/health', [('cookie', cookie)] if cookie else [], cookie=False)
    assert reply.status == (200 if allowed else 401)


def test_instances_on_two_ports_keep_separate_cookies(tmp_path):
    root, static = synthetic_root(tmp_path / 'root'), static_export(tmp_path / 'static')
    first, second = make_app(root, static, port=PORT), make_app(root, static, port=PORT + 1)
    assert cookie_name(PORT) != cookie_name(PORT + 1)
    a = loopback_client(first)
    b = loopback_client(second, port=PORT + 1)
    assert set(a.cookies) == {cookie_name(PORT)} and set(b.cookies) == {cookie_name(PORT + 1)}
    # The browser sends both cookies to 127.0.0.1; each instance reads its own.
    both = f'{cookie_name(PORT + 1)}=other; {session_cookie()}'
    assert asgi_request(first, 'GET', '/design', [('cookie', both)], cookie=False).status == 200
    assert asgi_request(second, 'GET', '/design', [('cookie', both)], cookie=False).status == 401


def test_tokens_are_new_for_every_process():
    tokens = [Tokens.generate() for _ in range(3)]
    for t in tokens:
        assert all(re.fullmatch(r'[0-9a-f]{64}', value) for value in (t.launch, t.session, t.csrf))
        assert len({t.launch, t.session, t.csrf}) == 3
    assert len({t.launch for t in tokens}) == 3


# --- The CSRF token on writes ---------------------------------------------------------------------------------

def test_mutation_endpoint_requires_the_session_token_including_unicode_input(app):
    """check-local-compute.mjs:116 'mutation endpoint requires the random local-session token, including unicode
    input'."""
    for token in (None, 'wrong', '文' * 64):
        assert not token_matches(token, TOKENS.csrf)
        headers = [] if token is None else [('x-eeg-compute-token', token.encode('utf-8'))]
        reply = asgi_request(app, 'POST', '/api/local-compute/jobs', [('content-type', 'application/json'), *headers],
                             b'{}')
        assert reply.status == 403
        assert reply.body == ('{"error":"' + COMPUTE_REFUSED + '","code":"request_forbidden"}').encode()


def test_http_enforces_same_origin_and_token(client):
    """check-community-queue.mjs:138 'HTTP enforces same-origin, token, cookie ownership; stats never expose IP or
    other receipts': the origin and token parts. Cookie ownership and visitor statistics are not carried over."""
    headers = {'x-eeg-compute-token': TOKENS.csrf, 'content-type': 'application/json'}
    # With the token the request passes access control; the queue endpoint itself arrives in slice 4.
    assert_error(client.post('/api/local-compute/jobs', headers=headers, content=b'{"n":1}'), 404, 'not_found',
                 'Unknown queue endpoint')
    assert_error(client.post('/api/local-compute/jobs', content=b'{}'), 403, 'request_forbidden', COMPUTE_REFUSED)
    assert_error(client.get('/api/local-compute/health', headers={'origin': 'http://evil.example'}), 403,
                 'request_forbidden', FORBIDDEN)


def test_editor_endpoint_retains_loopback_and_session_token_protection(app):
    """check-electrode-editor.mjs:52 'new local endpoint retains loopback and session-token protection'."""
    for peer, message in (('192.168.1.1', FORBIDDEN), ('127.0.0.1', COMPUTE_REFUSED)):
        reply = asgi_request(app, 'POST', '/api/electrode-editor/jobs', peer=peer)
        assert reply.status == 403
        assert reply.body == ('{"error":"' + message + '","code":"request_forbidden"}').encode()


def test_source_api_shares_local_origin_and_session_token_protections(app):
    """check-source-reception.mjs:287 'source API shares existing local-origin and session-token protections'."""
    for peer, token in (('127.0.0.1', None), ('127.0.0.1', 'bad'), ('192.168.1.4', TOKENS.csrf)):
        headers = [] if token is None else [('x-eeg-compute-token', token)]
        reply = asgi_request(app, 'POST', '/api/source-reception/jobs', headers, b'{}', peer=peer)
        assert reply.status == 403 and reply.headers['content-type'] == 'application/json; charset=utf-8'


@pytest.mark.parametrize('value', [
    TOKENS.csrf.upper(), TOKENS.csrf[:-1], TOKENS.csrf + '0', ' ' + TOKENS.csrf, TOKENS.launch, TOKENS.session,
    f'{TOKENS.csrf}, {TOKENS.csrf}', '0' * 64,
])
def test_token_matches_follows_node(value):
    assert not token_matches(value, TOKENS.csrf)
    assert token_matches(TOKENS.csrf, TOKENS.csrf)
    assert not token_matches(b'x', TOKENS.csrf) and not token_matches(1, TOKENS.csrf)


@pytest.mark.parametrize('path, message', [
    ('/api/local-compute/jobs', COMPUTE_REFUSED),
    ('/api/local-compute/library/' + 'a' * 64 + '/visibility', COMPUTE_REFUSED),
    ('/api/design-evaluation/lookup', COMPUTE_REFUSED),
    ('/api/source-reception/jobs/' + 'a' * 36 + '/cancel', COMPUTE_REFUSED),
    ('/api/electrode-editor/jobs', COMPUTE_REFUSED),
    ('/api/normalize/design-evaluation', COMPUTE_REFUSED),
    ('/api/projects', 'Refresh the page before saving the project.'),
    ('/api/projects/' + 'a' * 36 + '/entries', 'Refresh the page before saving the project.'),
    ('/api/robustness-studies', 'Refresh the page before changing a study.'),
    ('/api/robustness-studies/' + 'a' * 36 + '/start', 'Refresh the page before changing a study.'),
    ('/api/community/heartbeat', '刷新页面后重试'),
    ('/design', COMPUTE_REFUSED),
])
@pytest.mark.parametrize('method', ['POST', 'PATCH', 'PUT', 'DELETE'])
def test_every_write_needs_the_csrf_token_with_the_route_message(app, path, message, method):
    assert write_refusal(path) == message
    reply = asgi_request(app, method, path, [('content-type', 'application/json')], b'{}')
    assert reply.status == 403
    assert reply.body == jsjson.stringify({'error': message, 'code': 'request_forbidden'}).encode()


def test_write_messages_are_node_messages():
    sources = {
        COMPUTE_REFUSED: ['community-queue.mjs', 'local-compute-server.mjs'],
        'Refresh the page before saving the project.': ['projects/service.mjs'],
        'Refresh the page before changing a study.': ['studies/service.mjs'],
        '刷新页面后重试': ['community-queue.mjs'],
        FORBIDDEN: ['community-queue.mjs', 'local-compute-server.mjs', 'projects/service.mjs'],
    }
    for message, files in sources.items():
        for name in files:
            assert message in (NODE_SERVER / name).read_text(encoding='utf-8'), (message, name)


def test_reads_never_need_the_csrf_token(client):
    for path in ('/api/local-compute/health', '/api/openapi.json', '/design', '/favicon.svg'):
        assert client.get(path).status_code == 200
    assert client.head('/design').status_code == 200


def test_a_write_with_the_token_reaches_routing(client):
    headers = {'x-eeg-compute-token': TOKENS.csrf}
    response = client.post('/design', headers=headers)
    assert response.status_code == 405 and response.headers['allow'] == 'GET, HEAD'
    assert_error(client.post('/api/nope', headers=headers), 404, 'not_found', 'Not Found')
    assert_error(client.post('/api/local-compute/health', headers=headers), 404, 'not_found', 'Unknown queue endpoint')


# --- The production host, mapped to serve ---------------------------------------------------------------------

def test_production_host_preserves_ui_routing_and_local_api_guards(app, client):
    """check-local-production.mjs:8 'production host preserves UI routing, local API guards and disposal', mapped
    to ``eeglayoutlab serve`` (disposal: tests/service/test_workspace.py, the runtime file is removed on SIGTERM)."""
    page = client.get('/design')
    assert page.status_code == 200 and page.text == '<!doctype html><title>design</title>'
    response = client.get('/api/local-compute/health')
    assert response.headers['x-eeg-api-version'] == '1'
    health = response.json()
    assert health['local_only'] is True and isinstance(health['token'], str)
    assert client.get('/api/local-compute/health', headers={'origin': 'https://example.org'}).status_code == 403
    rejected = client.post('/api/local-compute/jobs')
    assert rejected.status_code == 403
    failure = rejected.json()
    assert failure['code'] == 'request_forbidden' and isinstance(failure['error'], str)
    assert asgi_request(app, 'GET', '/api/local-compute/health', host='example.org').status == 403


# --- Transport: fallbacks, limits and failures ---------------------------------------------------------------

@pytest.mark.parametrize('path, message', [
    ('/api/local-compute/unknown', '未知计算接口'),
    ('/api/local-computeX', '未知计算接口'),
    ('/api/local-compute', '未知计算接口'),
    ('/api/local-compute/library', '未知计算接口'),
    ('/api/design-evaluation/heads/x', '未知设计评价接口'),
    ('/api/source-reception/unknown', '未知源实验接口'),
    ('/api/electrode-editor/unknown', 'Unknown editor endpoint'),
    ('/api/local-compute/jobs', 'Unknown queue endpoint'),
    ('/api/design-evaluation/lookup', 'Unknown queue endpoint'),
    ('/api/electrode-editor/jobs/' + '0' * 36, 'Unknown queue endpoint'),
    ('/api/source-reception/jobs/' + '0' * 36 + '/cancel', 'Unknown queue endpoint'),
    ('/api/source-reception/jobs/' + '0' * 35, '未知源实验接口'),
    ('/api/community/status', 'Unknown community endpoint'),
    ('/api/projects/bad', 'Project endpoint not found.'),
    ('/api/robustness-studies/bad', 'Study not found.'),
    ('/api/unknown', 'Not Found'),
    ('/api/community', 'Not Found'),
    ('/api/projectsX', 'Not Found'),
])
def test_unknown_api_paths_get_nodes_message_per_prefix(client, path, message):
    assert node_fallback(path) == (None if message == 'Not Found' else message)
    assert_error(client.get(path), 404, 'not_found', message)


def test_fallback_messages_are_node_messages():
    for name, messages in {
        'community-queue.mjs': ['Unknown queue endpoint', 'Unknown community endpoint'],
        'local-compute-server.mjs': ['未知计算接口'], 'design-evaluation-server.mjs': ['未知设计评价接口'],
        'source-reception-server.mjs': ['未知源实验接口'], 'electrode-editor-server.mjs': ['Unknown editor endpoint'],
        'projects/service.mjs': ['Project endpoint not found.'], 'studies/service.mjs': ['Study not found.'],
    }.items():
        text = (NODE_SERVER / name).read_text(encoding='utf-8')
        assert all(f"'{message}'" in text or f'"{message}"' in text for message in messages), name


def test_other_methods_on_the_health_routes_are_unknown_queue_endpoints(app, client):
    for method in ('HEAD', 'OPTIONS'):
        response = client.request(method, '/api/local-compute/health')
        assert response.status_code == 404
    assert_error(client.options('/api/source-reception/health'), 404, 'not_found', 'Unknown queue endpoint')
    # An encoded spelling of a route is not that route; it is still under Node's prefix.
    reply = asgi_request(app, 'GET', '/api/local-compute/he%61lth')
    assert reply.status == 404 and reply.body == '{"error":"未知计算接口","code":"not_found"}'.encode()


def test_body_limits_are_nodes_per_kind():
    text = (NODE_SERVER / 'community-queue.mjs').read_text(encoding='utf-8')
    match = re.search(r"const limit = kind === 'design-evaluation' \? (\d+) : "
                      r"kind === 'electrode-editor' \? (\d+) : (\d+);", text)
    assert match, 'the Node limit expression changed'
    design, editor, other = map(int, match.groups())
    assert BODY_LIMITS == {'design-evaluation': design, 'electrode-editor': editor, 'local-compute': other,
                           'source-reception': other}


@pytest.mark.parametrize('kind', sorted(BODY_LIMITS))
def test_read_json_body_takes_the_route_limit(kind):
    limit = BODY_LIMITS[kind]
    api = FastAPI()

    @api.exception_handler(ApiError)
    async def failed(_, error):
        return error_response(error.status, error.message)

    @api.post('/body')
    async def body(request: Request):
        return json_response(200, {'value': await read_json_body(request, limit)})

    client = TestClient(api)
    padded = lambda n: b'{"a":"' + b'x' * (n - 8) + b'"}'  # noqa: E731
    assert client.post('/body', content=padded(limit), headers={'content-type': 'application/json'}).status_code == 200
    too_large = client.post('/body', content=padded(limit + 1), headers={'content-type': 'application/json'})
    assert too_large.status_code == 413 and too_large.json() == {'error': '配置过大', 'code': 'request_too_large'}
    # 415 before 413, as in Node.
    wrong = client.post('/body', content=padded(limit + 1), headers={'content-type': 'text/plain'})
    assert wrong.status_code == 415 and wrong.json()['error'] == 'JSON required'
    assert client.post('/body', content=b'{', headers={'content-type': 'application/json'}).json()['error'] == \
        '请求内容不是有效的JSON'


@pytest.mark.parametrize('fault', [
    OSError(errno.ENOENT, 'No such file or directory', '/srv/eeg/results/v2/current_multiregion_bank.json'),
    TypeError('x is undefined'),
    RecursionError('maximum recursion depth exceeded'),
])
def test_server_faults_are_generic_500s_and_paths_never_reach_the_browser(client, monkeypatch, caplog, fault):
    """check-abuse-limits.mjs:110 'server faults are generic 500s and paths never reach visitors': an unexpected
    exception is a 500 with Node's generic message, and the details go to the service log. Path redaction in
    worker messages (``redactPaths``) is not carried over (phase 2 plan, section 5)."""
    def broken(root):
        raise fault

    monkeypatch.setattr(health_module, 'available', broken)
    with caplog.at_level(logging.ERROR, logger='eeglayoutlab.server'):
        response = client.get('/api/local-compute/health')
    assert_error(response, 500, 'internal_error', INTERNAL_MESSAGE)
    assert '/srv' not in response.text and 'undefined' not in response.text
    assert any(record.exc_info and record.exc_info[1] is fault for record in caplog.records)


@pytest.mark.parametrize('status, code, message', [
    (400, 'invalid_request', '区域数只支持1、2、3、4、6'), (429, 'queue_limited', '队列已满'),
])
def test_a_status_error_keeps_its_status_and_message(client, monkeypatch, status, code, message):
    """check-abuse-limits.mjs:110, the other half: a refusal with a status keeps its status and message (Node
    gives a plain ``Error`` 400; the service raises ``ApiError``)."""
    def refused(root):
        raise ApiError(status, message)

    monkeypatch.setattr(health_module, 'available', refused)
    assert_error(client.get('/api/local-compute/health'), status, code, message)


def test_a_fault_outside_the_api_is_a_generic_500(app, client, monkeypatch, caplog):
    def broken(*args):
        raise PermissionError(errno.EACCES, 'Permission denied', '/srv/eeg/webapp/dist/client/design.html')

    monkeypatch.setattr(type(app.static), '_file', broken)
    with caplog.at_level(logging.ERROR, logger='eeglayoutlab.server'):
        response = client.get('/design')
    assert_error(response, 500, 'internal_error', INTERNAL_MESSAGE)
    assert any('internal error' in record.getMessage() for record in caplog.records)


def test_the_test_client_is_a_loopback_browser(client):
    # The helper itself: the peer, Host and cookie a browser on 127.0.0.1 sends.
    assert client.base_url.host == '127.0.0.1' and f'127.0.0.1:{client.base_url.port}' == HOST
    assert client.cookies.get(cookie_name(PORT)) == TOKENS.session


@needs_node
def test_the_script_helper_sends_the_secrets_to_127_0_0_1_only():
    # The service and Vite listen on 127.0.0.1 only. Node connects to localhost's ::1 first, where another local
    # user may listen on the same port, so neither the helper nor the Vite proxy (which uses serviceOrigin) takes
    # localhost or [::1]; nothing is sent before the check.
    script = f"""
import {{ openServiceSession, serviceOrigin }} from {json.dumps(SESSION_HELPER.as_uri())};
const verdict = (call) => {{ try {{ return call(); }} catch (error) {{ return 'refused: ' + error.message; }} }};
const values = ['http://127.0.0.1:8765', 'http://127.0.0.1:8765/x?y', 'http://localhost:8765', 'http://[::1]:8765',
  'http://LOCALHOST:8765', 'http://127.1:8765', 'https://127.0.0.1:8765', 'http://user:pw@127.0.0.1:8765', undefined];
const results = values.map(value => [verdict(() => serviceOrigin(value)),
  verdict(() => serviceOrigin(value, {{ exact: true, name: 'EEG_API_TARGET' }}))]);
const sessions = [];
for (const base of ['http://localhost:9', 'http://[::1]:9']) {{
  sessions.push(await openServiceSession({{ token: 'f'.repeat(64), base }}).then(() => 'opened', error => error.message));
}}
console.log(JSON.stringify({{ results, sessions }}));
"""
    env = {name: value for name, value in os.environ.items() if not name.startswith('EEG_')}
    output = subprocess.run(['node', '--input-type=module', '-e', script], check=True, capture_output=True, text=True,
                            cwd=ROOT, env=env, timeout=60).stdout
    verdicts = json.loads(output)
    plain, exact = zip(*verdicts['results'])
    assert plain[:2] == ('http://127.0.0.1:8765',) * 2 and exact[0] == 'http://127.0.0.1:8765'
    assert exact[1] == 'refused: EEG_API_TARGET must be http://127.0.0.1:<port>, not "http://127.0.0.1:8765/x?y".'
    # 127.1 is how URL spells 127.0.0.1; every other name is refused.
    assert plain[5] == 'http://127.0.0.1:8765'
    assert all(verdict.startswith('refused: The service URL must be http://127.0.0.1:<port>') for verdict in
               (*plain[2:5], *plain[6:]))
    assert verdicts['sessions'] == [
        'The service URL must be http://127.0.0.1:<port>, not "http://localhost:9".',
        'The service URL must be http://127.0.0.1:<port>, not "http://[::1]:9".',
    ]
