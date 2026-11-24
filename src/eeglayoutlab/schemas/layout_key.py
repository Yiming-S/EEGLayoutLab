"""A layout's key (design 0004, section 2), mirroring ``webapp/contracts/layout-key.mjs``.

The SHA-256 of ``JSON.stringify({xyz_mm, region_indices})``: the Ernie-native millimetre coordinates and region
indices of ``eeg-electrode-design/1``. It is derived for listing, never stored in a record, and enters no scientific
identity.
"""
from __future__ import annotations

from typing import Any

from . import jsjson


def layout_key(xyz_mm: Any, region_indices: Any) -> str:
    """``createHash('sha256').update(layoutKeyText(xyzMm, regionIndices)).digest('hex')``."""
    return jsjson.sha256_hex({'xyz_mm': xyz_mm, 'region_indices': region_indices})
