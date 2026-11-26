"""JavaScript JSON and number semantics needed to reproduce Node request keys byte for byte.

Node computes cache keys as SHA-256 of ``JSON.stringify(...)`` over values from
``JSON.parse``. Python's ``json`` differs in number spelling (``1.0`` vs ``1``,
``1e-07`` vs ``1e-7``, ``-0.0`` vs ``0``), accepts ``NaN``/``Infinity``, keeps
integers exact, keeps integer-like keys in insertion order, and slices strings by
code point rather than UTF-16 unit. The functions here follow ECMA-262 instead.
"""
from __future__ import annotations

import hashlib
import json
from json.decoder import scanstring
import math
import re
from decimal import Decimal
from typing import Any

__all__ = [
    'JSONSyntaxError', 'parse', 'stringify', 'sha256_hex', 'number_to_string', 'is_array_index',
    'is_number', 'to_number', 'is_integer', 'hypot', 'round_half_up',
    'equals_to_precision', 'slice_utf16', 'JS_TRIM', 'js_trim',
]


# --- JSON.parse -------------------------------------------------------------

class JSONSyntaxError(ValueError):
    """Text that ``JSON.parse`` refuses with a ``SyntaxError``. The message is Python's, not V8's."""

    name = 'SyntaxError'


def _reject_constant(name: str) -> Any:
    raise ValueError(f'JSON.parse rejects {name}')


def parse(text: str) -> Any:
    """``JSON.parse(text)``: every number is an IEEE double; NaN/Infinity literals are rejected.

    ``parse_int=float`` mirrors JavaScript, where ``2026`` and ``2026.0`` are the
    same value, and avoids Python's 4300-digit integer limit. A leading BOM is
    rejected by both parsers. Text that is not JSON raises ``JSONSyntaxError`` (a ``ValueError``).
    """
    if not isinstance(text, str):
        raise TypeError('parse expects str; decode bytes first')
    try:
        try:
            return json.loads(text, parse_constant=_reject_constant, parse_int=float)
        except RecursionError:
            # V8 parses any nesting depth; Python's scanner stops near the recursion limit (about 1,000 levels on
            # 3.11). Node ignores unknown design fields, so a deeply nested one can sit in an accepted request.
            return _parse_iterative(text)
    except JSONSyntaxError:
        raise
    except ValueError as error:
        raise JSONSyntaxError(str(error)) from None


_JSON_WHITESPACE = ' \t\n\r'
# ASCII digits only: JSON.parse, like Python's C scanner, rejects other Unicode digits.
_JSON_NUMBER = re.compile(r'-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][-+]?[0-9]+)?')


def _skip(text: str, index: int) -> int:
    while index < len(text) and text[index] in _JSON_WHITESPACE:
        index += 1
    return index


def _key(text: str, index: int) -> tuple[str, int]:
    if not text.startswith('"', index):
        raise ValueError(f'JSON.parse expects a property name at {index}')
    key, index = scanstring(text, index + 1, True)
    index = _skip(text, index)
    if not text.startswith(':', index):
        raise ValueError(f'JSON.parse expects ":" at {index}')
    return key, _skip(text, index + 1)


def _parse_iterative(text: str) -> Any:
    """``JSON.parse`` without recursion, with the same results as the ``json.loads`` call in ``parse``."""
    stack: list[list[Any]] = []  # open containers: [list] or [dict, pending key]
    index = _skip(text, 0)
    while True:
        if index >= len(text):
            raise ValueError('JSON.parse: unexpected end of input')
        char = text[index]
        if char in '[{':
            index = _skip(text, index + 1)
            if text.startswith(']' if char == '[' else '}', index):
                value, index = ([] if char == '[' else {}), index + 1
            elif char == '[':
                stack.append([[]])
                continue
            else:
                key, index = _key(text, index)
                stack.append([{}, key])
                continue
        elif char == '"':
            value, index = scanstring(text, index + 1, True)
        elif match := _JSON_NUMBER.match(text, index):
            value, index = float(match.group()), match.end()
        elif text.startswith('true', index):
            value, index = True, index + 4
        elif text.startswith('false', index):
            value, index = False, index + 5
        elif text.startswith('null', index):
            value, index = None, index + 4
        else:
            raise ValueError(f'JSON.parse: unexpected character at {index}')
        # Attach the value to the open containers, closing every one that ends here.
        while True:
            index = _skip(text, index)
            if not stack:
                if index != len(text):
                    raise ValueError(f'JSON.parse: unexpected data at {index}')
                return value
            frame = stack[-1]
            container = frame[0]
            if isinstance(container, dict):
                container[frame[1]] = value  # a repeated key keeps its first position and takes the last value
                closing = '}'
            else:
                container.append(value)
                closing = ']'
            if text.startswith(',', index):
                index = _skip(text, index + 1)
                if isinstance(container, dict):
                    frame[1], index = _key(text, index)
                break
            if not text.startswith(closing, index):
                raise ValueError(f'JSON.parse expects "," or "{closing}" at {index}')
            stack.pop()
            value, index = container, index + 1


def decode_body(body: bytes) -> str:
    """Node's ``Buffer.toString()`` of a whole body: UTF-8 with U+FFFD replacement, BOM kept."""
    return body.decode('utf-8', errors='replace')


# --- String.prototype.trim ----------------------------------------------------

# ECMAScript WhiteSpace and LineTerminator, which String.prototype.trim removes.
# Python's str.strip differs: it removes U+0085 and U+001C-U+001F but keeps U+FEFF.
JS_TRIM = frozenset('\t\n\x0b\x0c\r \xa0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a'
                    '\u2028\u2029\u202f\u205f\u3000\ufeff')


def js_trim(text: str) -> str:
    """``text.trim()``."""
    start, end = 0, len(text)
    while start < end and text[start] in JS_TRIM:
        start += 1
    while end > start and text[end - 1] in JS_TRIM:
        end -= 1
    return text[start:end]


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


_MAX_ARRAY_INDEX = 2**32 - 2


def is_array_index(key: str) -> bool:
    """ECMA-262 array index: the canonical decimal string of an integer from 0 to 2**32 - 2.

    ``"0"`` and ``"17"`` are indices; ``"01"``, ``"-1"``, ``"1.5"``, ``"4294967295"`` and non-ASCII digits
    such as ``"²"`` or ``"٣"`` are ordinary keys.
    """
    # The length test comes first: 2**32 - 2 has 10 digits, and int() refuses more than 4300.
    return (0 < len(key) <= 10 and key.isascii() and key.isdigit() and (key == '0' or key[0] != '0')
            and int(key) <= _MAX_ARRAY_INDEX)


def _own_keys(value: dict) -> list[str]:
    """OrdinaryOwnPropertyKeys: array indices in ascending numeric order, then the other keys in insertion order."""
    for key in value:
        if not isinstance(key, str):
            raise TypeError('object keys must be strings')
    indices = sorted((key for key in value if is_array_index(key)), key=int)
    if not indices:
        return list(value)
    return indices + [key for key in value if not is_array_index(key)]


def stringify(value: Any) -> str:
    """``JSON.stringify(value)`` for JSON data: JavaScript own-key order, no whitespace, JS numbers.

    Keys are written in V8's order for ordinary objects (ECMA-262 OrdinaryOwnPropertyKeys): array-index keys
    (``is_array_index``) first in ascending numeric order, then every other key in insertion order. This is
    the order ``JSON.parse`` gives an object, so ``stringify(parse(text))`` equals Node's
    ``JSON.stringify(JSON.parse(text))``; worker results with keys such as ``"1"`` and ``"-1"`` hash as in Node.

    Absent optional fields must be left out of the dict by the caller, as Node
    builds objects with conditional spreads; ``None`` is serialized as ``null``.

    It does not recurse, so like V8 it writes any nesting depth that ``parse`` accepts.
    """
    if not isinstance(value, (list, tuple, dict)):
        return _scalar(value)
    out: list[str] = []
    # Open containers: [iterator of (prefix, child), closing bracket, nothing written yet, id(container)].
    stack: list[list[Any]] = []
    open_ids: set[int] = set()
    child = value
    while True:
        if isinstance(child, dict):
            cid = id(child)
            if cid in open_ids:
                raise TypeError('Converting circular structure to JSON')
            open_ids.add(cid)
            out.append('{')
            stack.append([_members(child), '}', True, cid])
        elif isinstance(child, (list, tuple)):
            cid = id(child)
            if cid in open_ids:
                raise TypeError('Converting circular structure to JSON')
            open_ids.add(cid)
            out.append('[')
            stack.append([_items(child), ']', True, cid])
        else:
            out.append(_scalar(child))
        while stack:
            frame = stack[-1]
            entry = next(frame[0], None)
            if entry is None:
                out.append(frame[1])
                open_ids.discard(frame[3])
                stack.pop()
                continue
            if frame[2]:
                frame[2] = False
            else:
                out.append(',')
            out.append(entry[0])
            child = entry[1]
            break
        else:
            return ''.join(out)


def _members(value: dict):
    keys = _own_keys(value)  # checked before anything of the object is written
    return ((quote(key) + ':', value[key]) for key in keys)


def _items(value):
    return (('', item) for item in value)


def _scalar(value: Any) -> str:
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
