"""Channel-subset selection from recorded EEG covariance (``webapp/lib/channel-subset.ts``, phase 3 slice 12).

Pure Python IEEE-754 binary64 arithmetic in V8's exact order of operations, mulberry32 PRNG and ``toPrecision(6)``
rounding (no ``numpy``, no stdlib ``json``).
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Any, Callable, Optional, Sequence

from ..jobs.jssort import array_sort
from ..schemas import jsjson
from . import jsmath

__all__ = [
    'SUBSET_SCHEMA', 'SUMMARY_SCHEMA', 'PRIOR_SCHEMA',
    'DEFAULT_COUNTS', 'RANDOM_DRAWS', 'CHANNEL_PRESENCE', 'TEN_TWENTY',
    'Matrix', 'stats', 'covariance_matrix', 'restrict',
    'reconstruction_error', 'greedy_order', 'generator', 'channel_subsets',
]

SUBSET_SCHEMA = 'eeg-channel-subset/1'
SUMMARY_SCHEMA = 'eeg-covariance-summary/1'
PRIOR_SCHEMA = 'eeg-data-prior/1'
DEFAULT_COUNTS: tuple[int, ...] = (8, 16, 24, 32)
RANDOM_DRAWS = 200
CHANNEL_PRESENCE = 0.9
TEN_TWENTY: tuple[str, ...] = (
    'Fp1', 'Fp2', 'F7', 'F3', 'Fz', 'F4', 'F8',
    'T7', 'C3', 'Cz', 'C4', 'T8',
    'P7', 'P3', 'Pz', 'P4', 'P8',
    'O1', 'O2',
)
_SHA256_HEX_RE = re.compile(r'^[a-f0-9]{64}$', re.IGNORECASE)


@dataclass(frozen=True)
class Matrix:
    n: int
    a: list[float]


def _finite(v: Any) -> bool:
    return jsjson.is_number(v) and math.isfinite(float(v))


def _quantile(sorted_vals: Sequence[float], q: float) -> float:
    position = (len(sorted_vals) - 1) * q
    low = math.floor(position)
    high = math.ceil(position)
    return sorted_vals[low] + (sorted_vals[high] - sorted_vals[low]) * (position - low)


def stats(values: Sequence[float]) -> dict[str, float]:
    """``stats(values)``: left-to-right IEEE-754 mean and type-7 median/P10/P90."""
    sorted_vals = array_sort([float(v) for v in values], lambda x, y: x - y)
    s = 0.0
    for v in values:
        s += float(v)
    return {
        'mean': s / len(values),
        'median': _quantile(sorted_vals, 0.5),
        'p10': _quantile(sorted_vals, 0.1),
        'p90': _quantile(sorted_vals, 0.9),
    }


def _trace_of(n: int, a: Sequence[float]) -> float:
    t = 0.0
    for i in range(n):
        t += a[i * n + i]
    return t


def restrict(covariance: Sequence[Sequence[float]], channels: Sequence[str], names: Sequence[str]) -> Matrix:
    """``restrict(covariance, channels, names)``: symmetric, average-referenced, trace-normalized matrix."""
    chan_list = list(channels)
    index = [chan_list.index(name) if name in chan_list else -1 for name in names]
    n = len(names)
    a = [0.0] * (n * n)
    for i in range(n):
        ii = index[i]
        for j in range(n):
            jj = index[j]
            a[i * n + j] = (float(covariance[ii][jj]) + float(covariance[jj][ii])) / 2.0
    rows = [0.0] * n
    total = 0.0
    for i in range(n):
        base = i * n
        for j in range(n):
            rows[i] += a[base + j]
        total += rows[i]
    nn = float(n * n)
    nf = float(n)
    for i in range(n):
        base = i * n
        ri = rows[i] / nf
        for j in range(n):
            a[base + j] += total / nn - ri - rows[j] / nf
    tr = _trace_of(n, a)
    if not (tr > 0.0):
        raise ValueError('协方差的迹不为正')
    for k in range(len(a)):
        a[k] /= tr
    return Matrix(n=n, a=a)


def covariance_matrix(covariance: Sequence[Sequence[float]], channels: Sequence[str]) -> Matrix:
    return restrict(covariance, channels, channels)


def _mean_matrix(matrices: Sequence[Matrix]) -> Matrix:
    n = matrices[0].n
    a = [0.0] * (n * n)
    count = float(len(matrices))
    for m in matrices:
        for k in range(len(a)):
            a[k] += m.a[k] / count
    return Matrix(n=n, a=a)


def _solve(a_mat: Sequence[float], k: int, b_mat: Sequence[float], n: int) -> list[float]:
    """Cholesky solve of ``A X = B`` for SPD ``A`` (``k×k``) and ``B`` (``k×n``) with ``1e-12`` trace ridge."""
    trace = 0.0
    for i in range(k):
        trace += a_mat[i * k + i]
    lower = [0.0] * (k * k)
    ridge = 1e-12 * trace / max(k, 1)
    for i in range(k):
        for j in range(i + 1):
            s = a_mat[i * k + j] + (ridge if i == j else 0.0)
            for p in range(j):
                s -= lower[i * k + p] * lower[j * k + p]
            if i == j:
                if not (s > 0.0):
                    raise ValueError('子集通道的协方差奇异')
                lower[i * k + i] = math.sqrt(s)
            else:
                lower[i * k + j] = s / lower[j * k + j]
    x_mat = list(b_mat)
    for c in range(n):
        for i in range(k):
            s = x_mat[i * n + c]
            for p in range(i):
                s -= lower[i * k + p] * x_mat[p * n + c]
            x_mat[i * n + c] = s / lower[i * k + i]
        for i in range(k - 1, -1, -1):
            s = x_mat[i * n + c]
            for p in range(i + 1, k):
                s -= lower[p * k + i] * x_mat[p * n + c]
            x_mat[i * n + c] = s / lower[i * k + i]
    return x_mat


def _reconstructor(train: Matrix, subset: Sequence[int]) -> list[float]:
    n, a = train.n, train.a
    s0 = subset[0]
    k = len(subset) - 1
    b_mat = [0.0] * (k * n)
    for m in range(k):
        sm = subset[m + 1]
        for j in range(n):
            b_mat[m * n + j] = a[sm * n + j] - a[s0 * n + j]
    a_mat = [0.0] * (k * k)
    for m in range(k):
        for p in range(k):
            a_mat[m * k + p] = b_mat[m * n + subset[p + 1]] - b_mat[m * n + s0]
    return _solve(a_mat, k, b_mat, n)


def reconstruction_error(
    train: Matrix,
    test: Matrix,
    subset: Sequence[int],
    v_mat: Optional[Sequence[float]] = None,
) -> float:
    """``reconstructionError(train, test, subset, V)`` from ``webapp/lib/channel-subset.ts``."""
    n = test.n
    c = test.a
    total = _trace_of(n, c)
    if v_mat is None:
        v_mat = _reconstructor(train, subset) if len(subset) > 1 else None
    if not v_mat:
        return 1.0
    k = len(subset) - 1
    s0 = subset[0]
    m_mat = [0.0] * (n * n)
    for m in range(k):
        sm = subset[m + 1]
        v_base = m * n
        for i in range(n):
            val = v_mat[v_base + i]
            m_mat[i * n + sm] += val
            m_mat[i * n + s0] -= val
    columns = [s0, *subset[1:]]
    cross = 0.0
    quadratic = 0.0
    for i in range(n):
        i_base = i * n
        for p in columns:
            cross += m_mat[i_base + p] * c[p * n + i]
    for i in range(n):
        i_base = i * n
        for p in columns:
            mip = m_mat[i_base + p]
            p_base = p * n
            for q in columns:
                quadratic += mip * c[p_base + q] * m_mat[i_base + q]
    return max(0.0, (total - 2.0 * cross + quadratic) / total)


def greedy_order(m: Matrix, count: int) -> list[int]:
    """``greedyOrder(m, count)``: best pair first, then greedy forward residual updates."""
    n = m.n
    r_mat = list(m.a)
    total = _trace_of(n, r_mat)
    eps = 1e-12 * total
    best = -1.0
    pair = (0, 1)
    squared = [0.0] * (n * n)
    for i in range(n):
        i_base = i * n
        for j in range(n):
            s = 0.0
            for p in range(n):
                s += r_mat[i_base + p] * r_mat[p * n + j]
            squared[i_base + j] = s
    for i in range(n):
        for j in range(i + 1, n):
            den = r_mat[i * n + i] + r_mat[j * n + j] - 2.0 * r_mat[i * n + j]
            if den <= eps:
                continue
            gain = (squared[i * n + i] + squared[j * n + j] - 2.0 * squared[i * n + j]) / den
            if gain > best + 1e-15:
                best = gain
                pair = (i, j)
    order: list[int] = []

    def add(c: int, s0: int) -> None:
        u = [r_mat[i * n + c] - r_mat[i * n + s0] for i in range(n)]
        den = u[c] - u[s0]
        if den > eps:
            for i in range(n):
                ui = u[i]
                i_base = i * n
                for j in range(n):
                    r_mat[i_base + j] -= ui * u[j] / den
        order.append(c)

    order.append(pair[0])
    add(pair[1], pair[0])
    target_len = min(count, n)
    while len(order) < target_len:
        s0 = order[0]
        chosen = set(order)
        gain_best = -1.0
        nxt = -1
        for c in range(n):
            if c in chosen:
                continue
            den = r_mat[c * n + c] - 2.0 * r_mat[c * n + s0] + r_mat[s0 * n + s0]
            gain = 0.0
            if den > eps:
                for i in range(n):
                    d = r_mat[i * n + c] - r_mat[i * n + s0]
                    gain += d * d
                gain /= den
            if gain > gain_best + 1e-15:
                gain_best = gain
                nxt = c
        add(nxt, s0)
    return order


def _to_uint32(val: float | int) -> int:
    if isinstance(val, int) and not isinstance(val, bool):
        return val & 0xFFFFFFFF
    f = float(val)
    if not math.isfinite(f) or f == 0.0:
        return 0
    return int(math.fmod(math.trunc(f), 4294967296.0)) & 0xFFFFFFFF


def generator(seed: float | int) -> Callable[[], float]:
    """``generator(seed)``: mulberry32 PRNG matching JavaScript ``Math.imul`` and ``>>>`` bit for bit."""
    state = [_to_uint32(seed)]

    def _next() -> float:
        s = (state[0] + 0x6D2B79F5) & 0xFFFFFFFF
        state[0] = s
        t = ((s ^ (s >> 15)) * (s | 1)) & 0xFFFFFFFF
        m = ((t ^ (t >> 7)) * (t | 61)) & 0xFFFFFFFF
        t = (t ^ ((t + m) & 0xFFFFFFFF)) & 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296.0

    return _next


def _check_summary(value: Any, role: str) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get('schema') != SUMMARY_SCHEMA:
        raise ValueError(f'{role}不是eeg-covariance-summary/1协方差摘要')
    channels = value.get('channels')
    n = len(channels) if isinstance(channels, list) else 0
    cov = value.get('covariance')
    proc = value.get('processing')
    band = proc.get('band_hz') if isinstance(proc, dict) else None
    src = value.get('source')
    rec_sha = src.get('recording_sha256') if isinstance(src, dict) and 'recording_sha256' in src else None
    has_rec_sha = isinstance(src, dict) and 'recording_sha256' in src and src['recording_sha256'] is not None
    if (
        not n
        or not all(isinstance(c, str) for c in channels)
        or len(set(channels)) != n
        or not isinstance(cov, list)
        or len(cov) != n
        or not all(isinstance(row, list) and len(row) == n and all(_finite(x) for x in row) for row in cov)
        or not isinstance(band, list)
        or len(band) != 2
        or not isinstance(src, dict)
        or not isinstance(src.get('sha256'), str)
        or (
            isinstance(src, dict)
            and 'recording_sha256' in src
            and (not isinstance(rec_sha, str) or not _SHA256_HEX_RE.match(rec_sha))
        )
    ):
        raise ValueError(f'{role}不是eeg-covariance-summary/1协方差摘要')
    _ = has_rec_sha
    return value


def _check_prior(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get('schema') != PRIOR_SCHEMA:
        raise ValueError('不是eeg-data-prior/1数据先验文件')
    channels = value.get('channels')
    n = len(channels) if isinstance(channels, list) else 0
    cmodel = value.get('channel_model')

    def _square(m: Any) -> bool:
        return (
            isinstance(m, list)
            and len(m) == n
            and all(isinstance(row, list) and len(row) == n and all(_finite(x) for x in row) for row in m)
        )

    if (
        not n
        or not isinstance(value.get('id'), str)
        or not isinstance(value.get('band_hz'), list)
        or not isinstance(cmodel, dict)
        or not _square(cmodel.get('data_prior'))
        or not _square(cmodel.get('area_prior'))
    ):
        raise ValueError('不是eeg-data-prior/1数据先验文件')
    return value


def _same_band(a: Sequence[Any], b: Sequence[Any]) -> bool:
    return len(a) >= 2 and len(b) >= 2 and a[0] == b[0] and a[1] == b[1]


def _describe(s: dict[str, Any]) -> dict[str, Any]:
    src = s['source']
    out: dict[str, Any] = {
        'label': s.get('label') if s.get('label') is not None else None,
        'file': src.get('file'),
        'sha256': src['sha256'],
    }
    if 'recording_sha256' in src:
        out['recording_sha256'] = src['recording_sha256']
    return out


def _check_recording_split(training: Sequence[dict[str, Any]], test: Sequence[dict[str, Any]]) -> None:
    recording_hashes: set[str] = set()
    entry_hashes: set[str] = set()
    legacy_entry_hashes: set[str] = set()
    for s in training:
        src = s['source']
        entry_hash = str(src['sha256']).lower()
        entry_hashes.add(entry_hash)
        rec_sha = src.get('recording_sha256')
        if rec_sha:
            recording_hashes.add(str(rec_sha).lower())
        else:
            legacy_entry_hashes.add(entry_hash)
    for s in test:
        src = s['source']
        entry_hash = str(src['sha256']).lower()
        rec_sha = src.get('recording_sha256')
        repeated = (
            (str(rec_sha).lower() in recording_hashes or entry_hash in legacy_entry_hashes)
            if rec_sha
            else (entry_hash in entry_hashes)
        )
        if repeated:
            raise ValueError(f"训练和检验摘要包含同一份录制：{src.get('file')}")


def _round6(v: float) -> float:
    return jsmath.js_number(jsmath.to_precision(v, 6))


def _round_stats(s: dict[str, float]) -> dict[str, float]:
    return {
        'mean': _round6(s['mean']),
        'median': _round6(s['median']),
        'p10': _round6(s['p10']),
        'p90': _round6(s['p90']),
    }


def _dedup_js_numbers(items: Sequence[Any]) -> list[float]:
    seen: list[float] = []
    saw_nan = False
    for raw in items:
        val = float(raw) if jsjson.is_number(raw) else math.nan
        if math.isnan(val):
            if not saw_nan:
                saw_nan = True
                seen.append(val)
        elif not any(not math.isnan(prev) and prev == val for prev in seen):
            seen.append(val)
    return array_sort(seen, lambda a, b: a - b)


def channel_subsets(
    *,
    training: Sequence[Any],
    test: Optional[Sequence[Any]] = None,
    prior: Any = None,
    counts: Optional[Sequence[Any]] = None,
    draws: Optional[float | int] = None,
    seed: Optional[float | int] = None,
) -> dict[str, Any]:
    """``channelSubsets(options)`` from ``webapp/lib/channel-subset.ts``."""
    if not training:
        raise ValueError('至少需要一个训练摘要')
    checked_training = [_check_summary(s, f'训练摘要{i + 1}') for i, s in enumerate(training)]
    checked_test = [_check_summary(s, f'检验摘要{i + 1}') for i, s in enumerate(test or ())]
    _check_recording_split(checked_training, checked_test)
    checked_prior = None if prior is None else _check_prior(prior)
    band = checked_training[0]['processing']['band_hz']
    if not all(_same_band(s['processing']['band_hz'], band) for s in (*checked_training, *checked_test)):
        raise ValueError('训练与检验摘要须使用同一频带')
    if checked_prior is not None and not _same_band(checked_prior['band_hz'], band):
        raise ValueError('数据先验与摘要的频带不同')

    order_names: list[str] = []
    presence: dict[str, int] = {}
    for s in checked_training:
        for name in s['channels']:
            if name not in presence:
                order_names.append(name)
                presence[name] = 0
            presence[name] += 1
    threshold = CHANNEL_PRESENCE * len(checked_training)
    universe = [name for name in order_names if presence[name] >= threshold]
    prior_channels = set(checked_prior['channels']) if checked_prior is not None else set()
    outside_prior = [name for name in universe if name not in prior_channels] if checked_prior is not None else []
    if checked_prior is not None:
        universe = [name for name in universe if name in prior_channels]
    if len(universe) < 4:
        raise ValueError(f'共同通道少于4个（{len(universe)}个）')

    training_skipped = [
        {**_describe(s), 'missing': [name for name in universe if name not in s['channels']]}
        for s in checked_training
        if not all(name in s['channels'] for name in universe)
    ]
    used = [s for s in checked_training if all(name in s['channels'] for name in universe)]
    if not used:
        raise ValueError(f'没有一份训练摘要包含全部{len(universe)}个共同通道，请去掉缺通道较多的摘要后重试')

    raw_counts = [float(k) for k in DEFAULT_COUNTS if k < len(universe)] if counts is None else list(counts)
    dedup_counts = _dedup_js_numbers(raw_counts)
    if not dedup_counts or not all(
        jsjson.is_integer(k) and 2 <= int(k) < len(universe) for k in dedup_counts
    ):
        raise ValueError(f'通道数须为2到{len(universe) - 1}之间的整数')
    int_counts = [int(k) for k in dedup_counts]

    eff_draws = RANDOM_DRAWS if draws is None else draws
    eff_seed = 1 if seed is None else seed
    if (
        not jsjson.is_integer(eff_draws)
        or int(eff_draws) < 10
        or int(eff_draws) > 10000
        or not jsjson.is_integer(eff_seed)
        or int(eff_seed) < 0
    ):
        raise ValueError('随机子集次数或种子无效')
    n_draws = int(eff_draws)
    n_seed = int(eff_seed)

    train_mat = _mean_matrix([restrict(s['covariance'], s['channels'], universe) for s in used])
    test_skipped = [
        {**_describe(s), 'missing': [name for name in universe if name not in s['channels']]}
        for s in checked_test
        if not all(name in s['channels'] for name in universe)
    ]
    used_test = [s for s in checked_test if all(name in s['channels'] for name in universe)]
    test_mats = [restrict(s['covariance'], s['channels'], universe) for s in used_test]
    pooled_test = _mean_matrix(test_mats) if test_mats else None

    standard = [name for name in TEN_TWENTY if name in universe]
    max_count = max(int_counts[-1], len(standard) if len(standard) < len(universe) else 0)

    def evaluate_subset(subset: list[int]) -> dict[str, Any]:
        v_mat = _reconstructor(train_mat, subset)
        return {
            'train_error': _round6(reconstruction_error(train_mat, train_mat, subset, v_mat)),
            'test_error': (
                _round_stats(stats([reconstruction_error(train_mat, t, subset, v_mat) for t in test_mats]))
                if test_mats
                else None
            ),
        }

    def run_greedy(selection: Matrix) -> tuple[list[int], dict[str, Any]]:
        g_order = greedy_order(selection, max_count)
        return g_order, {
            'order': [universe[i] for i in g_order],
            'counts': [
                {
                    'count': k,
                    'channels': [universe[i] for i in g_order[:k]],
                    **evaluate_subset(g_order[:k]),
                }
                for k in int_counts
            ],
        }

    data_order, data_val = run_greedy(train_mat)
    methods: dict[str, Any] = {'data': data_val}
    if checked_prior is not None:
        _, dp_val = run_greedy(restrict(checked_prior['channel_model']['data_prior'], checked_prior['channels'], universe))
        _, ap_val = run_greedy(restrict(checked_prior['channel_model']['area_prior'], checked_prior['channels'], universe))
        methods['data_prior'] = dp_val
        methods['area_prior'] = ap_val

    rng = generator(n_seed)
    random_rows: list[dict[str, Any]] = []
    for k in int_counts:
        train_errors: list[float] = []
        test_errors: list[float] = []
        pool = list(range(len(universe)))
        for _ in range(n_draws):
            for i in range(k):
                j = i + math.floor(rng() * (len(pool) - i))
                pool[i], pool[j] = pool[j], pool[i]
            subset = pool[:k]
            v_mat = _reconstructor(train_mat, subset)
            train_errors.append(reconstruction_error(train_mat, train_mat, subset, v_mat))
            if pooled_test is not None:
                test_errors.append(reconstruction_error(train_mat, pooled_test, subset, v_mat))
        random_rows.append({
            'count': k,
            'train_error': _round_stats(stats(train_errors)),
            'test_error_mean': _round_stats(stats(test_errors)) if test_errors else None,
        })

    standard_block: Optional[dict[str, Any]] = None
    if len(standard) >= 2:
        std_indices = [universe.index(name) for name in standard]
        same_count = (
            {
                'channels': [universe[i] for i in data_order[:len(standard)]],
                **evaluate_subset(data_order[:len(standard)]),
            }
            if len(standard) < len(universe)
            else None
        )
        standard_block = {
            'channels': standard,
            'missing': [name for name in TEN_TWENTY if name not in universe],
            'count': len(standard),
            **evaluate_subset(std_indices),
            'data_same_count': same_count,
        }

    return {
        'schema': SUBSET_SCHEMA,
        'band_hz': band,
        'universe': universe,
        'channels_outside_prior': outside_prior,
        'counts': int_counts,
        'training': [_describe(s) for s in used],
        'training_skipped': training_skipped,
        'test': [_describe(s) for s in used_test],
        'test_skipped': test_skipped,
        'prior': {'id': checked_prior['id']} if checked_prior is not None else None,
        'methods': methods,
        'standard_10_20': standard_block,
        'random': {
            'draws': n_draws,
            'seed': n_seed,
            'generator': 'mulberry32',
            'counts': random_rows,
        },
        'definition': {
            'error': 'unexplained variance fraction of the average-referenced universe channels; subset recorded against one of its own channels',
            'reconstructor': 'linear minimum mean-square error, fitted on the pooled trace-normalized training covariance for every method',
            'selection': 'greedy forward: best pair, then the channel explaining the most residual variance; methods differ only in the covariance used',
            'test_error': 'per held-out summary: mean, median, P10, P90; random subsets report the distribution over draws of the mean held-out error',
        },
    }
