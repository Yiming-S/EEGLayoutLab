"""Research deliveries of workspace projects: Node's ``delivery/research-bundle.mjs`` (``buildResearchDelivery``,
``validateResearchDelivery``, ``deliveryReadme``, lines 4-183) and ``delivery/project-delivery.mjs``
(``runtimeLockPath``, ``deliveryVersions`` and ``ProjectDelivery``, lines 14-44), statement by statement (design 0001,
phase 2, slice 9).

A delivery (``eeg-research-delivery/1``) is one JSON object that hands a project's saved science to a reader::

    {schema, exported_at, project, host, records, files, scientific_results_recomputed: false, manifest_sha256}

- ``project`` is the project's public metadata (no credentials, no entries); ``records`` describe each entry
  (``path`` ``records/<entry id>.json`` and its ``snapshot_sha256``); ``files`` are ``README.md`` and one file per
  entry whose ``content`` is the exact text of the stored snapshot, with its ``size_bytes`` (UTF-8) and ``sha256``.
- ``host`` names the exporting host only through explicitly selected values (``delivery_versions``), never the
  environment. ``manifest_sha256`` is the SHA-256 of ``JSON.stringify`` of the delivery without that member and
  without the file contents, in the delivery's own key order.
- ``build_research_delivery`` refuses, with Node's statuses and messages, a project or entry list that does not
  match the saved snapshots byte for byte, and a delivery over ``max_bytes`` (32 MiB) as snapshots or as JSON text.
  ``validate_research_delivery`` is Node's verifier of a delivery read back.

The values follow JavaScript's: ``===`` and ``SameValueZero``, ``String(value)`` in ``RegExp.prototype.test`` and in
the README's template literals, property reads that throw ``TypeError`` (``jobs.identity.JSTypeError``) on ``null``
and ``undefined`` where V8 throws, UTF-16 string lengths, and UTF-8 bytes with a lone surrogate as U+FFFD. Refusals
are ``workspace_files.ProjectError`` (Node's ``projectSafe`` errors); a snapshot or file that ``JSON.parse`` refuses
in ``validate_research_delivery`` raises ``jsjson.JSONSyntaxError`` as V8 raises ``SyntaxError``.

Differences from Node, deliberate:

- ``delivery_versions`` describes the Python service: ``application_version`` is ``[project] version`` of
  ``pyproject.toml``, and ``source_files`` hash ``HOST_FILES`` (``pyproject.toml`` and the service's project and
  delivery modules) instead of ``webapp/package.json``, ``package-lock.json`` and Node's four modules. An installed
  package (design 0002) has no ``pyproject.toml``: its version is the distribution's (``compact-eeg``,
  ``data.store.DISTRIBUTION``), and ``source_files`` hash its four modules only. A delivery is no key input, so this
  changes no key, but a delivery's ``manifest_sha256`` differs from a Node-built delivery of the same project.
  ``data_manifest_sha256``, ``data_bundle_id`` and ``runtime_lock_sha256`` are Node's in a checkout.
- In the installed form (``jobs.runtime.installed_form``) without a managed runtime, the runtime lock is the Linux
  lock ``configs/runtime/manifest-linux-64.json``: the recipe pins its numerical versions on both platforms (0002,
  decision 2), and the macOS lock describes a SimNIBS runtime that the installed form does not have.
- ``ProjectDelivery.export(project_id)`` takes no credential (one local user); the build runs in a worker thread.
- Times are checked as ``Date.parse``'s ISO date-time format (``workspace_studies.iso_date_finite``); a time in one
  of V8's legacy formats is refused here, accepted by Node. Every time a host writes is ``toISOString()``.
- The README's comparison requirements read ``URLSearchParams`` of the saved comparison link as the WHATWG URL
  parser does for any link it parses (the query after the first ``?``, before ``#``); a link that ``new URL``
  refuses (a malformed host or port), which the project store never saves, raises nothing here.
- A layout snapshot's electrode names are checked by ``jobs.annotations.validate_electrode_annotation``, which
  requires a string record identifier; Node compares it with ``===`` (only a builder input whose ``record_id`` is not
  a string, which the store never saves, can tell them apart).
"""
from __future__ import annotations

import asyncio
import datetime
import hashlib
import inspect
import re
import time
from typing import Any, Callable, Iterable, Optional

from ..jobs import nodefs, nodepath
from ..jobs.identity import UNDEFINED, JSTypeError, _js_string, _member, _same, js_truthy
from ..jobs.runtime import installed_form, managed_python, table_python_path
from ..schemas import jsjson
from .workspace_files import UUID, SHA, ProjectError

__all__ = [
    'DELIVERY_SCHEMA', 'MAX_DELIVERY_BYTES', 'HOST_FILES', 'build_research_delivery', 'validate_research_delivery',
    'delivery_readme', 'delivery_json', 'search_params', 'runtime_lock_path', 'delivery_versions', 'ProjectDelivery',
]

DELIVERY_SCHEMA = 'eeg-research-delivery/1'
MAX_DELIVERY_BYTES = 32 * 1024 * 1024
PROJECT_SCHEMA = 'research-project/1'
SNAPSHOT_SCHEMA = 'research-project-snapshot/1'
KINDS = ('layout', 'editor', 'source')
# The files whose bytes identify the exporting host (Node's hostFiles); the first one holds the application version.
HOST_FILES = ('pyproject.toml', 'src/eeglayoutlab/schemas/projects.py', 'src/eeglayoutlab/server/workspace_files.py',
              'src/eeglayoutlab/server/workspace_projects.py', 'src/eeglayoutlab/server/delivery.py')
PACKAGE_SOURCE = 'src/eeglayoutlab'  # this package's directory in a checkout

PROJECT_FIELDS = ('id', 'title', 'owner_name', 'notes', 'revision', 'created_at', 'updated_at', 'workflow')
HOST_FIELDS = ('application_version', 'data_manifest_sha256', 'data_bundle_id', 'runtime_lock_sha256', 'source_files')
BUNDLE_FIELDS = ('schema', 'exported_at', 'project', 'host', 'records', 'files', 'manifest_sha256',
                 'scientific_results_recomputed')
FILE_FIELDS = ('path', 'media_type', 'encoding', 'size_bytes', 'sha256', 'content')
RECORD_FIELDS = ('id', 'kind', 'record_id', 'annotation_id', 'title', 'notes', 'created_at', 'summary', 'path',
                 'snapshot_sha256')

# Node's messages (delivery/research-bundle.mjs, delivery/project-delivery.mjs), verbatim.
INVALID_PROJECT = 'Invalid project for research delivery.'
METADATA_INVALID = 'Project delivery metadata is invalid.'
ENTRIES_INCOMPLETE = 'Project delivery entries are incomplete.'
ENTRY_MISMATCH = 'Project delivery entry identity mismatch.'
CHECKSUM_MISMATCH = 'Project snapshot checksum mismatch.'
SNAPSHOT_NOT_JSON = 'Project snapshot is not valid JSON.'
SNAPSHOT_MISMATCH = 'Project snapshot scientific identity mismatch.'
TOO_LARGE = 'Project delivery exceeds the export size limit.'
HOST_INVALID = 'Research delivery host metadata is invalid.'
UNSUPPORTED = 'Unsupported research delivery.'
FILE_INTEGRITY = 'Research delivery file failed integrity checks.'
MANIFEST_INTEGRITY = 'Research delivery manifest failed integrity checks.'
RECORD_MISMATCH = 'Research delivery record identity mismatch.'
RECORD_MISSING = 'Research delivery record is missing.'
VERSIONS_UNAVAILABLE = ('Delivery version information is unavailable. Verify the application, model manifest and '
                        'runtime lock.')
BUSY = 'Another research delivery is being prepared. Try again shortly.'

_MAX_SAFE_INTEGER = 2**53 - 1
_SURROGATE = re.compile('[\ud800-\udfff]')
# JSON.stringify's escapes of the characters it escapes in a well-formed string (QuoteJSONString).
_ESCAPES = {code: f'\\u{code:04x}' for code in range(0x20)}
_ESCAPES.update({0x08: '\\b', 0x09: '\\t', 0x0A: '\\n', 0x0C: '\\f', 0x0D: '\\r', 0x22: '\\"', 0x5C: '\\\\'})
_PERCENT = re.compile(rb'%([0-9A-Fa-f]{2})')
_C0_OR_SPACE = ''.join(chr(code) for code in range(0x21))


def _fail(message: str, status: int = 409) -> ProjectError:
    return ProjectError(message, status)


# --- JavaScript values -----------------------------------------------------------------------------------------------

def _utf8(text: str) -> bytes:
    """``Buffer.from(text)``: UTF-8 with a lone surrogate as U+FFFD (two surrogate code points that pair are one
    character, as in a JavaScript string)."""
    try:
        return text.encode('utf-8')
    except UnicodeEncodeError:
        return text.encode('utf-16-le', 'surrogatepass').decode('utf-16-le', 'replace').encode('utf-8')


def _hash(text: str) -> str:
    """``createHash('sha256').update(text).digest('hex')``."""
    return hashlib.sha256(_utf8(text)).hexdigest()


def _length(text: str) -> int:
    """``text.length``: UTF-16 code units."""
    return len(text) + sum(1 for char in text if ord(char) > 0xFFFF) if not text.isascii() else len(text)


def _test(pattern: re.Pattern, value: Any) -> bool:
    """``/^...$/.test(value)``: the argument converted with ``String``, which can throw ``TypeError``."""
    return pattern.fullmatch(_js_string(value)) is not None


def _object(value: Any) -> bool:
    """``value && typeof value === 'object' && !Array.isArray(value)``."""
    return isinstance(value, dict)


def _fields(value: Any, allowed: tuple) -> bool:
    return isinstance(value, dict) and all(key in allowed for key in value)


def _optional(value: Any, key: str) -> Any:
    """``value?.key``."""
    return UNDEFINED if value is None or value is UNDEFINED else _member(value, key)


def _same_value_zero(a: Any, b: Any) -> bool:
    """``Set.prototype.has``'s comparison: ``===``, except that ``NaN`` equals ``NaN``."""
    if jsjson.is_number(a) and jsjson.is_number(b) and a != a and b != b:
        return True
    return _same(a, b)


def _has(values: list, value: Any) -> bool:
    return any(_same_value_zero(item, value) for item in values)


def _safe_integer(value: Any) -> bool:
    """``Number.isSafeInteger(value)``."""
    return jsjson.is_integer(value) and abs(jsjson.to_number(value)) <= _MAX_SAFE_INTEGER


def _timestamp(value: Any) -> bool:
    """``typeof value === 'string' && Number.isFinite(Date.parse(value))``, for the ISO date-time format."""
    from .workspace_studies import iso_date_finite  # the studies' Date.parse port; loads job modules
    return isinstance(value, str) and iso_date_finite(value)


def _defined(members: Iterable[tuple[str, Any]]) -> dict:
    """An object literal whose ``undefined`` members ``JSON.stringify`` leaves out."""
    return {key: value for key, value in members if value is not UNDEFINED}


def _clone(value: Any) -> Any:
    """``JSON.parse(JSON.stringify(value))``."""
    return jsjson.parse(jsjson.stringify(value))


def _clean(value: Any) -> str:
    """``cleanText(value)``: ``String(value ?? '')`` with line breaks and table bars as spaces, backticks as ``'``."""
    text = '' if value is None or value is UNDEFINED else _js_string(value)
    return text.replace('\r', ' ').replace('\n', ' ').replace('|', ' ').replace('`', "'")


def _reading(value: Any) -> str:
    if value is UNDEFINED:
        return 'unrecorded / 未记录'
    if value is None:
        return 'null / 原记录不可计算'
    return _clean(value)


def _quote(text: str) -> str:
    """``jsjson.quote(text)``, translated at C speed unless a surrogate needs its code-unit rules."""
    if _SURROGATE.search(text):
        return jsjson.quote(text)
    return '"' + text.translate(_ESCAPES) + '"'


def _keys(value: dict) -> list:
    """``Object.keys`` order of an object: array indices ascending, then the other keys in insertion order."""
    indices = sorted((key for key in value if jsjson.is_array_index(key)), key=int)
    return indices + [key for key in value if not jsjson.is_array_index(key)] if indices else list(value)


def delivery_json(bundle: dict) -> str:
    """``JSON.stringify(bundle)`` of a delivery: ``jsjson.stringify``'s text, with each file's ``content`` quoted at
    C speed (a delivery holds up to 32 MiB of snapshot text)."""
    members = []
    for key in _keys(bundle):
        value = bundle[key]
        if key == 'files' and isinstance(value, list) and all(isinstance(file, dict) for file in value):
            text = '[' + ','.join(
                '{' + ','.join(jsjson.quote(name) + ':' + (_quote(file[name]) if name == 'content' and isinstance(
                    file[name], str) else jsjson.stringify(file[name])) for name in _keys(file)) + '}'
                for file in value) + ']'
        else:
            text = jsjson.stringify(value)
        members.append(jsjson.quote(key) + ':' + text)
    return '{' + ','.join(members) + '}'


# --- Comparison links ------------------------------------------------------------------------------------------------

def _usv(text: str) -> str:
    """WebIDL's ``USVString``: a lone surrogate becomes U+FFFD."""
    if not _SURROGATE.search(text):
        return text
    return text.encode('utf-16-le', 'surrogatepass').decode('utf-16-le', 'replace')


def _form_decode(raw: bytes) -> str:
    """One name or value of ``application/x-www-form-urlencoded``: ``+`` as a space, ``%XX`` as its byte, then UTF-8
    without BOM handling, an invalid sequence as U+FFFD."""
    return _PERCENT.sub(lambda match: bytes([int(match[1], 16)]), raw.replace(b'+', b' ')).decode('utf-8', 'replace')


def search_params(href: Any) -> list[tuple[str, str]]:
    """``[...new URL(href, 'http://localhost').searchParams]``: ``href`` converted with ``String``; leading and
    trailing C0 controls and spaces and every tab and line break removed, as the URL parser does; the query is the
    text after the first ``?`` that comes before any ``#`` (the parser percent-encodes it, which the form decoding
    undoes); its ``&``-separated non-empty parts split at their first ``=``. A link the URL parser refuses (a
    malformed host or port, never one the project store saves) is read the same way instead of failing."""
    text = _usv(_js_string(href)).strip(_C0_OR_SPACE).replace('\t', '').replace('\n', '').replace('\r', '')
    fragment = text.find('#')
    if fragment >= 0:
        text = text[:fragment]
    start = text.find('?')
    if start < 0:
        return []
    pairs = []
    for part in text[start + 1:].encode('utf-8').split(b'&'):
        if part:
            name, _, value = part.partition(b'=')
            pairs.append((_form_decode(name), _form_decode(value)))
    return pairs


# --- Validation -------------------------------------------------------------------------------------------------------

def _valid_project(project: Any) -> bool:
    """``validateProject(project)``."""
    if not _fields(project, PROJECT_FIELDS) or not _test(UUID, project.get('id', UNDEFINED)):
        return False
    title, owner, notes = (project.get(name, UNDEFINED) for name in ('title', 'owner_name', 'notes'))
    revision, workflow = project.get('revision', UNDEFINED), project.get('workflow', UNDEFINED)
    return (isinstance(title, str) and 0 < _length(title) <= 200 and isinstance(owner, str)
            and 0 < _length(owner) <= 120 and isinstance(notes, str) and _length(notes) <= 8000
            and _safe_integer(revision) and revision > 0 and _timestamp(project.get('created_at', UNDEFINED))
            and _timestamp(project.get('updated_at', UNDEFINED)) and (workflow is UNDEFINED or _object(workflow)))


def _invalid_source_file(row: Any) -> bool:
    if not _fields(row, ('path', 'sha256')):
        return True
    path = row.get('path', UNDEFINED)
    return (not isinstance(path, str) or path.startswith('/')
            or any(not part or part in ('.', '..') for part in path.split('/'))
            or not _test(SHA, row.get('sha256', UNDEFINED)))


def _valid_host(host: Any) -> bool:
    """``validateHost(host)``."""
    if not _fields(host, HOST_FIELDS):
        return False
    for name in ('data_manifest_sha256', 'runtime_lock_sha256'):
        value = host.get(name, UNDEFINED)
        if value is not UNDEFINED and not _test(SHA, value):
            return False
    for name in ('application_version', 'data_bundle_id'):
        value = host.get(name, UNDEFINED)
        if value is not UNDEFINED and (not isinstance(value, str) or not value or _length(value) > 200):
            return False
    files = host.get('source_files', UNDEFINED)
    return files is UNDEFINED or (isinstance(files, list) and not any(_invalid_source_file(row) for row in files))


def _annotation_matches(snapshot: Any, annotation_id: Any) -> bool:
    """``annotationMatches(snapshot, id)``: no names on either side, or a layout's names bound to its record."""
    from ..jobs.annotations import validate_electrode_annotation

    annotation = _member(snapshot, 'electrode_annotation')
    if annotation_id is UNDEFINED and annotation is UNDEFINED:
        return True
    try:
        return (_same(_member(snapshot, 'kind'), 'layout') and _test(SHA, annotation_id)
                and _same(_optional(annotation, 'id'), annotation_id)
                and js_truthy(validate_electrode_annotation(annotation, _member(snapshot, 'record_id'))))
    except Exception:
        return False


def _snapshot_matches(snapshot: Any, kind: Any, record_id: Any, annotation_id: Any) -> bool:
    return (_same(_member(snapshot, 'schema'), SNAPSHOT_SCHEMA) and _same(_member(snapshot, 'kind'), kind)
            and _same(_member(snapshot, 'record_id'), record_id) and _object(_member(snapshot, 'payload'))
            and _annotation_matches(snapshot, annotation_id))


def _manifest(bundle: dict) -> dict:
    """``manifest(bundle)``: the delivery without ``manifest_sha256`` and with the files without ``content``."""
    metadata = {key: value for key, value in bundle.items() if key not in ('manifest_sha256', 'files')}
    return {**metadata, 'files': [{key: value for key, value in file.items() if key != 'content'}
                                  for file in bundle['files']]}


def validate_research_delivery(bundle: Any) -> bool:
    """``validateResearchDelivery(bundle)``: ``True``, or a ``ProjectError`` (409) with Node's message."""
    if (not _fields(bundle, BUNDLE_FIELDS) or not _same(bundle.get('schema', UNDEFINED), DELIVERY_SCHEMA)
            or not _timestamp(bundle.get('exported_at', UNDEFINED))
            or not _valid_project(bundle.get('project', UNDEFINED))
            or not _valid_host(bundle.get('host', UNDEFINED)) or not isinstance(bundle.get('files'), list)
            or not isinstance(bundle.get('records'), list) or bundle.get('scientific_results_recomputed') is not False):
        raise _fail(UNSUPPORTED)
    files, records = bundle['files'], bundle['records']
    names: set[str] = set()
    for file in files:
        path = file.get('path', UNDEFINED) if isinstance(file, dict) else UNDEFINED
        if not (_fields(file, FILE_FIELDS) and isinstance(path, str)
                and (path == 'README.md' or (path.startswith('records/') and path.endswith('.json')
                                             and _test(UUID, path[8:-5])))
                and path not in names and _same(file.get('encoding', UNDEFINED), 'utf-8')
                and _same(file.get('media_type', UNDEFINED),
                          'text/markdown' if path == 'README.md' else 'application/json')
                and isinstance(file.get('content'), str)
                and _same(file.get('size_bytes', UNDEFINED), len(_utf8(file['content'])))
                and _same(file.get('sha256', UNDEFINED), _hash(file['content']))):
            raise _fail(FILE_INTEGRITY)
        names.add(path)
    if ('README.md' not in names or len(files) != len(records) + 1
            or not _same(bundle.get('manifest_sha256', UNDEFINED), _hash(jsjson.stringify(_manifest(bundle))))):
        raise _fail(MANIFEST_INTEGRITY)
    record_ids: list = []
    record_paths: set[str] = set()
    for record in records:
        if not (_fields(record, RECORD_FIELDS) and _test(UUID, record.get('id', UNDEFINED))
                and isinstance(record.get('kind'), str) and record['kind'] in KINDS
                and _test(SHA, record.get('record_id', UNDEFINED))
                and _same(record.get('path', UNDEFINED), f'records/{_js_string(record.get("id", UNDEFINED))}.json')
                and _object(record.get('summary')) and isinstance(record.get('title'), str)
                and isinstance(record.get('notes'), str) and _timestamp(record.get('created_at', UNDEFINED))
                and not _has(record_ids, record['id']) and record['path'] not in record_paths):
            raise _fail(RECORD_MISMATCH)
        record_ids.append(record['id'])
        record_paths.add(record['path'])
        file = next((value for value in files if _same(value.get('path', UNDEFINED), record['path'])), UNDEFINED)
        if not js_truthy(file) or not _same(file.get('sha256', UNDEFINED), record.get('snapshot_sha256', UNDEFINED)):
            raise _fail(RECORD_MISSING)
        snapshot = jsjson.parse(file['content'])  # V8's SyntaxError propagates
        if not _snapshot_matches(snapshot, record['kind'], record['record_id'], record.get('annotation_id', UNDEFINED)):
            raise _fail(RECORD_MISMATCH)
    return True


# --- Building ---------------------------------------------------------------------------------------------------------

def _public_project(project: Any) -> dict:
    """``publicProject(project)``: the project's metadata without credentials, operational fields or entries."""
    if (not _object(project) or not _same(project.get('schema', UNDEFINED), PROJECT_SCHEMA)
            or not isinstance(project.get('entries'), list)):
        raise _fail(INVALID_PROJECT)
    members = [(name, project.get(name, UNDEFINED)) for name in PROJECT_FIELDS[:-1]]
    workflow = project.get('workflow', UNDEFINED)
    if js_truthy(workflow):
        members.append(('workflow', workflow))
    return _clone(_defined(members))


def _saved_readings(rows: list) -> list[str]:
    """``savedReadings(rows)``: the saved metrics of layouts and edited layouts, copied as they are."""
    lines = []
    for row in rows:
        record, payload = _member(row, 'record'), _member(row, 'payload')
        kind = _member(record, 'kind')
        if _same(kind, 'layout'):
            metrics = _optional(_member(payload, 'record'), 'metrics')
        elif _same(kind, 'editor'):
            metrics = _optional(_optional(_member(payload, 'cache'), 'result'), 'edited_metrics')
        else:
            metrics = None
        if js_truthy(metrics):
            cells = [_clean(_member(record, 'title')), _clean(_member(_member(record, 'summary'), 'protocol')),
                     *(_reading(_member(metrics, name))
                       for name in ('field_relative', 'sensitivity_tail', 'localization_relative', 'p90_mm'))]
            lines.append('| ' + ' | '.join(cells) + ' |')
    if not lines:
        return []
    return ['', '## Saved layout readings / 保存的布局读数', '',
            '| Record / 记录 | Protocol / 协议 | Field ratio / 场保留比值 | Amplitude ratio / 幅度保留比值 | '
            'Localization ratio / 定位效用比值 | P90 (mm) |',
            '| --- | --- | --- | --- | --- | --- |', *lines, '',
            'Values are copied from the saved metrics without rounding or recomputation. Interpret each protocol '
            'separately.',
            '读数直接取自保存指标，没有重新计算或舍入；各评价协议分别解释。']


def _source_sections(rows: list) -> list[str]:
    lines = []
    for row in [row for row in rows if _same(_member(_member(row, 'record'), 'kind'), 'source')]:
        record, payload = _member(row, 'record'), _member(row, 'payload')
        lines += ['', f"## {_clean(_member(record, 'title'))}", '',
                  '| Signal condition / 信号条件 | Saved field retention / 保存的场保留比值 |', '| --- | --- |']
        conditions = _member(payload, 'conditions')
        if isinstance(conditions, list):
            lines += [f"| {_clean(_member(condition, 'condition'))} "
                      f"| {_reading(_member(condition, 'field_retention'))} |" for condition in conditions]
    return lines


def delivery_readme(project: Any, records: list, versions: Any, rows: list = ()) -> str:
    """``deliveryReadme(project, records, versions, rows)``: the delivery's bilingual ``README.md``."""
    workflow = _member(project, 'workflow')

    def selected(name: str) -> Any:
        wanted = _optional(workflow, name)
        return next((record for record in records if _same(_member(record, 'id'), wanted)), UNDEFINED)

    reference, candidate = selected('reference_entry_id'), selected('candidate_entry_id')
    href = _optional(workflow, 'comparison_href')
    pairs = search_params(href) if js_truthy(href) else []
    requirements = [f'- {name}: {value}' for name, value in pairs if name not in ('a', 'b')]

    def chosen(record: Any) -> str:
        if not js_truthy(record):
            return 'unselected / 未选择'
        return _clean(_member(record, 'title')) + ' · ' + _js_string(_member(record, 'record_id'))

    notes = _member(project, 'notes')
    lines = [
        f"# {_clean(_member(project, 'title'))}",
        '',
        'EEG Layout Lab research delivery / 科研交付包',
        '',
        f"Project / 项目: {_js_string(_member(project, 'id'))}",
        f"Researcher / 负责人: {_clean(_member(project, 'owner_name'))}",
        f"Project revision / 项目版本: {_js_string(_member(project, 'revision'))}",
        '',
        _js_string(notes) if js_truthy(notes) else '',
        '',
        '| Record / 记录 | Kind / 类型 | Protocol / 协议 | Scientific identity / 科学身份 |',
        '| --- | --- | --- | --- |',
        *[f"| {_clean(_member(record, 'title'))} | {_js_string(_member(record, 'kind'))} "
          f"| {_clean(_member(_member(record, 'summary'), 'protocol'))} | {_js_string(_member(record, 'record_id'))} |"
          for record in records],
        '',
        '## Study comparison / 研究比较',
        '',
        f'Reference / 参考布局: {chosen(reference)}',
        f'Candidate / 候选布局: {chosen(candidate)}',
        *requirements,
        *(['', 'ar, sensitivity and localization use percent; p90 uses millimetres. thresholdMode records joint or '
               'independent requirements.',
           'ar、sensitivity、localization 使用百分数，p90 使用毫米；thresholdMode 记录共同要求或独立要求。']
          if requirements else []),
        *_saved_readings(rows),
        *_source_sections(rows),
        '',
        '## Read the saved results / 读取保存结果',
        '',
        'Each file.content is the exact UTF-8 JSON text of a verified project snapshot. Parse that text as JSON to '
        'read snapshot.payload. file.sha256 checks the original text bytes.',
        '每个 file.content 是已验证项目快照的原始 UTF-8 JSON 文本。将该文本解析为 JSON 后读取 snapshot.payload；file.sha256 用于核对原始文本字节。',
        '',
        'Layout payloads include the existing reproducibility bundle; edited-layout payloads include the saved record '
        'and evaluation cache; signal payloads contain the complete scientific result, including requests, conditions '
        'and waveforms.',
        '布局快照包含原有复现包；编辑快照包含记录与评价缓存；信号快照包含完整科学结果，包括请求、条件与波形。',
        '',
        'Use each record under its saved model, coordinate system, units, source/noise conditions, protocol and '
        'runtime identity. Different evaluation protocols retain their own metric definitions.',
        '按各记录保存的头模、坐标系、单位、源与噪声条件、评价协议及运行环境身份解释结果；不同协议保留各自的指标定义。',
        '',
        '## Reproduce / 复现',
        '',
        'Install the matching scientific source, frozen model bundle and qualified runtime listed in the saved '
        'identities. Layout payload.reproduction specifies its request and entry point. Signal payload.request and '
        'payload.provenance retain the corresponding inputs and scientific identity.',
        '安装保存身份所对应的科学源码、冻结模型包和已验证运行环境。布局 payload.reproduction 记录请求与入口；'
        '信号 payload.request 和 payload.provenance 记录其输入及科学身份。',
        '',
        f"Export host version / 导出宿主版本: {_clean(_or_default(_member(versions, 'application_version'), 'unrecorded'))}",
        f"Frozen data manifest SHA-256 / 冻结数据清单: "
        f"{_js_string(_or_default(_member(versions, 'data_manifest_sha256'), 'unrecorded'))}",
        '',
        'The host version describes this export. The identities inside saved snapshots describe the original '
        'calculation. Model files are referenced by the data manifest and scientific identities, rather than '
        'duplicated in each delivery.',
        '宿主版本说明本次导出；快照内部身份说明原始计算。模型文件通过数据清单与科学身份引用，不在每份交付包中重复保存。',
        '',
    ]
    return '\n'.join(lines)


def _or_default(value: Any, default: str) -> Any:
    """``value ?? default``."""
    return default if value is None or value is UNDEFINED else value


def _now_iso() -> str:
    """``new Date().toISOString()``."""
    milliseconds = int(time.time() * 1000)
    moment = datetime.datetime.fromtimestamp(milliseconds // 1000, datetime.timezone.utc)
    return f'{moment:%Y-%m-%dT%H:%M:%S}.{milliseconds % 1000:03d}Z'


def build_research_delivery(saved: Any, versions: Any = UNDEFINED, *, now: Optional[Callable[[], Any]] = None,
                            max_bytes: Any = MAX_DELIVERY_BYTES) -> dict:
    """``buildResearchDelivery({project, entries}, versions = {}, {now, maxBytes})``.

    ``saved`` is ``ProjectStore.readSnapshots``'s value: ``project``, a ``research-project/1`` record whose
    ``entries`` list each saved entry, and ``entries``, one ``{entry, snapshot_json}`` per listed entry with the exact
    snapshot text. ``versions`` is ``delivery_versions``'s value (only its five members are read). Returns the
    delivery (serialize it with ``delivery_json``); the inputs are not changed. Raises ``ProjectError`` with Node's
    status (409, or 413 over ``max_bytes``), or ``JSTypeError`` where V8 throws ``TypeError``.
    """
    source_project, entries = _member(saved, 'project'), _member(saved, 'entries')
    if versions is UNDEFINED:
        versions = {}
    project = _public_project(source_project)
    if not _valid_project(project):
        raise _fail(METADATA_INVALID)
    listed_entries = source_project['entries']
    if (not isinstance(entries, list) or len(entries) != len(listed_entries) or not _safe_integer(max_bytes)
            or max_bytes < 1):
        raise _fail(ENTRIES_INCOMPLETE)
    seen: list = []
    records: list = []
    files: list = []
    readings: list = []
    total = 0
    for item in entries:
        entry, snapshot_json = _member(item, 'entry'), _member(item, 'snapshot_json')
        wanted = _optional(entry, 'id')
        listed = next((value for value in listed_entries if _same(_member(value, 'id'), wanted)), UNDEFINED)
        if not js_truthy(listed) or _has(seen, _member(entry, 'id')) or not _test(UUID, _member(entry, 'id')):
            raise _fail(ENTRY_MISMATCH)
        entry_id, kind = _member(entry, 'id'), _member(entry, 'kind')
        if not isinstance(kind, str) or kind not in KINDS or not isinstance(snapshot_json, str):
            raise _fail(ENTRY_MISMATCH)
        seen.append(entry_id)
        data = _utf8(snapshot_json)
        size, sha256 = len(data), hashlib.sha256(data).hexdigest()
        if (not _same(sha256, _member(entry, 'snapshot_sha256'))
                or not _same(sha256, _member(listed, 'snapshot_sha256'))
                or not _same(size, _member(entry, 'snapshot_bytes'))
                or not _same(size, _member(listed, 'snapshot_bytes'))):
            raise _fail(CHECKSUM_MISMATCH)
        try:
            snapshot = jsjson.parse(snapshot_json)
        except Exception:
            raise _fail(SNAPSHOT_NOT_JSON) from None
        annotation_id = _member(entry, 'annotation_id')
        if not _snapshot_matches(snapshot, kind, _member(entry, 'record_id'), annotation_id):
            raise _fail(SNAPSHOT_MISMATCH)
        total += size
        if total > max_bytes:
            raise _fail(TOO_LARGE, 413)
        path = f'records/{_js_string(entry_id)}.json'
        records.append(_clone(_defined([
            ('id', entry_id), ('kind', kind), ('record_id', _member(entry, 'record_id')),
            *([('annotation_id', annotation_id)] if js_truthy(annotation_id) else []),
            ('title', _member(entry, 'title')), ('notes', _member(entry, 'notes')),
            ('created_at', _member(entry, 'created_at')), ('summary', _member(entry, 'summary')), ('path', path),
            ('snapshot_sha256', sha256)])))
        readings.append({'record': records[-1], 'payload': snapshot['payload']})
        files.append({'path': path, 'media_type': 'application/json', 'encoding': 'utf-8', 'size_bytes': size,
                      'sha256': sha256, 'content': snapshot_json})
    # Only explicitly selected host metadata is exported, never environment values.
    host = _clone(_defined([(name, _member(versions, name)) for name in HOST_FIELDS]))
    if not _valid_host(host):
        raise _fail(HOST_INVALID)
    readme = delivery_readme(project, records, host, readings)
    files.insert(0, {'path': 'README.md', 'media_type': 'text/markdown', 'encoding': 'utf-8',
                     'size_bytes': len(_utf8(readme)), 'sha256': _hash(readme), 'content': readme})
    exported_at = now() if now is not None else _now_iso()
    bundle = _defined([('schema', DELIVERY_SCHEMA), ('exported_at', exported_at), ('project', project),
                       ('host', host), ('records', records), ('files', files),
                       ('scientific_results_recomputed', False)])
    bundle['manifest_sha256'] = _hash(jsjson.stringify(_manifest(bundle)))
    # Escaped embedded JSON can exceed its original byte count; bound the wire object too.
    if len(_utf8(delivery_json(bundle))) > max_bytes:
        raise _fail(TOO_LARGE, 413)
    return bundle


# --- Host versions and exports ----------------------------------------------------------------------------------------

def _package_directory() -> str:
    """This package's directory, ``eeglayoutlab``, links resolved."""
    return nodepath.resolve(nodefs.realpath_sync(nodepath.resolve(__file__)), '../..')


def _source_root() -> Optional[str]:
    """The checkout that holds this package (Node's ``resolve(import.meta.dirname, '../../..')``), or ``None`` when
    the package is installed (design 0002: ``site-packages/eeglayoutlab``, with no checkout around it)."""
    package = _package_directory()
    checkout = nodepath.resolve(package, '../..')
    try:
        return checkout if nodefs.realpath_sync(nodepath.join(checkout, PACKAGE_SOURCE)) == package else None
    except OSError:
        return None


LINUX_LOCK = 'configs/runtime/manifest-linux-64.json'
MACOS_LOCK = 'configs/runtime/manifest.json'


def runtime_lock_path(scientific_root: str, prefix: Optional[str] = None, package_file: Optional[str] = None) -> str:
    """``runtimeLockPath(root)``: the lock of the managed runtime in use, the Linux table runtime's own when that
    runtime is the managed one, else the macOS lock. The installed form without a managed runtime names the Linux
    lock, whose versions its environment pins."""
    root = nodepath.resolve(scientific_root)
    managed = managed_python(root)
    if managed == table_python_path(root) or (managed is None and installed_form(root, prefix, package_file)):
        return LINUX_LOCK
    return MACOS_LOCK


def delivery_versions(scientific_root: str, source_root: Optional[str] = None) -> dict:
    """``deliveryVersions(root, sourceRoot)`` for the Python service: the application version of ``pyproject.toml``,
    the SHA-256 of ``R/data/manifest.json`` (``eeglayoutlab-data-bundle/1``) and its ``bundle_id``, the SHA-256 of the
    runtime lock (``eeglayoutlab-runtime-lock/1``), and the SHA-256 of each of ``HOST_FILES``. An installed package
    has no ``pyproject.toml``: the version is its distribution's, and the files are its own modules of ``HOST_FILES``
    (the same bytes, named by their path in the source). Any failure is a ``ProjectError`` 503 that names no path."""
    try:
        import importlib.metadata
        import tomllib

        from ..data.store import DISTRIBUTION

        source = _source_root() if source_root is None else source_root
        data_bytes = nodefs.read_file(nodepath.resolve(scientific_root, 'data/manifest.json'))
        runtime_bytes = nodefs.read_file(nodepath.resolve(scientific_root, runtime_lock_path(scientific_root)))
        if source is None:
            package = _package_directory()
            files = [path for path in HOST_FILES if path.startswith(PACKAGE_SOURCE + '/')]
            source_bytes = [nodefs.read_file(nodepath.join(package, path[len(PACKAGE_SOURCE) + 1:])) for path in files]
            version = importlib.metadata.version(DISTRIBUTION)
        else:
            files = list(HOST_FILES)
            source_bytes = [nodefs.read_file(nodepath.resolve(source, path)) for path in files]
            version = tomllib.loads(source_bytes[0].decode('utf-8')).get('project', {}).get('version')
        data, runtime = jsjson.parse(jsjson.decode_body(data_bytes)), jsjson.parse(jsjson.decode_body(runtime_bytes))
        bundle_id = _member(data, 'bundle_id')
        if (not _same(_member(data, 'schema_version'), 'eeglayoutlab-data-bundle/1') or not isinstance(bundle_id, str)
                or not bundle_id or not _same(_member(runtime, 'schema'), 'eeglayoutlab-runtime-lock/1')
                or not isinstance(version, str) or not version):
            raise ValueError('Missing version identity')
        return {'application_version': version, 'data_manifest_sha256': hashlib.sha256(data_bytes).hexdigest(),
                'data_bundle_id': bundle_id, 'runtime_lock_sha256': hashlib.sha256(runtime_bytes).hexdigest(),
                'source_files': [{'path': path, 'sha256': hashlib.sha256(raw).hexdigest()}
                                 for path, raw in zip(files, source_bytes)]}
    except Exception:
        raise ProjectError(VERSIONS_UNAVAILABLE, 503) from None


class ProjectDelivery:
    """``ProjectDelivery``: one delivery at a time (another is 429), read from the store within ``maximum_bytes``.

    ``store.read_snapshots(project_id, max_bytes=...)`` is awaited for ``{project, entries}`` (Node's
    ``readSnapshots``; the store refuses a project over the bound before it reads a payload), and ``versions()``
    (sync or async; by default ``delivery_versions(scientific_root)`` in a worker thread) for the host's versions.
    """

    def __init__(self, store: Any, scientific_root: Optional[str] = None, versions: Optional[Callable[[], Any]] = None,
                 maximum_bytes: int = MAX_DELIVERY_BYTES):
        self.store = store
        self.versions = versions if versions is not None else (
            lambda: asyncio.to_thread(delivery_versions, scientific_root))
        self.maximum_bytes = maximum_bytes
        self.active = False

    async def export(self, project_id: str) -> dict:
        if self.active:
            raise ProjectError(BUSY, 429)
        self.active = True
        try:
            saved = await self.store.read_snapshots(project_id, max_bytes=self.maximum_bytes)
            versions = self.versions()
            if inspect.isawaitable(versions):
                versions = await versions
            return await asyncio.to_thread(build_research_delivery, saved, versions, max_bytes=self.maximum_bytes)
        finally:
            self.active = False
