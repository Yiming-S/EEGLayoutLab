"""Research-project requests (``webapp/server/projects/store.mjs`` and ``service.mjs``).

A research project (``research-project/1``) keeps named scientific results: frozen snapshots of a layout record, a
named evaluation (a layout record with its electrode-name annotation), an editor record or a signal-reception
result. Its endpoints take five request bodies, each the value ``JSON.parse`` gives:

- ``project-create`` (``POST /api/projects``): ``{title, owner_name, notes?}``;
- ``project-patch`` (``PATCH /api/projects/<id>``): ``{revision, title?, owner_name?, notes?, workflow?}``, at least
  one change;
- ``project-entry`` (``POST /api/projects/<id>/entries``): ``{revision, kind, record_id | receipt_id,
  annotation_id?, title?, notes?}``;
- ``project-entry-patch`` (``PATCH .../entries/<entry>``): ``{revision, title?, notes?}``, at least one change;
- ``project-entry-delete`` (``DELETE .../entries/<entry>`` without ``If-Match``): ``{revision}``, other keys ignored.

The functions here are Node's checks, statement by statement, with Node's messages and statuses
(``ProjectRequestError``): ``body_object`` (the service's ``body``: a plain object), ``fields``, ``text``,
``revision``, ``attachment`` (service.mjs) and ``workflow`` (the comparison settings, which the store checks against
the project's entries; its link is read as WHATWG ``new URL(href, 'http://localhost')`` reads it). A format is the
checks Node makes before the project is read, in Node's order: the service's body check, then the store's
synchronous checks (``create``'s, ``patch``'s, ``attach``'s with the electrode annotation it reads, ``patchEntry``'s)
and the revision. A workflow is passed through: the store checks it against the project's entries.

The canonical value of a format is the request as the store uses it: texts trimmed, ``notes`` of a new project
``''`` when absent or null, an entry's ``title`` and ``notes`` left out when absent or null (the title then defaults
to ``<kind> <first 8 digits of the record>``), the revision as sent. The models describe it for the OpenAPI
document. Values are ``jsjson.parse`` values or plain Python data (tuples count as arrays, ``bool`` is not a number);
they are not changed.
"""
from __future__ import annotations

import math
import re
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import (BaseModel, BeforeValidator, ConfigDict, Discriminator, Field, Tag, WithJsonSchema,
                      WrapValidator)

from . import jsjson
from .types import js_integer

__all__ = [
    'PROJECT_SCHEMA', 'SNAPSHOT_SCHEMA', 'ENTRY_KINDS', 'COMPARISON_PROTOCOLS', 'MAX_SAFE_INTEGER', 'UNDEFINED',
    'ProjectRequestError', 'body_object', 'fields', 'has_control', 'text', 'revision', 'sha_test', 'valid_uuid',
    'same', 'truthy', 'defined', 'coalesce', 'is_object', 'safe_integer', 'units',
    'attachment', 'workflow', 'js_string', 'string_to_number', 'search_params',
    'normalize_create', 'normalize_patch', 'normalize_entry', 'normalize_entry_patch', 'normalize_entry_delete',
    'ProjectCreate', 'ProjectPatch', 'ProjectEntryInput', 'ProjectEntryPatch', 'ProjectEntryDelete',
    'LayoutRecordEntry', 'NamedEvaluationEntry', 'EditorRecordEntry', 'SignalReceiptEntry',
]

PROJECT_SCHEMA = 'research-project/1'
SNAPSHOT_SCHEMA = 'research-project-snapshot/1'
ENTRY_KINDS = ('layout', 'editor', 'source')
COMPARISON_PROTOCOLS = ('strict_area', 'cache', 'design_evaluation')
COMPARISON_PARAMETERS = ('a', 'b', 'ar', 'thresholdMode', 'sensitivity', 'localization', 'p90')
THRESHOLD_MODES = ('joint', 'custom')
MAX_SAFE_INTEGER = 2**53 - 1
TITLE_UNITS, OWNER_UNITS, NOTES_UNITS, HREF_UNITS = 200, 120, 8000, 4096

CREATE_FIELDS = ('title', 'owner_name', 'notes')
PATCH_FIELDS = ('revision', 'title', 'owner_name', 'notes', 'workflow')
ATTACHMENT_FIELDS = ('revision', 'kind', 'record_id', 'receipt_id', 'title', 'notes', 'annotation_id')
ENTRY_PATCH_FIELDS = ('revision', 'title', 'notes')
WORKFLOW_FIELDS = ('reference_entry_id', 'candidate_entry_id', 'comparison_href')

# Node's messages, verbatim.
INVALID_JSON = 'Invalid project JSON.'
INVALID_FIELDS = 'Invalid project fields.'
REVISION = 'A current project revision is required.'
NO_PROJECT_CHANGES = 'No project changes supplied.'
NO_ENTRY_CHANGES = 'No entry changes supplied.'
INVALID_ATTACHMENT = 'Invalid project attachment.'
INVALID_ANNOTATION = 'Invalid electrode name annotation.'
RECEIPT_REQUIRED = 'A completed signal task receipt is required.'
RECORD_REQUIRED = 'A saved scientific record is required.'
ELECTRODE_NAMES = 'Project electrode names failed integrity checks.'
INVALID_LINK = 'Invalid project comparison link.'
CHOOSE_LAYOUT = 'Choose a layout saved in this project.'
TWO_LAYOUTS = 'Choose two different saved layouts.'
INVALID_PARAMETERS = 'Invalid project comparison parameters.'
SELECTED_LAYOUTS = 'Comparison must use the selected evaluated layouts.'
INVALID_REQUIREMENT = 'Invalid project comparison requirement.'
INVALID_MODE = 'Invalid project comparison mode.'
JOINT_LIMIT = 'Joint comparison requirements must use the same 10–100 percent limit for all three metrics.'

_UUID = re.compile('[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}')
_SHA = re.compile('[a-f0-9]{64}')


class _Undefined:
    """JavaScript ``undefined``: a member that is absent, which is not ``null``."""

    def __repr__(self) -> str:
        return 'undefined'


UNDEFINED = _Undefined()


class ProjectRequestError(ValueError):
    """``projectError(message, status)``: a refusal shown with its status and message (``projectSafe``)."""

    project_safe = True

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


# --- JavaScript values -------------------------------------------------------------------------------------------

def units(value: str) -> int:
    """``value.length``: UTF-16 code units."""
    return len(value.encode('utf-16-le', errors='surrogatepass')) // 2


def _is_array(value: Any) -> bool:
    return isinstance(value, (list, tuple))


def is_object(value: Any) -> bool:
    """``value && typeof value === 'object' && !Array.isArray(value)``."""
    return isinstance(value, dict)


def safe_integer(value: Any) -> bool:
    """``Number.isSafeInteger(value)``."""
    return jsjson.is_integer(value) and abs(jsjson.to_number(value)) <= MAX_SAFE_INTEGER


def js_string(value: Any) -> str:
    """``String(value)`` of parsed JSON or ``UNDEFINED``: an array is joined with commas (null elements empty), an
    object is ``[object Object]``; an object with its own ``toString`` (never callable in JSON) raises JavaScript's
    ``TypeError``."""
    if isinstance(value, str):
        return value
    if value is UNDEFINED:
        return 'undefined'
    if value is True:
        return 'true'
    if value is False:
        return 'false'
    if value is None:
        return 'null'
    if jsjson.is_number(value):
        number = jsjson.to_number(value)
        if math.isnan(number):
            return 'NaN'
        if math.isinf(number):
            return 'Infinity' if number > 0 else '-Infinity'
        return jsjson.number_to_string(number)
    if _is_array(value):
        return ','.join('' if item is None or item is UNDEFINED else js_string(item) for item in value)
    if isinstance(value, dict):
        if 'toString' in value:
            raise TypeError('Cannot convert object to primitive value')
        return '[object Object]'
    raise TypeError(f'not JSON data: {type(value).__name__}')


def same(a: Any, b: Any) -> bool:
    """``a === b`` of parsed JSON or ``UNDEFINED``: objects and arrays only by identity, numbers by value (NaN is
    not itself, -0 is 0), ``bool`` is not a number."""
    if isinstance(a, (dict, list, tuple)) or isinstance(b, (dict, list, tuple)):
        return a is b
    if jsjson.is_number(a) and jsjson.is_number(b):
        return jsjson.to_number(a) == jsjson.to_number(b)
    if isinstance(a, str) and isinstance(b, str):
        return a == b
    return a is b


def truthy(value: Any) -> bool:
    """JavaScript truthiness: ``{}`` and ``[]`` are true; ``undefined``, ``null``, ``false``, ``0``, ``NaN`` and ``''``
    are false."""
    if value is None or value is UNDEFINED or value is False:
        return False
    if jsjson.is_number(value):
        number = jsjson.to_number(value)
        return number != 0 and not math.isnan(number)
    if isinstance(value, str):
        return value != ''
    return True


def defined(value: dict, key: str) -> bool:
    """``value.key !== undefined`` for an object: the member is present and not ``UNDEFINED``."""
    return value.get(key, UNDEFINED) is not UNDEFINED


def coalesce(value: Any, default: Any) -> Any:
    """``value ?? default``."""
    return default if value is None or value is UNDEFINED else value


def sha_test(value: Any) -> bool:
    """``/^[a-f0-9]{64}$/.test(value)``: the value converted with ``String``."""
    return _SHA.fullmatch(js_string(value)) is not None


def valid_uuid(value: Any) -> bool:
    """``validProjectId(value)``: a string that is a lowercase UUID v4."""
    return isinstance(value, str) and _UUID.fullmatch(value) is not None


def _in(value: Any, allowed: tuple[str, ...]) -> bool:
    """``allowed.includes(value)`` for a list of strings."""
    return isinstance(value, str) and value in allowed


_DECIMAL = re.compile(r'[+-]?(?:Infinity|(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)')
_RADIX = re.compile(r'0([xXoObB])([0-9a-fA-F]+)')


def string_to_number(value: str) -> float:
    """``Number(value)`` of a string (ECMA-262 StringToNumber): JavaScript white space trimmed, empty is 0, a
    decimal literal with an optional sign or ``Infinity``, or an unsigned ``0x``, ``0o`` or ``0b`` integer; else
    NaN."""
    trimmed = jsjson.js_trim(value)
    if not trimmed:
        return 0.0
    radix = _RADIX.fullmatch(trimmed)
    if radix is not None:
        try:
            return jsjson.to_number(int(radix[2], {'x': 16, 'o': 8, 'b': 2}[radix[1].lower()]))
        except ValueError:
            return math.nan
    if _DECIMAL.fullmatch(trimmed) is not None:
        return float(trimmed)
    return math.nan


# --- Node's checks -----------------------------------------------------------------------------------------------

def body_object(value: Any) -> Any:
    """The service's ``body(req)`` after ``JSON.parse``: a plain object, else 400 ``Invalid project JSON.``."""
    if not isinstance(value, dict):
        raise ProjectRequestError(INVALID_JSON)
    return value


def fields(value: Any, allowed: tuple[str, ...]) -> None:
    """``fields(value, allowed)``: a plain object whose keys are all allowed."""
    if not isinstance(value, dict) or any(key not in allowed for key in value):
        raise ProjectRequestError(INVALID_FIELDS)


def has_control(value: str) -> bool:
    """``hasControl(value)``: a UTF-16 unit below 32 other than tab, line feed and carriage return."""
    return any(ord(c) < 32 and c not in '\t\n\r' for c in value)


def text(value: Any, name: str, maximum: int, required: bool = False) -> str:
    """``text(value, name, max, required)``: a string of at most ``maximum`` UTF-16 units without control characters,
    not blank when required (else 400 ``Invalid <name>.``); returns it trimmed."""
    if not isinstance(value, str) or units(value) > maximum or has_control(value) or (required and not jsjson.js_trim(value)):
        raise ProjectRequestError(f'Invalid {name}.')
    return jsjson.js_trim(value)


def revision(value: Any) -> Any:
    """``revision(value)``: ``Number.isSafeInteger(value) && value >= 1``, else 400 ``A current project revision is
    required.``; returns the value."""
    if not (safe_integer(value) and jsjson.to_number(value) >= 1):
        raise ProjectRequestError(REVISION)
    return value


def attachment(value: Any) -> None:
    """``attachment(input)`` (service.mjs): the kind and the scientific reference of a new entry."""
    if (not isinstance(value, dict) or any(key not in ATTACHMENT_FIELDS for key in value)
            or not _in(value.get('kind'), ENTRY_KINDS)):
        raise ProjectRequestError(INVALID_ATTACHMENT)
    if defined(value, 'annotation_id') and (value['kind'] != 'layout' or not sha_test(value['annotation_id'])):
        raise ProjectRequestError(INVALID_ANNOTATION)
    if value['kind'] == 'source':
        if not valid_uuid(value.get('receipt_id')) or defined(value, 'record_id'):
            raise ProjectRequestError(RECEIPT_REQUIRED)
    elif (not (isinstance(value.get('record_id'), str) and _SHA.fullmatch(value['record_id']))
          or defined(value, 'receipt_id')):
        raise ProjectRequestError(RECORD_REQUIRED)


# --- The comparison link ------------------------------------------------------------------------------------------

def _scalar_values(value: str) -> str:
    """The USVString of a JavaScript string: surrogate pairs joined, lone surrogates U+FFFD."""
    joined = value.encode('utf-16-le', errors='surrogatepass').decode('utf-16-le', errors='surrogatepass')
    return ''.join('�' if 0xD800 <= ord(c) <= 0xDFFF else c for c in joined)


_QUERY_ENCODED = frozenset(' "#<>\'')


def _percent_encode(query: str) -> str:
    """The special-query percent-encode set: C0 controls, code points above U+007E, space, ``"``, ``#``, ``<``,
    ``>`` and ``'``, as UTF-8 bytes with uppercase hex digits."""
    out = []
    for c in query:
        if ord(c) < 0x20 or ord(c) > 0x7E or c in _QUERY_ENCODED:
            out.append(''.join(f'%{byte:02X}' for byte in c.encode('utf-8')))
        else:
            out.append(c)
    return ''.join(out)


def _comparison_url(href: str) -> tuple[str, bool]:
    """``new URL(href, 'http://localhost')`` of a link that starts with ``/decision?``: ``(query, hash)``, the
    percent-encoded query (``url.search`` without its ``?``) and whether ``url.hash`` is not empty. Such a link
    always parses, with origin ``http://localhost`` and path ``/decision``."""
    value = _scalar_values(href)
    start, end = 0, len(value)
    while start < end and ord(value[start]) <= 0x20:
        start += 1
    while end > start and ord(value[end - 1]) <= 0x20:
        end -= 1
    value = value[start:end].replace('\t', '').replace('\n', '').replace('\r', '')
    query, _, fragment = value[value.index('?') + 1:].partition('#')
    return _percent_encode(query), fragment != ''


def _percent_decode(text: str) -> str:
    data = text.replace('+', ' ').encode('utf-8')
    out = bytearray()
    index = 0
    while index < len(data):
        if data[index] == 0x25 and re.fullmatch(rb'[0-9a-fA-F]{2}', data[index + 1:index + 3]):
            out.append(int(data[index + 1:index + 3], 16))
            index += 3
        else:
            out.append(data[index])
            index += 1
    return out.decode('utf-8', errors='replace')


def search_params(query: str) -> list[tuple[str, str]]:
    """``new URLSearchParams(query)`` of a percent-encoded query: the name/value pairs of
    ``application/x-www-form-urlencoded`` parsing (``+`` is a space, invalid escapes are kept, UTF-8 with
    replacement)."""
    pairs = []
    for part in query.split('&'):
        if part:
            name, _, value = part.partition('=')
            pairs.append((_percent_decode(name), _percent_decode(value)))
    return pairs


def _layout(entries: list, id: Any) -> Optional[dict]:
    """``entries.find(row => row.id === id && row.kind === 'layout')`` for a UUID ``id``."""
    for row in entries:
        if isinstance(row, dict) and row.get('id') == id and row.get('kind') == 'layout':
            return row
    return None


def workflow(value: Any, entries: list) -> dict[str, Any]:
    """``workflow(value, entries)`` (store.mjs): the comparison settings of a project whose entries are
    ``entries``, normalized (``comparison_href`` is ``url.pathname + url.search``)."""
    fields(value, WORKFLOW_FIELDS)
    href = value.get('comparison_href', UNDEFINED)
    if href is not UNDEFINED and href is not None and not isinstance(href, str):
        raise ProjectRequestError(INVALID_LINK)
    result = {'reference_entry_id': coalesce(value.get('reference_entry_id'), None),
              'candidate_entry_id': coalesce(value.get('candidate_entry_id'), None),
              'comparison_href': href if truthy(href) else None}
    selected: dict[str, dict] = {}
    for name in ('reference_entry_id', 'candidate_entry_id'):
        id = result[name]
        if id is None:
            continue
        entry = _layout(entries, id) if valid_uuid(id) else None
        if entry is None:
            raise ProjectRequestError(CHOOSE_LAYOUT)
        selected[name] = entry
    if result['reference_entry_id'] and result['reference_entry_id'] == result['candidate_entry_id']:
        raise ProjectRequestError(TWO_LAYOUTS)
    href = result['comparison_href']
    if href is not None:
        if units(href) > HREF_UNITS or not href.startswith('/decision?'):
            raise ProjectRequestError(INVALID_LINK)
        query, fragment = _comparison_url(href)
        if fragment:
            raise ProjectRequestError(INVALID_LINK)
        pairs = search_params(query)
        names = [name for name, _ in pairs]
        if any(name not in COMPARISON_PARAMETERS or names.count(name) != 1 for name in names):
            raise ProjectRequestError(INVALID_PARAMETERS)
        params = dict(pairs)
        reference, candidate = selected.get('reference_entry_id'), selected.get('candidate_entry_id')
        if (not reference or not candidate or params.get('a') != reference.get('record_id')
                or params.get('b') != candidate.get('record_id')
                or any(not _in(entry['summary'].get('protocol'), COMPARISON_PROTOCOLS) for entry in (reference, candidate))):
            raise ProjectRequestError(SELECTED_LAYOUTS)
        for name, maximum in (('ar', 100), ('sensitivity', 100), ('localization', 100), ('p90', 500)):
            if name not in params:
                continue
            number = string_to_number(params[name])
            if (not params[name] or not math.isfinite(number) or number < (1 if name == 'ar' else 0) or number > maximum
                    or (name == 'ar' and not number.is_integer())):
                raise ProjectRequestError(INVALID_REQUIREMENT)
        if 'thresholdMode' in params and params['thresholdMode'] not in THRESHOLD_MODES:
            raise ProjectRequestError(INVALID_MODE)
        mode = params.get('thresholdMode')
        joint = mode == 'joint' or (mode != 'custom' and not any(name in params for name in ('sensitivity', 'localization', 'p90')))
        if joint:
            field = string_to_number(params['ar']) if 'ar' in params else 90
            if (field < 10 or field > 100 or 'p90' in params
                    or any(name in params and string_to_number(params[name]) != field for name in ('sensitivity', 'localization'))):
                raise ProjectRequestError(JOINT_LIMIT)
        result['comparison_href'] = '/decision' + ('?' + query if query else '')
    return result


# --- Request formats ---------------------------------------------------------------------------------------------

def _clone(value: Any) -> Any:
    """A copy of parsed JSON (tuples become lists)."""
    if isinstance(value, dict):
        return {key: _clone(item) for key, item in value.items()}
    if _is_array(value):
        return [_clone(item) for item in value]
    return value


def normalize_create(value: Any) -> dict[str, Any]:
    """``POST /api/projects``: ``body``, then ``ProjectStore.create``'s checks; ``{title, owner_name, notes}``."""
    body_object(value)
    fields(value, CREATE_FIELDS)
    return {'title': text(value.get('title', UNDEFINED), 'project title', TITLE_UNITS, True),
            'owner_name': text(value.get('owner_name', UNDEFINED), 'researcher name', OWNER_UNITS, True),
            'notes': text(coalesce(value.get('notes'), ''), 'project notes', NOTES_UNITS)}


def normalize_patch(value: Any) -> dict[str, Any]:
    """``PATCH /api/projects/<id>``: ``body``, then ``ProjectStore.patch``'s checks before the project is read;
    ``{revision, title?, owner_name?, notes?, workflow?}``, the workflow as sent."""
    body_object(value)
    fields(value, PATCH_FIELDS)
    if len(value) < 2:
        raise ProjectRequestError(NO_PROJECT_CHANGES)
    values = {name: text(value[name], name, NOTES_UNITS if name == 'notes' else TITLE_UNITS if name == 'title' else OWNER_UNITS,
                         name != 'notes')
              for name in ('title', 'owner_name', 'notes') if defined(value, name)}
    out = {'revision': revision(value.get('revision', UNDEFINED)), **values}
    if defined(value, 'workflow'):
        out['workflow'] = _clone(value['workflow'])
    return out


def normalize_entry(value: Any) -> dict[str, Any]:
    """``POST /api/projects/<id>/entries``: ``body``, ``attachment``, then ``ProjectStore.attach``'s checks of the
    request with the electrode annotation it names (an annotation's ``id`` is a string, so an ``annotation_id``
    that only converts to a digest is refused) and the revision; ``{revision, kind, record_id | receipt_id,
    annotation_id?, title?, notes?}``."""
    body_object(value)
    attachment(value)
    if defined(value, 'annotation_id') and not isinstance(value['annotation_id'], str):
        raise ProjectRequestError(ELECTRODE_NAMES, 409)
    title, notes = coalesce(value.get('title'), None), coalesce(value.get('notes'), None)
    if title is not None:
        title = text(title, 'entry title', TITLE_UNITS, True)
    notes = text(coalesce(notes, ''), 'entry notes', NOTES_UNITS)
    out: dict[str, Any] = {'revision': revision(value.get('revision', UNDEFINED)), 'kind': value['kind']}
    reference = 'receipt_id' if value['kind'] == 'source' else 'record_id'
    out[reference] = value[reference]
    if defined(value, 'annotation_id'):
        out['annotation_id'] = value['annotation_id']
    if title is not None:
        out['title'] = title
    if coalesce(value.get('notes'), None) is not None:
        out['notes'] = notes
    return out


def normalize_entry_patch(value: Any) -> dict[str, Any]:
    """``PATCH /api/projects/<id>/entries/<entry>``: ``body``, then ``ProjectStore.patchEntry``'s checks;
    ``{revision, title?, notes?}``."""
    body_object(value)
    fields(value, ENTRY_PATCH_FIELDS)
    if len(value) < 2:
        raise ProjectRequestError(NO_ENTRY_CHANGES)
    values = {name: text(value[name], name, NOTES_UNITS if name == 'notes' else TITLE_UNITS, name == 'title')
              for name in ('title', 'notes') if defined(value, name)}
    return {'revision': revision(value.get('revision', UNDEFINED)), **values}


def normalize_entry_delete(value: Any) -> dict[str, Any]:
    """``DELETE /api/projects/<id>/entries/<entry>`` without ``If-Match``: ``body``, then the revision it names
    (other keys are ignored); ``{revision}``."""
    body_object(value)
    return {'revision': revision(value.get('revision', UNDEFINED))}


# --- Schema --------------------------------------------------------------------

def _absent_defaults(schema: dict[str, Any]) -> None:
    # Optional but not nullable: the canonical form leaves a field out instead of writing null. Set on the model, as a
    # field's own json_schema_extra would replace the bounds its type carries.
    for name, field in schema['properties'].items():
        if field.get('default', '') is None:
            field.pop('default')


_EXACT = ConfigDict(extra='forbid', json_schema_extra=_absent_defaults)


def _string(maximum: int, required: bool, description: str) -> Any:
    # Lengths are UTF-16 units, checked by text(); the bounds are kept for the schema only (see submission.py).
    return Annotated[str, Field(strict=True, description=description,
                                json_schema_extra={**({'minLength': 1} if required else {}), 'maxLength': maximum})]


Revision = Annotated[int, Field(strict=True, ge=1, le=MAX_SAFE_INTEGER,
                                description="The project's current revision, which the change replaces."),
                     BeforeValidator(js_integer)]
ProjectTitle = _string(TITLE_UNITS, True, 'Trimmed; no control characters other than tab and line breaks.')
OwnerName = _string(OWNER_UNITS, True, 'The researcher named on the project; trimmed.')
ProjectNotes = _string(NOTES_UNITS, False, 'Trimmed; no control characters other than tab and line breaks.')
RecordId = Annotated[str, Field(strict=True, pattern='^[a-f0-9]{64}$',
                                description='The scientific record: a lowercase SHA-256 hex digest.')]
AnnotationId = Annotated[str, Field(strict=True, pattern='^[a-f0-9]{64}$',
                                    description='The electrode-name annotation of the evaluation.')]
ReceiptId = Annotated[str, Field(strict=True, pattern='^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$',
                                 description='The receipt of a completed signal-reception task.')]
WORKFLOW_SCHEMA = {
    'type': 'object',
    'title': 'ProjectWorkflowInput',
    'description': "Comparison settings, checked against the project's entries when saved: two different saved "
                   'layouts and a /decision? link to their comparison.',
    'properties': {
        'reference_entry_id': {'type': ['string', 'null']},
        'candidate_entry_id': {'type': ['string', 'null']},
        'comparison_href': {'type': ['string', 'null'], 'maxLength': HREF_UNITS},
    },
    'additionalProperties': False,
}


class ProjectCreate(BaseModel):
    """A new project: its title, the researcher's name and optional notes."""
    model_config = _EXACT
    title: ProjectTitle
    owner_name: OwnerName
    notes: ProjectNotes = ''

    def canonical(self) -> dict[str, Any]:
        return {'title': self.title, 'owner_name': self.owner_name, 'notes': self.notes}


class ProjectPatch(BaseModel):
    """Changes to a project at its current revision: at least one of title, researcher name, notes and the
    comparison settings."""
    model_config = _EXACT
    revision: Revision
    title: ProjectTitle = None
    owner_name: OwnerName = None
    notes: ProjectNotes = None
    workflow: Annotated[Any, WithJsonSchema(WORKFLOW_SCHEMA)] = None

    def canonical(self) -> dict[str, Any]:
        out: dict[str, Any] = {'revision': self.revision}
        for name in ('title', 'owner_name', 'notes', 'workflow'):
            if name in self.model_fields_set:
                out[name] = _clone(getattr(self, name))
        return out


class _Entry(BaseModel):
    model_config = _EXACT
    revision: Revision
    title: Annotated[str, Field(strict=True, json_schema_extra={'minLength': 1, 'maxLength': TITLE_UNITS},
                                description='Trimmed; defaults to the kind and the first 8 digits of the record.')] = None
    notes: ProjectNotes = None

    def canonical(self) -> dict[str, Any]:
        out: dict[str, Any] = {'revision': self.revision, 'kind': self.kind}  # type: ignore[attr-defined]
        for name in ('record_id', 'receipt_id', 'annotation_id', 'title', 'notes'):
            if name in type(self).model_fields and getattr(self, name) is not None:
                out[name] = getattr(self, name)
        return out


class LayoutRecordEntry(_Entry):
    """A completed layout record of the library."""
    kind: Literal['layout']
    record_id: RecordId


class NamedEvaluationEntry(_Entry):
    """A completed design evaluation with the electrode-name annotation it was submitted with."""
    kind: Literal['layout']
    record_id: RecordId
    annotation_id: AnnotationId


class EditorRecordEntry(_Entry):
    """A completed evaluation of the electrode editor."""
    kind: Literal['editor']
    record_id: RecordId


class SignalReceiptEntry(_Entry):
    """A completed signal-reception task, by its receipt."""
    kind: Literal['source']
    receipt_id: ReceiptId


class ProjectEntryPatch(BaseModel):
    """Changes to an entry at the project's current revision: its title, its notes or both."""
    model_config = _EXACT
    revision: Revision
    title: ProjectTitle = None
    notes: ProjectNotes = None

    def canonical(self) -> dict[str, Any]:
        out: dict[str, Any] = {'revision': self.revision}
        for name in ('title', 'notes'):
            if name in self.model_fields_set:
                out[name] = getattr(self, name)
        return out


class ProjectEntryDelete(BaseModel):
    """The project's current revision, when the request has no ``If-Match`` header; other keys are ignored."""
    model_config = ConfigDict(extra='ignore')
    revision: Revision

    def canonical(self) -> dict[str, Any]:
        return {'revision': self.revision}


def _rules(normalize: Any, model: Any) -> Any:
    # Node's rules decide and give the message; the model then checks the canonical value it describes.
    def check(value: Any, handler: Any) -> Any:
        if isinstance(value, model):
            return value
        return handler(normalize(value))
    return WrapValidator(check)


_ENTRY_MODELS = (LayoutRecordEntry, NamedEvaluationEntry, EditorRecordEntry, SignalReceiptEntry)


def _entry_kind(value: Any) -> str:
    # Node's rules have run, so a dict is a canonical entry.
    if isinstance(value, dict):
        return 'named_evaluation' if 'annotation_id' in value else value.get('kind')
    return {LayoutRecordEntry: 'layout', NamedEvaluationEntry: 'named_evaluation', EditorRecordEntry: 'editor',
            SignalReceiptEntry: 'source'}.get(type(value))


ProjectCreateBody = Annotated[ProjectCreate, _rules(normalize_create, ProjectCreate)]
ProjectPatchBody = Annotated[ProjectPatch, _rules(normalize_patch, ProjectPatch)]
ProjectEntryInput = Annotated[
    Union[Annotated[LayoutRecordEntry, Tag('layout')], Annotated[NamedEvaluationEntry, Tag('named_evaluation')],
          Annotated[EditorRecordEntry, Tag('editor')], Annotated[SignalReceiptEntry, Tag('source')]],
    Discriminator(_entry_kind), _rules(normalize_entry, _ENTRY_MODELS),
]
ProjectEntryPatchBody = Annotated[ProjectEntryPatch, _rules(normalize_entry_patch, ProjectEntryPatch)]
ProjectEntryDeleteBody = Annotated[ProjectEntryDelete, _rules(normalize_entry_delete, ProjectEntryDelete)]


def canonical(value: Any) -> dict[str, Any]:
    """The registry's canonical value of a validated body."""
    return value.canonical()
