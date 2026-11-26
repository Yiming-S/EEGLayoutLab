"""Multi-objective Pareto non-dominated sorting and CLI report builder (``webapp/lib/pareto.ts``, phase 3 slice 11).

Pure Python floats, V8 TimSort (``jobs/jssort.py``) and ``schemas/jsjson`` only (no ``numpy``, no stdlib ``json``,
no ``pydantic``).
"""
from __future__ import annotations

import math
from typing import Any, Sequence

from ..jobs.jssort import array_sort
from ..schemas import jsjson

__all__ = [
    'PARETO_SCHEMA', 'PARETO_OBJECTIVES', 'DEFAULT_OBJECTIVES',
    'robustness_summary_from_block', 'summary_objectives', 'comparison_group',
    'dominates', 'pareto_ranks', 'pareto_analysis', 'run_objectives', 'pareto_cli_report',
]

PARETO_SCHEMA = 'eeglayoutlab-cli-pareto/1'
RUN_SCHEMA = 'eeglayoutlab-cli-run/1'

PARETO_OBJECTIVES: tuple[dict[str, str], ...] = (
    {'id': 'field', 'label': '重建保留率', 'direction': 'max', 'unit': 'ratio'},
    {'id': 'sensitivity', 'label': '幅度保留率', 'direction': 'max', 'unit': 'ratio'},
    {'id': 'localization', 'label': '相对定位评分', 'direction': 'max', 'unit': 'ratio'},
    {'id': 'p90', 'label': '定位误差P90', 'direction': 'min', 'unit': 'mm'},
    {'id': 'area', 'label': '电极贴片总面积', 'direction': 'min', 'unit': 'cm2'},
    {'id': 'dropout', 'label': '随机脱落4个电极后的重建保留率', 'direction': 'max', 'unit': 'ratio'},
    {'id': 'impedance', 'label': '电极噪声不均（对数标准差1.0）后的重建保留率', 'direction': 'max', 'unit': 'ratio'},
    {'id': 'replacement', 'label': '重新佩戴10 mm后的重建保留率（沿用原重建器）', 'direction': 'max', 'unit': 'ratio'},
)

DEFAULT_OBJECTIVES: tuple[str, ...] = ('field', 'sensitivity', 'localization')
_OBJECTIVE_BY_ID: dict[str, dict[str, str]] = {obj['id']: obj for obj in PARETO_OBJECTIVES}


def _finite(value: Any) -> bool:
    return jsjson.is_number(value) and math.isfinite(float(value))


def _index_of_number(levels: Any, wanted: float) -> int:
    if not isinstance(levels, list):
        return -1
    for idx, item in enumerate(levels):
        if jsjson.is_number(item) and float(item) == wanted:
            return idx
    return -1


def _level(levels: Any, values: Any, wanted: float) -> Optional_float:
    idx = _index_of_number(levels, wanted)
    if idx < 0 or not isinstance(values, list) or idx >= len(values):
        return None
    val = values[idx]
    return None if val is None else val


Optional_float = Any


def _nullish_median(entry: Any) -> Any:
    if not isinstance(entry, dict):
        return None
    med = entry.get('median')
    return None if med is None else med


def robustness_summary_from_block(block: Any) -> dict[str, Any]:
    """Pure-dict port of ``robustnessSummary`` (``webapp/contracts/scientific-options.mjs``) without Pydantic."""
    if not isinstance(block, dict):
        return {'dropout': {'removed': [], 'candidate': [], 'reference': []},
                'impedance': {'log_sd': [], 'candidate': [], 'reference': []},
                'replacement': None}
    rep_block = block.get('replacement')
    replacement: Any = None
    if isinstance(rep_block, dict) and rep_block.get('status') == 'completed':
        levels = rep_block.get('levels') or []
        replacement = {
            'rms_mm': [lvl.get('rms_mm') if isinstance(lvl, dict) else None for lvl in levels],
            'fixed': {
                'candidate': [
                    _nullish_median((lvl.get('candidate') or {}).get('fixed_estimator'))
                    if isinstance(lvl, dict) and isinstance(lvl.get('candidate'), dict) else None
                    for lvl in levels
                ],
                'reference': [
                    _nullish_median((lvl.get('reference') or {}).get('fixed_estimator'))
                    if isinstance(lvl, dict) and isinstance(lvl.get('reference'), dict) else None
                    for lvl in levels
                ],
            },
            'redigitized': {
                'candidate': [
                    _nullish_median((lvl.get('candidate') or {}).get('redigitized'))
                    if isinstance(lvl, dict) and isinstance(lvl.get('candidate'), dict) else None
                    for lvl in levels
                ],
                'reference': [
                    _nullish_median((lvl.get('reference') or {}).get('redigitized'))
                    if isinstance(lvl, dict) and isinstance(lvl.get('reference'), dict) else None
                    for lvl in levels
                ],
            },
        }
    dropout_block = block.get('dropout')
    dropout_levels = dropout_block.get('random') if isinstance(dropout_block, dict) and isinstance(dropout_block.get('random'), list) else []
    impedance_levels = block.get('impedance') if isinstance(block.get('impedance'), list) else []
    out: dict[str, Any] = {}
    if 'protocol' in block:
        out['protocol'] = block['protocol']
    out['dropout'] = {
        'removed': [lvl.get('removed') if isinstance(lvl, dict) else None for lvl in dropout_levels],
        'candidate': [_nullish_median(lvl.get('candidate')) if isinstance(lvl, dict) else None for lvl in dropout_levels],
        'reference': [_nullish_median(lvl.get('reference')) if isinstance(lvl, dict) else None for lvl in dropout_levels],
    }
    out['impedance'] = {
        'log_sd': [lvl.get('log_sd') if isinstance(lvl, dict) else None for lvl in impedance_levels],
        'candidate': [_nullish_median(lvl.get('candidate')) if isinstance(lvl, dict) else None for lvl in impedance_levels],
        'reference': [_nullish_median(lvl.get('reference')) if isinstance(lvl, dict) else None for lvl in impedance_levels],
    }
    out['replacement'] = replacement
    return out


def summary_objectives(record: dict[str, Any]) -> dict[str, Any]:
    """``summaryObjectives(record)`` from ``webapp/lib/pareto.ts``."""
    m = record.get('metrics') if isinstance(record, dict) else None
    m_dict = m if isinstance(m, dict) else {}
    geom = record.get('geometry') if isinstance(record, dict) else None
    g_dict = geom if isinstance(geom, dict) else {}
    robust = record.get('robustness') if isinstance(record, dict) else None
    r_dict = robust if isinstance(robust, dict) else {}
    dropout = r_dict.get('dropout') if isinstance(r_dict.get('dropout'), dict) else {}
    impedance = r_dict.get('impedance') if isinstance(r_dict.get('impedance'), dict) else {}
    replacement = r_dict.get('replacement') if isinstance(r_dict.get('replacement'), dict) else {}
    fixed_rep = replacement.get('fixed') if isinstance(replacement.get('fixed'), dict) else {}
    return {
        'field': m_dict.get('field_relative') if m_dict.get('field_relative') is not None else None,
        'sensitivity': m_dict.get('sensitivity_tail') if m_dict.get('sensitivity_tail') is not None else None,
        'localization': m_dict.get('localization_relative') if m_dict.get('localization_relative') is not None else None,
        'p90': m_dict.get('p90_mm') if m_dict.get('p90_mm') is not None else None,
        'area': g_dict.get('union_area_cm2') if g_dict.get('union_area_cm2') is not None else None,
        'dropout': _level(dropout.get('removed'), dropout.get('candidate'), 4.0),
        'impedance': _level(impedance.get('log_sd'), impedance.get('candidate'), 1.0),
        'replacement': _level(replacement.get('rms_mm'), fixed_rep.get('candidate'), 10.0),
    }


def comparison_group(record: dict[str, Any]) -> Any:
    """``comparisonGroup(record)`` from ``webapp/lib/pareto.ts``."""
    ds = record.get('dataset_id')
    current = ds in ('design_evaluation', 'strict_area') or (ds == 'cache' and bool(record.get('compatible')))
    if not current or record.get('status') != 'completed':
        return None
    req = record.get('request') if isinstance(record.get('request'), dict) else {}
    cond = record.get('evaluation_condition') if isinstance(record.get('evaluation_condition'), dict) else {}
    noise = req.get('noise_model') if req.get('noise_model') is not None else cond.get('noise_model')
    prior = req.get('data_prior') if req.get('data_prior') is not None else cond.get('data_prior')
    group: dict[str, Any] = {
        'noise': noise if noise is not None else None,
        'scenario': cond.get('conductivity_scenario') if cond.get('conductivity_scenario') is not None else None,
        'head': cond.get('head_id') if cond.get('head_id') is not None else None,
    }
    if prior:
        group['prior'] = prior
    return jsjson.stringify(group)


def dominates(a: Sequence[float], b: Sequence[float], directions: Sequence[str]) -> bool:
    """``dominates(a, b, directions)``: ties within ``1e-12`` are equal."""
    better = False
    for k in range(len(a)):
        gain = (a[k] - b[k]) if directions[k] == 'max' else (b[k] - a[k])
        if gain < -1e-12:
            return False
        if gain > 1e-12:
            better = True
    return better


def pareto_ranks(points: Sequence[Sequence[float]], directions: Sequence[str]) -> dict[str, list[int]]:
    """``paretoRanks(points, directions)``: 1-based non-dominated front rank and dominating count per point."""
    n = len(points)
    dominated_by = [0] * n
    dominating: list[list[int]] = [[] for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i != j and dominates(points[i], points[j], directions):
                dominating[i].append(j)
                dominated_by[j] += 1
    rank = [0] * n
    remaining = list(dominated_by)
    front = [i for i, count in enumerate(remaining) if count == 0]
    current = 1
    while front:
        nxt: list[int] = []
        for i in front:
            rank[i] = current
            for j in dominating[i]:
                remaining[j] -= 1
                if remaining[j] == 0:
                    nxt.append(j)
        front = nxt
        current += 1
    return {'rank': rank, 'dominatedBy': dominated_by}


def pareto_analysis(items: Sequence[dict[str, Any]], objectives: Sequence[str]) -> dict[str, Any]:
    """``paretoAnalysis(items, objectives)`` from ``webapp/lib/pareto.ts``."""
    if not objectives or len(set(objectives)) != len(objectives) or any(oid not in _OBJECTIVE_BY_ID for oid in objectives):
        raise ValueError('请选择不重复的比较目标')
    chosen = [dict(_OBJECTIVE_BY_ID[oid]) for oid in objectives]
    complete_indices = [
        idx for idx, entry in enumerate(items)
        if all(_finite((entry.get('values') or {}).get(oid)) for oid in objectives)
    ]
    complete_set = set(complete_indices)
    complete = [items[idx] for idx in complete_indices]
    excluded = [items[idx]['item'] for idx in range(len(items)) if idx not in complete_set]
    points = [[float(entry['values'][oid]) for oid in objectives] for entry in complete]
    ranks_info = pareto_ranks(points, [obj['direction'] for obj in chosen])
    ranks = ranks_info['rank']
    dom_by = ranks_info['dominatedBy']
    first_dir = -1.0 if chosen[0]['direction'] == 'max' else 1.0
    unsorted_rows = [
        {
            'item': entry['item'],
            'values': points[i],
            'rank': ranks[i],
            'dominated_by': dom_by[i],
        }
        for i, entry in enumerate(complete)
    ]

    def _cmp(a: dict[str, Any], b: dict[str, Any]) -> float:
        diff = a['rank'] - b['rank']
        if diff != 0:
            return float(diff)
        return first_dir * (a['values'][0] - b['values'][0])

    rows = array_sort(unsorted_rows, _cmp)
    return {'objectives': chosen, 'rows': rows, 'excluded': excluded}


def run_objectives(path: str, run: Any) -> dict[str, Any]:
    """``runObjectives(path)`` from ``webapp/scripts/eeglayoutlab.mjs``."""
    if not isinstance(run, dict) or run.get('schema') != RUN_SCHEMA or not run.get('result'):
        raise ValueError(f'{path} is not an evaluate or search result of this tool')
    request = run.get('request') if isinstance(run.get('request'), dict) else {}
    result = run.get('result') if isinstance(run.get('result'), dict) else {}
    service = run.get('service')
    if service == 'design-evaluation':
        if request.get('action') != 'evaluate':
            raise ValueError(f'{path}: perturbation runs have no single nominal score')
        design = request.get('design') if isinstance(request.get('design'), dict) else {}
        rob_raw = result.get('robustness')
        return {
            'name': design.get('name'),
            'condition': {
                'noise': request.get('noise_model') if request.get('noise_model') is not None else None,
                'scenario': request.get('conductivity_scenario') if request.get('conductivity_scenario') is not None else None,
                'head': request.get('head_id') if request.get('head_id') is not None else None,
                'prior': request.get('data_prior') if request.get('data_prior') is not None else None,
            },
            'values': summary_objectives({
                'metrics': result.get('nominal'),
                'geometry': None,
                'robustness': robustness_summary_from_block(rob_raw) if rob_raw else None,
            }),
        }
    if service == 'radius-search':
        if result.get('status') != 'completed':
            raise ValueError(f'{path}: the search found no layout')
        reg_s = jsjson.number_to_string(request['region_count'])
        rad_s = jsjson.number_to_string(request['radius_mm'])
        return {
            'name': f"search {reg_s} regions, {rad_s} mm, {request.get('mode')}",
            'condition': {
                'noise': request.get('noise_model') if request.get('noise_model') is not None else None,
                'scenario': None,
                'head': None,
                'prior': request.get('data_prior') if request.get('data_prior') is not None else None,
            },
            'values': summary_objectives({
                'metrics': result.get('metrics'),
                'geometry': result.get('geometry'),
            }),
        }
    raise ValueError(f'{path}: unknown service {service}')


def pareto_cli_report(file_runs: Sequence[tuple[str, Any]], objectives_list: str | None = None) -> dict[str, Any]:
    """``pareto(files, list)`` from ``webapp/scripts/eeglayoutlab.mjs``."""
    objectives = (
        [jsjson.js_trim(v) for v in objectives_list.split(',')]
        if objectives_list
        else list(DEFAULT_OBJECTIVES)
    )
    unknown = [oid for oid in objectives if oid not in _OBJECTIVE_BY_ID]
    if unknown:
        raise ValueError(f"unknown objective {', '.join(unknown)}")
    items = [{'file': path, **run_objectives(path, raw)} for path, raw in file_runs]
    if len({jsjson.stringify(item['condition']) for item in items}) > 1:
        raise ValueError(
            'the results use different noise models, data priors, conductivity scenarios or heads; '
            'compare one condition at a time'
        )
    analysis = pareto_analysis(
        [{'item': item, 'values': item['values']} for item in items],
        objectives,
    )
    chosen = analysis['objectives']
    return {
        'schema': PARETO_SCHEMA,
        'objectives': [obj['id'] for obj in chosen],
        'directions': {obj['id']: obj['direction'] for obj in chosen},
        'condition': items[0]['condition'],
        'rows': [
            {
                'file': row['item']['file'],
                'name': row['item']['name'],
                'rank': row['rank'],
                'dominated_by': row['dominated_by'],
                'values': {obj['id']: row['values'][k] for k, obj in enumerate(chosen)},
            }
            for row in analysis['rows']
        ],
        'excluded': [
            {
                'file': item['file'],
                'name': item['name'],
                'missing': [oid for oid in objectives if not _finite(item['values'].get(oid))],
            }
            for item in analysis['excluded']
        ],
    }
