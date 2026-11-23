"""JavaScript JSON and number semantics needed to reproduce Node request keys byte for byte.

Node computes cache keys as SHA-256 of ``JSON.stringify(...)`` over values from
``JSON.parse``. Python's ``json`` differs in number spelling (``1.0`` vs ``1``,
``1e-07`` vs ``1e-7``, ``-0.0`` vs ``0``), accepts ``NaN``/``Infinity``, keeps
integers exact, and slices strings by code point rather than UTF-16 unit. The
functions here follow ECMA-262 instead.
"""
from __future__ import annotations

import hashlib
import json
import math
from decimal import Decimal
from typing import Any

__all__ = [
    'parse', 'stringify', 'sha256_hex', 'number_to_string',
    'is_number', 'to_number', 'is_integer', 'hypot', 'round_half_up',
    'equals_to_precision', 'slice_utf16',
]


# --- JSON.parse -------------------------------------------------------------

def _reject_constant(name: str) -> Any:
    raise ValueError(f'JSON.parse rejects {name}')


def parse(text: str) -> Any:
    """``JSON.parse(text)``: every number is an IEEE double; NaN/Infinity literals are rejected.

    ``parse_int=float`` mirrors JavaScript, where ``2026`` and ``2026.0`` are the
    same value, and avoids Python's 4300-digit integer limit. A leading BOM is
    rejected by both parsers.
    """
    if not isinstance(text, str):
        raise TypeError('parse expects str; decode bytes first')
    return json.loads(text, parse_constant=_reject_constant, parse_int=float)


def decode_body(body: bytes) -> str:
    """Node's ``Buffer.toString()`` of a whole body: UTF-8 with U+FFFD replacement, BOM kept."""
    return body.decode('utf-8', errors='replace')


# --- JSON.stringify ---------------------------------------------------------

def number_to_string(value: float) -> str:
    """ECMA-262 Number::toString(10), with JSON.stringify's NaN/Infinity -> null."""
    if isinstance(value, bool):
        raise TypeError('bool is not a number')
    if isinstance(value, int):
        try:
            value = float(value)
        except OverflowError:
            return 'null'
    if not math.isfinite(value):
        return 'null'
    if value == 0:
        return '0'  # also -0
    sign = '-' if value < 0 else ''
    # repr() is the shortest round-trip decimal, the same digit string ECMAScript selects.
    _, digit_tuple, exponent = Decimal(repr(abs(value))).normalize().as_tuple()
    digits = ''.join(map(str, digit_tuple))
    k = len(digits)
    n = exponent + k  # value = 0.digits * 10**n
    if k <= n <= 21:
        text = digits + '0' * (n - k)
    elif 0 < n <= 21:
        text = digits[:n] + '.' + digits[n:]
    elif -6 < n <= 0:
        text = '0.' + '0' * (-n) + digits
    else:
        e = n - 1
        mantissa = digits if k == 1 else digits[0] + '.' + digits[1:]
        text = f"{mantissa}e{'+' if e >= 0 else '-'}{abs(e)}"
    return sign + text


_SHORT_ESCAPES = {0x08: '\\b', 0x09: '\\t', 0x0A: '\\n', 0x0C: '\\f', 0x0D: '\\r', 0x22: '\\"', 0x5C: '\\\\'}


def _utf16_units(text: str) -> list[int]:
    data = text.encode('utf-16-le', errors='surrogatepass')
    return [data[i] | data[i + 1] << 8 for i in range(0, len(data), 2)]


def quote(text: str) -> str:
    """ECMA-262 QuoteJSONString over UTF-16 code units (well-formed JSON.stringify)."""
    units = _utf16_units(text)
    out: list[str] = ['"']
    i = 0
    while i < len(units):
        u = units[i]
        if 0xD800 <= u <= 0xDBFF and i + 1 < len(units) and 0xDC00 <= units[i + 1] <= 0xDFFF:
            out.append(chr(0x10000 + ((u - 0xD800) << 10) + (units[i + 1] - 0xDC00)))
            i += 2
            continue
        if u in _SHORT_ESCAPES:
            out.append(_SHORT_ESCAPES[u])
        elif u < 0x20 or 0xD800 <= u <= 0xDFFF:
            out.append(f'\\u{u:04x}')
        else:
            out.append(chr(u))
        i += 1
    out.append('"')
    return ''.join(out)


def stringify(value: Any) -> str:
    """``JSON.stringify(value)`` for JSON data: insertion key order, no whitespace, JS numbers.

    Absent optional fields must be left out of the dict by the caller, as Node
    builds objects with conditional spreads; ``None`` is serialized as ``null``.
    """
    if value is None:
        return 'null'
    if value is True:
        return 'true'
    if value is False:
        return 'false'
    if isinstance(value, (int, float)):
        return number_to_string(value)
    if isinstance(value, str):
        return quote(value)
    if isinstance(value, (list, tuple)):
        return '[' + ','.join(stringify(v) for v in value) + ']'
    if isinstance(value, dict):
        for key in value:
            if not isinstance(key, str):
                raise TypeError('object keys must be strings')
        # JavaScript orders integer-like keys first; request formats have none, so refuse rather than guess.
        if any(key.isdigit() for key in value):
            raise ValueError('integer-like object keys are ordered differently in JavaScript')
        return '{' + ','.join(quote(k) + ':' + stringify(v) for k, v in value.items()) + '}'
    raise TypeError(f'not JSON data: {type(value).__name__}')


def sha256_hex(value: Any) -> str:
    """Node's ``createHash('sha256').update(JSON.stringify(value)).digest('hex')``."""
    return hashlib.sha256(stringify(value).encode('utf-8')).hexdigest()


# --- Number predicates and Math -------------------------------------------

def is_number(value: Any) -> bool:
    """``typeof value === 'number'`` for parsed JSON (bool is not a number)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def to_number(value: Any) -> float:
    """The double JavaScript would hold; huge Python ints become +/-Infinity."""
    try:
        return float(value)
    except OverflowError:
        return math.inf if value > 0 else -math.inf


def is_integer(value: Any) -> bool:
    """``Number.isInteger(value)``."""
    if not is_number(value):
        return False
    number = to_number(value)
    return math.isfinite(number) and number.is_integer()


def hypot(*values: float) -> float:
    """V8's ``Math.hypot``: scale by the largest magnitude, Kahan-sum the squares.

    ``math.hypot`` and ``sqrt(x*x + y*y + z*z)`` round differently in the last
    bit, which matters at the 4 mm spacing threshold.
    """
    magnitudes = [abs(float(v)) for v in values]
    if not magnitudes:
        return 0.0
    if any(math.isinf(v) for v in magnitudes):
        return math.inf
    if any(math.isnan(v) for v in magnitudes):
        return math.nan
    largest = max(magnitudes)
    if largest == 0:
        return 0.0
    total = compensation = 0.0
    for v in magnitudes:
        n = v / largest
        summand = n * n - compensation
        preliminary = total + summand
        compensation = (preliminary - total) - summand
        total = preliminary
    return math.sqrt(total) * largest


def round_half_up(value: float) -> float:
    """``Math.round``: nearest integer, ties toward +Infinity (Python's round() is half-even)."""
    if not math.isfinite(value):
        return value
    floor = math.floor(value)
    return float(floor + 1 if value - floor >= 0.5 else floor)


def equals_to_precision(value: float, digits: int) -> bool:
    """``Number(value.toPrecision(digits)) === value``.

    JavaScript rounds exact ties up and Python rounds them to even; an exact tie
    has more than ``digits`` significant digits, so it fails either way.
    """
    return float(f'{value:.{digits - 1}e}') == value


def slice_utf16(text: str, end: int) -> str:
    """``text.slice(0, end)`` in UTF-16 code units; may leave a lone high surrogate."""
    data = text.encode('utf-16-le', errors='surrogatepass')[: 2 * end]
    return data.decode('utf-16-le', errors='surrogatepass')
