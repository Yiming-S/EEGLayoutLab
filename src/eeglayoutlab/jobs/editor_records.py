"""Saved electrode-editor evaluations and the layouts the editor can start from: ``ElectrodeEditorService.records``
and ``parents`` of Node's ``webapp/server/electrode-editor-server.mjs`` (lines 64-87) with ``validateEditorResult``
(line 22), statement by statement.

- ``records(store)`` lists every ``results/v2/electrode_editor_jobs/<key>/cache.json`` that holds an ``evaluate``
  result whose checksum, stored key and request key (``sha256(JSON.stringify({request, identity}))``) agree and
  that ``validate_editor_result`` accepts; anything else is skipped silently, as Node never exposes incomplete
  evaluations as scores. The rows are sorted newest first by ``finished_at``.
- ``parents(library)`` lists the library summaries of completed strict-area and radius layouts searched under
  independent noise whose full record has saved region patches. Node first narrows the rows to one browser's
  view (``visible``); locally every row is visible, so there is no such filter.

Known differences from Node, none of which reaches a key: ``records`` sorts with V8's algorithm as Node 26 runs it
(``jssort``), so with a row whose ``finished_at`` is not a string the sort fails (Node's ``TypeError``) exactly when
Node 26's does, but 3 to 7 rows can fail on one side only under Node 22 or 24; and it compares ``finished_at``
texts by UTF-16 code units where Node uses ``localeCompare`` (ICU), which orders Node's own ``toISOString`` stamps
the same way (stamps that ICU orders otherwise can change which rows are compared, and so whether the sort fails).
"""
from __future__ import annotations

import math
import re
from typing import Any

from ..schemas import jsjson
from . import jssort
from .design_result import same
from .identity import UNDEFINED, JSTypeError, _js_string, _member, _same, js_truthy, request_key
from .records import RecordStore

__all__ = ['EDITOR_RESULT_SCHEMA', 'RESTORED_AS', 'EditorResultError', 'validate_editor_result', 'records',
           'parents']

EDITOR_RESULT_SCHEMA = 'electrode-editor/1'
RESTORED_AS = 'draft_requires_current_evaluation'
_KEY = re.compile('[a-f0-9]{64}')
_PARENT_DATASETS = ('strict_area', 'cache')
_METRICS = ('sensitivity_tail', 'localization_relative', 'median_mm', 'p90_mm')
_SCORES = ('field_relative', 'sensitivity_tail', 'localization_relative')


class EditorResultError(ValueError):
    """An editor result Node refuses; the message is Node's, verbatim."""


# --- JavaScript values ------------------------------------------------------------------------------------------

def _nullish(value: Any) -> bool:
    return value is None or value is UNDEFINED


def _opt(value: Any, key: str) -> Any:
    """``value?.key``."""
    return UNDEFINED if _nullish(value) else _member(value, key)


def _length(value: Any) -> Any:
    """``value?.length`` of a parsed JSON value: an object's ``length`` member, ``undefined`` for a number."""
    if isinstance(value, list):
        return len(value)
    if isinstance(value, str):
        return len(value.encode('utf-16-le', errors='surrogatepass')) // 2
    if isinstance(value, dict):
        return value.get('length', UNDEFINED)
    return UNDEFINED


def _required_length(value: Any) -> Any:
    """``value.length``: V8's ``TypeError`` for ``null`` and ``undefined``."""
    _member(value, 'length')
    return _length(value)


def _method(value: Any, expression: str, method: str) -> list:
    """The array whose ``method`` Node calls; V8's ``TypeError`` for anything else."""
    if _nullish(value):
        raise JSTypeError(f"Cannot read properties of {'null' if value is None else 'undefined'} (reading '{method}')")
    if not isinstance(value, list):
        raise JSTypeError(f'{expression}.{method} is not a function')
    return value


def _finite(value: Any) -> bool:
    """``Number.isFinite(value)``."""
    return jsjson.is_number(value) and math.isfinite(jsjson.to_number(value))


def _defined(members: list[tuple[str, Any]]) -> dict:
    """An object literal as ``JSON.stringify`` writes it: ``undefined`` members are left out."""
    return {key: value for key, value in members if value is not UNDEFINED}


# --- validateEditorResult ---------------------------------------------------------------------------------------

def validate_editor_result(r: Any, request: Any) -> None:
    """``validateEditorResult(r, request)``: raises ``EditorResultError`` with Node's message, or ``JSTypeError``
    where V8 throws one; returns ``None`` for a result Node accepts."""
    if (not _same(_opt(r, 'schema'), EDITOR_RESULT_SCHEMA) or not _same(_member(r, 'status'), 'completed')
            or not same(_member(r, 'request'), request)):
        raise EditorResultError('Editor result identity mismatch')
    if _same(_member(request, 'action'), 'prepare'):
        parent = _member(r, 'parent')
        regions = _member(r, 'regions')
        if (not _same(_opt(parent, 'id'), _member(request, 'parent_id'))
                or not _same(_length(_member(r, 'original_indices')), 64)
                or not _same(_length(regions), _member(parent, 'region_count'))
                or any(_region_invalid(a) for a in _method(regions, 'r.regions', 'some'))):
            raise EditorResultError('Invalid editor region data')
        return
    slots = _method(_member(request, 'slots'), 'request.slots', 'filter')
    enabled = [js_truthy(_member(s, 'enabled')) for s in slots]
    n = sum(enabled)
    if (not _same(_member(r, 'electrode_count'), n) or not _same(_length(_member(r, 'evaluated_xyz_mm')), n)
            or not _same(_length(_member(r, 'active_slots')), n)
            or not _same(_length(_member(r, 'region_indices')), n)):
        raise EditorResultError('Invalid edited electrode count')
    if not same([i for i, on in enumerate(enabled) if on], _member(r, 'active_slots')):
        raise EditorResultError('Stable electrode identities changed')
    distance = _member(r, 'minimum_distance_mm')
    if (not _finite(distance) or jsjson.to_number(distance) < 4 - 1e-7
            or any(_point_invalid(p) for p in _method(_member(r, 'evaluated_xyz_mm'), 'r.evaluated_xyz_mm', 'some'))):
        raise EditorResultError('Invalid edited geometry')
    for m in (_member(r, 'baseline'), _member(r, 'parent_metrics'), _member(r, 'edited_metrics')):
        if not js_truthy(m) or not _finite(_member(m, 'field_relative')) or not _finite(_member(m, 'field_absolute')):
            raise EditorResultError('Missing field metric')
        for k in _METRICS:
            if _member(m, k) is not None and not _finite(_member(m, k)):
                raise EditorResultError('Invalid editor metric')
    for m in (_member(r, 'parent_metrics'), _member(r, 'edited_metrics')):
        values = [_member(m, k) for k in _SCORES]
        expected = None if any(v is None for v in values) else min(jsjson.to_number(v) for v in values)
        score = _member(m, 'conditional_global')
        if (score is not None if expected is None
                else not _finite(score) or abs(expected - jsjson.to_number(score)) > 1e-10):
            raise EditorResultError('Invalid editor decision score')


def _region_invalid(a: Any) -> bool:
    """``!a.bank_indices?.length || a.bank_indices.length !== a.xyz_mm?.length``."""
    indices = _member(a, 'bank_indices')
    if not js_truthy(_length(indices)):
        return True
    return not _same(_required_length(indices), _length(_member(a, 'xyz_mm')))


def _point_invalid(p: Any) -> bool:
    """``p.length !== 3 || !p.every(Number.isFinite)``."""
    if not _same(_required_length(p), 3):
        return True
    return not all(_finite(v) for v in _method(p, 'p', 'every'))


# --- records() --------------------------------------------------------------------------------------------------

def records(store: RecordStore) -> list[dict]:
    """``await records()``: the saved ``evaluate`` results as editor drafts, newest first.

    Errors listing the record tree propagate (Node rejects); a record that cannot be read or fails a check is
    skipped. The sort (``jssort``, Node's comparator) raises ``JSTypeError`` where Node's does (a row compared as
    ``b`` without a string ``finished_at``).
    """
    rows = []
    for key in store.keys('editor'):
        if not (isinstance(key, str) and _KEY.fullmatch(key)):
            continue
        try:
            c = store.read(store.path('editor', key, 'cache.json'))
            r = _member(c, 'result')
            request = _opt(r, 'request')
            if (not _same(_opt(request, 'action'), 'evaluate')
                    or not _same(jsjson.sha256_hex(r), _member(c, 'result_sha256'))
                    or not _same(_member(c, 'key'), key) or _request_key(request, _member(c, 'identity')) != key):
                continue
            validate_editor_result(r, request)
            rows.append(_defined([
                ('key', key), ('finished_at', _member(c, 'finished_at')),
                ('parent_id', _member(request, 'parent_id')), ('parent_label', _member(r, 'parent_label')),
                ('electrode_count', _member(r, 'electrode_count')), ('active_regions', _member(r, 'active_regions')),
                ('metrics', _member(r, 'edited_metrics')), ('request', request), ('protocol', _member(r, 'schema')),
                ('restored_as', RESTORED_AS),
            ]))
        except Exception:  # noqa: BLE001 - Never expose incomplete evaluations as scores.
            continue
    return jssort.array_sort(rows, _newest_first)


def _request_key(request: Any, identity: Any) -> str:
    """``hash({request, identity})``: an absent identity is left out of the text."""
    return jsjson.sha256_hex({'request': request}) if identity is UNDEFINED else request_key(request, identity)


def _newest_first(a: dict, b: dict) -> int:
    """``(a, b) => b.finished_at.localeCompare(a.finished_at)``, by UTF-16 code units."""
    mine = b.get('finished_at', UNDEFINED)
    if _nullish(mine):
        raise JSTypeError(f"Cannot read properties of {'null' if mine is None else 'undefined'} "
                          "(reading 'localeCompare')")
    if not isinstance(mine, str):
        raise JSTypeError('b.finished_at.localeCompare is not a function')
    x = mine.encode('utf-16-be', errors='surrogatepass')
    y = _js_string(a.get('finished_at', UNDEFINED)).encode('utf-16-be', errors='surrogatepass')
    return (x > y) - (x < y)


# --- parents() --------------------------------------------------------------------------------------------------

def parents(library: Any) -> list[dict]:
    """``await parents()``: the library summaries (``Library.list()`` order) of completed strict-area and radius
    layouts without a noise model whose full record (``Library.get``) has ``layout.regionPatchVertexIndices``.
    ``library`` is a ``jobs.library.Library``; its errors propagate, as Node's do."""
    rows = []
    for summary in library.list()['records']:
        if (not _same(summary.get('status', UNDEFINED), 'completed')
                or summary.get('dataset_id', UNDEFINED) not in _PARENT_DATASETS
                or js_truthy(_opt(summary.get('request', UNDEFINED), 'noise_model'))
                or js_truthy(_opt(summary.get('request', UNDEFINED), 'electrode_count'))):
            continue
        record = library.get(summary['id'])
        if (js_truthy(_opt(_opt(record, 'layout'), 'regionPatchVertexIndices'))
                and _same(_length(_opt(_opt(record, 'layout'), 'xyzMm')), 64)):
            rows.append(summary)
    return rows
