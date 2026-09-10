#!/usr/bin/env python3
"""Bounded v2 reception job, or read-only frozen source catalog."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

for _key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_key] = "1"
sys.dont_write_bytecode = True

from threadpoolctl import threadpool_limits
from source_reception_v2 import get_source_catalog, run_experiment


def emit(**value):
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", required=True, type=Path)
    parser.add_argument("--catalog", action="store_true")
    parser.add_argument("--request", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    started = time.perf_counter()
    try:
        if args.catalog:
            if args.request is not None or args.output is not None:
                raise ValueError("--catalog is read-only and cannot be combined with --request or --output")
            with threadpool_limits(limits=1):
                catalog = get_source_catalog(args.repository_root)
            encoded = json.dumps(catalog, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            if len(encoded.encode()) > 1024 * 1024:
                raise ValueError("Catalog exceeds the 1 MiB response bound")
            print(encoded, flush=True)
            return 0
        if args.request is None or args.output is None:
            raise ValueError("A simulation requires --request and --output")
        if args.request.stat().st_size > 2 * 1024 * 1024:
            raise ValueError("Request exceeds the 2 MiB resolved-record bound")
        if args.output.exists():
            raise ValueError("Output already exists; completed experiment results are never overwritten")
        payload = json.loads(args.request.read_text())
        with threadpool_limits(limits=1):
            result = run_experiment(args.repository_root, payload, lambda **value: emit(type="progress", **value))
        result["elapsed_seconds"] = time.perf_counter() - started
        encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
        if len(encoded) > 16 * 1024 * 1024:
            raise ValueError("Result exceeds the 16 MiB response bound")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("xb") as stream:
            stream.write(encoded)
        emit(type="progress", stage="completed", message="固定皮层法向源实验已完成", progress=1.)
        emit(type="result", status="completed", output=str(args.output), output_bytes=len(encoded), elapsed_seconds=result["elapsed_seconds"])
        return 0
    except Exception as error:
        emit(type="error", code="source_reception_v2_error", message=str(error))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
