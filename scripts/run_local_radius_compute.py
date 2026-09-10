#!/usr/bin/env python3
"""Read one local radius-design request from stdin and emit NDJSON, without files."""
from __future__ import annotations
import json
import os
from pathlib import Path
import sys
import time

for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[name] = "2"
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from threadpoolctl import threadpool_limits
from compact_eeg.local_radius_compute import LocalRadiusComputer, validate_request


def emit(value):
    print(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")), flush=True)


def main():
    started = time.perf_counter()
    try:
        payload = sys.stdin.read(8193)
        if len(payload) > 8192:
            raise ValueError("Request exceeds 8192 characters")
        request = validate_request(json.loads(payload))
    except (ValueError, TypeError) as error:
        emit({"type": "error", "code": "invalid_request", "message": str(error)})
        return 2
    def progress(**values):
        emit({"type": "progress", **values})
    try:
        with threadpool_limits(limits=2):
            computer = LocalRadiusComputer(ROOT, progress)
            result = computer.compute(request, progress)
        result["total_elapsed_seconds"] = time.perf_counter() - started
        progress(stage="completed", message="本地计算完成" if result["status"] == "completed" else "本次预算未构造出完整布局", progress=1.)
        emit({"type": "result", "result": result})
        return 0
    except Exception as error:
        emit({"type": "error", "code": "compute_error", "message": str(error)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
