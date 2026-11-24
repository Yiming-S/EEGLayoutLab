"""``eeglayoutlab.jobs.nodefs`` resolves real paths and names as Node does (plan B4, B8).

Node's ``InputIntegrity`` resolves its root with ``fs.realpathSync`` (lib/fs.js: link targets lexically, the given
spelling kept) and every input with ``fs.promises.realpath`` (``realpath(3)``: physically, and on macOS in the
on-disk letter case and Unicode normalization). ``tests/service/parity/fs.mjs`` runs both, ``readdir`` and
``readFile`` on a tree of links, loops, misspelled and differently normalized paths; ``realpath_sync``,
``realpath``, ``readdir`` and ``read_file`` must give the same values, or fail with the same code and message
(``records.node_message``: the syscall, and the path as the system received it). Without Node (or the service
extra) the parity test is skipped.
"""
from __future__ import annotations

import errno
import json
import os
from pathlib import Path
import subprocess
import unicodedata

import pytest

from eeglayoutlab.jobs import nodefs, nodepath
from eeglayoutlab.jobs.records import node_message
from eeglayoutlab.schemas import jsjson

from .key_parity_support import NODE_ENV, ROOT, needs_node

DRIVER = ROOT / 'tests/service/parity/fs.mjs'
NFC = unicodedata.normalize('NFC', 'Jos\u00e9')


def _tree(base: Path) -> Path:
    t = base / 't'
    (t / 'Dir/Sub').mkdir(parents=True)
    (t / 'Dir/Sub/f.txt').write_text('f', encoding='utf-8')
    (t / 'Dir/Sub/g.txt').write_text('g', encoding='utf-8')
    (t / 'rel').symlink_to('Dir/Sub/f.txt')
    (t / 'abs').symlink_to(t / 'Dir/Sub/f.txt')
    (t / 'chain').symlink_to('rel')
    (t / 'dirlink').symlink_to('Dir')
    # lex -> alias/../x.txt with alias -> deep/b: lexically t/x.txt, physically t/deep/x.txt.
    (t / 'deep/b').mkdir(parents=True)
    (t / 'deep/x.txt').write_text('physical', encoding='utf-8')
    (t / 'x.txt').write_text('lexical', encoding='utf-8')
    (t / 'alias').symlink_to('deep/b')
    (t / 'lex').symlink_to('alias/../x.txt')
    (t / 'lexdir').symlink_to('alias/../deep')
    (t / 'dangling').symlink_to('missing')
    (t / 'loop1').symlink_to('loop2')
    (t / 'loop2').symlink_to('loop1')
    (t / 'caselink').symlink_to(f'{t}/DIR/sub/F.TXT')
    (t / NFC).mkdir()
    (t / NFC / 'n.txt').write_text('n', encoding='utf-8')
    (t / 'nfdlink').symlink_to(unicodedata.normalize('NFD', f'{t}/{NFC}/n.txt'))
    return t


def _paths(t: Path) -> list[str]:
    s = str(t)
    return [
        f'{s}/Dir/Sub/f.txt', f'{s}/dir/sub/F.TXT', f'{s}/DIR', f'{s}/rel', f'{s}/abs', f'{s}/chain', f'{s}/dirlink/Sub/f.txt',
        f'{s}/DIRLINK/sub/f.txt', f'{s}/lex', f'{s}/lexdir/x.txt', f'{s}/alias/../x.txt', f'{s}/dirlink/../x.txt',
        f'{s}/dangling', f'{s}/loop1', f'{s}/Dir/Sub/f.txt/x', f'{s}/missing', f'{s}/missing/x', f'{s}/caselink',
        f'{s}/{NFC}/n.txt', unicodedata.normalize('NFD', f'{s}/{NFC}/n.txt'), f'{s}/nfdlink',
        f'{s}/./Dir//Sub/../Sub/f.txt', f'{s}/Dir/', f'{s}/', '/', '//', f'{s}/Dir/Sub/f.txt\0',
        f'{s}/\ud800', f'{s}/\ufffd',
    ]


def _python(function, path: str) -> dict:
    try:
        return {'ok': True, 'value': function(path)}
    except OSError as error:
        return {'ok': False, 'code': errno.errorcode[error.errno], 'message': node_message(error)}
    except (TypeError, ValueError) as error:
        return {'ok': False, 'code': getattr(error, 'code', None) or f'{type(error).__name__}: {error}',
                'message': str(error)}


# fs.mjs's operations and theirs here: readdir's names sorted (the tree's are in the BMP, where JavaScript's sort
# and Python's agree), readFile by its length.
OPERATIONS = {'sync': nodefs.realpath_sync, 'promise': nodefs.realpath,
              'list': lambda path: sorted(nodefs.readdir(path)), 'read': lambda path: len(nodefs.read_file(path))}


@pytest.fixture(scope='module')
def node_results(tmp_path_factory):
    base = tmp_path_factory.mktemp('nodefs')
    t = _tree(base)
    spec, out = base / 'spec.json', base / 'out.json'
    spec.write_text(jsjson.stringify({'paths': _paths(t)}), encoding='utf-8')
    subprocess.run(['node', str(DRIVER), str(spec), str(out)], check=True, cwd=ROOT, env=NODE_ENV)
    return t, json.loads(out.read_text(encoding='utf-8'))


@needs_node
def test_real_paths_listings_reads_and_their_errors_match_node(node_results):
    t, node = node_results
    assert [entry['path'] for entry in node['results']] == _paths(t)
    mismatches = []
    for entry in node['results']:
        for name, function in OPERATIONS.items():
            ours = _python(function, entry['path'])
            if ours != entry[name]:
                mismatches.append((name, entry['path'], entry[name], ours))
    assert mismatches == []


@needs_node
def test_the_two_real_paths_differ_where_node_s_do(node_results):
    # Pins what the corpus exercises; parity alone would also pass if both functions were os.path.realpath on a
    # tree without these cases.
    t, node = node_results
    by_path = {entry['path']: entry for entry in node['results']}
    s = str(t)
    lexical = by_path[f'{s}/lex']
    assert lexical['sync']['value'].endswith('/t/x.txt') and lexical['promise']['value'].endswith('/t/deep/x.txt')
    assert by_path[f'{s}/dangling']['sync']['code'] == by_path[f'{s}/dangling']['promise']['code'] == 'ENOENT'
    assert by_path[f'{s}/loop1']['promise']['code'] == 'ELOOP'
    assert by_path[f'{s}/Dir/Sub/f.txt\0']['sync']['code'] == 'ERR_INVALID_ARG_VALUE'
    if os.path.exists(f'{s}/dir/sub/F.TXT'):  # a case-insensitive volume (macOS)
        misspelled = by_path[f'{s}/dir/sub/F.TXT']
        assert misspelled['sync']['value'].endswith('/t/dir/sub/F.TXT')
        assert misspelled['promise']['value'].endswith('/t/Dir/Sub/f.txt')
        assert by_path[f'{s}/caselink']['promise']['value'].endswith('/t/Dir/Sub/f.txt')
        # os.path.realpath keeps the spelling, so it cannot stand in for realpath(3).
        assert os.path.realpath(f'{s}/dir/sub/F.TXT') != misspelled['promise']['value']
    nfd = unicodedata.normalize('NFD', f'{s}/{NFC}/n.txt')
    if os.path.exists(nfd):  # a normalization-insensitive volume (APFS)
        assert by_path[nfd]['sync']['value'] == nfd
        assert by_path[nfd]['promise']['value'] == f'{s}/{NFC}/n.txt'


def test_realpath_sync_resolves_link_targets_lexically(tmp_path):
    # Without Node: the walk of lib/fs.js. os.path.realpath resolves the same link physically.
    t = _tree(tmp_path)
    assert nodefs.realpath_sync(f'{t}/lex') == f'{os.path.realpath(t)}/x.txt'
    assert os.path.realpath(f'{t}/lex') == f'{os.path.realpath(t)}/deep/x.txt'
    assert nodefs.realpath(f'{t}/lex') == f'{os.path.realpath(t)}/deep/x.txt'
    assert nodefs.realpath_sync(f'{t}/chain') == f'{os.path.realpath(t)}/Dir/Sub/f.txt'
    for path, error in ((f'{t}/dangling', FileNotFoundError), (f'{t}/missing', FileNotFoundError),
                        (f'{t}/Dir/Sub/f.txt/x', NotADirectoryError)):
        for function in (nodefs.realpath_sync, nodefs.realpath):
            with pytest.raises(error):
                function(path)
    with pytest.raises(OSError) as raised:
        nodefs.realpath_sync(f'{t}/loop1')
    assert raised.value.errno == errno.ELOOP


def test_realpath_sync_stops_where_node_would_loop_forever(tmp_path, monkeypatch):
    # a -> b/../a with b -> deep/x: the kernel reaches deep/a, but the lexical walk comes back to t/a, from which
    # Node's realpathSync restarts forever. The port raises ELOOP as soon as the walk restarts from a string it
    # has seen (here the original path, after one link).
    t = tmp_path / 't'
    (t / 'deep/x').mkdir(parents=True)
    (t / 'deep/a').mkdir()
    (t / 'b').symlink_to('deep/x')
    (t / 'a').symlink_to('b/../a')
    real_lstat, calls = nodefs.lstat, []
    monkeypatch.setattr(nodefs, 'lstat', lambda path: calls.append(path) or real_lstat(path))
    with pytest.raises(OSError) as raised:
        nodefs.realpath_sync(f'{t}/a/f')
    assert raised.value.errno == errno.ELOOP and len(calls) < 20


def test_realpath_sync_bounds_the_number_of_links(tmp_path, monkeypatch):
    # A deliberate difference (nodefs._MAX_RESTARTS): Node follows any number of links that make progress.
    (tmp_path / 'self').symlink_to('.')
    (tmp_path / 'x.txt').write_text('x', encoding='utf-8')
    monkeypatch.setattr(nodefs, '_MAX_RESTARTS', 5)
    root = nodefs.realpath_sync(str(tmp_path))
    assert nodefs.realpath_sync(root + '/self' * 5 + '/x.txt') == f'{root}/x.txt'
    with pytest.raises(OSError) as raised:
        nodefs.realpath_sync(root + '/self' * 6 + '/x.txt')
    assert raised.value.errno == errno.ELOOP


def test_path_arguments_fail_with_node_codes():
    # Both are TypeErrors in Node, so its routes answer 500 for them (test_compute_routes).
    for function in (nodefs.realpath, nodefs.realpath_sync, nodefs.read_file, nodefs.readdir, nodefs.stat):
        with pytest.raises(nodefs.InvalidArgValueError) as raised:
            function('/tmp/a\0b')
        assert raised.value.code == 'ERR_INVALID_ARG_VALUE' and isinstance(raised.value, TypeError)
        with pytest.raises(nodepath.InvalidArgTypeError) as raised:
            function(None)
        assert raised.value.code == 'ERR_INVALID_ARG_TYPE'


def test_strings_become_bytes_and_names_strings_as_in_node():
    # V8 writes a lone surrogate as U+FFFD; Python's file system encoding would refuse it or keep it escaped.
    assert nodefs.encode('a\ud800b\U0001F600') == 'a\ufffdb\U0001F600'.encode('utf-8')
    assert nodefs.decode(b'\xff.json') == '\ufffd.json'
    assert os.fsdecode(b'\xff.json') == '\udcff.json'


def test_readdir_decodes_names_that_are_not_utf8(monkeypatch, tmp_path):
    # Node lists b'\xff.json' as '\ufffd.json', which then fails to open (ENOENT); os.listdir(str) would give
    # '\udcff.json', which opens the original file. macOS cannot create such a name, so os.listdir is replaced.
    real = os.listdir
    monkeypatch.setattr(os, 'listdir', lambda path: [b'\xff.json', b'ok.json'] if isinstance(path, bytes) else
                        ['\udcff.json', 'ok.json'] if path == str(tmp_path) else real(path))
    assert nodefs.readdir(str(tmp_path)) == ['\ufffd.json', 'ok.json']
