"""Core definitions for the fixed-64 compact-region EEG study."""

from .protocol import (
    REGION_COUNTS,
    TOTAL_ELECTRODES,
    balanced_allocation,
    load_protocol,
    validate_protocol,
)

__all__ = [
    "REGION_COUNTS",
    "TOTAL_ELECTRODES",
    "balanced_allocation",
    "load_protocol",
    "validate_protocol",
]
