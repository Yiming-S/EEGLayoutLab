"""Robustness-study protocol and aggregation: Node's ``studies/protocol.mjs``, statement by statement.

A study is 1 to 12 explicit cases of one design-evaluation protocol: ``noise_seeds`` (one radius, several seeds),
``grid_displacements`` (seed/radius pairs, perturbation trials) or ``heads`` (one head package per case, one shared
seed and radius). ``normalize_study_input`` checks a study body in Node's order and returns Node's normalized study
(``{protocol, title, notes, design, noise_model?, conductivity_scenario?, annotation, requests}``), each case a
canonical design-evaluation request; every refusal is ``StudyError`` (400) with Node's message, the messages of
``normalizeDesignRequest``, ``electrodeNames`` and ``validateCoordinateSource`` included.

``empirical_summary``, ``summarize_study_case`` and ``aggregate_study`` describe completed cases with type-7
quantiles over finite readings, each case weighted once: JavaScript number semantics on IEEE doubles in Node's
order of operations, so the JSON written with ``jsjson.stringify`` equals Node's (``NaN`` and infinities as
``null``, ``-0`` as ``0``). Members are read as Node reads them (``identity._member``: absent is ``UNDEFINED``,
a member of ``null`` raises ``JSTypeError``), so a malformed value fails where Node's code fails.

``STUDY_LIMITS`` keeps Node's size bounds; the public service's study counts (100 in all, 10 per owner, 15 per
network) and the 7-day pruning of unstarted drafts are not carried over (design 0001, phase 2, slice 8).
"""
from __future__ import annotations

import math
from typing import Any

from ..schemas import jsjson
# The option lists the registry reads too (webapp/contracts/robustness-study.ts, studies/store.mjs).
from ..schemas.study_options import CASE_STATUSES, NOMINAL_METRICS, STUDY_PROTOCOLS, STUDY_STATUSES, TRIAL_METRICS
from . import annotations
from .design_result import normalize_design_request
from .identity import UNDEFINED, JSTypeError, _member, _same, js_truthy, to_number
from .jssort import array_sort

__all__ = [
    'STUDY_LIMITS', 'STUDY_PROTOCOLS', 'STUDY_STATUSES', 'CASE_STATUSES', 'TERMINAL_CASE_STATUSES',
    'NOMINAL_METRICS', 'TRIAL_METRICS', 'QUANTILE_METHOD', 'DEFAULT_TITLE', 'StudyError', 'study_error',
    'terminal_case', 'study_action', 'normalize_study_input', 'empirical_summary', 'summarize_study_case',
    'aggregate_study',
]

STUDY_LIMITS = {
    'cases': 12,
    'metadataBytes': 256 * 1024,
    'caseBytes': 16 * 1024 * 1024,
    'studyBytes': 64 * 1024 * 1024,
    'totalBytes': 512 * 1024 * 1024,
}
TERMINAL_CASE_STATUSES = ('completed', 'failed', 'cancelled', 'failed_uncertain')
QUANTILE_METHOD = 'type7_linear'
DEFAULT_TITLE = 'Robustness study'
_INPUT_KEYS = ('protocol', 'design', 'cases', 'title', 'notes', 'noise_model', 'conductivity_scenario')
_FAILED = ('failed', 'failed_uncertain')
_TITLE_UNITS = 200
_NOTES_UNITS = 2000

# Node's messages, verbatim.
CASES = 'Choose a study protocol and 1–12 explicit cases.'
TITLE = 'Invalid study title or notes.'
HEAD_SCENARIO = 'Conductivity scenarios are defined on Ernie only.'
HEAD_CASE_FIELDS = 'Each case requires only head_id, seed and radius_mm.'
CASE_FIELDS = 'Each case requires only an explicit seed and radius_mm.'
HEAD_PACKAGE = 'Each cross-head case names one head package.'
HEAD_REPEATED = 'Each head package appears once in a cross-head study.'
HEAD_SEED = 'Every case in a cross-head study uses the same seed.'
PAIR_REPEATED = 'Each seed/radius pair must be unique.'
RADIUS_FIXED = 'Noise-seed studies hold radius fixed; radius affects displacement trials only.'
FALLBACK = 'Invalid study input.'
SOURCE = annotations.SOURCE


class StudyError(ValueError):
    """``studyError(message, status)``: a refusal shown to the browser with its status (``studySafe``)."""

    study_safe = True

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def study_error(message: str, status: int = 400) -> StudyError:
    return StudyError(message, status)


def terminal_case(status: Any) -> bool:
    """``terminalCase(status)``."""
    return isinstance(status, str) and status in TERMINAL_CASE_STATUSES


def study_action(protocol: Any) -> str:
    """``studyAction(protocol)``: evaluation protocols hold the radius fixed; only grid displacements vary it."""
    return 'perturb' if _same(protocol, 'grid_displacements') else 'evaluate'


# --- normalizeStudyInput ------------------------------------------------------------------------------------------

def _units(text: str) -> int:
    """``text.length``: UTF-16 code units."""
    return len(text.encode('utf-16-le', errors='surrogatepass')) // 2


def _sorted_keys(value: dict) -> str:
    """``Object.keys(value).sort().join(',')``: UTF-16 code-unit order."""
    return ','.join(sorted((str(key) for key in value),
                           key=lambda key: key.encode('utf-16-be', errors='surrogatepass')))


def _defined(value: dict, key: str) -> bool:
    """``value.key !== undefined`` for an object."""
    return value.get(key, UNDEFINED) is not UNDEFINED


def _distinct(values: list) -> list:
    """``[...new Set(values)]``: SameValueZero (``NaN`` is itself, objects by identity), ``-0`` stored as ``+0``,
    first occurrences in order."""
    seen, out = set(), []
    for value in values:
        if isinstance(value, bool):
            key: Any = ('boolean', value)
        elif jsjson.is_number(value):
            number = jsjson.to_number(value)
            key = ('number', 'NaN' if math.isnan(number) else number)
            value = 0.0 if number == 0 else value
        elif isinstance(value, str):
            key = ('string', value)
        elif value is None:
            key = ('null',)
        elif value is UNDEFINED:
            key = ('undefined',)
        else:
            key = ('object', id(value))
        if key not in seen:
            seen.add(key)
            out.append(value)
    return out


def _number_text(value: Any) -> str:
    """``${value}`` of a normalized seed or radius (a finite number)."""
    return jsjson.number_to_string(jsjson.to_number(value))


def _coordinate_source(value: Any) -> dict:
    """``validateCoordinateSource(value)`` through the phase 1 schema: a copy in the input's key order."""
    from ..schemas.coordinate_source import normalize_coordinate_source  # Pydantic: the service extra
    try:
        return normalize_coordinate_source(value)
    except ValueError:
        raise StudyError(SOURCE) from None


def normalize_study_input(raw: Any) -> dict:
    """``normalizeStudyInput(raw)``: Node's normalized study, or ``StudyError`` (400) with Node's message. ``raw`` is
    a ``jsjson.parse`` value or plain Python data (tuples count as arrays); it is not changed. The normalized
    requests are ``normalizeDesignRequest``'s; ``design`` is the first request's design."""
    try:
        return _normalize(raw)
    except StudyError:
        raise
    except annotations.AnnotationError as error:
        raise StudyError(error.message or FALLBACK) from None
    except (ValueError, JSTypeError) as error:
        # `throw studyError(error.message || "Invalid study input.")`
        raise StudyError(str(error) or FALLBACK) from None


def _normalize(raw: Any) -> dict:
    cases = raw.get('cases') if isinstance(raw, dict) else None
    if (not isinstance(raw, dict) or any(key not in _INPUT_KEYS for key in raw)
            or not (isinstance(raw.get('protocol'), str) and raw['protocol'] in STUDY_PROTOCOLS)
            or not isinstance(cases, (list, tuple)) or not cases or len(cases) > STUDY_LIMITS['cases']):
        raise StudyError(CASES)
    # `input.title ?? "Robustness study"`: null and an absent title both mean the default.
    title, notes = raw.get('title', UNDEFINED), raw.get('notes', UNDEFINED)
    title = DEFAULT_TITLE if title is None or title is UNDEFINED else title
    notes = '' if notes is None or notes is UNDEFINED else notes
    if (not isinstance(title, str) or not jsjson.js_trim(title) or _units(title) > _TITLE_UNITS
            or not isinstance(notes, str) or _units(notes) > _NOTES_UNITS):
        raise StudyError(TITLE)
    protocol = raw['protocol']
    action, heads = study_action(protocol), protocol == 'heads'
    if heads and _defined(raw, 'conductivity_scenario'):
        raise StudyError(HEAD_SCENARIO)
    expected = 'head_id,radius_mm,seed' if heads else 'radius_mm,seed'
    requests = []
    for value in cases:
        if not isinstance(value, dict) or _sorted_keys(value) != expected:
            raise StudyError(HEAD_CASE_FIELDS if heads else CASE_FIELDS)
        # The joined names also match keys such as 'radius_mm,seed', whose members are then undefined.
        head_id = value.get('head_id', UNDEFINED)
        if heads and not (isinstance(head_id, str) and head_id):
            raise StudyError(HEAD_PACKAGE)
        request = {'action': action, 'design': raw.get('design', UNDEFINED),
                   'radius_mm': value.get('radius_mm', UNDEFINED), 'seed': value.get('seed', UNDEFINED)}
        if _defined(raw, 'noise_model'):
            request['noise_model'] = raw['noise_model']
        if _defined(raw, 'conductivity_scenario'):
            request['conductivity_scenario'] = raw['conductivity_scenario']
        if heads:
            request['head_id'] = head_id
        requests.append(normalize_design_request(request))
    if heads and len(_distinct([request['head_id'] for request in requests])) != len(requests):
        raise StudyError(HEAD_REPEATED)
    # One shared seed pairs the noise draws across heads.
    if heads and len(_distinct([request['seed'] for request in requests])) != 1:
        raise StudyError(HEAD_SEED)
    if not heads and len({f"{_number_text(request['seed'])}:{_number_text(request['radius_mm'])}"
                          for request in requests}) != len(requests):
        raise StudyError(PAIR_REPEATED)
    if action == 'evaluate' and len(_distinct([request['radius_mm'] for request in requests])) != 1:
        raise StudyError(RADIUS_FIXED)
    design = raw['design']  # an object: normalizeDesignRequest accepted it
    annotation: dict = {}
    if _defined(design, 'electrode_names'):
        annotation['electrode_names'] = annotations.electrode_names(design['electrode_names'])
    if _defined(design, 'source_metadata'):
        annotation['source_metadata'] = _coordinate_source(design['source_metadata'])
        # `annotation.electrode_names ??= ...`: the default names follow the source in key order.
        if 'electrode_names' not in annotation:
            annotation['electrode_names'] = [f'E{index + 1}' for index in range(64)]
    first = requests[0]
    out = {'protocol': protocol, 'title': jsjson.js_trim(title), 'notes': notes, 'design': first['design']}
    # One noise model for every case; absent means independent noise.
    if js_truthy(first.get('noise_model', UNDEFINED)):
        out['noise_model'] = first['noise_model']
    if js_truthy(first.get('conductivity_scenario', UNDEFINED)):
        out['conductivity_scenario'] = first['conductivity_scenario']
    out['annotation'] = annotation
    out['requests'] = requests
    return out


# --- Aggregation --------------------------------------------------------------------------------------------------

def empirical_summary(values: Any) -> dict:
    """``empiricalSummary(values)``: the count of finite numbers and their type-7 median, 10th and 90th
    percentiles (``None`` without readings), computed on doubles in Node's order of operations."""
    finite = []
    for value in _items(values, 'values'):
        if jsjson.is_number(value):
            number = jsjson.to_number(value)
            if math.isfinite(number):
                finite.append(number)
    # `(a, b) => a - b` orders finite doubles consistently (-0 equals 0), so every stable sort, V8's included, gives
    # this order.
    ordered = sorted(finite)

    def quantile(p: float) -> Any:
        if not ordered:
            return None
        h = (len(ordered) - 1) * p
        lower, upper = math.floor(h), math.ceil(h)
        return ordered[lower] + (ordered[upper] - ordered[lower]) * (h - lower)

    return {'n': len(ordered), 'median': quantile(0.5), 'p10': quantile(0.1), 'p90': quantile(0.9)}


def _clone(value: Any) -> Any:
    """``structuredClone(value)`` of parsed JSON, as ``JSON.stringify`` writes the clone: an ``undefined`` member is
    left out, an ``undefined`` item becomes ``null``. Iterative, for any depth ``jsjson.parse`` accepts."""
    if not isinstance(value, (dict, list, tuple)):
        return value
    root: Any = {} if isinstance(value, dict) else []
    stack = [(value, root)]
    while stack:
        source, target = stack.pop()
        items = source.items() if isinstance(source, dict) else enumerate(source)
        for key, child in items:
            if child is UNDEFINED:
                if isinstance(target, list):
                    target.append(None)
                continue
            if isinstance(child, (dict, list, tuple)):
                copy: Any = {} if isinstance(child, dict) else []
                stack.append((child, copy))
                child = copy
            if isinstance(target, list):
                target.append(child)
            else:
                target[key] = child
    return root


def _items(value: Any, name: str) -> list:
    """An array read by ``value.filter`` or ``value.map``; V8's ``TypeError`` otherwise."""
    if isinstance(value, (list, tuple)):
        return list(value)
    if value is None or value is UNDEFINED:
        raise JSTypeError(f"Cannot read properties of {'null' if value is None else 'undefined'} (reading 'filter')")
    raise JSTypeError(f'{name}.filter is not a function')


def summarize_study_case(result: Any) -> dict:
    """``summarizeStudyCase(result)``: the nominal metrics and trials of a design result, the counts of completed
    and geometry-rejected trials and the empirical summary of each trial metric over the completed trials."""
    trials = _items(_member(result, 'trials'), 'trials')
    valid = [trial for trial in trials if _same(_member(trial, 'status'), 'completed')]
    out: dict = {}
    nominal = _member(result, 'nominal')
    if nominal is not UNDEFINED:
        out['nominal'] = _clone(nominal)
    out['trials'] = _clone(trials)
    out['valid_trials'] = len(valid)
    out['rejected_trials'] = sum(1 for trial in trials if _same(_member(trial, 'status'), 'geometry_rejected'))
    out['trial_metrics'] = {metric: empirical_summary([_member(trial, metric) for trial in valid])
                            for metric in TRIAL_METRICS}
    return out


def _in(value: Any, allowed: tuple) -> bool:
    """``allowed.includes(value)`` for a list of strings."""
    return isinstance(value, str) and value in allowed


def _subtract(a: Any, b: Any) -> float:
    """``a - b``: both converted with ``ToNumber`` (``NaN`` and infinities as JavaScript gives them)."""
    return to_number(a) - to_number(b)


def _numeric_order(values: list) -> list:
    """``values.sort((a, b) => a - b)``: V8's sort, ``undefined`` moved to the end without a comparison."""
    return array_sort([value for value in values if value is not UNDEFINED], _subtract) + \
        [value for value in values if value is UNDEFINED]


def _radius(case: Any) -> Any:
    return _member(_member(case, 'request'), 'radius_mm')


def aggregate_study(protocol: Any, cases: Any) -> dict:
    """``aggregateStudy(protocol, cases)``: case counts by status and, per radius in ascending order, the empirical
    summaries over completed cases with a summary, each case weighted once: the nominal metrics, and the median
    and 10th percentile of each trial metric. Pending cases are those not in a terminal status."""
    cases = _items(cases, 'cases')

    def count(statuses: tuple) -> int:
        return sum(1 for value in cases if _in(_member(value, 'status'), statuses))

    out: dict = {}
    if protocol is not UNDEFINED:
        out['protocol'] = protocol
    out.update({
        'case_count': len(cases),
        'completed_cases': count(('completed',)),
        'failed_cases': count(_FAILED),
        'cancelled_cases': count(('cancelled',)),
        'pending_cases': sum(1 for value in cases if not terminal_case(_member(value, 'status'))),
        'quantile_method': QUANTILE_METHOD,
        'interpretation': ('cross_head_empirical_cases' if _same(protocol, 'heads')
                           else 'Ernie_within_model_empirical_cases'),
    })
    groups = []
    for radius_mm in _numeric_order(_distinct([_radius(value) for value in cases])):
        selected = [value for value in cases if _same(_radius(value), radius_mm)]
        complete = [value for value in selected
                    if _same(_member(value, 'status'), 'completed') and js_truthy(_member(value, 'summary'))]
        group: dict = {} if radius_mm is UNDEFINED else {'radius_mm': radius_mm}
        group.update({
            'case_count': len(selected),
            'completed_cases': len(complete),
            'failed_cases': sum(1 for value in selected if _in(_member(value, 'status'), _FAILED)),
            'nominal': {
                metric: empirical_summary([_member(_member(_member(value, 'summary'), 'nominal'), metric)
                                           for value in complete])
                for metric in NOMINAL_METRICS},
            'trial_case_medians': {
                metric: empirical_summary([_member(_trial_metric(value, metric), 'median') for value in complete])
                for metric in TRIAL_METRICS},
            'trial_case_p10': {
                metric: empirical_summary([_member(_trial_metric(value, metric), 'p10') for value in complete])
                for metric in TRIAL_METRICS},
        })
        groups.append(group)
    out['groups'] = groups
    return out


def _trial_metric(case: Any, metric: str) -> Any:
    return _member(_member(_member(case, 'summary'), 'trial_metrics'), metric)
