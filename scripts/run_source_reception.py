#!/usr/bin/env python3
"""One bounded source/reception job; progress on stdout, result in output JSON."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

for _key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_key] = "2"
sys.dont_write_bytecode = True

from threadpoolctl import threadpool_limits
from source_reception import run_experiment


def emit(**data):
    print(json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", required=True, type=Path)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    started = time.perf_counter()
    try:
        if args.request.stat().st_size > 2 * 1024 * 1024:
            raise ValueError("Request JSON exceeds the 2 MiB resolved-record bound")
        if args.output.exists():
            raise ValueError("Output already exists; existing experiment results are not overwritten")
        payload = json.loads(args.request.read_text())
        with threadpool_limits(limits=2):
            result = run_experiment(args.repository_root, payload, lambda **v: emit(type="progress", **v))
        result["elapsed_seconds"] = time.perf_counter() - started
        encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
        if len(encoded) > 16 * 1024 * 1024:
            raise ValueError("Result exceeds the 16 MiB waveform-response bound")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation preserves previously completed results on retries.
        with args.output.open("xb") as stream:
            stream.write(encoded)
        emit(type="progress", stage="completed", message="源—接收对照计算完成", progress=1.)
        emit(type="result", status="completed", output=str(args.output), output_bytes=len(encoded), elapsed_seconds=result["elapsed_seconds"])
        return 0
    except (Exception,) as error:
        emit(type="error", code="source_reception_error", message=str(error))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
