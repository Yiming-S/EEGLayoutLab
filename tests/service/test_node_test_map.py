"""The Node test map (plan section 6.3): phase 2 exits when every Node test is ported to a Python test or mapped.

``node_tests.toml`` has one entry under ``[sites]`` per ``test(`` / ``dataTest(`` call site in the unit-test files,
the ``webapp/scripts/check-*.mjs`` that import ``node:test`` (the files ``run-unit-tests.mjs`` runs). A site is
keyed by ``"<file>::<title>"`` when its title is a string literal (quotes, or a template without substitutions),
else by ``"<file>:<line>"``, with the file's basename and the line of ``test``. A title that recurs in one file
keys its second and later sites, in source order, as ``"<file>::<title> #2"``, ``#3`` and so on. The opt-in live
and Playwright scripts (the other ``check-*.mjs``) are listed under ``[scripts]`` with the slice that retargets
them to the Python service.

Dispositions (tests.md section 0):

- ``P``: ported; ``target`` names the Python test, ``"tests/service/test_<name>.py::test_x"`` or
  ``"...::TestClass::test_x"``: a test that pytest collects, named without a parametrized ``[id]``.
- ``pending``: to be ported in ``slice`` (2-10) into ``module``, ``"tests/service/test_<name>.py"``.
- ``C``: mirrored by format parity; ``mirror`` names the Python test (``"tests/<path>/test_<name>.py::test_x"``,
  as for ``P`` but anywhere under ``tests/``), ``formats`` the request formats it needs,
  and ``slice`` the slice that adds the formats that have no Node generator in ``tests/schema_parity/formats/``.
- ``NA``: stays in Node, adapted in ``slice``. ``D``: dropped, for ``reason`` R1-R7 (plan section 5.1).
  ``N``: stays in Node. ``E``: Node-host structure, retired with Node. ``CLI``: follows the Node command line.

Any entry may carry a ``note``. ``python tests/service/test_node_test_map.py`` prints the counts.
"""
from __future__ import annotations

import ast
from collections import Counter
from dataclasses import dataclass
from functools import cache
from pathlib import Path
import re
import tomllib

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / 'webapp/scripts'
MAP = Path(__file__).with_name('node_tests.toml')
FORMATS = ROOT / 'tests/schema_parity/formats'
UNIT_TEST_IMPORT = re.compile(r'''from ['"]node:test['"]''')  # as run-unit-tests.mjs selects files

# Slices whose ports are done: a pending (or NA) entry for one of them fails, unless PENDING_ALLOWED lists it.
SLICES_DONE = 8
# Sites of a done slice whose ports are written beside the map in the same stage; empty once a slice is linked.
PENDING_ALLOWED: frozenset[str] = frozenset()

# Per disposition: required and optional fields besides disposition and note.
FIELDS = {
    'P': ({'target'}, set()),
    'pending': ({'slice', 'module'}, set()),
    'C': ({'mirror'}, {'formats', 'slice'}),
    'NA': ({'slice'}, set()),
    'D': ({'reason'}, set()),
    'N': (set(), set()),
    'E': (set(), set()),
    'CLI': (set(), set()),
}
REASONS = {f'R{n}' for n in range(1, 8)}


# --- Call sites --------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Token:
    kind: str  # word, punct, string, template (no substitutions), part (of a template with substitutions), regex
    text: str  # the word or punctuation; the value of a string or template; '${' or '`' at the end of a part
    line: int


@dataclass(frozen=True)
class Site:
    file: str
    line: int
    title: str | None  # None when the title is not a string literal


_WORD = re.compile(r'[A-Za-z0-9_$\u0080-\U0010ffff]+')
_SPACE = frozenset(' \t\r\f\v\u00a0\u2028\u2029\ufeff')
_ESCAPES = {'b': '\b', 'f': '\f', 'n': '\n', 'r': '\r', 't': '\t', 'v': '\v', '0': '\0'}
# A '/' after one of these words starts a regular expression, as after an operator or an opening bracket.
_BEFORE_EXPRESSION = frozenset({'return', 'typeof', 'instanceof', 'in', 'of', 'new', 'delete', 'void', 'throw',
                                'case', 'do', 'else', 'yield', 'await'})


def _escape(source: str, i: int) -> tuple[str, int]:
    """The value of the escape sequence whose backslash is at ``i``, and the index after it."""
    c = source[i + 1]
    if c in _ESCAPES and not (c == '0' and source[i + 2:i + 3].isdigit()):
        return _ESCAPES[c], i + 2
    if c == 'x':
        return chr(int(source[i + 2:i + 4], 16)), i + 4
    if c == 'u' and source[i + 2] == '{':
        end = source.index('}', i + 3)
        return chr(int(source[i + 3:end], 16)), end + 1
    if c == 'u':
        return chr(int(source[i + 2:i + 6], 16)), i + 6
    if c == '\r':
        return '', i + (3 if source[i + 2:i + 3] == '\n' else 2)
    if c in '\n\u2028\u2029':
        return '', i + 2
    if c.isdigit():
        raise ValueError('octal escapes are not allowed in modules')
    return c, i + 2


def _text(parts: list[str]) -> str:
    # Escaped surrogate pairs (\uD83D\uDE00) join as in JavaScript's UTF-16 strings.
    return ''.join(parts).encode('utf-16-le', 'surrogatepass').decode('utf-16-le')


def tokenize(source: str) -> list[Token]:
    """The tokens of a module that call sites are found in; comments and white space are skipped."""
    tokens: list[Token] = []
    braces: list[bool] = []  # one per open '{' or '${', True for a template substitution
    i, line = 0, 1

    def template(i: int, whole: bool) -> int:
        # Template text from i to the closing '`' or the next '${'; returns the index after either.
        parts = []
        while source[i] != '`' and not source.startswith('${', i):
            if source[i] == '\\':
                value, i = _escape(source, i)
            else:  # template text reads CR and CRLF as LF
                value, i = ('\n', i + 1 + (source[i:i + 2] == '\r\n')) if source[i] == '\r' else (source[i], i + 1)
            parts.append(value)
        end = source[i] == '`'
        tokens.append(Token('template', _text(parts), line) if whole and end
                      else Token('part', '`' if end else '${', line))
        if not end:
            braces.append(True)
        return i + (1 if end else 2)

    try:
        while i < len(source):
            c = source[i]
            start = i
            if c in _SPACE or c == '\n':
                i += 1
            elif source.startswith('//', i):
                end = source.find('\n', i)
                i = len(source) if end < 0 else end
            elif source.startswith('/*', i):
                i = source.index('*/', i + 2) + 2
            elif c in '\'"':
                parts, i = [], i + 1
                while source[i] != c:
                    if source[i] in '\r\n':
                        raise ValueError(f'unterminated string on line {line}')
                    value, i = _escape(source, i) if source[i] == '\\' else (source[i], i + 1)
                    parts.append(value)
                tokens.append(Token('string', _text(parts), line))
                i += 1
            elif c == '`' or c == '}' and braces and braces[-1]:
                if c == '}':
                    braces.pop()
                i = template(i + 1, c == '`')
            elif c == '/' and (not tokens or tokens[-1].kind == 'punct' and tokens[-1].text not in ')]}'
                               or tokens[-1].kind == 'part' and tokens[-1].text == '${'
                               or tokens[-1].kind == 'word' and tokens[-1].text in _BEFORE_EXPRESSION):
                i, in_class = i + 1, False
                while in_class or source[i] != '/':
                    if source[i] == '\n':
                        raise ValueError(f'unterminated regular expression on line {line}')
                    in_class = (in_class or source[i] == '[') and source[i] != ']'
                    i += 2 if source[i] == '\\' else 1
                tokens.append(Token('regex', '', line))
                flags = _WORD.match(source, i + 1)
                i = flags.end() if flags else i + 1
            elif word := _WORD.match(source, i):
                tokens.append(Token('word', word.group(), line))
                i = word.end()
            else:
                if c == '{':
                    braces.append(False)
                elif c == '}' and braces:
                    braces.pop()
                tokens.append(Token('punct', c, line))
                i += 1
            line += source.count('\n', start, i)
    except IndexError:
        raise ValueError('unexpected end of module') from None
    if any(braces):
        raise ValueError('unterminated template')
    return tokens


def _is(token: Token, kind: str, *texts: str) -> bool:
    return token.kind == kind and (not texts or token.text in texts)


def call_sites(file: str, source: str) -> list[Site]:
    """The ``test(``, ``test.skip|only|todo(`` and ``dataTest(`` calls of one module, in source order."""
    tokens = tokenize(source) + [Token('end', '', 0)] * 4
    sites = []
    for k, token in enumerate(tokens):
        if not _is(token, 'word', 'test', 'dataTest') or k and (
                _is(tokens[k - 1], 'punct', '.') or _is(tokens[k - 1], 'word', 'function')):
            continue  # another word, or a method such as pattern.test(...)
        j = k + 1
        if token.text == 'test' and _is(tokens[j], 'punct', '.') and _is(tokens[j + 1], 'word', 'skip', 'only', 'todo'):
            j += 2
        if not _is(tokens[j], 'punct', '('):
            continue  # the import, or a hook such as test.after(...)
        title, after = tokens[j + 1], tokens[j + 2]
        literal = title.kind in ('string', 'template') and _is(after, 'punct', ',', ')')
        sites.append(Site(file, token.line, title.text if literal else None))
    return sites


def site_keys(sites: list[Site]) -> dict[str, Site]:
    keys: dict[str, Site] = {}
    seen: Counter[str] = Counter()
    for site in sites:
        if site.title is None:
            key = f'{site.file}:{site.line}'
        else:
            key = f'{site.file}::{site.title}'
            seen[key] += 1
            key += f' #{seen[key]}' if seen[key] > 1 else ''
        if key in keys:
            raise ValueError(f'two sites have the key {key!r}')
        keys[key] = site
    return keys


def unit_test_files() -> list[Path]:
    return [path for path in sorted(SCRIPTS.glob('check-*.mjs')) if UNIT_TEST_IMPORT.search(path.read_text('utf-8'))]


@cache
def node_sites() -> dict[str, Site]:
    return site_keys([site for path in unit_test_files() for site in call_sites(path.name, path.read_text('utf-8'))])


@cache
def node_map() -> dict:
    return tomllib.loads(MAP.read_text(encoding='utf-8'))


def entries() -> dict[str, dict]:
    return node_map().get('sites', {})


# --- Python tests ------------------------------------------------------------------------------------------------

# What pytest collects with its default python_files, python_classes and python_functions.
_TARGET = re.compile(r'(tests/(?:\w+/)*test_\w+\.py)::((?:Test\w*::)?test\w*)')


@cache
def _definitions(path: Path) -> frozenset[str]:
    """The module-level functions and the methods of ``Test`` classes of a test module."""
    names = set()
    for node in ast.parse(path.read_text(encoding='utf-8')).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, ast.ClassDef) and node.name.startswith('Test'):
            names |= {f'{node.name}::{item.name}' for item in node.body
                      if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))}
    return frozenset(names)


def defined(target: str) -> bool:
    """Whether ``tests/<path>/test_<name>.py::test_x`` (or ``::TestClass::test_x``) is a test pytest collects."""
    match = _TARGET.fullmatch(target)
    return match is not None and (ROOT / match[1]).is_file() and match[2] in _definitions(ROOT / match[1])


def target_problem(disposition: str, target: str) -> str | None:
    """Why ``target`` cannot be the Python test of a ``P`` (in tests/service/) or ``C`` entry; ``None`` if it can."""
    if disposition == 'P' and not target.startswith('tests/service/'):
        return 'a port is a test in tests/service/'
    if not defined(target):
        return 'is not a test that pytest collects (a module-level test function or a Test class method, no [id])'
    return None


# --- The map -----------------------------------------------------------------------------------------------------

def _malformed(entry: dict) -> str | None:
    if not isinstance(entry, dict):
        return 'is not a table'
    disposition = entry.get('disposition')
    if disposition not in FIELDS:
        return f'disposition {disposition!r} is not one of {sorted(FIELDS)}'
    required, optional = FIELDS[disposition]
    fields = set(entry) - {'disposition', 'note'}
    if fields - required - optional or required - fields:
        return f'{disposition} takes {sorted(required)} (optional {sorted(optional)}), not {sorted(fields)}'
    if not isinstance(entry.get('note', ''), str):
        return 'note is not a string'
    if disposition == 'D' and entry['reason'] not in REASONS:
        return f'reason {entry["reason"]!r} is not R1-R7'
    if 'slice' in entry and (type(entry['slice']) is not int or not 2 <= entry['slice'] <= 10):
        return f'slice {entry["slice"]!r} is not 2-10'
    if disposition == 'pending' and not re.fullmatch(r'tests/service/test_\w+\.py', str(entry['module'])):
        return f'module {entry["module"]!r} is not tests/service/test_<name>.py'
    if 'formats' in entry and not (isinstance(entry['formats'], list) and entry['formats']
                                   and all(isinstance(name, str) for name in entry['formats'])):
        return 'formats is not a list of format names'
    return None


def test_every_node_test_site_is_mapped():
    missing = sorted(set(node_sites()) - set(entries()))
    assert missing == [], 'add these Node test sites to tests/service/node_tests.toml:\n' + '\n'.join(missing)


def test_the_map_has_no_stale_entries():
    stale = sorted(set(entries()) - set(node_sites()))
    assert stale == [], 'these entries match no Node test site (renamed, moved or removed):\n' + '\n'.join(stale)


def test_entries_are_well_formed():
    problems = sorted(f'{key}: {problem}' for key, entry in entries().items() if (problem := _malformed(entry)))
    assert problems == [], '\n'.join(problems)


def test_ported_and_mirrored_sites_name_existing_python_tests():
    absent = []
    for key, entry in entries().items():
        if entry.get('disposition') in ('P', 'C'):
            target = str(entry.get('target', entry.get('mirror')))
            if problem := target_problem(entry['disposition'], target):
                absent.append(f'{key}: {target} {problem}')
    assert absent == [], 'these entries do not name a Python test of theirs:\n' + '\n'.join(sorted(absent))


@pytest.mark.parametrize('disposition, target, accepted', [
    ('P', 'tests/service/test_access.py::test_local_origin_host_and_remote_address_are_all_checked', True),
    ('C', 'tests/test_schema_parity.py::test_variant_parity', True),
    # A port belongs in tests/service/; a mirror may be elsewhere under tests/.
    ('P', 'tests/test_schema_parity.py::test_variant_parity', False),
    # A parametrized id is not checked against the parameters, so it is not accepted.
    ('P', 'tests/service/test_access.py::test_guard_cases[does-not-exist]', False),
    ('P', 'tests/service/test_access.py::test_local_origin_host_and_remote_address_are_all_checked[x]', False),
    ('P', 'tests/service/test_access.py::test_missing', False),
    ('P', 'tests/service/test_missing.py::test_x', False),
    ('P', 'tests/service/service_support.py::synthetic_root', False),
    ('P', 'tests/service/../service/test_access.py::test_local_origin_host_and_remote_address_are_all_checked', False),
    ('C', 'webapp/test_x.py::test_x', False),
])
def test_targets_are_tests_that_pytest_collects(disposition, target, accepted):
    assert (target_problem(disposition, target) is None) is accepted


def test_only_methods_of_test_classes_are_tests(tmp_path):
    module = tmp_path / 'test_classes.py'
    module.write_text('class Helper:\n    def test_a(self): pass\n\n\nclass TestThing:\n    def test_b(self): pass\n\n\n'
                      'def test_c(): pass\n', encoding='utf-8')
    assert _definitions(module) == {'TestThing::test_b', 'test_c'}


def test_mirrored_formats_exist_or_belong_to_an_open_slice():
    problems = []
    for key, entry in entries().items():
        if entry.get('disposition') != 'C':
            continue
        missing = [name for name in entry.get('formats', []) if not (FORMATS / f'{name}.mjs').is_file()]
        if missing and entry.get('slice', 0) <= SLICES_DONE:
            problems.append(f'{key}: {missing} have no Node generator, and slice {entry.get("slice")} is done')
        elif not missing and 'slice' in entry:
            problems.append(f'{key}: every format has its generator; drop slice')
    assert problems == [], '\n'.join(sorted(problems))


def test_pending_ports_belong_to_open_slices():
    overdue = sorted(f'{key}: {entry["disposition"]}, slice {entry["slice"]}' for key, entry in entries().items()
                     if entry.get('disposition') in ('pending', 'NA') and entry.get('slice', 11) <= SLICES_DONE
                     and key not in PENDING_ALLOWED)
    assert overdue == [], f'slices up to {SLICES_DONE} are done; port or map these sites:\n' + '\n'.join(overdue)
    linked = sorted(key for key in PENDING_ALLOWED if entries().get(key, {}).get('disposition') != 'pending')
    assert linked == [], 'these sites are not pending; remove them from PENDING_ALLOWED:\n' + '\n'.join(linked)


def test_scripts_lists_every_opt_in_script():
    scripts = node_map().get('scripts', {})
    expected = {path.name for path in SCRIPTS.glob('check-*.mjs')} - {path.name for path in unit_test_files()}
    missing, extra = sorted(expected - set(scripts)), sorted(set(scripts) - expected)
    assert missing == [], 'add these opt-in scripts to [scripts]:\n' + '\n'.join(missing)
    assert extra == [], 'these [scripts] entries are not opt-in check-*.mjs scripts:\n' + '\n'.join(extra)
    malformed = sorted(name for name, entry in scripts.items()
                       if not isinstance(entry, dict) or set(entry) - {'note'} != {'kind', 'slice'}
                       or entry['kind'] not in ('live', 'browser') or not isinstance(entry.get('note', ''), str)
                       or type(entry['slice']) is not int or not 2 <= entry['slice'] <= 10)
    assert malformed == [], 'each script takes kind ("live" or "browser"), slice (2-10) and an optional note:\n' + \
        '\n'.join(malformed)


# --- The parser --------------------------------------------------------------------------------------------------

def test_call_sites_are_read_as_javascript_reads_them():
    source = r'''import test from 'node:test';
import { dataTest } from './test-tiers.mjs';
// test('in a line comment', () => {});
/* test('in a block
comment', () => {}); */
const pattern = /test\('in a regex[/']/u; const text = "test('in a string')";
test.after(() => {});
assert.ok(pattern.test('x'));
void test('it\'s \u0041 "quoted" \x42\
 title', () => {});
await test("double \"quoted\" \u{1F600}\uD83D\uDE00", async t => {});
dataTest(`template ${`nested ${'}'}`} substitution`, () => {});
test(`plain
template`, () => {});
for (const x of [1, 2]) void test(
  'repeated', { skip: !x }, () => {},
);
test('joined ' + 'title', () => {});
test.skip('skipped', () => {});
test(name, () => {});
test('repeated', () => {});
const ratio = 1 / 2; test('after a division', () => {});
'''
    sites = call_sites('check-x.mjs', source)
    assert [(site.line, site.title) for site in sites] == [
        (9, 'it\'s A "quoted" B title'), (11, 'double "quoted" \U0001F600\U0001F600'), (12, None),
        (13, 'plain\ntemplate'), (15, 'repeated'), (18, None), (19, 'skipped'), (20, None), (21, 'repeated'),
        (22, 'after a division'),
    ]
    assert list(site_keys(sites)) == [
        'check-x.mjs::it\'s A "quoted" B title', 'check-x.mjs::double "quoted" \U0001F600\U0001F600', 'check-x.mjs:12',
        'check-x.mjs::plain\ntemplate', 'check-x.mjs::repeated', 'check-x.mjs:18', 'check-x.mjs::skipped',
        'check-x.mjs:20', 'check-x.mjs::repeated #2', 'check-x.mjs::after a division',
    ]


@pytest.mark.parametrize('source', ["test('unterminated", "test('line\nbreak')", 'test(/unterminated\n)',
                                    "test('\\101')", 'test(`open ${x'])
def test_malformed_modules_are_refused(source):
    with pytest.raises(ValueError):
        tokenize(source)


def test_every_unit_test_file_has_sites():
    files = {site.file for site in node_sites().values()}
    assert [path.name for path in unit_test_files() if path.name not in files] == []


if __name__ == '__main__':
    counts = Counter(entry['disposition'] for entry in entries().values())
    pending = Counter(entry['slice'] for entry in entries().values() if entry['disposition'] == 'pending')
    print(f'{len(node_sites())} sites in {len(unit_test_files())} files:',
          ', '.join(f'{name} {counts[name]}' for name in FIELDS))
    print('pending by slice:', ', '.join(f'{number}: {pending[number]}' for number in sorted(pending)))
