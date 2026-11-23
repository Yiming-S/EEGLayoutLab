"""The read-only library and catalogs of phase 2 slice 3 give Node's bytes, through the library and through the HTTP
routes (``eeglayoutlab.server.routes.library``).

The Node reference is tests/service/parity/library.mjs (its header documents the spec), run once over every root:

- Library level: Node's own ``LocalComputeQueue``, ``ElectrodeEditorService`` and ``DesignEvaluationService``
  against ``eeglayoutlab.jobs``: ``identityFor`` of the radius requests, the list (records as a set of texts plus
  their ``finished_at`` order, the rest as text), every record, the bundle of every record as the library route
  builds it (``original_record`` by the digest of its text) and the four catalogs.
- HTTP level: Node's composed service (``createLocalComputeService``, the middleware the Node host runs, its
  session pinned to one owner) against the Python application, target by target: status, content type and body.
  Node's public-service machinery is taken out of its bodies (``visibility`` on rows and ``library_scope``), and
  Node's path redaction (``redactPayload``) is applied to the Python body, since neither is carried over (phase 2
  plan). The bodies whose records Node sorts with ``localeCompare`` (the list, the editor's parents, the reception
  layouts) compare their records as a set and by ``finished_at`` order, as the library level does, so the
  comparison holds under any locale; the list's ``electrode_annotations`` compare with Python's restricted to the
  pinned owner's files. The differences that remain by design are asserted as such (``KNOWN``).

The synthetic roots hold every kind of library record (radius caches compatible, from another code identity, with
a bad checksum, malformed or unreadable; strict-area and historical-area reports; saved evaluations under each
evaluation condition), saved searches whose frozen-bank coordinates are exported by a stand-in interpreter that
both hosts run, editor records, head packages and electrode-name annotations; a link to that root (B4), a root
whose radius code includes a linked file (B8), an empty root, and roots whose annotation storage is tampered,
holds a stray file, is a link, cannot be listed, or belongs to another owner.

With ``EEG_KEY_PARITY_ROOT`` (marked ``data_bundle``) the routes are compared on that installation: the list,
every record, the catalogs and a sample of bundles of each dataset. Nothing is written under any root.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
from typing import Any, Optional

import pytest

from .key_parity_support import needs_node, require

require('fastapi')
require('httpx')
require('pydantic')

from eeglayoutlab.jobs.bundle import experiment_bundle  # noqa: E402
from eeglayoutlab.jobs.design_heads import heads  # noqa: E402
from eeglayoutlab.jobs.editor_records import parents, records  # noqa: E402
from eeglayoutlab.jobs.integrity import InputIntegrity  # noqa: E402
from eeglayoutlab.jobs.library import Library  # noqa: E402
from eeglayoutlab.jobs.reception_records import reception_layouts  # noqa: E402
from eeglayoutlab.jobs.runtime import runtime_config  # noqa: E402
from eeglayoutlab.schemas import jsjson  # noqa: E402
from eeglayoutlab.server.app import ServiceConfig, create_app  # noqa: E402
from eeglayoutlab.server.workspace import UserContext  # noqa: E402

from .bundle_support import HISTORY_REQUESTS, Packer, bundle_root, fake_interpreters  # noqa: E402
from .key_parity_support import run_library_node  # noqa: E402
from .library_support import (  # noqa: E402
    NODE_ANNOTATIONS, RADIUS_REQUESTS, annotation, annotations, attempt, finished_order, library_root, node_failure,
    records_by_text, sha, write_annotation,
)
from .service_support import PORT, TOKENS, asgi_request  # noqa: E402
from .test_catalogs import (  # noqa: E402
    _finished, _texts, assert_same_catalogs, editor_records, head_package, patched_caches,
)

OWNER = 'browser-parity'
OTHER = 'browser-other'
LIBRARY = '/api/local-compute/library'
CATALOGS = ('/api/electrode-editor/records', '/api/electrode-editor/parents', '/api/source-reception/layouts',
            '/api/design-evaluation/heads')
TEMPORARY = '.0123abcd-0000-4000-8000-000000000000.tmp'
ANNOTATION_KINDS = ('tampered', 'stray', 'link', 'closed', 'other-owner')
LAYOUTS = '/api/source-reception/layouts'
# Bodies whose records Node sorts with localeCompare (ICU collation, which follows the locale; Python compares
# UTF-16 code units, a documented difference).
LISTS = (LIBRARY, '/api/electrode-editor/parents', LAYOUTS)


# --- Node's public-service layer ------------------------------------------------------------------------------

# http/public-errors.mjs: ABSOLUTE_PATH, with JavaScript's \s spelled out.
_JS_SPACE = '\t\n\v\f\r \u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff'
ABSOLUTE_PATH = re.compile('(^|[' + _JS_SPACE + '\'"(=\\[])((?:/[^' + _JS_SPACE + '/\'"`:,;)\\]]+){2,})')


def redact_paths(text: Any) -> Any:
    """``redactPaths``."""
    return ABSOLUTE_PATH.sub(lambda match: match.group(1) + '[server path]', text) if isinstance(text, str) else text


def redact_payload(value: Any) -> Any:
    """``redactPayload``: what ``sendJson`` changes in every body it writes."""
    if not isinstance(value, dict):
        return value
    out = dict(value)

    def job(item: Any) -> Any:
        if isinstance(item, dict) and isinstance(item.get('message'), str):
            return {**item, 'message': redact_paths(item['message'])}
        return item

    for name in ('error', 'message'):
        if isinstance(out.get(name), str):
            out[name] = redact_paths(out[name])
    if out.get('job'):
        out['job'] = job(out['job'])
    if isinstance(out.get('jobs'), list):
        out['jobs'] = [job(item) for item in out['jobs']]
    if isinstance(out.get('warnings'), list):
        out['warnings'] = [redact_paths(item) for item in out['warnings']]
    return out


def without_access(value: Any) -> Any:
    """A Node body without ``libraryAccess``'s members: ``library_scope`` and ``visibility`` on the rows."""
    if isinstance(value, dict):
        value.pop('library_scope', None)
        rows = value.get('records')
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, dict):
                row.pop('visibility', None)
        if isinstance(value.get('record'), dict):
            value['record'].pop('visibility', None)
    return value


def node_view(text: str) -> str:
    return jsjson.stringify(without_access(jsjson.parse(text)))


def python_view(text: str) -> str:
    return jsjson.stringify(redact_payload(jsjson.parse(text)))


# --- The Python side ------------------------------------------------------------------------------------------

def python_library(item: dict, packer: Packer) -> dict:
    """The driver's library-level entry for one root, computed with ``eeglayoutlab.jobs`` in Node's call order."""
    config = runtime_config(item['root'], item.get('python'), env={})
    library = Library(item['root'], config)
    entry: dict[str, Any] = {'root': library.root, 'python': config.python, 'identity': {}, 'get': {}, 'bundle': {}}
    for name, request in item.get('requests', {}).items():
        def derive(request: dict = request) -> dict:
            identity, key = library.radius.identity_for(request)
            return {'identity': jsjson.stringify(identity), 'key': key}
        entry['identity'][name] = attempt(derive)
    entry['list'] = attempt(lambda: jsjson.stringify(library.list()))
    listed = [row['id'] for row in jsjson.parse(entry['list']['value'])['records']] if entry['list']['ok'] else []
    for id in dict.fromkeys([*item.get('ids', []), *(listed if item.get('listed', True) else [])]):
        entry['get'][id] = attempt(lambda id=id: jsjson.stringify(library.get(id)))
    for id in listed if item.get('bundles') is True else item.get('bundles', []):
        def bundle(id: str = id) -> Optional[dict]:
            record = library.get(id)
            return None if record is None else packer(experiment_bundle(library.root, record, config.python))
        entry['bundle'][id] = attempt(bundle)
    if item.get('catalogs'):
        entry['records'] = attempt(lambda: jsjson.stringify(records(library.store)))
        entry['parents'] = attempt(lambda: jsjson.stringify(parents(library)))
        entry['layouts'] = attempt(lambda: jsjson.stringify(reception_layouts(library)))
        entry['heads'] = attempt(lambda: jsjson.stringify(heads(library.root, InputIntegrity(library.root))))
    return entry


def python_http(item: dict, workspace: Path) -> list[dict]:
    """Each target of ``item`` through the Python application (one per root, as the driver composes one Node
    service per root), with a workspace that holds no annotations."""
    root = item['root']
    config = ServiceConfig(root=root, port=PORT, tokens=TOKENS, user=UserContext.local(str(workspace), root),
                           runtime=runtime_config(root, item.get('python'), env={}))
    app = create_app(config)
    answers = []
    for target in item['http']:
        reply = asgi_request(app, 'GET', target)
        answers.append({'target': target, 'status': reply.status, 'type': reply.headers.get('content-type'),
                        'body': reply.body.decode('utf-8')})
    return answers


def annotation_owner(root: str, id: Any) -> Any:
    """The owner recorded in Node's annotation file ``id`` under ``root``."""
    try:
        value = jsjson.parse((Path(root) / NODE_ANNOTATIONS / f'{id}.json').read_bytes().decode('utf-8'))
    except (OSError, ValueError):
        return None
    return value.get('owner') if isinstance(value, dict) else None


def same_lists(target: str, theirs: Any, mine: Any, root: Optional[str]) -> bool:
    """Whether two bodies of ``LISTS`` agree: the records as a set and by ``finished_at`` order (the saved
    evaluations of the layouts, which Node appends in store order, in order), and the list's annotations as the
    pinned owner's (Node's session) among Python's, which reads every owner's."""
    if not isinstance(theirs, dict) or not isinstance(mine, dict):
        return False
    target = target.split('?', 1)[0]
    if target == LIBRARY:
        ours = mine.pop('electrode_annotations', None)
        if isinstance(ours, list) and root is not None:
            ours = [value for value in ours if annotation_owner(root, value.get('id')) == OWNER]
        if jsjson.stringify(theirs.pop('electrode_annotations', None)) != jsjson.stringify(ours):
            return False
    rows = [theirs.pop('records', None), mine.pop('records', None)]
    if not all(isinstance(group, list) and all(isinstance(row, dict) for row in group) for group in rows):
        return False
    evaluations = [[jsjson.stringify(row) for row in group if row.get('dataset_id') == 'design_evaluation']
                   for group in rows] if target == LAYOUTS else [[], []]
    return (jsjson.stringify(theirs) == jsjson.stringify(mine) and _texts(rows[0]) == _texts(rows[1])
            and _finished(rows[0]) == _finished(rows[1]) and evaluations[0] == evaluations[1])


def http_difference(node: dict, python: dict, root: Optional[str] = None) -> Optional[tuple]:
    """``None`` when the answers agree, else what differs; ``root`` is the root whose annotation files tell the
    owners of the list's annotations."""
    assert node['target'] == python['target']
    if (node['status'], node['type']) != (python['status'], python['type']):
        return (node['target'], (node['status'], node['type'], node.get('body', '')[:300]),
                (python['status'], python['type'], python['body'][:300]))
    if 'sha256' in node:  # a large bundle: no member that redactPayload or libraryAccess changes
        if hashlib.sha256(python['body'].encode('utf-8')).hexdigest() == node['sha256']:
            return None
        mine = Packer()(jsjson.parse(python['body']))
        return (node['target'], node['packed']['text'][:300], mine['text'][:300])
    theirs, mine = node_view(node['body']), python_view(python['body'])
    if theirs == mine:
        return None
    if node['status'] == 200 and node['target'].split('?', 1)[0] in LISTS and same_lists(
            node['target'], jsjson.parse(theirs), jsjson.parse(mine), root):
        return None
    index = next((i for i, (a, b) in enumerate(zip(theirs, mine)) if a != b), min(len(theirs), len(mine)))
    return (node['target'], theirs[max(0, index - 150):index + 150], mine[max(0, index - 150):index + 150])


def test_list_bodies_compare_records_as_a_set_and_annotations_by_owner(tmp_path):
    """List bodies agree when only the order of records with the same ``finished_at`` differs (Node's follows the
    locale's collation) and when Python lists another owner's annotation; not when a record, the ``finished_at``
    order, the order of the layouts' saved evaluations or one of the pinned owner's annotations differs."""
    record = sha('record')
    own, other = annotation(OWNER, record), annotation(OTHER, record)
    for value in (own, other):
        write_annotation(tmp_path / NODE_ANNOTATIONS, value)
    public = [{'id': value['id'], 'record_id': record} for value in (own, other)]
    rows = [{'id': 'c', 'dataset_id': 'cache', 'label': 'c', 'finished_at': '2026-10-01T00:00:00Z'},
            {'id': 'a', 'dataset_id': 'offline_radius', 'label': 'B'},
            {'id': 'b', 'dataset_id': 'offline_radius', 'label': 'a'},
            {'id': 'd', 'dataset_id': 'design_evaluation', 'label': 'd'},
            {'id': 'e', 'dataset_id': 'design_evaluation', 'label': 'e'}]

    def answer(order: list[int], annotations: list[int], target: str = LIBRARY) -> dict:
        body: dict[str, Any] = {'schema': 'local-data-library/1', 'records': [rows[i] for i in order], 'warnings': []}
        if target == LIBRARY:
            body['electrode_annotations'] = [public[i] for i in annotations]
        return {'target': target, 'status': 200, 'type': 'application/json; charset=utf-8',
                'body': jsjson.stringify(body)}

    root = str(tmp_path)
    assert http_difference(answer([0, 1, 2, 3, 4], [0]), answer([0, 2, 1, 3, 4], [0, 1]), root) is None
    for target in ('/api/electrode-editor/parents', LAYOUTS, f'{LIBRARY}?x=1'):
        assert http_difference(answer([0, 1, 2, 3, 4], [0], target), answer([0, 2, 1, 3, 4], [0], target), root) is None
    assert http_difference(answer([0, 1, 2, 3, 4], [0], LAYOUTS), answer([0, 1, 2, 4, 3], [0], LAYOUTS), root)
    assert http_difference(answer([0, 1, 2, 3, 4], [0]), answer([1, 0, 2, 3, 4], [0]), root) is not None
    assert http_difference(answer([0, 1, 2, 3, 4], [0]), answer([0, 1, 3, 4], [0]), root) is not None
    assert http_difference(answer([0, 1, 2, 3, 4], [0]), answer([0, 1, 2, 3, 4], [1]), root) is not None
    assert http_difference(answer([0, 1, 2, 3, 4], [0, 1]), answer([0, 1, 2, 3, 4], [0, 1]), root) is None
    assert http_difference(answer([0, 1, 2, 3, 4], [1]), answer([0, 2, 1, 3, 4], [0, 1]), root) is not None


def library_differences(node: dict, python: dict) -> list:
    """The library-level members on which the two hosts differ."""
    found: list = []
    if (node['root'], node['python']) != (python['root'], python['python']):
        found.append(('config', (node['root'], node['python']), (python['root'], python['python'])))
    for name in ('identity', 'get', 'bundle'):
        assert set(node[name]) == set(python[name]), name
        found += [(name, key, node_failure(result), python[name][key]) for key, result in node[name].items()
                  if python[name][key] != node_failure(result)]
    if not node['list']['ok'] or not python['list']['ok']:
        if python['list'] != node_failure(node['list']):
            found.append(('list', node_failure(node['list']), python['list']))
    else:
        theirs, mine = node['list']['value'], python['list']['value']
        if records_by_text(theirs) != records_by_text(mine) or finished_order(theirs) != finished_order(mine):
            found.append(('list', theirs[:300], mine[:300]))
    if 'records' in node:
        try:
            assert_same_catalogs(node, python)
        except AssertionError as error:
            found.append(('catalogs', str(error)[:600]))
    return found


def snapshot(root: Path) -> dict:
    """Every path under ``root`` with its type, size and modification time (links not followed)."""
    state = {}
    for directory, names, files in os.walk(root):
        for name in names + files:
            info = os.lstat(os.path.join(directory, name))
            state[os.path.join(directory, name)] = (info.st_mode, info.st_size, info.st_mtime_ns)
    return state


# --- Roots and targets ----------------------------------------------------------------------------------------

def unknown_targets(id: str) -> list[str]:
    """Paths under the routes' prefixes that are no route (each prefix's 404), and routes with a query."""
    library = f'{LIBRARY}/{id}'
    return [
        f'{LIBRARY}/', f'{LIBRARY}/{"A" * 64}', f'{LIBRARY}/{"a" * 63}', f'{LIBRARY}/{"a" * 65}', f'{library}/',
        f'{library}/bundle/', f'{library}/other', f'{LIBRARY}x', f'{LIBRARY}/{id[:-1]}g/bundle',
        '/api/local-compute/%6Cibrary', f'{LIBRARY}%2F{id}', *(path + '/' for path in CATALOGS),
        '/api/design-evaluation/head', '/api/electrode-editor/record', f'{LIBRARY}?x=1',
        *(path + '?annotation_id=x&x=1' for path in CATALOGS), f'{LIBRARY}?annotation_id=x&x=1',
    ]


def query_targets(id: str, own: str, foreign: str) -> list[str]:
    """``readAnnotation``'s query rules on record ``id``, whose annotation is ``own`` (``foreign`` belongs to
    another record)."""
    last = own[-1]
    queries = [
        f'annotation_id={own}', f'annotation_id={own}&x=1', f'x=1&annotation_id={own}',
        f'annotation_id={own}&annotation_id={own}', 'x=1', 'x=1&x=2', 'annotation_id=', 'annotation_id',
        f'annotation_id={own.upper()}', f'annotation_id={foreign}', f'&&annotation_id={own}&', f'annotation%5Fid={own}',
        f'annotation_id={own[:-1]}%{ord(last):02X}', f'annotation_id={own}+', f'annotation_id=+{own}',
        f'annotation_id={sha("no such annotation")}', 'annotation_id=%FF', '', '=annotation_id', ';annotation_id=x',
        f'annotation_id={own}&=', f'annotation_id={own};x=1', f'ANNOTATION_ID={own}', f'annotation_id={own}&&&',
    ]
    return [f'{LIBRARY}/{id}?{query}' for query in queries]


def annotation_root(path: Path, python: str, kind: str, outside: Path) -> dict:
    """A library root whose Node annotation directory is broken in one way (``kind``); returns the record and
    annotation ids its targets use."""
    keys = library_root(path, python)
    record = keys['design']['default']
    directory = path / NODE_ANNOTATIONS
    own = annotation(OWNER, record)
    if kind == 'tampered':
        broken = annotations(path, record, broken=True)
        write_annotation(directory, own)
        return {'record': record, 'ids': [own['id'], broken['tampered']['id'], broken['invalid']['id']]}
    if kind == 'stray':
        write_annotation(directory, own)
        (directory / 'notes.txt').write_text('stray', encoding='utf-8')
    elif kind == 'link':
        write_annotation(outside, own)
        directory.symlink_to(outside, target_is_directory=True)
    elif kind == 'closed':
        write_annotation(directory, own)
    elif kind == 'other-owner':
        own = annotation(OTHER, record)
        write_annotation(directory, own)
    else:
        raise ValueError(kind)
    return {'record': record, 'ids': [own['id']]}


def annotation_targets(record: str, ids: list[str]) -> list[str]:
    targets = [LIBRARY]
    for id in ids:
        targets += [f'{LIBRARY}/{record}?annotation_id={id}', f'{LIBRARY}/{record}/bundle?annotation_id={id}']
    return targets


def known(roots: dict, keys: dict) -> dict:
    """The differences by design: ``(root, target) -> ((Node status, error), (Python status, error))``, an error
    of ``None`` not compared."""
    found = {}
    for root in roots:
        record = keys.get(root, {}).get('record')
        if record:
            # Node's public-library visibility route is not carried over (R4).
            found[(root, f'{LIBRARY}/{record}/visibility')] = ((405, '请使用POST'), (404, '未知计算接口'))
    other = keys['annotations-other-owner']
    # Annotations are read without regard to their owner (the local service has one user); the list compares them
    # by owner (``same_lists``).
    for suffix in ('', '/bundle'):
        target = f'{LIBRARY}/{other["record"]}{suffix}?annotation_id={other["ids"][0]}'
        found[('annotations-other-owner', target)] = ((404, 'Electrode name annotation not found.'), (200, None))
    return found


@pytest.fixture(scope='session')
def parity(tmp_path_factory):
    base = tmp_path_factory.mktemp('library-parity')
    scratch = tmp_path_factory.mktemp('library-parity-node')
    python = fake_interpreters(base / 'fakes')['coords']
    roots: dict[str, Path] = {}
    keys: dict[str, dict] = {}

    # Every kind of record, saved searches whose coordinates the stand-in interpreter exports, editor records,
    # heads, and this owner's annotations beside a temporary file.
    root = base / 'base'
    built = bundle_root(root, python)
    built['patched'] = patched_caches(root, built['provenance'], python)
    built['editor'] = editor_records(root, base / 'outside')
    head_package(root, 'ixi002')
    head_package(root, 'ixi012', skip=('mapping.npz',))
    design = built['design']
    own = annotation(OWNER, design['default'])
    noise = annotation(OWNER, design['noise'], [f'Ch{i}' for i in range(64)])
    for value in (own, noise):
        write_annotation(root / NODE_ANNOTATIONS, value)
    (root / NODE_ANNOTATIONS / TEMPORARY).write_text('{}', encoding='utf-8')
    roots['base'] = root
    keys['base'] = {**built, 'record': design['default'], 'own': own['id'], 'noise': noise['id']}
    (base / 'symlinked').symlink_to(root, target_is_directory=True)
    roots['symlinked'] = base / 'symlinked'
    keys['symlinked'] = keys['base']
    (base / 'outside-code.py').write_text('linked code', encoding='utf-8')
    linked = library_root(base / 'linked-code', python, linked=base / 'outside-code.py')
    roots['linked-code'] = base / 'linked-code'
    keys['linked-code'] = {**linked, 'record': linked['design']['default']}
    (base / 'bare').mkdir()
    roots['bare'] = base / 'bare'
    keys['bare'] = {}
    closed = None
    for kind in ANNOTATION_KINDS:
        if kind == 'closed' and os.geteuid() == 0:
            continue
        name = f'annotations-{kind}'
        keys[name] = annotation_root(base / name, python, kind, base / f'{name}-outside')
        roots[name] = base / name
        if kind == 'closed':
            closed = base / name / NODE_ANNOTATIONS

    extra = [built['radius'][name] for name in ('malformed', 'unreadable', 'missing', 'other-code')]
    extra += [design['missing'], design['checksum'], sha('no such record')]
    listed = [row['id'] for row in Library(str(root), runtime_config(str(root), python, env={})).list()['records']]
    record = keys['base']['record']
    http = [LIBRARY, *CATALOGS]
    http += [f'{LIBRARY}/{id}' for id in [*listed, *extra]]
    http += [f'{LIBRARY}/{id}/bundle' for id in [*listed, *extra]]
    http += query_targets(record, own['id'], noise['id'])
    http += [f'{LIBRARY}/{record}/bundle?{query}' for query in (
        f'annotation_id={own["id"]}', f'annotation_id={own["id"]}&x=1', 'annotation_id=', f'annotation_id={noise["id"]}',
        'x=1')]
    http += [f'{LIBRARY}/{sha("no such record")}{suffix}?annotation_id=x&x=1' for suffix in ('', '/bundle')]
    http += [*unknown_targets(record), f'{LIBRARY}/{record}/visibility']
    # Every bundle goes through the route below; the library level packs the saved searches and the misses (every
    # Python get re-validates the radius caches, as Node's does, at about 0.2 s on this root).
    searches = [built['radius'][name] for name in HISTORY_REQUESTS]
    items = [{'id': 'base', 'root': str(root), 'python': python, 'requests': RADIUS_REQUESTS, 'ids': extra,
              'bundles': [*searches, *extra], 'catalogs': True, 'http': http}]
    for name in ('symlinked', 'linked-code'):
        record_id = keys[name]['record']
        # The link to the root refuses every source; under the linked code file, the radius rows are what changes.
        bundles = True if name == 'symlinked' else [*keys[name]['radius'].values(), record_id]
        items.append({'id': name, 'root': str(roots[name]), 'python': python, 'requests': RADIUS_REQUESTS,
                      'bundles': bundles, 'catalogs': True,
                      'http': [LIBRARY, *CATALOGS, f'{LIBRARY}/{record_id}', f'{LIBRARY}/{record_id}/bundle',
                               f'{LIBRARY}/{record_id}/visibility']})
    items.append({'id': 'bare', 'root': str(roots['bare']), 'python': python, 'requests': RADIUS_REQUESTS,
                  'ids': [record], 'bundles': [record], 'catalogs': True,
                  'http': [LIBRARY, *CATALOGS, f'{LIBRARY}/{record}', f'{LIBRARY}/{record}/bundle',
                           *unknown_targets(record)]})
    for name in roots:
        if name.startswith('annotations-'):
            item = keys[name]
            items.append({'id': name, 'root': str(roots[name]), 'python': python, 'ids': [item['record']],
                          'listed': False,
                          'http': [*annotation_targets(item['record'], item['ids']),
                                   f'{LIBRARY}/{item["record"]}/visibility']})

    spec = {'serviceDirectory': str(scratch / 'service'), 'owner': OWNER, 'roots': items}
    before = snapshot(base)
    mode = closed.stat().st_mode & 0o7777 if closed is not None else None
    if closed is not None:
        closed.chmod(0)
    try:
        node = run_library_node(spec, scratch)
        packer = Packer()
        python_out = {}
        for item in items:
            entry = python_library(item, packer)
            entry['http'] = python_http(item, scratch / 'workspaces' / item['id'])
            python_out[item['id']] = entry
    finally:
        if closed is not None:
            closed.chmod(mode)
    assert snapshot(base) == before
    assert not (scratch / 'workspaces').exists()
    return {'roots': roots, 'keys': keys, 'items': {item['id']: item for item in items}, 'node': node['roots'],
            'python': python_out}


ROOTS = ['base', 'symlinked', 'linked-code', 'bare', *(f'annotations-{kind}' for kind in ANNOTATION_KINDS)]


def _skip_missing(parity: dict, root: str) -> None:
    if root not in parity['node']:
        pytest.skip('permissions do not apply to root')


@needs_node
@pytest.mark.parametrize('root', ROOTS)
def test_library_level_parity(root, parity):
    """identityFor, the list, every record, every bundle and the catalogs equal Node's on each root."""
    _skip_missing(parity, root)
    assert library_differences(parity['node'][root], parity['python'][root]) == []


@needs_node
@pytest.mark.parametrize('root', ROOTS)
def test_http_parity(root, parity):
    """Each route answers as Node's composed service does, apart from the differences by design."""
    _skip_missing(parity, root)
    expected = known(parity['roots'], parity['keys'])
    found = []
    for node, python in zip(parity['node'][root]['http'], parity['python'][root]['http'], strict=True):
        if (root, node['target']) in expected:
            continue
        difference = http_difference(node, python, parity['items'][root]['root'])
        if difference is not None:
            found.append(difference)
    assert found == []


def _error(answer: dict) -> Optional[str]:
    value = jsjson.parse(answer['body'])
    return value.get('error') if isinstance(value, dict) else None


def _text(answer: dict) -> str:
    """An answer's body, or the packed text of a large bundle."""
    return answer['body'] if 'body' in answer else answer['packed']['text']


@needs_node
def test_known_differences_are_the_documented_ones(parity):
    """Node's public library visibility route (405 on GET) is an unknown path here, and another owner's
    annotations are listed and read, since the local service has one user."""
    expected = known(parity['roots'], parity['keys'])
    seen = 0
    for root in parity['node']:
        for node, python in zip(parity['node'][root]['http'], parity['python'][root]['http'], strict=True):
            if (root, node['target']) not in expected:
                continue
            seen += 1
            theirs, mine = expected[(root, node['target'])]
            assert (node['status'], _error(node) if theirs[1] else None) == theirs, node['target']
            assert (python['status'], _error(python) if mine[1] else None) == mine, python['target']
    assert seen == len(expected)
    other = parity['keys']['annotations-other-owner']
    node_list = jsjson.parse(parity['node']['annotations-other-owner']['http'][0]['body'])
    python_list = jsjson.parse(parity['python']['annotations-other-owner']['http'][0]['body'])
    assert node_list['electrode_annotations'] == []
    assert [value['id'] for value in python_list['electrode_annotations']] == other['ids']
    # The rest of that list (records as a set, under any locale) is compared by test_http_parity (same_lists).
    assert same_lists(LIBRARY, without_access(node_list), redact_payload(python_list),
                      parity['items']['annotations-other-owner']['root'])


def _answers(parity: dict, root: str, host: str = 'node') -> dict[str, dict]:
    return {answer['target']: answer for answer in parity[host][root]['http']}


@needs_node
def test_parity_covers_each_route_outcome(parity):
    """The roots reach what the comparison is for: every dataset in the list with compatible and incompatible
    radius rows, warnings that Node redacts, Node's visibility members (taken out), bundles of each dataset with the
    stand-in export, each answer of the annotation query, each storage failure, and each prefix's 404."""
    keys, node = parity['keys'], parity['node']
    base = _answers(parity, 'base')
    listing = jsjson.parse(base[LIBRARY]['body'])
    assert {row['dataset_id'] for row in listing['records']} == {'offline_radius', 'strict_area', 'historical_area',
                                                                 'cache', 'design_evaluation'}
    assert {row.get('compatible') for row in listing['records'] if row['dataset_id'] == 'cache'} == {True, False}
    assert 'library_scope' in listing and any('visibility' in row for row in listing['records'])
    assert [value['id'] for value in listing['electrode_annotations']] == sorted([keys['base']['own'],
                                                                                  keys['base']['noise']])
    python_listing = jsjson.parse(_answers(parity, 'base', 'python')[LIBRARY]['body'])
    assert list(python_listing) == ['schema', 'local_only', 'records', 'warnings', 'datasets', 'retention',
                                    'electrode_annotations']
    warnings = [jsjson.parse(_answers(parity, name)[LIBRARY]['body']).get('warnings', [])
                for name in parity['node'] if _answers(parity, name)[LIBRARY]['status'] == 200]
    assert any('[server path]' in warning for group in warnings for warning in group)
    bundles = [jsjson.parse(_text(answer)) for target, answer in base.items()
               if target.endswith('/bundle') and answer['status'] == 200]
    assert {bundle['record']['dataset_id'] for bundle in bundles} == {
        'offline_radius', 'strict_area', 'historical_area', 'cache', 'design_evaluation'}
    assert any(bundle['record']['dataset_id'] == 'cache' and bundle['coordinate_note'] is None
               and isinstance((bundle['snapshots'][0] or {}).get('xyzMm'), list) for bundle in bundles)
    record, own = keys['base']['record'], keys['base']['own']
    query = {target.split('?', 1)[1]: (answer['status'], _error(answer)) for target, answer in base.items()
             if target.startswith(f'{LIBRARY}/{record}?')}
    assert query[f'annotation_id={own}'] == (200, None)
    assert query[f'&&annotation_id={own}&'] == (200, None)
    assert query[f'annotation%5Fid={own}'] == (200, None)
    assert query['x=1'] == (200, None)
    assert query[f'annotation_id={own}&x=1'] == (400, 'Invalid electrode name annotation query.')
    assert query[f'annotation_id={own}&annotation_id={own}'] == (400, 'Invalid electrode name annotation query.')
    assert query[f'annotation_id={own}+'] == (404, 'Electrode name annotation not found.')
    with_annotation = jsjson.parse(base[f'{LIBRARY}/{record}?annotation_id={own}']['body'])['record']
    assert list(with_annotation)[-2:] == ['visibility', 'electrode_annotation']
    missing = sha('no such record')
    assert (base[f'{LIBRARY}/{missing}?annotation_id=x&x=1']['status'],
            _error(base[f'{LIBRARY}/{missing}?annotation_id=x&x=1'])) == (404, '记录不存在或完整性校验未通过')
    assert _error(base[f'{LIBRARY}/{missing}/bundle?annotation_id=x&x=1']) == '记录不存在'
    assert {_error(base[f'{LIBRARY}/{record}/bundle?annotation_id={own}&x=1'])} == {
        'Invalid electrode name annotation query.'}
    linked = _answers(parity, 'symlinked')
    assert linked[f'{LIBRARY}/{record}/bundle']['status'] == 500
    assert _error(linked[f'{LIBRARY}/{record}/bundle']) == '计算记录无法读取'
    failures = {}
    for name in parity['node']:
        if name.startswith('annotations-'):
            failures[name] = [(answer['status'], _error(answer)) for answer in node[name]['http']]
    tampered = failures['annotations-tampered']
    assert tampered[0][0] in (400, 409) and tampered[1] == (200, None)
    assert tampered[3] == (409, 'Electrode name annotation failed integrity checks.')
    assert tampered[5][0] == 400
    assert failures['annotations-stray'][0] == (409, 'Electrode name storage needs inspection.')
    assert failures['annotations-stray'][1] == (200, None)
    assert failures['annotations-link'][0] == (409, 'Electrode name storage is unavailable.')
    assert failures['annotations-link'][1] == (409, 'Electrode name storage is unavailable.')
    if 'annotations-closed' in failures:
        assert failures['annotations-closed'][0] == (500, '计算记录无法读取')
        assert failures['annotations-closed'][1] == (404, 'Electrode name annotation not found.')
    assert {_error(base[target]) for target in unknown_targets(record) if base[target]['status'] == 404} == {
        '未知计算接口', 'Unknown editor endpoint', '未知源实验接口', '未知设计评价接口'}


# --- The real installation (EEG_KEY_PARITY_ROOT) ----------------------------------------------------------------

REAL_ROOT = os.environ.get('EEG_KEY_PARITY_ROOT')
real_root = pytest.mark.skipif(not REAL_ROOT, reason='set EEG_KEY_PARITY_ROOT to a checkout with results/v2')
# Bundles compared through the routes, by dataset (the first ones listed); all of them are compared at the library
# level by test_bundle.py.
REAL_BUNDLES = {'offline_radius': 2, 'strict_area': 3, 'historical_area': 3, 'cache': 7, 'design_evaluation': 2}


@pytest.mark.data_bundle
@real_root
@needs_node
def test_real_root_library_routes_parity(tmp_path):
    """The installation's list, every record and the catalogs through both hosts' library and routes, and the
    bundles of a sample of each dataset through the routes (the cache bundles export their frozen-bank coordinates
    with the installation's compute interpreter in both hosts). Nothing is written under the root."""
    watched = [Path(REAL_ROOT) / name for name in ('results/v2', 'webapp/public/data', 'scripts', 'src')]
    before = [snapshot(path) for path in watched]
    rows = Library(REAL_ROOT, runtime_config(REAL_ROOT, env={})).list()['records']
    sample, taken = [], dict.fromkeys(REAL_BUNDLES, 0)
    for row in rows:
        if taken.get(row['dataset_id'], 0) < REAL_BUNDLES.get(row['dataset_id'], 0):
            taken[row['dataset_id']] += 1
            sample.append(row['id'])
    http = [LIBRARY, *CATALOGS, *(f'{LIBRARY}/{row["id"]}' for row in rows), *(f'{LIBRARY}/{id}/bundle' for id in sample)]
    item = {'id': 'real', 'root': REAL_ROOT, 'catalogs': True, 'http': http}
    node = run_library_node({'serviceDirectory': str(tmp_path / 'service'), 'owner': OWNER, 'roots': [item]},
                            tmp_path)['roots']['real']
    python = python_library(item, Packer())
    python['http'] = python_http(item, tmp_path / 'workspace')
    assert library_differences(node, python) == []
    found = [difference for difference in (http_difference(theirs, mine, REAL_ROOT) for theirs, mine in zip(
        node['http'], python['http'], strict=True)) if difference is not None]
    assert found == []
    datasets: dict[str, int] = {}
    for answer in node['http'][len(CATALOGS) + 1:len(CATALOGS) + 1 + len(rows)]:
        assert answer['status'] == 200, answer['target']
        dataset = jsjson.parse(answer['body'])['record']['dataset_id']
        datasets[dataset] = datasets.get(dataset, 0) + 1
    assert (datasets['offline_radius'], datasets['strict_area'], datasets['historical_area']) == (342, 30, 30)
    assert all(answer['status'] == 200 for answer in node['http'][:len(CATALOGS) + 1])
    # Node's bundles through the routes cover every dataset its list counts, up to REAL_BUNDLES each.
    listed = {dataset['id']: dataset['count'] for dataset in jsjson.parse(_text(node['http'][0]))['datasets']}
    bundled: dict[str, int] = {}
    for answer in node['http'][len(http) - len(sample):]:
        assert answer['status'] == 200, answer['target']
        dataset = jsjson.parse(_text(answer))['record']['dataset_id']
        bundled[dataset] = bundled.get(dataset, 0) + 1
    assert bundled == {dataset: min(count, listed[dataset]) for dataset, count in REAL_BUNDLES.items()
                       if listed[dataset]}
    assert [before == after for before, after in zip(before, [snapshot(path) for path in watched])] == [True] * 4
