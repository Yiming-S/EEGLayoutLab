"""The service under test (tests/service/README.md): known tokens, synthetic roots and static exports, and a
loopback client that has exchanged the launch token for the session cookie.

``asgi_request`` calls the application with a request line as written, which the HTTP clients would normalize
(``..`` segments, percent-encoding).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Optional
from urllib.parse import unquote

from fastapi.testclient import TestClient

from eeglayoutlab.server.access import Tokens, cookie_name
from eeglayoutlab.server.app import Service, ServiceConfig, create_app
from eeglayoutlab.server.workspace import UserContext

PORT = 47321
TOKENS = Tokens(*(hashlib.sha256(name.encode()).hexdigest() for name in ('launch', 'session', 'csrf')))
HOST = f'127.0.0.1:{PORT}'
# The pages of the static export (design 0001, phase 0): app/page.tsx and app/<name>/page.tsx.
PAGES = ('channels', 'coordinates', 'decision', 'deliveries', 'design', 'electrodes', 'findings', 'guide', 'layout',
         'library', 'method', 'pilot-results', 'projects', 'reception', 'results', 'robustness')
PAGE_NAMES = frozenset({'index', *PAGES})


def synthetic_root(path: Path, available: bool = True) -> Path:
    """A scientific root with (or without) the radius worker and its bank, which health reports as available."""
    path.mkdir(parents=True, exist_ok=True)
    if available:
        for name in ('scripts/run_local_radius_compute.py', 'results/v2/current_multiregion_bank.json'):
            (path / name).parent.mkdir(parents=True, exist_ok=True)
            (path / name).write_text('{}\n', encoding='utf-8')
    return path


def static_export(path: Path) -> Path:
    """A small export laid out as ``npm run build`` writes it, with sidecars, a dot directory and links."""
    files = {
        'index.html': '<!doctype html><title>home</title>', 'index.txt': '0:{"page:/":1}',
        '404.html': '<!doctype html><title>not found</title>',
        '_next/static/chunks/app-3f2a.js': 'console.log(1);', '_next/static/css/layout.css': 'body{}',
        '_next/static/media/geist.woff2': 'wOF2', 'favicon.svg': '<svg xmlns="http://www.w3.org/2000/svg"/>',
        'LICENSE.txt': 'GPL', 'models/ernie/manifest.json': '{"files":[]}', 'models/ernie/README.md': '# ernie',
        'models/ernie/scalp.bin': bytes(range(256)) * 4, 'models/ernie/head.glb': 'glTF',
        'data/experiment.json': '{"a":1}', 'data/table.csv': 'a,b', 'runtime.wasm': '\0asm',
        'images/plot.png': '\x89PNG', 'vinext-client-entry-manifest.json': '{}',
        '.vite/manifest.json': '{}', 'models/.hidden.json': '{}',
    }
    for page in PAGES:
        files[f'{page}.html'] = f'<!doctype html><title>{page}</title>'
        files[f'{page}.txt'] = f'0:{{"page:/{page}":1}}'
    for name in ('design.html', 'favicon.svg', 'models/ernie/scalp.bin', '_next/static/chunks/app-3f2a.js'):
        files[name + '.br'] = 'brotli'
        files[name + '.gz'] = 'gzip'
    for name, content in files.items():
        target = path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content, encoding='latin-1')
    secret = path.parent / f'{path.name}-outside.json'
    secret.write_text('{"secret":true}', encoding='utf-8')
    (path / 'models/escape.json').symlink_to(secret)
    (path / 'outside').symlink_to(path.parent, target_is_directory=True)
    (path / 'data/alias.json').symlink_to('experiment.json')
    return path


def service_config(root: Path, static: Optional[Path] = None, workspace: Optional[Path] = None,
                   port: int = PORT, docs: Optional[Path] = None, cache_only: bool = False) -> ServiceConfig:
    user = UserContext.local(str(workspace or root), str(root))
    return ServiceConfig(root=str(root), port=port, tokens=TOKENS, user=user,
                         static_dir=str(static) if static is not None else None,
                         docs_dir=str(docs) if docs is not None else None,
                         cache_only=cache_only)


def make_app(root: Path, static: Optional[Path] = None, port: int = PORT, docs: Optional[Path] = None,
             workspace: Optional[Path] = None, cache_only: bool = False) -> Service:
    return create_app(service_config(root, static, workspace=workspace, port=port, docs=docs, cache_only=cache_only))


def docs_site(path: Path) -> Path:
    """A small built documentation site in the shape ``mkdocs build`` writes (directory URLs)."""
    files = {
        'index.html': '<!doctype html><title>EEGLayoutLab</title>',
        '404.html': '<!doctype html><title>docs not found</title>',
        'method-details/index.html': '<!doctype html><h2 id="signal-model">Signal model</h2>',
        'assets/javascripts/bundle.1a2b.min.js': 'console.log(1)',
        'search/search_index.json': '{"docs":[]}',
        'sitemap.xml.gz': b'\x1f\x8b\x08\x00',
    }
    for name, content in files.items():
        target = path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content if isinstance(content, bytes) else content.encode('utf-8'))
    return path


def loopback_client(app: Service, port: int = PORT, authenticate: bool = True, csrf: bool = False,
                    peer: str = '127.0.0.1') -> TestClient:
    """A client at ``http://127.0.0.1:<port>`` whose peer address is ``peer``; ``authenticate`` performs
    ``/open`` so that the cookie jar holds the session cookie; ``csrf`` sends the CSRF token on every request."""
    headers = {'x-eeg-compute-token': TOKENS.csrf} if csrf else None
    client = TestClient(app, base_url=f'http://{HOST if port == PORT else f"127.0.0.1:{port}"}',
                        client=(peer, 50000), raise_server_exceptions=False, follow_redirects=False,
                        headers=headers)
    if authenticate:
        response = client.get(f'/open?token={TOKENS.launch}')
        assert response.status_code == 303, response.text
        assert client.cookies.get(cookie_name(port)) == TOKENS.session
    return client


def session_cookie(port: int = PORT) -> str:
    return f'{cookie_name(port)}={TOKENS.session}'


@dataclass
class Reply:
    status: int
    headers: dict[str, str]
    """Lower-case names; a repeated header keeps its values joined with ``', '``."""
    body: bytes


def asgi_request(app: Service, method: str, target: str, headers: Optional[list[tuple[str, str | bytes]]] = None,
                 body: bytes = b'', peer: Optional[str] = '127.0.0.1', host: Optional[str] = HOST,
                 cookie: bool = True) -> Reply:
    """Sends one request to the ASGI application as a server would pass it: ``target`` is the request target
    exactly as written; the path is its percent-decoded form, as uvicorn decodes it."""
    raw, _, query = target.partition('?')
    sent: list[tuple[bytes, bytes]] = []
    if host is not None:
        sent.append((b'host', host.encode('latin-1')))
    if cookie:
        sent.append((b'cookie', session_cookie().encode('ascii')))
    for name, value in headers or []:
        sent.append((name.lower().encode('latin-1'), value if isinstance(value, bytes) else value.encode('latin-1')))
    scope = {
        'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1', 'method': method, 'scheme': 'http',
        'path': unquote(raw), 'raw_path': raw.encode('latin-1'), 'query_string': query.encode('latin-1'),
        'root_path': '', 'headers': sent, 'client': (peer, 50000) if peer else None, 'server': ('127.0.0.1', PORT),
    }
    messages: list[dict] = []

    async def receive() -> dict:
        return {'type': 'http.request', 'body': body, 'more_body': False}

    async def send(message: dict) -> None:
        messages.append(message)

    asyncio.run(app(scope, receive, send))
    start = next(message for message in messages if message['type'] == 'http.response.start')
    collected: dict[str, list[str]] = {}
    for name, value in start['headers']:
        collected.setdefault(name.decode('latin-1').lower(), []).append(value.decode('latin-1'))
    content = b''.join(message.get('body', b'') for message in messages if message['type'] == 'http.response.body')
    return Reply(start['status'], {name: ', '.join(values) for name, values in collected.items()}, content)
