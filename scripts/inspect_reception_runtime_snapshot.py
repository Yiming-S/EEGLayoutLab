#!/usr/bin/env python3
"""Read-only host snapshot; the legacy runtime inspector stays unchanged."""
import json

from runtime_identity_watch import inspect_snapshot

if __name__ == "__main__":
    print(json.dumps(inspect_snapshot(), separators=(",", ":")))
