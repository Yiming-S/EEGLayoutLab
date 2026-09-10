#!/usr/bin/env python3
"""Compatibility entry point; implementation: compact_eeg.workflows.design_evaluation."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from compact_eeg.workflows import design_evaluation as _implementation

# Normal legacy imports share module identity, including private helpers and mocks.
def __getattr__(name):
    return getattr(_implementation, name)

def __dir__():
    return dir(_implementation)

if __name__ == '__main__':
    raise SystemExit(_implementation.main())
sys.modules[__name__] = _implementation
