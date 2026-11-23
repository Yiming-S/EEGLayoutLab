"""``eeglayoutlab.jobs.nodepath`` equals Node's ``path.posix`` (plan B7) on the ``paths`` corpus
(tests/schema_parity/reference.mjs): dot segments, repeated and trailing slashes, absolute parts, empty strings,
a leading ``//`` and non-BMP characters."""
from __future__ import annotations

import os.path

import pytest

from eeglayoutlab.jobs import nodepath
from schema_parity_support import CORPUS, needs_node


def _call(name, args, cwd):
    if name == 'relative':
        return nodepath.relative(*args, cwd=cwd)
    return getattr(nodepath, name)(*args)


@needs_node
def test_path_functions_match_node():
    corpus = CORPUS['paths']
    assert {name for name, _, _ in corpus['cases']} == {'join', 'dirname', 'resolve', 'relative', 'normalize'}
    mismatches = [(name, args, expected, _call(name, args, corpus['cwd'])) for name, args, expected in corpus['cases']
                  if _call(name, args, corpus['cwd']) != expected]
    assert mismatches == []


@needs_node
def test_resolve_with_an_explicit_cwd_matches_node():
    # The corpus passes an absolute cwd as resolve's first argument; the cwd keyword gives the same result.
    cases = [(args, expected) for name, args, expected in CORPUS['paths']['cases'] if name == 'resolve']
    assert cases and [args for args, expected in cases if nodepath.resolve(*args[1:], cwd=args[0]) != expected] == []


@pytest.mark.parametrize('call, node, python', [
    (lambda m: m.dirname('a'), '.', ''),
    (lambda m: m.dirname('a/b/'), 'a', 'a/b'),
    (lambda m: m.join('a', '/b'), 'a/b', '/b'),
    (lambda m: m.normalize('//a'), '/a', '//a'),
])
def test_os_path_differs_from_node(call, node, python):
    # Why key strings are never built with os.path (plan 2.2).
    assert call(nodepath) == node
    assert call(_OsPath) == python


class _OsPath:
    dirname = staticmethod(os.path.dirname)
    join = staticmethod(os.path.join)
    normalize = staticmethod(os.path.normpath)


def test_resolve_never_follows_symbolic_links(tmp_path):
    (tmp_path / 'real').mkdir()
    (tmp_path / 'link').symlink_to(tmp_path / 'real')
    assert nodepath.resolve(str(tmp_path / 'link'), 'x/../y') == f'{tmp_path}/link/y'


def test_relative_and_is_absolute():
    assert nodepath.relative('/root', '/root/.runtime/simnibs-4.6.0/bin/python') == '.runtime/simnibs-4.6.0/bin/python'
    assert nodepath.relative('/a/b/c', '/a/x') == '../../x'
    assert nodepath.relative('a', 'b', cwd='/w') == '../b'
    assert nodepath.is_absolute('/a') and not nodepath.is_absolute('a') and not nodepath.is_absolute('')


def test_paths_must_be_strings():
    for call in (lambda: nodepath.join('a', None), lambda: nodepath.dirname(None), lambda: nodepath.resolve('/a', 1)):
        with pytest.raises(TypeError):
            call()


def test_js_sort_uses_utf16_code_units():
    names = ['\uff5a.json', '\U0001F600.json', 'a.json', 'Z.json', '\u00e4.json']
    assert nodepath.js_sort(names) == ['Z.json', 'a.json', '\u00e4.json', '\U0001F600.json', '\uff5a.json']
    assert sorted(names) != nodepath.js_sort(names)  # code-point order puts U+FF5A before U+1F600
