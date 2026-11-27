"""The static interface (phase 2 slice 2; endpoints.md section 9.4): page routes, the 404 page, files with their
types and cache headers, conditional and range requests, HEAD, 405, and the paths that are never served.

The export is built in a temporary directory (``service_support.static_export``); the last test also reads the
real ``webapp/dist/client`` when ``npm run build`` has written it.
"""
from __future__ import annotations

from email.utils import formatdate
import json
import os
from pathlib import Path
import subprocess
import time

import pytest

from .key_parity_support import REQUIRED, needs_node, require

require('fastapi')
require('httpx')

from eeglayoutlab.server.static import CONTENT_TYPES, export_root, page_names, parse_http_date  # noqa: E402

from .service_support import (  # noqa: E402
    PAGE_NAMES, PAGES, TOKENS, asgi_request, docs_site, loopback_client, make_app, static_export, synthetic_root,
)

ROOT = Path(__file__).resolve().parents[2]
REAL_EXPORT = ROOT / 'webapp/dist/client'
VINEXT = ROOT / 'webapp/node_modules/vinext/dist/server'
DRIVER = ROOT / 'tests/service/parity/static_requests.mjs'
HTML = 'text/html; charset=utf-8'
SCALP = bytes(range(256)) * 4
NOT_FOUND = '<!doctype html><title>not found</title>'


@pytest.fixture
def export(tmp_path):
    return static_export(tmp_path / 'static')


@pytest.fixture
def app(tmp_path, export):
    return make_app(synthetic_root(tmp_path / 'root'), export)


@pytest.fixture
def client(app):
    return loopback_client(app)


def assert_not_found(response):
    assert response.status_code == 404
    assert response.headers['content-type'] == HTML and response.headers['cache-control'] == 'no-store'
    assert response.text == NOT_FOUND


def test_the_page_names_are_the_exports_and_the_apps(export):
    assert page_names(export) == PAGE_NAMES
    # The 17 pages of the interface: app/page.tsx is '/', app/<name>/page.tsx is '/<name>'.
    app_pages = {entry.name for entry in (ROOT / 'webapp/app').iterdir() if (entry / 'page.tsx').is_file()}
    assert (ROOT / 'webapp/app/page.tsx').is_file()
    assert {'index', *app_pages} == PAGE_NAMES and len(PAGE_NAMES) == 17


@pytest.mark.parametrize('path', ['/', *(f'/{page}' for page in PAGES)])
def test_every_page_route_serves_its_html(client, export, path):
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers['content-type'] == HTML and response.headers['cache-control'] == 'no-store'
    assert response.content == (export / f'{path[1:] or "index"}.html').read_bytes()
    assert response.headers['x-content-type-options'] == 'nosniff'
    # Query strings do not change the lookup (/design?record=..., /decision?a=...&b=...).
    assert client.get(path + '?record=' + 'a' * 64 + '&a=1').content == response.content
    head = client.head(path)
    assert head.status_code == 200 and head.content == b''
    assert head.headers['content-length'] == str(len(response.content))


@pytest.mark.parametrize('path', [
    '/nope', '/design.html', '/index.html', '/404.html', '/index', '/favicon.ico', '/design/extra', '/Design',
    '/models', '/models/', '/models/ernie/missing.bin', '/api', '/_next/static/chunks/missing.js', '/index/',
])
def test_unknown_paths_get_the_404_page(client, path):
    assert_not_found(client.get(path))
    head = client.head(path)
    assert head.status_code == 404 and head.content == b'' and head.headers['content-length'] == str(len(NOT_FOUND))


def test_unknown_api_paths_get_json(client):
    response = client.get('/api/unknown')
    assert response.status_code == 404 and response.json() == {'error': 'Not Found', 'code': 'not_found'}
    assert client.get('/api/design').headers['content-type'] == 'application/json; charset=utf-8'


def test_without_404_html_a_built_in_page_answers(tmp_path, export):
    (export / '404.html').unlink()
    response = loopback_client(make_app(tmp_path, export)).get('/nope')
    assert response.status_code == 404 and response.headers['content-type'] == HTML
    assert 'Page not found' in response.text


def test_a_trailing_slash_redirects_to_the_page(app, client):
    for path, location in (('/design/', '/design'), ('/pilot-results/', '/pilot-results'),
                           ('/design/?record=x&a=1', '/design?record=x&a=1')):
        response = client.get(path)
        assert response.status_code == 308 and response.headers['location'] == location
    # Never an absolute URL built from Host.
    assert asgi_request(app, 'GET', '/design/', host='localhost:1').headers['location'] == '/design'


@pytest.mark.parametrize('path, content_type', [
    ('/_next/static/chunks/app-3f2a.js', 'application/javascript; charset=utf-8'),
    ('/_next/static/css/layout.css', 'text/css; charset=utf-8'),
    ('/_next/static/media/geist.woff2', 'font/woff2'),
    ('/favicon.svg', 'image/svg+xml'),
    ('/models/ernie/manifest.json', 'application/json; charset=utf-8'),
    ('/models/ernie/scalp.bin', 'application/octet-stream'),
    ('/models/ernie/head.glb', 'model/gltf-binary'),
    ('/models/ernie/README.md', 'application/octet-stream'),
    ('/data/table.csv', 'text/csv; charset=utf-8'),
    ('/images/plot.png', 'image/png'),
    ('/runtime.wasm', 'application/wasm'),
    ('/LICENSE.txt', 'text/plain; charset=utf-8'),
    # The pages' RSC payloads.
    ('/design.txt', 'text/plain; charset=utf-8'),
    ('/index.txt', 'text/plain; charset=utf-8'),
    ('/vinext-client-entry-manifest.json', 'application/json; charset=utf-8'),
])
def test_files_carry_their_type_and_cache_headers(client, export, path, content_type):
    response = client.get(path)
    assert response.status_code == 200 and response.content == (export / path[1:]).read_bytes()
    assert response.headers['content-type'] == content_type
    expected = 'public, max-age=31536000, immutable' if path.startswith('/_next/static/') else 'public, max-age=3600'
    assert response.headers['cache-control'] == expected
    assert response.headers['accept-ranges'] == 'bytes' and response.headers['x-content-type-options'] == 'nosniff'
    assert response.headers['etag'].startswith('"') and response.headers['last-modified'].endswith(' GMT')
    assert response.headers['content-length'] == str(len(response.content))


def test_content_types_follow_vinext():
    assert CONTENT_TYPES['.js'] == 'application/javascript; charset=utf-8'
    assert CONTENT_TYPES['.json'] == 'application/json; charset=utf-8' and CONTENT_TYPES['.woff2'] == 'font/woff2'
    vinext = ROOT / 'webapp/node_modules/vinext/dist/server/static-file-cache.js'
    if vinext.is_file():
        text = vinext.read_text(encoding='utf-8')
        for extension, content_type in CONTENT_TYPES.items():
            if extension != '.glb':
                assert f'"{extension}": "{content_type}"' in text, extension


@pytest.mark.parametrize('path', [
    '/favicon.svg.BR', '/favicon.svg.Gz', '/design.html.BR', '/models/ernie/scalp.bin.GZ', '/design.HTML',
    '/index.HTML', '/404.HTML', '/Favicon.svg', '/FAVICON.SVG', '/LICENSE.TXT', '/models/ERNIE/manifest.json',
    '/Models/ernie/manifest.json', '/_next/static/chunks/APP-3f2a.js', '/Design.txt',
])
def test_a_name_is_looked_up_exactly(client, path):
    # vinext keeps the export's names in a table; a file system that ignores case (APFS, NTFS) must not let
    # another spelling reach a file, a sidecar or a page by name.
    assert_not_found(client.get(path))


def test_sidecars_are_never_served(client, export):
    for path in ('/favicon.svg.br', '/favicon.svg.gz', '/design.html.br', '/models/ernie/scalp.bin.gz'):
        assert_not_found(client.get(path))
    response = client.get('/favicon.svg', headers={'accept-encoding': 'br, gzip'})
    assert response.status_code == 200 and response.content == (export / 'favicon.svg').read_bytes()
    assert 'content-encoding' not in response.headers and 'vary' not in response.headers


@pytest.mark.parametrize('target', [
    '/models/../index.html', '/models/ernie/../../LICENSE.txt', '/./favicon.svg', '/%2e%2e/LICENSE.txt',
    '/models%2Fernie%2Fmanifest.json', '/models/ernie/manifest%2Ejson', '/models%5Cernie%5Cmanifest.json',
    '/models\\ernie\\manifest.json', '//favicon.svg', '/favicon.svg/', '/%64esign', '/models/ernie/manifest.json%00',
])
def test_traversal_and_encoded_separators_are_rejected(app, target):
    reply = asgi_request(app, 'GET', target)
    assert reply.status == 404 and reply.body == NOT_FOUND.encode()


def test_links_out_of_the_export_and_dotfiles_are_not_served(app, export):
    for target in ('/models/escape.json', f'/outside/{export.name}-outside.json', '/.vite/manifest.json',
                   '/models/.hidden.json'):
        reply = asgi_request(app, 'GET', target)
        assert reply.status == 404 and b'secret' not in reply.body, target
    # A link whose real path stays inside the export reaches a file of the export.
    for target, body in (('/data/alias.json', b'{"a":1}'), (f'/outside/{export.name}/LICENSE.txt', b'GPL')):
        reply = asgi_request(app, 'GET', target)
        assert reply.status == 200 and reply.body == body


def test_an_exported_directory_that_is_a_link_is_followed(tmp_path, export):
    linked = tmp_path / 'linked-static'
    linked.symlink_to(export, target_is_directory=True)
    client = loopback_client(make_app(tmp_path, linked))
    assert client.get('/design').status_code == 200 and client.get('/favicon.svg').status_code == 200
    assert client.get('/models/escape.json').status_code == 404


def test_conditional_requests(client, export):
    os.utime(export / 'models/ernie/manifest.json', ns=(1_795_000_000_600_000_000,) * 2)
    first = client.get('/models/ernie/manifest.json')
    etag, modified = first.headers['etag'], first.headers['last-modified']
    for headers in ({'if-none-match': etag}, {'if-none-match': 'W/' + etag}, {'if-none-match': f'"x", {etag}'},
                    {'if-none-match': '*'}, {'if-modified-since': modified},
                    {'if-modified-since': 'Thu, 19 Nov 2026 11:06:40 GMT'}):
        response = client.get('/models/ernie/manifest.json', headers=headers)
        assert response.status_code == 304 and response.content == b'', headers
        assert response.headers['etag'] == etag and response.headers['cache-control'] == 'public, max-age=3600'
        assert response.headers['last-modified'] == modified
    for headers in ({'if-none-match': '"other"'}, {'if-modified-since': formatdate(0, usegmt=True)},
                    {'if-modified-since': 'not a date'},
                    # If-None-Match wins over If-Modified-Since.
                    {'if-none-match': '"other"', 'if-modified-since': modified}):
        assert client.get('/models/ernie/manifest.json', headers=headers).status_code == 200, headers
    assert client.head('/models/ernie/manifest.json', headers={'if-none-match': etag}).status_code == 304
    # The ETag follows the file.
    page = client.get('/design')
    assert client.get('/design', headers={'if-none-match': page.headers['etag']}).status_code == 304


def test_preconditions_follow_vinext(client, export):
    target = export / 'models/ernie/manifest.json'
    os.utime(target, ns=(1_795_000_000_600_000_000,) * 2)
    first = client.get('/models/ernie/manifest.json')
    etag, modified = first.headers['etag'], first.headers['last-modified']
    assert modified == 'Wed, 18 Nov 2026 11:06:40 GMT'
    cases = [
        # If-Match and If-Unmodified-Since: 412 when they fail.
        ({'if-match': '"nope"'}, 412), ({'if-match': etag}, 200), ({'if-match': '*'}, 200), ({'if-match': ''}, 412),
        ({'if-unmodified-since': 'Wed, 18 Nov 2026 11:06:39 GMT'}, 412),
        ({'if-unmodified-since': modified}, 200), ({'if-unmodified-since': 'not a date'}, 200),
        ({'if-match': etag, 'if-unmodified-since': 'Wed, 18 Nov 2026 11:06:39 GMT'}, 200),
        # A request Cache-Control: no-cache never gets 304.
        ({'if-none-match': etag, 'cache-control': 'no-cache'}, 200),
        ({'if-none-match': etag, 'cache-control': 'max-age=0, No-Cache'}, 200),
        ({'if-modified-since': modified, 'cache-control': 'no-cache'}, 200),
        ({'if-none-match': etag, 'cache-control': 'no-cache-x'}, 304),
        # A malformed list matches nothing.
        ({'if-none-match': f'{etag}, garbage'}, 200), ({'if-none-match': f'{etag} "x"'}, 200),
        ({'if-none-match': f' "x",, {etag}'}, 304),
        # The three HTTP-date formats, all in GMT, and nothing else.
        ({'if-modified-since': 'Wednesday, 18-Nov-26 11:06:40 GMT'}, 304),
        ({'if-modified-since': 'Wed Nov 18 11:06:40 2026'}, 304),
        ({'if-modified-since': 'Wed Nov 18 10:06:40 2026'}, 200),
        ({'if-modified-since': 'Wed, 18 Nov 2026 10:06:40'}, 200),
        ({'if-modified-since': 'Wed, 18 Nov 2026 16:06:40 +0500'}, 200),
        ({'if-modified-since': 'Thu, 18 Nov 2026 11:06:40 GMT'}, 200),
        ({'if-modified-since': 'Wed, 31 Feb 2027 00:00:00 GMT'}, 200),
    ]
    for headers, status in cases:
        response = client.get('/models/ernie/manifest.json', headers=headers)
        assert response.status_code == status, headers
        if status == 412:
            assert response.content == b'' and response.headers['etag'] == etag
            assert response.headers['content-type'] == 'application/json; charset=utf-8'
    # Repeated If-None-Match lines are one list; of repeated dates the first counts.
    for headers, status in (([('if-none-match', '"zzz"'), ('if-none-match', etag)], 304),
                            ([('if-modified-since', formatdate(0, usegmt=True)), ('if-modified-since', modified)], 200),
                            ([('if-match', '"zzz"'), ('if-match', etag)], 200)):
        assert asgi_request(client.app, 'GET', '/models/ernie/manifest.json', headers).status == status, headers


def test_last_modified_is_the_second_that_is_compared(client, export):
    # Node truncates the mtime to whole seconds. Rounded, the header would name the next second, so that a rewrite
    # within that second would look unmodified (304), or a date If-Range would splice its bytes onto the old ones.
    target = export / 'models/ernie/scalp.bin'
    os.utime(target, ns=(1_795_000_000_999_999_700,) * 2)
    modified = client.get('/models/ernie/scalp.bin').headers['last-modified']
    assert modified == 'Wed, 18 Nov 2026 11:06:40 GMT'
    target.write_bytes(bytes(1024))
    os.utime(target, ns=(1_795_000_001_300_000_000,) * 2)
    assert client.get('/models/ernie/scalp.bin', headers={'if-modified-since': modified}).status_code == 200
    response = client.get('/models/ernie/scalp.bin', headers={'range': 'bytes=0-3', 'if-range': modified})
    assert response.status_code == 200 and response.content == bytes(1024)


def test_dates_do_not_depend_on_the_local_time_zone(client, export, monkeypatch):
    os.utime(export / 'favicon.svg', ns=(1_795_000_000_000_000_000,) * 2)
    assert client.get('/favicon.svg').headers['last-modified'] == 'Wed, 18 Nov 2026 11:06:40 GMT'
    for zone in ('America/New_York', 'Asia/Shanghai', 'UTC'):
        monkeypatch.setenv('TZ', zone)
        time.tzset()
        # An hour before the file: modified since then, whatever the server's zone.
        for since in ('Wed Nov 18 10:06:40 2026', 'Wednesday, 18-Nov-26 10:06:40 GMT', 'Wed, 18 Nov 2026 10:06:40'):
            assert client.get('/favicon.svg', headers={'if-modified-since': since}).status_code == 200, (zone, since)
        assert parse_http_date('Wed Nov 18 11:06:40 2026') == 1_795_000_000
    monkeypatch.delenv('TZ')
    time.tzset()


def test_http_dates_as_vinext_parses_them():
    assert parse_http_date('Thu, 01 Jan 1970 00:00:00 GMT') == 0
    assert parse_http_date('Thu Jan  1 00:00:00 1970') == 0
    assert parse_http_date('Sat, 01 Jan 0000 00:00:00 GMT') == -62167219200
    assert parse_http_date('Tue, 29 Feb 2028 23:59:59 GMT') == 1835481599
    for value in ('Thu, 01 Jan 1970 00:00:00 UTC', 'Thu, 1 Jan 1970 00:00:00 GMT', 'Thu, 01 Jan 1970 24:00:00 GMT',
                  'Thu, 01 Jan 1970 00:00:60 GMT', 'Wed, 01 Jan 1970 00:00:00 GMT', 'Thu, 01 Jan 1970 00:00:00 GMT\n',
                  'Thu Jan 01 00:00:00 1970 ', 'Fri, 29 Feb 2030 00:00:00 GMT', '', 'Thursday, 01-Jan-70 00:00:00'):
        assert parse_http_date(value) is None, value


def static_case_headers() -> tuple[list[list[tuple[str, str]]], list[str]]:
    """Requests (header lines) and dates for the comparison with vinext; ``ETAG`` stands for the file's ETag and
    ``MODIFIED`` for its Last-Modified."""
    ranges = ['bytes=0-9', 'bytes=1000-', 'bytes=-24', 'bytes=-5000', 'bytes=1020-5000', 'BYTES=0-1', 'Bytes=0-1',
              'bytes = 0-1', 'bytes=5-1', 'bytes=1024-', 'bytes=-0', 'bytes=-', 'bytes=0-1,4-5', 'items=0-1',
              'bytes=a-b', 'bytes=00005-00009', 'bytes=0-1\xa0', 'bytes=\xa00-1', 'bytes=0 -1', 'bytes=\xd9\xa1-2',
              'bytes=\xb2-3', 'bytes=0-' + '9' * 5000, 'bytes=-' + '9' * 5000, 'bytes=' + '9' * 5000 + '-',
              'bytes=0-9007199254740991', 'bytes=0-9007199254740992', 'bytes=9007199254740992-',
              'bytes=-9007199254740991', 'bytes=-9007199254740992', 'bytes=1023-9007199254740993', 'bytes=']
    requests = [[('Range', value)] for value in ranges]
    requests += [[('Range', 'bytes=0-1'), ('Range', 'bytes=4-5')], [('Range', 'bytes=0-1'), ('Range', '')]]
    conditions = ['ETAG', 'W/ETAG', '"other"', 'MODIFIED', 'Wed, 18 Nov 2026 11:06:39 GMT',
                  'Thu, 19 Nov 2026 11:06:40 GMT', 'Wed Nov 18 11:06:40 2026', 'not a date', 'W/"x"']
    requests += [[('Range', 'bytes=0-3'), ('If-Range', value)] for value in conditions]
    requests += [[('Range', 'bytes=0-3'), ('If-Range', 'ETAG'), ('If-Range', 'ETAG')]]
    dates = ['MODIFIED', 'Wed, 18 Nov 2026 11:06:39 GMT', 'Thu, 19 Nov 2026 11:06:40 GMT', 'Wed Nov 18 10:06:40 2026',
             'Wed Nov 18 11:06:40 2026', 'Wednesday, 18-Nov-26 11:06:40 GMT', 'Wednesday, 18-Nov-26 11:06:41 GMT',
             'Wed, 18 Nov 2026 10:06:40', 'Wed, 18 Nov 2026 16:06:40 +0500', 'Thu, 18 Nov 2026 11:06:40 GMT',
             'not a date', '']
    for name in ('If-Modified-Since', 'If-Unmodified-Since'):
        requests += [[(name, value)] for value in dates]
        requests += [[(name, 'Thu, 01 Jan 1970 00:00:00 GMT'), (name, 'MODIFIED')],
                     [(name, 'MODIFIED'), (name, 'Thu, 01 Jan 1970 00:00:00 GMT')]]
    tags = ['ETAG', 'W/ETAG', '"x", ETAG', 'ETAG, garbage', 'ETAG "x"', '"x",, ETAG', '*', ' *', '*, ETAG', '"x"',
            'garbage', '', '"\x80"', 'W/"x"']
    for name in ('If-None-Match', 'If-Match'):
        requests += [[(name, value)] for value in tags]
        requests += [[(name, '"zzz"'), (name, 'ETAG')], [(name, 'ETAG'), (name, 'garbage')]]
    for control in ('no-cache', 'max-age=0, No-Cache', 'no-cache-x', 'private,no-cache', 'no-cache\xa0', 'x-no-cache'):
        requests += [[('If-None-Match', 'ETAG'), ('Cache-Control', control)],
                     [('If-Modified-Since', 'MODIFIED'), ('Cache-Control', control)]]
    requests += [[('Cache-Control', 'no-cache'), ('Cache-Control', 'max-age=0'), ('If-None-Match', 'ETAG')],
                 [('If-Match', '"nope"'), ('If-None-Match', 'ETAG')],
                 [('If-Match', 'ETAG'), ('If-Unmodified-Since', 'Thu, 01 Jan 1970 00:00:00 GMT')],
                 [('If-Unmodified-Since', 'Thu, 01 Jan 1970 00:00:00 GMT'), ('If-None-Match', 'ETAG')],
                 [('If-None-Match', '"x"'), ('If-Modified-Since', 'MODIFIED')],
                 [('If-None-Match', 'ETAG'), ('Range', 'bytes=0-3')],
                 [('If-Modified-Since', 'Thu, 01 Jan 1970 00:00:00 GMT'), ('Range', 'bytes=0-3')]]
    return requests, dates + ['Thursday, 01-Jan-70 00:00:00 GMT', 'Wednesday, 31-Dec-69 23:59:59 GMT',
                              'Monday, 01-Jan-76 00:00:00 GMT', 'Thu Jan  1 00:00:00 1970', 'Sat, 01 Jan 0000 00:00:00 GMT']


@needs_node
@pytest.mark.skipif(not REQUIRED and not (VINEXT / 'http-range.js').is_file(),
                    reason='webapp/node_modules is installed by npm ci')
def test_conditional_and_range_requests_match_vinext(tmp_path, app, export):
    target = export / 'models/ernie/scalp.bin'
    os.utime(target, ns=(1_795_000_000_600_000_000,) * 2)
    first = asgi_request(app, 'GET', '/models/ernie/scalp.bin')
    etag, modified = first.headers['etag'], first.headers['last-modified']
    requests, dates = static_case_headers()

    def spell(value: str) -> str:
        return value.replace('W/ETAG', 'W/' + etag).replace('ETAG', etag).replace('MODIFIED', modified)

    requests = [[(name, spell(value)) for name, value in headers] for headers in requests]
    dates = [spell(value) for value in dates]
    cases, out = tmp_path / 'cases.json', tmp_path / 'node.json'
    cases.write_text(json.dumps({'etag': etag, 'mtimeMs': 1_795_000_000_600, 'size': len(SCALP),
                                 'requests': requests, 'dates': dates}), encoding='utf-8')
    env = {name: value for name, value in os.environ.items() if not name.startswith('EEG_')}
    subprocess.run(['node', str(DRIVER), str(cases), str(out)], check=True, cwd=ROOT, env=env, timeout=120)
    node = json.loads(out.read_text(encoding='utf-8'))
    assert [None if ms is None else ms / 1000 for ms in node['dates']] == [parse_http_date(value) for value in dates]
    assert len(node['results']) == len(requests)
    for headers, expected in zip(requests, node['results']):
        reply = asgi_request(app, 'GET', '/models/ernie/scalp.bin',
                             [(name, value.encode('latin-1')) for name, value in headers])
        if expected['precondition'] == 'not-modified':
            status, span = 304, None
        elif expected['precondition'] == 'precondition-failed':
            status, span = 412, None
        else:
            kind = expected['range']['kind']
            status = {'range': 206, 'unsatisfiable': 416, 'ignore': 200}[kind]
            span = (expected['range']['start'], expected['range']['end']) if kind == 'range' else None
        assert reply.status == status, headers
        if span is not None:
            assert reply.headers['content-range'] == f'bytes {span[0]}-{span[1]}/{len(SCALP)}', headers
            assert reply.body == SCALP[span[0]:span[1] + 1]


def test_a_new_build_changes_the_etag(client, export):
    etag = client.get('/favicon.svg').headers['etag']
    target = export / 'favicon.svg'
    target.write_text('<svg xmlns="http://www.w3.org/2000/svg"><g/></svg>', encoding='utf-8')
    os.utime(target, ns=(1_900_000_000_000_000_000, 1_900_000_000_000_000_000))
    response = client.get('/favicon.svg', headers={'if-none-match': etag})
    assert response.status_code == 200 and response.headers['etag'] != etag and b'<g/>' in response.content


@pytest.mark.parametrize('header, status, span', [
    ('bytes=0-9', 206, (0, 9)),
    ('bytes=1000-', 206, (1000, 1023)),
    ('bytes=-24', 206, (1000, 1023)),
    ('bytes=-5000', 206, (0, 1023)),
    ('bytes=1020-5000', 206, (1020, 1023)),
    ('bytes=1023-1023', 206, (1023, 1023)),
    ('BYTES=0-1', 206, (0, 1)),
    ('bytes=00005-00009', 206, (5, 9)),
    # Beyond Number.MAX_SAFE_INTEGER (and beyond the 4300 digits int() takes): to the end, or 416 for the start.
    ('bytes=0-' + '9' * 5000, 206, (0, 1023)),
    ('bytes=-' + '9' * 5000, 206, (0, 1023)),
    ('bytes=0-9007199254740992', 206, (0, 1023)),
    ('bytes=-9007199254740991', 206, (0, 1023)),
    ('bytes=1024-', 416, None),
    ('bytes=5000-6000', 416, None),
    ('bytes=-0', 416, None),
    ('bytes=5-1', 416, None),
    ('bytes=' + '9' * 5000 + '-', 416, None),
    ('bytes=9007199254740992-', 416, None),
    # Ignored: the whole file.
    ('bytes = 0-1', 200, None),
    ('items=0-1', 200, None),
    ('bytes=0-1,4-5', 200, None),
    ('bytes=a-b', 200, None),
    ('bytes=-', 200, None),
    # Digits are ASCII digits (the values are sent as bytes, read as Latin-1).
    (b'bytes=\xd9\xa1-2', 200, None),
    (b'bytes=\xb2-3', 200, None),
])
def test_ranges_apply_to_the_original_bytes(client, header, status, span):
    response = client.get('/models/ernie/scalp.bin', headers={'range': header, 'accept-encoding': 'br'})
    assert response.status_code == status
    assert 'content-encoding' not in response.headers
    if status == 206:
        first, last = span
        assert response.content == SCALP[first:last + 1]
        assert response.headers['content-range'] == f'bytes {first}-{last}/{len(SCALP)}'
        assert response.headers['content-length'] == str(last - first + 1)
    elif status == 416:
        assert response.headers['content-range'] == f'bytes */{len(SCALP)}' and response.content == b''
    else:
        assert response.content == SCALP and 'content-range' not in response.headers


def test_repeated_range_headers_are_joined_as_node_does(app):
    # Node joins them with ', ', which is several ranges: the whole file.
    reply = asgi_request(app, 'GET', '/models/ernie/scalp.bin', [('range', 'bytes=0-1'), ('range', 'bytes=4-5')])
    assert reply.status == 200 and reply.body == SCALP and 'content-range' not in reply.headers


def test_if_range_and_head_with_a_range(client, export):
    os.utime(export / 'models/ernie/scalp.bin', ns=(1_795_000_000_600_000_000,) * 2)
    first = client.get('/models/ernie/scalp.bin')
    etag, modified = first.headers['etag'], first.headers['last-modified']
    # The strong ETag allows the range too; Node's tags are weak, so there only the date does (design 0001,
    # slice 2, known differences).
    for condition in (etag, modified):
        response = client.get('/models/ernie/scalp.bin', headers={'range': 'bytes=0-3', 'if-range': condition})
        assert response.status_code == 206
    # A date at or after the file's whole second allows the range, as vinext compares it.
    response = client.get('/models/ernie/scalp.bin',
                          headers={'range': 'bytes=0-3', 'if-range': 'Thu, 19 Nov 2026 11:06:40 GMT'})
    assert response.status_code == 206
    for condition in ('"other"', 'W/' + etag, formatdate(0, usegmt=True), 'not a date'):
        response = client.get('/models/ernie/scalp.bin', headers={'range': 'bytes=0-3', 'if-range': condition})
        assert response.status_code == 200 and response.content == SCALP
    head = client.head('/models/ernie/scalp.bin', headers={'range': 'bytes=4-7'})
    assert head.status_code == 206 and head.content == b'' and head.headers['content-range'] == 'bytes 4-7/1024'


def test_an_empty_file(client, export):
    (export / 'data/empty.json').write_bytes(b'')
    response = client.get('/data/empty.json')
    assert response.status_code == 200 and response.content == b'' and response.headers['content-length'] == '0'
    assert client.get('/data/empty.json', headers={'range': 'bytes=0-'}).status_code == 416


def test_a_large_file_is_sent_in_chunks(client, export):
    body = os.urandom(300_000)
    (export / 'models/ernie/cortex.bin').write_bytes(body)
    assert client.get('/models/ernie/cortex.bin').content == body
    assert client.get('/models/ernie/cortex.bin', headers={'range': 'bytes=70000-200000'}).content == body[70000:200001]


@pytest.mark.parametrize('method', ['POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'])
@pytest.mark.parametrize('path', ['/', '/design', '/favicon.svg', '/nope'])
def test_other_methods_get_405(client, method, path):
    response = client.request(method, path, headers={'x-eeg-compute-token': TOKENS.csrf})
    assert response.status_code == 405 and response.headers['allow'] == 'GET, HEAD'
    assert response.headers['content-type'] == 'text/plain; charset=utf-8'


def test_without_an_export_pages_answer_503_and_the_api_works(tmp_path):
    export = tmp_path / 'static'
    client = loopback_client(make_app(synthetic_root(tmp_path / 'root'), export))
    for path in ('/', '/design', '/favicon.svg'):
        response = client.get(path)
        assert response.status_code == 503 and response.headers['content-type'] == HTML
        assert 'npm run build' in response.text and response.headers['cache-control'] == 'no-store'
    assert client.get('/api/local-compute/health').status_code == 200
    # A build made while the service runs is picked up.
    static_export(export)
    assert client.get('/design').status_code == 200
    assert loopback_client(make_app(tmp_path, None)).get('/').status_code == 503


def test_a_directory_without_index_html_is_not_the_export_and_pages_are_found_at_every_request(tmp_path):
    # An older build that was not an export (assets, no pages), or one that npm run build is still writing: it
    # removes dist, writes the assets, then the pages last. Neither is the export, and once the pages are written
    # every one of them is served without a restart.
    export = tmp_path / 'static'
    (export / '_next/static/chunks').mkdir(parents=True)
    (export / '_next/static/chunks/app-3f2a.js').write_text('console.log(0);', encoding='utf-8')
    (export / 'favicon.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding='utf-8')
    client = loopback_client(make_app(synthetic_root(tmp_path / 'root'), export))
    assert export_root(str(export)) is None
    for path in ('/', '/design', '/favicon.svg'):
        response = client.get(path)
        assert response.status_code == 503 and 'npm run build' in response.text, path
    # The pages are written one by one; each is served once it is there.
    (export / 'index.html').write_text('<!doctype html><title>home</title>', encoding='utf-8')
    assert client.get('/').status_code == 200 and client.get('/design').status_code == 404
    static_export(export)
    assert export_root(str(export)) == os.path.realpath(export)
    for path in ('/', *(f'/{page}' for page in PAGES)):
        assert client.get(path).status_code == 200, path
    assert client.get('/library/').headers['location'] == '/library'
    # A page removed or added later counts at once.
    (export / 'design.html').unlink()
    assert_not_found(client.get('/design'))
    (export / 'extra.html').write_text('<!doctype html><title>extra</title>', encoding='utf-8')
    assert client.get('/extra').text == '<!doctype html><title>extra</title>'


@pytest.mark.skipif(not (REAL_EXPORT / 'index.html').is_file(), reason='webapp/dist/client is built by npm run build')
def test_the_real_export(tmp_path):
    assert page_names(str(REAL_EXPORT)) == PAGE_NAMES
    client = loopback_client(make_app(synthetic_root(tmp_path / 'root'), REAL_EXPORT))
    for page in ('', *PAGES):
        response = client.get('/' + page)
        assert response.status_code == 200 and response.headers['content-type'] == HTML
    html = client.get('/design').text
    assert client.get('/favicon.ico').status_code == 404
    assets = sorted(path for path in (REAL_EXPORT / '_next/static').rglob('*.js') if path.is_file())
    assert assets, 'the export has scripts'
    asset = '/' + assets[0].relative_to(REAL_EXPORT).as_posix()
    assert asset in html or any(path.name in html for path in assets)
    response = client.get(asset)
    assert response.status_code == 200 and response.headers['cache-control'] == 'public, max-age=31536000, immutable'
    assert response.content == assets[0].read_bytes()
    assert client.get('/models/ernie/manifest.json').headers['content-type'] == 'application/json; charset=utf-8'
    assert client.get('/.vite/manifest.json').status_code == 404


# --- The documentation site under /docs/ ---------------------------------------------------------------------


@pytest.fixture
def docs_client(tmp_path, export):
    return loopback_client(make_app(synthetic_root(tmp_path / 'root'), export, docs=docs_site(tmp_path / 'site')))


def test_docs_pages_and_files_are_served(docs_client):
    for path, kind, cache in (('/docs/', HTML, 'no-store'), ('/docs/method-details/', HTML, 'no-store'),
                              ('/docs/method-details/index.html', HTML, 'no-store'),
                              ('/docs/assets/javascripts/bundle.1a2b.min.js', 'application/javascript; charset=utf-8',
                               'public, max-age=3600'),
                              ('/docs/search/search_index.json', 'application/json; charset=utf-8',
                               'public, max-age=3600'),
                              ('/docs/sitemap.xml.gz', 'application/octet-stream', 'public, max-age=3600')):
        response = docs_client.get(path)
        assert response.status_code == 200, path
        assert response.headers['content-type'] == kind and response.headers['cache-control'] == cache, path
    assert 'signal-model' in docs_client.get('/docs/method-details/').text
    assert docs_client.head('/docs/').status_code == 200


def test_docs_directories_redirect_to_their_slash(docs_client):
    for path, location in (('/docs', '/docs/'), ('/docs?x=1', '/docs/?x=1'),
                           ('/docs/method-details', '/docs/method-details/'),
                           ('/docs/method-details?ar=50', '/docs/method-details/?ar=50')):
        response = docs_client.get(path)
        assert response.status_code == 308 and response.headers['location'] == location, path


def test_docs_unknown_paths_get_the_sites_404(docs_client):
    for path in ('/docs/nope/', '/docs/nope', '/docs/.hidden', '/docs/Method-Details/', '/docs/%2e%2e/index.html'):
        response = docs_client.get(path)
        assert response.status_code == 404, path
        assert response.text == '<!doctype html><title>docs not found</title>', path
    response = docs_client.request('POST', '/docs/', headers={'x-eeg-compute-token': TOKENS.csrf})
    assert response.status_code == 405 and response.headers['allow'] == 'GET, HEAD'


def test_docs_answer_503_until_built_and_leave_the_interface_alone(tmp_path, export):
    client = loopback_client(make_app(synthetic_root(tmp_path / 'root'), export, docs=tmp_path / 'missing'))
    response = client.get('/docs/method-details/')
    assert response.status_code == 503
    assert 'not included in this installation' in response.text and 'mkdocs build' in response.text
    assert 'at the top of the repository' not in response.text
    assert client.get('/').status_code == 200
    # A page of the interface whose name starts with "docs" is not the site.
    assert client.get('/docsx').status_code == 404
