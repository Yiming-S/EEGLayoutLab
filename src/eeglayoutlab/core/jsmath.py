"""V8 JavaScript numerics, string parsing and UAX #29 extended grapheme clusters (phase 3, U12).

Pure Python only (no ``numpy``, no ``json``):

- ``atan2``, ``acos``, ``sin`` and ``cos`` port V8's ``src/base/ieee754.cc`` (FDLIBM 5.3) bit for bit in IEEE-754
  binary64 arithmetic;
- ``to_fixed`` and ``to_precision`` follow ECMA-262 ``Number.prototype.toFixed`` and ``toPrecision`` (exact binary64
  value via ``Decimal.from_float``, ties away from zero, ``toFixed`` switching to ``Number::toString`` at ``1e21``);
- ``js_number`` implements ECMA-262 ``ToNumber`` on strings (``JS_TRIM`` whitespace, empty string -> ``0.0``,
  unsigned ``0x``/``0b``/``0o``, decimal with ``Infinity``, ``NaN`` otherwise);
- ``graphemes`` implements Unicode Standard Annex #29 extended grapheme cluster segmentation on ``unicodedata``.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
import math
import re
import struct
import unicodedata

from ..schemas.jsjson import JS_TRIM, js_trim, number_to_string

__all__ = [
    'JS_WHITESPACE_RE', 'ASCII_DIGITS_RE', 'js_number', 'to_fixed', 'to_precision', 'fixed_2',
    'atan2', 'acos', 'sin', 'cos', 'graphemes',
]

# JavaScript \s (WhiteSpace + LineTerminator) and \d (ASCII digits only).
JS_WHITESPACE_CHARS = ''.join(sorted(JS_TRIM))
JS_WHITESPACE_RE = re.compile(f'[{re.escape(JS_WHITESPACE_CHARS)}]+')
ASCII_DIGITS_RE = re.compile(r'^[0-9]+$')

_JS_DECIMAL_RE = re.compile(r'^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$')
_JS_HEX_RE = re.compile(r'^0[xX][0-9a-fA-F]+$')
_JS_BIN_RE = re.compile(r'^0[bB][01]+$')
_JS_OCT_RE = re.compile(r'^0[oO][0-7]+$')


def js_number(value: object) -> float:
    """ECMA-262 ``Number(value)`` for numbers, booleans, ``None`` and strings."""
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        try:
            return float(value)
        except OverflowError:
            return math.inf if value > 0 else -math.inf
    if not isinstance(value, str):
        return math.nan
    s = js_trim(value)
    if not s:
        return 0.0
    if s in ('Infinity', '+Infinity'):
        return math.inf
    if s == '-Infinity':
        return -math.inf
    if _JS_DECIMAL_RE.match(s):
        return float(s)
    if _JS_HEX_RE.match(s):
        return float(int(s[2:], 16))
    if _JS_BIN_RE.match(s):
        return float(int(s[2:], 2))
    if _JS_OCT_RE.match(s):
        return float(int(s[2:], 8))
    return math.nan


# --- Number.prototype.toFixed & toPrecision -----------------------------------

def to_fixed(value: float, digits: int = 0) -> str:
    """ECMA-262 ``Number.prototype.toFixed(digits)`` for ``0 <= digits <= 100``."""
    if not isinstance(digits, int) or isinstance(digits, bool) or not 0 <= digits <= 100:
        raise ValueError('toFixed() digits argument must be between 0 and 100')
    x = float(value)
    if math.isnan(x):
        return 'NaN'
    if abs(x) >= 1e21:
        return number_to_string(x)
    # ECMA-262: x is the mathematical real value R(value); R(-0) is 0, so (-0).toFixed(2) is "0.00",
    # whereas (-1e-5).toFixed(2) has x < 0 and produces "-0.00".
    sign = ''
    if x < 0.0:
        sign = '-'
        x = -x
    else:
        x = abs(x)  # normalize -0.0 to +0.0 so Decimal.from_float has positive sign
    d = Decimal.from_float(x)
    quant = Decimal(10) ** (-digits) if digits else Decimal(1)
    rounded = d.quantize(quant, rounding=ROUND_HALF_UP)
    return sign + f'{rounded:.{digits}f}'


def fixed_2(value: float) -> float:
    """``Number(value.toFixed(2))`` as used in SVG coordinate formatting."""
    return js_number(to_fixed(value, 2))


def to_precision(value: float, precision: int) -> str:
    """ECMA-262 ``Number.prototype.toPrecision(precision)`` for ``1 <= precision <= 100``."""
    if not isinstance(precision, int) or isinstance(precision, bool) or not 1 <= precision <= 100:
        raise ValueError('toPrecision() argument must be between 1 and 100')
    x = float(value)
    if math.isnan(x):
        return 'NaN'
    if math.isinf(x):
        return '-Infinity' if x < 0 else 'Infinity'
    if x == 0.0:
        return '0' if precision == 1 else '0.' + '0' * (precision - 1)
    sign = '-' if x < 0.0 else ''
    d = Decimal.from_float(abs(x))
    e = d.adjusted()
    scale = Decimal(10) ** (e - precision + 1)
    n = int((d / scale).to_integral_value(rounding=ROUND_HALF_UP))
    if n >= 10 ** precision:
        e += 1
        n = 10 ** (precision - 1)
    digits = str(n)
    if e < -6 or e >= precision:
        mantissa = digits[0] if precision == 1 else f'{digits[0]}.{digits[1:]}'
        return f"{sign}{mantissa}e{'+' if e >= 0 else '-'}{abs(e)}"
    if e == precision - 1:
        return sign + digits
    if e >= 0:
        return f'{sign}{digits[:e + 1]}.{digits[e + 1:]}'
    return f"{sign}0.{'0' * (-(e + 1))}{digits}"


# --- IEEE-754 binary64 word access & FDLIBM (V8 src/base/ieee754.cc) ----------

_PACK_D = struct.Struct('>d')
_PACK_II = struct.Struct('>II')


def _words(x: float) -> tuple[int, int]:
    return _PACK_II.unpack(_PACK_D.pack(float(x)))


def _from_words(hi: int, lo: int) -> float:
    return _PACK_D.unpack(_PACK_II.pack(hi & 0xFFFFFFFF, lo & 0xFFFFFFFF))[0]


def _set_lo(x: float, lo: int) -> float:
    hi, _ = _words(x)
    return _from_words(hi, lo)


def _set_hi(x: float, hi: int) -> float:
    _, lo = _words(x)
    return _from_words(hi, lo)


def _s32(u: int) -> int:
    u &= 0xFFFFFFFF
    return u - 0x100000000 if u & 0x80000000 else u


# FDLIBM atan / atan2 constants
_ATANHI = (
    4.63647609000806093515e-01,  # atan(0.5) hi
    7.85398163397448278999e-01,  # atan(1.0) hi
    9.82793723247329054082e-01,  # atan(1.5) hi
    1.57079632679489655800e+00,  # atan(inf) hi
)
_ATANLO = (
    2.26987774529616870924e-17,
    3.06161699786838301793e-17,
    1.39033110312309984516e-17,
    6.12323399573676603587e-17,
)
_AT = (
    3.33333333333329318027e-01,
    -1.99999999998764832476e-01,
    1.42857142725034663711e-01,
    -1.11111104054623557880e-01,
    9.09088713343650656196e-02,
    -7.69187620504482999495e-02,
    6.66107313738753120669e-02,
    -5.83357013379057348645e-02,
    4.97687799461593236017e-02,
    -3.65315727442169155270e-02,
    1.62858201153657823623e-02,
)
_PI_O_4 = 7.8539816339744827900e-01
_PI_O_2 = 1.5707963267948965580e+00
_PI = 3.1415926535897931160e+00
_PI_LO = 1.2246467991473531772e-16


def _atan(x: float) -> float:
    hx_u, lx = _words(x)
    hx = _s32(hx_u)
    ix = hx & 0x7FFFFFFF
    if ix >= 0x44100000:  # |x| >= 2^66 or NaN
        if ix > 0x7FF00000 or (ix == 0x7FF00000 and lx != 0):
            return x + x
        return (_ATANHI[3] + _ATANLO[3]) if hx > 0 else (-_ATANHI[3] - _ATANLO[3])
    if ix < 0x3FDC0000:  # |x| < 0.4375
        if ix < 0x3E200000:  # |x| < 2^-29
            return x
        ident = -1
    else:
        x = abs(x)
        if ix < 0x3FF30000:  # |x| < 1.1875
            if ix < 0x3FE60000:  # 7/16 <= |x| < 11/16
                ident = 0
                x = (2.0 * x - 1.0) / (2.0 + x)
            else:  # 11/16 <= |x| < 19/16
                ident = 1
                x = (x - 1.0) / (x + 1.0)
        else:
            if ix < 0x40038000:  # |x| < 2.4375
                ident = 2
                x = (x - 1.5) / (1.0 + 1.5 * x)
            else:  # 2.4375 <= |x| < 2^66
                ident = 3
                x = -1.0 / x
    z = x * x
    w = z * z
    s1 = z * (_AT[0] + w * (_AT[2] + w * (_AT[4] + w * (_AT[6] + w * (_AT[8] + w * _AT[10])))))
    s2 = w * (_AT[1] + w * (_AT[3] + w * (_AT[5] + w * (_AT[7] + w * _AT[9]))))
    if ident < 0:
        return x - x * (s1 + s2)
    z = _ATANHI[ident] - ((x * (s1 + s2) - _ATANLO[ident]) - x)
    return -z if hx < 0 else z


def atan2(y: float, x: float) -> float:
    """V8 ``Math.atan2(y, x)`` (FDLIBM ``__ieee754_atan2``)."""
    y = float(y)
    x = float(x)
    hx_u, lx = _words(x)
    hy_u, ly = _words(y)
    hx, hy = _s32(hx_u), _s32(hy_u)
    ix, iy = hx & 0x7FFFFFFF, hy & 0x7FFFFFFF
    if (ix | ((lx | (-lx & 0xFFFFFFFF)) >> 31)) > 0x7FF00000 or (iy | ((ly | (-ly & 0xFFFFFFFF)) >> 31)) > 0x7FF00000:
        return x + y
    if ((hx - 0x3FF00000) | lx) == 0:
        return _atan(y)
    m = ((hy >> 31) & 1) | ((hx >> 30) & 2)  # 2*sign(x) + sign(y)
    if (iy | ly) == 0:
        if m in (0, 1):
            return y
        return (_PI + 1e-300) if m == 2 else (-_PI - 1e-300)
    if (ix | lx) == 0:
        return -_PI_O_2 - 1e-300 if hy < 0 else _PI_O_2 + 1e-300
    if ix == 0x7FF00000:
        if iy == 0x7FF00000:
            if m == 0:
                return _PI_O_4 + 1e-300
            if m == 1:
                return -_PI_O_4 - 1e-300
            if m == 2:
                return 3.0 * _PI_O_4 + 1e-300
            return -3.0 * _PI_O_4 - 1e-300
        if m == 0:
            return 0.0
        if m == 1:
            return -0.0
        if m == 2:
            return _PI + 1e-300
        return -_PI - 1e-300
    if iy == 0x7FF00000:
        return -_PI_O_2 - 1e-300 if hy < 0 else _PI_O_2 + 1e-300
    k = (iy - ix) >> 20
    if k > 60:
        z = _PI_O_2 + 0.5 * _PI_LO
        m &= 1
    elif hx < 0 and k < -60:
        z = 0.0
    else:
        z = _atan(abs(y / x))
    if m == 0:
        return z
    if m == 1:
        return -z
    if m == 2:
        return _PI - (z - _PI_LO)
    return (z - _PI_LO) - _PI


# FDLIBM acos
_PIO2_HI = 1.57079632679489655800e+00
_PIO2_LO = 6.12323399573676603587e-17
_PS0 = 1.66666666666666657415e-01
_PS1 = -3.25565818622400915405e-01
_PS2 = 2.01212532134862925881e-01
_PS3 = -4.00555345006794114027e-02
_PS4 = 7.91534994289814532176e-04
_PS5 = 3.47933107596021167570e-05
_QS1 = -2.40339491173441421878e+00
_QS2 = 2.02094576023350569471e+00
_QS3 = -6.88283971605453293030e-01
_QS4 = 7.70381505559019352791e-02


def acos(x: float) -> float:
    """V8 ``Math.acos(x)`` (FDLIBM ``__ieee754_acos``)."""
    x = float(x)
    hx_u, lx = _words(x)
    hx = _s32(hx_u)
    ix = hx & 0x7FFFFFFF
    if ix >= 0x3FF00000:  # |x| >= 1
        if ((ix - 0x3FF00000) | lx) == 0:
            return 0.0 if hx > 0 else _PI + 2.0 * _PIO2_LO
        return math.nan
    if ix < 0x3FE00000:  # |x| < 0.5
        if ix <= 0x3C600000:  # |x| <= 2^-57
            return _PIO2_HI + _PIO2_LO
        z = x * x
        p = z * (_PS0 + z * (_PS1 + z * (_PS2 + z * (_PS3 + z * (_PS4 + z * _PS5)))))
        q = 1.0 + z * (_QS1 + z * (_QS2 + z * (_QS3 + z * _QS4)))
        r = p / q
        return _PIO2_HI - (x - (_PIO2_LO - x * r))
    if hx < 0:  # x < -0.5
        z = (1.0 + x) * 0.5
        p = z * (_PS0 + z * (_PS1 + z * (_PS2 + z * (_PS3 + z * (_PS4 + z * _PS5)))))
        q = 1.0 + z * (_QS1 + z * (_QS2 + z * (_QS3 + z * _QS4)))
        s = math.sqrt(z)
        r = p / q
        w = r * s - _PIO2_LO
        return _PI - 2.0 * (s + w)
    # x >= 0.5
    z = (1.0 - x) * 0.5
    s = math.sqrt(z)
    df = _set_lo(s, 0)
    c = (z - df * df) / (s + df)
    p = z * (_PS0 + z * (_PS1 + z * (_PS2 + z * (_PS3 + z * (_PS4 + z * _PS5)))))
    q = 1.0 + z * (_QS1 + z * (_QS2 + z * (_QS3 + z * _QS4)))
    r = p / q
    w = r * s + c
    return 2.0 * (df + w)


# FDLIBM __kernel_sin, __kernel_cos and medium-argument reduction (|x| < 2^19 * pi/2) + exact big-arg fallback
_S1 = -1.66666666666666324348e-01
_S2 = 8.33333333332248946124e-03
_S3 = -1.98412698298579493134e-04
_S4 = 2.75573137070700676789e-06
_S5 = -2.50507602534068634195e-08
_S6 = 1.58969099521155010221e-10

_C1 = 4.16666666666666019037e-02
_C2 = -1.38888888888741095749e-03
_C3 = 2.48015872894767294178e-05
_C4 = -2.75573143513906633035e-07
_C5 = 2.08757232129817482790e-09
_C6 = -1.13596475577881948265e-11

_INVPIO2 = 6.36619772367581382433e-01
_PIO2_1 = 1.57079632673412561417e+00
_PIO2_1T = 6.07710050650619224932e-11
_PIO2_2 = 6.07710050630396597660e-11
_PIO2_2T = 2.02226624879595063154e-21
_PIO2_3 = 2.02226624871116645580e-21
_PIO2_3T = 8.47842766036889956997e-32


def _kernel_sin(x: float, y: float, iy: int) -> float:
    hx_u, _ = _words(x)
    ix = hx_u & 0x7FFFFFFF
    if ix < 0x3E400000:  # |x| < 2^-27
        return x
    z = x * x
    v = z * x
    r = _S2 + z * (_S3 + z * (_S4 + z * (_S5 + z * _S6)))
    if iy == 0:
        return x + v * (_S1 + z * r)
    return x - ((z * (0.5 * y - v * r) - y) - v * _S1)


def _kernel_cos(x: float, y: float) -> float:
    hx_u, _ = _words(x)
    ix = hx_u & 0x7FFFFFFF
    if ix < 0x3E400000:  # |x| < 2^-27
        return 1.0
    z = x * x
    r = z * (_C1 + z * (_C2 + z * (_C3 + z * (_C4 + z * (_C5 + z * _C6)))))
    if ix < 0x3FD33333:  # |x| < 0.3
        return 1.0 - (0.5 * z - (z * r - x * y))
    if ix > 0x3FE90000:  # |x| > 0.78125
        qx = 0.28125
    else:
        qx = _from_words(ix - 0x00200000, 0)  # x / 4 with low word zeroed? Wait: in fdlibm qx = 0 for |x| <= 0.3, else x/4 hi!
        # Wait: in fdlibm k_cos.c: if ix > 0x3fe90000: qx = 0.28125 else INSERT_WORDS(qx, ix - 0x00200000, 0)!
    hz = 0.5 * z - qx
    a = 1.0 - qx
    return a - (hz - (z * r - x * y))


# High-precision 2/pi digits (1144 bits) for Payne-Hanek when |x| >= 2^19 * pi/2
_TWO_OVER_PI_HEX = (
    'a2f9836e4e441529fc2757d1f534ddc0db6295993c439041fe5163abdebbc561'
    'b7246e3a424dd2e006492eea09d1921cfe1deb1cb129a73ee88235f52ebb4484'
    'e99c7026b45f7e413991d639835339f49c845f8bbdf9283b1ff897ffde05980f'
    'ef2f118b5a0a6d1f6d367ecf27cb09b74f463f669e5fea2d7527bac7ebe5f17b'
    '3d0739f78a5292ea6bfb5fb11f8d5d0856033046fc7b6babf0cfbc209af4361d'
    'a9e391615ee61b086599855f14a068408dffd8804d73273106061556ca73a8c9'
)
_TWO_OVER_PI_INT = int(_TWO_OVER_PI_HEX, 16)
_TWO_OVER_PI_BITS = len(_TWO_OVER_PI_HEX) * 4


def _rem_pio2_large(x: float) -> tuple[int, float, float]:
    """Exact Payne-Hanek reduction mod pi/2 returning (n & 7, y0, y1) for |x| >= 2^19 * pi/2."""
    hx_u, lx = _words(abs(x))
    exp = ((hx_u >> 20) & 0x7FF) - 1023
    mant = ((1 << 52) | ((hx_u & 0xFFFFF) << 32) | lx)
    # x = mant * 2^(exp - 52); x * (2/pi) = mant * _TWO_OVER_PI_INT * 2^(exp - 52 - _TWO_OVER_PI_BITS)
    shift = _TWO_OVER_PI_BITS + 52 - exp
    prod = mant * _TWO_OVER_PI_INT
    # Round to nearest integer n:
    half = 1 << (shift - 1)
    n = (prod + half) >> shift
    rem = prod - (n << shift)  # signed in [-half, half)
    # Multiply rem * 2^(-shift) by pi/2 to 106+ bits:
    # pi/2 = pi * 2^-1; since 2/pi = _TWO_OVER_PI_INT * 2^(-_TWO_OVER_PI_BITS), use high-precision Decimal for pi/2:
    from decimal import localcontext
    with localcontext() as ctx:
        ctx.prec = 80
        pio2_dec = Decimal('1.5707963267948966192313216916397514420985846996875529104874722961539082031431044993')
        r_dec = (Decimal(rem) / Decimal(1 << shift)) * pio2_dec
        y0 = float(r_dec)
        y1 = float(r_dec - Decimal.from_float(y0))
    if x < 0:
        return (-n) & 7, -y0, -y1
    return n & 7, y0, y1


def _rem_pio2(x: float) -> tuple[int, float, float]:
    """FDLIBM ``__ieee754_rem_pio2``."""
    hx_u, lx = _words(x)
    hx = _s32(hx_u)
    ix = hx & 0x7FFFFFFF
    if ix <= 0x3FE921FB:  # |x| <= pi/4
        return 0, x, 0.0
    if ix < 0x4002D97C:  # |x| < 3*pi/4: special case n = +-1
        if hx > 0:
            z = x - _PIO2_1
            if ix != 0x3FF921FB:
                y0 = z - _PIO2_1T
                y1 = (z - y0) - _PIO2_1T
            else:
                z -= _PIO2_2
                y0 = z - _PIO2_2T
                y1 = (z - y0) - _PIO2_2T
            return 1, y0, y1
        z = x + _PIO2_1
        if ix != 0x3FF921FB:
            y0 = z + _PIO2_1T
            y1 = (z - y0) + _PIO2_1T
        else:
            z += _PIO2_2
            y0 = z + _PIO2_2T
            y1 = (z - y0) + _PIO2_2T
        return -1, y0, y1
    if ix <= 0x413921FB:  # |x| <= 2^19 * (pi/2), medium size
        t = abs(x)
        n = int(t * _INVPIO2 + 0.5)
        fn = float(n)
        r = t - fn * _PIO2_1
        w = fn * _PIO2_1T
        j = ix >> 20
        y0 = r - w
        i = j - ((_words(y0)[0] >> 20) & 0x7FF)
        if i > 16:
            t = r
            w = fn * _PIO2_2
            r = t - w
            w = fn * _PIO2_2T - ((t - r) - w)
            y0 = r - w
            i = j - ((_words(y0)[0] >> 20) & 0x7FF)
            if i > 49:
                t = r
                w = fn * _PIO2_3
                r = t - w
                w = fn * _PIO2_3T - ((t - r) - w)
                y0 = r - w
        y1 = (r - y0) - w
        if hx < 0:
            return -n, -y0, -y1
        return n, y0, y1
    return _rem_pio2_large(x)


def sin(x: float) -> float:
    """V8 ``Math.sin(x)`` (FDLIBM ``sin``)."""
    x = float(x)
    hx_u, _ = _words(x)
    ix = hx_u & 0x7FFFFFFF
    if ix <= 0x3FE921FB:
        return _kernel_sin(x, 0.0, 0)
    if ix >= 0x7FF00000:
        return x - x
    n, y0, y1 = _rem_pio2(x)
    q = n & 3
    if q == 0:
        return _kernel_sin(y0, y1, 1)
    if q == 1:
        return _kernel_cos(y0, y1)
    if q == 2:
        return -_kernel_sin(y0, y1, 1)
    return -_kernel_cos(y0, y1)


def cos(x: float) -> float:
    """V8 ``Math.cos(x)`` (FDLIBM ``cos``)."""
    x = float(x)
    hx_u, _ = _words(x)
    ix = hx_u & 0x7FFFFFFF
    if ix <= 0x3FE921FB:
        return _kernel_cos(x, 0.0)
    if ix >= 0x7FF00000:
        return x - x
    n, y0, y1 = _rem_pio2(x)
    q = n & 3
    if q == 0:
        return _kernel_cos(y0, y1)
    if q == 1:
        return -_kernel_sin(y0, y1, 1)
    if q == 2:
        return -_kernel_cos(y0, y1)
    return _kernel_sin(y0, y1, 1)


# --- UAX #29 Extended Grapheme Clusters ---------------------------------------

def _gcb(cp: int) -> str:
    """ Grapheme_Cluster_Break property derived from Unicode Character Database in ``unicodedata``."""
    if cp == 0x000D:
        return 'CR'
    if cp == 0x000A:
        return 'LF'
    if cp == 0x200D:
        return 'ZWJ'
    if cp == 0x200C:
        return 'Extend'
    if 0x1F1E6 <= cp <= 0x1F1FF:
        return 'RI'
    # Hangul syllable / jamo classes (GB6-GB8)
    if 0x1100 <= cp <= 0x115F or 0xA960 <= cp <= 0xA97C:
        return 'L'
    if 0x1160 <= cp <= 0x11A7 or 0xD7B0 <= cp <= 0xD7C6:
        return 'V'
    if 0x11A8 <= cp <= 0x11FF or 0xD7CB <= cp <= 0xD7FB:
        return 'T'
    if 0xAC00 <= cp <= 0xD7A3:
        return 'LV' if (cp - 0xAC00) % 28 == 0 else 'LVT'
    # Emoji skin-tone modifiers and tags are Extend in UAX #29
    if 0x1F3FB <= cp <= 0x1F3FF or 0xE0020 <= cp <= 0xE007F or cp in (0xFF9E, 0xFF9F):
        return 'Extend'
    cat = unicodedata.category(chr(cp))
    if cat in ('Cc', 'Cf') or cp in (0x2028, 0x2029):
        # Prepend characters in Cf (Arabic/Brahmi number signs)
        if cp in (0x0600, 0x0601, 0x0602, 0x0603, 0x0604, 0x0605, 0x06DD, 0x070F, 0x0890, 0x0891, 0x08E2, 0x110BD, 0x110CD):
            return 'Prepend'
        return 'Control'
    if cat in ('Mn', 'Me'):
        return 'Extend'
    if cat == 'Mc':
        return 'SpacingMark'
    return 'Other'


def _is_extended_pictographic(cp: int) -> bool:
    """Extended_Pictographic range check for GB11 (Emoji ZWJ sequences)."""
    return (
        0x1F300 <= cp <= 0x1FAFF
        or 0x2600 <= cp <= 0x27BF
        or 0x1F000 <= cp <= 0x1F2FF
        or cp in (0x00A9, 0x00AE, 0x203C, 0x2049, 0x2122, 0x2139, 0x231A, 0x231B, 0x2328, 0x23CF)
        or 0x23E9 <= cp <= 0x23FA
        or 0x25AA <= cp <= 0x25FE
        or 0x2934 <= cp <= 0x2935
        or 0x2B05 <= cp <= 0x2B55
        or cp in (0x3030, 0x303D, 0x3297, 0x3299)
    )


def graphemes(text: str) -> list[str]:
    """Segments ``text`` into UAX #29 extended grapheme clusters (matching ``Intl.Segmenter``)."""
    if not text:
        return []
    n = len(text)
    cps = [ord(ch) for ch in text]
    props = [_gcb(cp) for cp in cps]
    pics = [_is_extended_pictographic(cp) for cp in cps]
    clusters: list[str] = []
    start = 0
    ri_run = 1 if props[0] == 'RI' else 0
    # Track GB11 state: saw Extended_Pictographic followed only by Extend*, then ZWJ
    ep_chain = pics[0]

    for i in range(1, n):
        prev_p, curr_p = props[i - 1], props[i]
        no_break = False
        # GB3: CR x LF
        if prev_p == 'CR' and curr_p == 'LF':
            no_break = True
        # GB4, GB5: (Control|CR|LF) ÷ and ÷ (Control|CR|LF)
        elif prev_p in ('Control', 'CR', 'LF') or curr_p in ('Control', 'CR', 'LF'):
            no_break = False
        # GB6-GB8: Hangul
        elif prev_p == 'L' and curr_p in ('L', 'V', 'LV', 'LVT'):
            no_break = True
        elif prev_p in ('LV', 'V') and curr_p in ('V', 'T'):
            no_break = True
        elif prev_p in ('LVT', 'T') and curr_p == 'T':
            no_break = True
        # GB9: x (Extend | ZWJ)
        elif curr_p in ('Extend', 'ZWJ'):
            no_break = True
        # GB9a: x SpacingMark
        elif curr_p == 'SpacingMark':
            no_break = True
        # GB9b: Prepend x
        elif prev_p == 'Prepend':
            no_break = True
        # GB11: \p{Extended_Pictographic} Extend* ZWJ x \p{Extended_Pictographic}
        elif prev_p == 'ZWJ' and ep_chain and pics[i]:
            no_break = True
        # GB12, GB13: RI x RI (pairs only)
        elif prev_p == 'RI' and curr_p == 'RI' and (ri_run % 2 == 1):
            no_break = True

        if not no_break:
            clusters.append(text[start:i])
            start = i
            ri_run = 1 if curr_p == 'RI' else 0
            ep_chain = pics[i]
        else:
            if curr_p == 'RI':
                ri_run += 1
            else:
                ri_run = 0
            if pics[i]:
                ep_chain = True
            elif curr_p not in ('Extend', 'ZWJ'):
                ep_chain = False

    clusters.append(text[start:])
    return clusters
