"""The routes of the read-only library and catalogs (``eeglayoutlab.server.routes.library``, phase 2 slice 3), on
their own: what the parity with Node's composed service (test_library_parity.py) cannot show.

- The listing's members and Node's order, the annotation added last to a record and to a bundle and its record.
- Electrode-name annotations of every owner, from the workspace's directory first, then Node's.
- ``readAnnotation``'s query rules (``annotation_query``), checked only for a record that exists and, for a bundle,
  after the bundle is built.
- Node's catch block: annotation errors keep their status and message, any other failure is a 500 that names no
  path (and is logged); other paths and methods under the prefixes are each prefix's 404.
- The library, its runtime and the head digests are built on first use and shared by concurrent requests; the
  default runtime reads ``EEG_COMPUTE_PYTHON``, whose interpreter the bundles use.
- Nothing is written under the root or the workspace.
- The HTTP half of check-coordinate-bundles.mjs:80 (the library half is in test_bundle.py).
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import errno
import logging
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Optional

import pytest

from .key_parity_support import require

require('fastapi')
require('httpx')
require('pydantic')

from eeglayoutlab.jobs import bundle as bundle_module  # noqa: E402
from eeglayoutlab.jobs import design_heads, editor_records, reception_records  # noqa: E402
from eeglayoutlab.jobs import library as library_module  # noqa: E402
from eeglayoutlab.jobs import runtime as runtime_module  # noqa: E402
from eeglayoutlab.jobs.annotations import (  # noqa: E402
    INSPECTION, INTEGRITY, LIMIT, NOT_FOUND, AnnotationError, ElectrodeAnnotations,
)
from eeglayoutlab.jobs.bundle import BundleError  # noqa: E402
from eeglayoutlab.jobs.library import Library  # noqa: E402
from eeglayoutlab.jobs.runtime import runtime_config  # noqa: E402
from eeglayoutlab.schemas import jsjson  # noqa: E402
from eeglayoutlab.server.app import Service, ServiceConfig, create_app  # noqa: E402
from eeglayoutlab.server.routes.library import (  # noqa: E402
    INVALID_QUERY, NO_BUNDLE_RECORD, NO_RECORD, UNREADABLE, LibraryRoutes, annotation_query,
)
from eeglayoutlab.server.workspace import UserContext  # noqa: E402

from .bundle_support import coordinate_fixture  # noqa: E402
from .library_support import NODE_ANNOTATIONS, annotation, library_root, sha, write_annotation  # noqa: E402
from .service_support import PORT, TOKENS, asgi_request  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
LIBRARY = '/api/local-compute/library'
CATALOGS = ('/api/electrode-editor/records', '/api/electrode-editor/parents', '/api/source-reception/layouts',
            '/api/design-evaluation/heads')
WORKSPACE_ANNOTATIONS = 'annotations/electrode-names'
PUBLIC_KEYS = ['schema', 'id', 'record_id', 'request_sha256', 'electrode_names']


def config(root: Path, workspace: Path, python: Optional[str] = 'python3', *, default: bool = False) -> ServiceConfig:
    """The service of ``root`` with workspace ``workspace``; ``default`` leaves the runtime to the routes."""
    runtime = None if default else runtime_config(str(root), python, env={})
    return ServiceConfig(root=str(root), port=PORT, tokens=TOKENS, user=UserContext.local(str(workspace), str(root)),
                         runtime=runtime)


def make(root: Path, workspace: Path, python: Optional[str] = 'python3', *, default: bool = False) -> Service:
    return create_app(config(root, workspace, python, default=default))


def get(app: Service, target: str, method: str = 'GET', headers: Optional[list] = None) -> tuple[int, Any]:
    reply = asgi_request(app, method, target, headers=headers)
    return reply.status, jsjson.parse(reply.body.decode('utf-8')) if reply.body else None


def snapshot(root: Path) -> dict:
    """Every path under ``root`` with its type, size and modification time (links not followed)."""
    state = {}
    for directory, names, files in os.walk(root):
        for name in names + files:
            info = os.lstat(os.path.join(directory, name))
            state[os.path.join(directory, name)] = (info.st_mode, info.st_size, info.st_mtime_ns)
    return state


@pytest.fixture(scope='module')
def base(tmp_path_factory):
    """A library root with one annotation in Node's directory, and a workspace path that is never created."""
    directory = tmp_path_factory.mktemp('library-routes')
    root = directory / 'root'
    keys = library_root(root, 'python3')
    record = keys['design']['default']
    stored = annotation('browser-a', record)
    write_annotation(root / NODE_ANNOTATIONS, stored)
    return {'root': root, 'workspace': directory / 'workspace', 'keys': keys, 'record': record,
            'annotation': stored['id']}


@pytest.fixture
def app(base):
    return make(base['root'], base['workspace'])


# --- Bodies -------------------------------------------------------------------------------------------------------

def test_listing_has_nodes_members_in_order(app, base):
    reply = asgi_request(app, 'GET', LIBRARY)
    assert reply.status == 200
    assert reply.headers['content-type'] == 'application/json; charset=utf-8'
    assert (reply.headers['cache-control'], reply.headers['x-eeg-api-version']) == ('no-store', '1')
    body = jsjson.parse(reply.body.decode('utf-8'))
    assert list(body) == ['schema', 'local_only', 'records', 'warnings', 'datasets', 'retention',
                          'electrode_annotations']
    assert [value['id'] for value in body['electrode_annotations']] == [base['annotation']]
    assert all('visibility' not in row for row in body['records']) and 'library_scope' not in body
    assert {row['dataset_id'] for row in body['records']} >= {'offline_radius', 'cache', 'design_evaluation'}


def test_annotations_are_read_from_the_workspace_first_and_without_regard_to_owner(tmp_path):
    keys = library_root(tmp_path / 'root', 'python3')
    root, record = tmp_path / 'root', keys['design']['default']
    workspace = tmp_path / 'workspace'
    own = annotation('browser-w', record)
    write_annotation(workspace / WORKSPACE_ANNOTATIONS, own)
    first, second = annotation('browser-a', record), annotation('browser-b', record, [f'Ch{i}' for i in range(64)])
    for value in (first, second):
        write_annotation(root / NODE_ANNOTATIONS, value)
    app = make(root, workspace)

    status, body = get(app, LIBRARY)
    assert status == 200
    assert [value['id'] for value in body['electrode_annotations']] == [own['id'], *sorted([first['id'],
                                                                                            second['id']])]
    assert all(list(value) == PUBLIC_KEYS for value in body['electrode_annotations'])

    status, body = get(app, f'{LIBRARY}/{record}?annotation_id={second["id"]}')
    assert status == 200 and list(body) == ['record']
    assert list(body['record'])[-1] == 'electrode_annotation'
    assert body['record']['electrode_annotation']['electrode_names'] == second['electrode_names']

    status, body = get(app, f'{LIBRARY}/{record}/bundle?annotation_id={first["id"]}')
    assert status == 200 and list(body)[-1] == 'electrode_annotation'
    assert list(body).index('record') < list(body).index('original_record')
    assert body['electrode_annotation'] == body['record']['electrode_annotation']
    assert list(body['record'])[-1] == 'electrode_annotation' and body['electrode_annotation']['id'] == first['id']

    # A tampered copy in Node's directory: the workspace's file is read first, while the list checks every file.
    write_annotation(root / NODE_ANNOTATIONS, own, {**own, 'owner': 'browser-z'})
    status, body = get(app, f'{LIBRARY}/{record}?annotation_id={own["id"]}')
    assert status == 200 and body['record']['electrode_annotation']['id'] == own['id']
    assert get(app, LIBRARY) == (409, {'error': INTEGRITY, 'code': 'compute_busy'})
    # An annotation of another record is not found.
    other = keys['design']['noise']
    assert get(app, f'{LIBRARY}/{other}?annotation_id={first["id"]}') == (404, {'error': NOT_FOUND,
                                                                                'code': 'not_found'})


# --- The annotation query -----------------------------------------------------------------------------------------

@pytest.mark.parametrize('query, expected', [
    (b'', None), (b'x=1', None), (b'x=1&x=2', None), (b'=annotation_id', None), (b';annotation_id=a', None),
    (b'ANNOTATION_ID=a', None), (b'annotation_id=abc', 'abc'), (b'annotation_id=', ''), (b'annotation_id', ''),
    (b'&&annotation_id=abc&', 'abc'), (b'annotation_id=a+b', 'a b'), (b'annotation_id=%61%62', 'ab'),
    (b'annotation%5Fid=abc', 'abc'), (b'annotation_id=%FF', '�'), (b'annotation_id=%zz', '%zz'),
    (b'annotation_id=abc;x=1', 'abc;x=1'), (b'annotation_id==', '='),
    (b'annotation_id=a&annotation_id=a', INVALID_QUERY), (b'annotation_id=a&x=1', INVALID_QUERY),
    (b'x&annotation_id=a', INVALID_QUERY), (b'annotation_id=a&=', INVALID_QUERY),
    (b'annotation_id=a&annotation%5Fid=b', INVALID_QUERY),
])
def test_annotation_query_follows_url_search_params(query, expected):
    """``readAnnotation``: no ``annotation_id`` ignores the query; otherwise it must be the only name, once."""
    if expected == INVALID_QUERY:
        with pytest.raises(AnnotationError) as raised:
            annotation_query(query)
        assert (raised.value.status, raised.value.message) == (400, INVALID_QUERY)
    else:
        assert annotation_query(query) == expected


def test_the_query_is_checked_for_a_record_that_exists_after_its_bundle(app, base, monkeypatch):
    missing, record = sha('no such record'), base['record']
    bad = '?annotation_id=x&x=1'
    assert get(app, f'{LIBRARY}/{missing}{bad}') == (404, {'error': NO_RECORD, 'code': 'not_found'})
    assert get(app, f'{LIBRARY}/{missing}/bundle{bad}') == (404, {'error': NO_BUNDLE_RECORD, 'code': 'not_found'})
    assert get(app, f'{LIBRARY}/{record}{bad}') == (400, {'error': INVALID_QUERY, 'code': 'invalid_request'})
    assert get(app, f'{LIBRARY}/{record}/bundle{bad}') == (400, {'error': INVALID_QUERY, 'code': 'invalid_request'})
    assert get(app, f'{LIBRARY}/{record}?x=1')[0] == 200

    def failed(*args: Any, **kwargs: Any) -> dict:
        raise BundleError('原始文件校验失败')

    monkeypatch.setattr(bundle_module, 'experiment_bundle', failed)
    assert get(app, f'{LIBRARY}/{record}/bundle{bad}') == (500, {'error': UNREADABLE, 'code': 'internal_error'})


# --- Errors -------------------------------------------------------------------------------------------------------

def _denied(*args: Any, **kwargs: Any) -> Any:
    raise PermissionError(errno.EACCES, 'Permission denied', '/secret/place/cache.json')


@pytest.mark.parametrize('target, owner, name', [
    (LIBRARY, Library, 'list'),
    (LIBRARY, ElectrodeAnnotations, 'list'),
    ('record', Library, 'get'),
    ('bundle', Library, 'get'),
    ('bundle', bundle_module, 'experiment_bundle'),
    ('annotated', ElectrodeAnnotations, 'read'),
    (CATALOGS[0], editor_records, 'records'),
    (CATALOGS[1], editor_records, 'parents'),
    (CATALOGS[2], reception_records, 'reception_layouts'),
    (CATALOGS[3], design_heads, 'heads'),
])
def test_unexpected_failures_answer_nodes_500_without_details(app, base, monkeypatch, caplog, target, owner, name):
    monkeypatch.setattr(owner, name, _denied)
    record = base['record']
    target = {'record': f'{LIBRARY}/{record}', 'bundle': f'{LIBRARY}/{record}/bundle',
              'annotated': f'{LIBRARY}/{record}?annotation_id={base["annotation"]}'}.get(target, target)
    with caplog.at_level(logging.ERROR, logger='eeglayoutlab.server'):
        reply = asgi_request(app, 'GET', target)
    assert reply.status == 500
    assert reply.body == '{"error":"计算记录无法读取","code":"internal_error"}'.encode('utf-8')
    assert any('library request failed' in record.getMessage() and record.exc_info for record in caplog.records)


@pytest.mark.parametrize('status, message, code', [
    (507, LIMIT, 'request_failed'), (409, INSPECTION, 'compute_busy'), (404, NOT_FOUND, 'not_found'),
])
def test_annotation_errors_keep_their_status_and_message(app, monkeypatch, status, message, code):
    def failed(self: Any) -> list:
        raise AnnotationError(message, status)

    monkeypatch.setattr(ElectrodeAnnotations, 'list', failed)
    assert get(app, LIBRARY) == (status, {'error': message, 'code': code})


def test_other_paths_and_methods_are_unknown(app, base):
    record = base['record']
    for target, message in (
            (f'{LIBRARY}/', '未知计算接口'), (f'{LIBRARY}/{"A" * 64}', '未知计算接口'),
            (f'{LIBRARY}/{record[:-1]}', '未知计算接口'), (f'{LIBRARY}/{"A" * 64}/bundle', '未知计算接口'),
            (f'{LIBRARY}/{record}/visibility', '未知计算接口'), (f'{LIBRARY}/{record}/bundle/', '未知计算接口'),
            ('/api/local-compute/%6Cibrary', '未知计算接口'), ('/api/electrode-editor/records/', 'Unknown editor endpoint'),
            ('/api/source-reception/layouts/', '未知源实验接口'), ('/api/design-evaluation/heads/', '未知设计评价接口')):
        assert get(app, target) == (404, {'error': message, 'code': 'not_found'}), target
    for target in (LIBRARY, f'{LIBRARY}/{record}', f'{LIBRARY}/{record}/bundle', *CATALOGS):
        assert asgi_request(app, 'HEAD', target).status == 404, target
        reply = asgi_request(app, 'POST', target, headers=[('x-eeg-compute-token', TOKENS.csrf),
                                                           ('content-type', 'application/json')], body=b'{}')
        assert reply.status == 404, target


# --- Lifetime -----------------------------------------------------------------------------------------------------

def test_the_library_is_built_on_first_use(tmp_path, monkeypatch):
    """A root that cannot be read does not stop the service: its routes answer 500, the runtime is resolved once."""
    resolved = []
    original = runtime_module.runtime_config

    def counted(root: str, *args: Any, **kwargs: Any) -> Any:
        resolved.append(root)
        return original(root, *args, **kwargs)

    monkeypatch.setattr(runtime_module, 'runtime_config', counted)
    monkeypatch.setattr(library_module, 'Library', _denied)
    app = make(tmp_path / 'root', tmp_path / 'workspace', default=True)
    assert resolved == []
    for _ in range(2):
        assert get(app, LIBRARY) == (500, {'error': UNREADABLE, 'code': 'internal_error'})
    assert resolved == [str(tmp_path / 'root')]


def test_building_the_application_imports_no_library_module(tmp_path):
    """``eeglayoutlab serve`` writes its runtime file before it builds the application and installs its signal
    handlers (cli/main.py), so the library's modules load on the first request instead."""
    script = (
        'import sys\n'
        'from eeglayoutlab.server.access import Tokens\n'
        'from eeglayoutlab.server.app import ServiceConfig, create_app\n'
        'from eeglayoutlab.server.workspace import UserContext\n'
        f'root = {str(tmp_path)!r}\n'
        "create_app(ServiceConfig(root=root, port=1, tokens=Tokens.generate(), user=UserContext.local(root, root)))\n"
        "print(sorted(name for name in sys.modules if name.startswith('eeglayoutlab.jobs.')))\n")
    loaded = subprocess.run([sys.executable, '-c', script], check=True, capture_output=True, text=True,
                            cwd=ROOT, env={**os.environ, 'PYTHONPATH': str(ROOT / 'src')}).stdout
    for name in ('library', 'bundle', 'annotations', 'radius', 'editor_records', 'reception_records', 'design_heads'):
        assert f"'eeglayoutlab.jobs.{name}'" not in loaded, loaded


def test_the_default_runtime_reads_eeg_compute_python(base, monkeypatch):
    monkeypatch.setenv('EEG_COMPUTE_PYTHON', '/opt/eeg/bin/python')
    routes = LibraryRoutes(config(base['root'], base['workspace'], default=True))
    assert (routes.runtime().repository_root, routes.runtime().python) == (str(base['root']), '/opt/eeg/bin/python')
    given = runtime_config(str(base['root']), '/usr/bin/python3', env={})
    assert LibraryRoutes(config(base['root'], base['workspace'], '/usr/bin/python3')).runtime() == given
    seen = []

    def bundle(root: str, record: dict, python: Any = None) -> dict:
        seen.append((root, python))
        return {'record': record}

    monkeypatch.setattr(bundle_module, 'experiment_bundle', bundle)
    app = make(base['root'], base['workspace'], default=True)
    assert get(app, f'{LIBRARY}/{base["record"]}/bundle')[0] == 200
    assert seen == [(str(base['root']), '/opt/eeg/bin/python')]


def test_concurrent_requests_share_one_library(base, monkeypatch):
    built = []
    original = library_module.Library

    def counted(*args: Any, **kwargs: Any) -> Library:
        built.append(args[0])
        return original(*args, **kwargs)

    monkeypatch.setattr(library_module, 'Library', counted)
    app = make(base['root'], base['workspace'])
    record = base['record']
    targets = [LIBRARY, f'{LIBRARY}/{record}', f'{LIBRARY}/{record}?annotation_id={base["annotation"]}',
               f'{LIBRARY}/{record}/bundle', *CATALOGS] * 3
    with ThreadPoolExecutor(8) as pool:
        replies = list(pool.map(lambda target: asgi_request(app, 'GET', target), targets))
    assert built == [str(base['root'])]
    alone = {target: asgi_request(app, 'GET', target) for target in dict.fromkeys(targets)}
    assert [(reply.status, reply.body) for reply in replies] == [(alone[t].status, alone[t].body) for t in targets]
    assert all(reply.status == 200 for reply in replies)


def test_routes_never_write(base):
    """Every route on every record of the root, with and without annotations: nothing under the root changes and
    the workspace is not created."""
    app = make(base['root'], base['workspace'])
    before = snapshot(base['root'])
    status, listing = get(app, LIBRARY)
    assert status == 200
    ids = [row['id'] for row in listing['records']]
    for id in ids:
        assert get(app, f'{LIBRARY}/{id}')[0] == 200
        asgi_request(app, 'GET', f'{LIBRARY}/{id}/bundle')
    for target in (*CATALOGS, f'{LIBRARY}/{base["record"]}?annotation_id={base["annotation"]}',
                   f'{LIBRARY}/{base["record"]}/bundle?annotation_id={base["annotation"]}'):
        assert get(app, target)[0] == 200, target
    assert snapshot(base['root']) == before
    assert not base['workspace'].exists()


# --- check-coordinate-bundles.mjs ---------------------------------------------------------------------------------

def test_read_only_coordinate_bundle_endpoint_returns_a_matching_export_without_starting_a_worker(tmp_path,
                                                                                                  monkeypatch):
    """:80, through the route (the library half is in test_bundle.py): the record the library gives is packed with
    its source, and no interpreter is started although one is configured."""
    fx = coordinate_fixture(tmp_path / 'root')

    def stub(self: Library, key: Any) -> Optional[dict]:  # the Node test's library: its own id only
        return fx['record'] if key == fx['id'] else None

    def started(*args: Any, **kwargs: Any) -> str:
        pytest.fail('the coordinate bundle must not start a worker')

    monkeypatch.setattr(Library, 'get', stub)
    monkeypatch.setattr(bundle_module, 'exec_file', started)
    app = make(fx['root'], tmp_path / 'workspace', 'python3')
    status, body = get(app, f'{LIBRARY}/{fx["id"]}/bundle')
    assert status == 200
    assert body['record_id'] == fx['id']
    assert body['record'] == fx['record']
    assert body['original_record']['key'] == fx['id']
    assert body['search']['history_status'] == 'not_applicable_coordinate_evaluation'
    assert get(app, f'{LIBRARY}/{sha("another")}/bundle') == (404, {'error': NO_BUNDLE_RECORD, 'code': 'not_found'})
