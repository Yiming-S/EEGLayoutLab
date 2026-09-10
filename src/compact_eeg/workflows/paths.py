"""Checkout defaults shared by App workflows; callers can pass an explicit root.

No cwd dependence and no automatic migration of scientific artifacts.
"""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
NATIVE_RUNTIME_RELATIVE = Path(".runtime/simnibs-4.6.0")
