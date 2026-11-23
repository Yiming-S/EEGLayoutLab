"""Field types with JavaScript value semantics.

Pydantic's lax mode coerces ``True`` to ``1`` (also for ``Literal[1]``) and
``"3"`` to ``3``; strict mode rejects ``3.0`` for ``int``. Node accepts exactly
``typeof v === 'number'`` values, with ``3.0 === 3``. These before-validators
reproduce that and hand Pydantic a canonical Python value, so the generated
JSON Schema still says ``number`` or ``integer``.
"""
from __future__ import annotations

from typing import Annotated, Any

from pydantic import BeforeValidator, Field

from . import jsjson


def js_number(value: Any) -> float:
    if not jsjson.is_number(value):
        raise ValueError('must be a JSON number')
    return jsjson.to_number(value)


def js_integer(value: Any) -> int:
    if not jsjson.is_integer(value):
        raise ValueError('must be an integer')
    return int(jsjson.to_number(value))


def js_integer_or_none(value: Any) -> int | None:
    return None if value is None else js_integer(value)


def empty_as_absent(value: Any) -> Any:
    """``undefined``, ``null`` and ``''`` mean the default choice."""
    return None if value is None or (isinstance(value, str) and value == '') else value


def number(**constraints: float) -> Any:
    """Finite double (``Number.isFinite``). Constraints sit inside the before-validator so they reach the JSON Schema."""
    return Annotated[float, Field(strict=True, allow_inf_nan=False, **constraints), BeforeValidator(js_number)]


def integer(**constraints: int) -> Any:
    """``Number.isInteger``: 3.0 is accepted and becomes 3; true and "3" are rejected."""
    return Annotated[int, Field(strict=True, **constraints), BeforeValidator(js_integer)]


JsNumber = number()
JsInteger = integer()
