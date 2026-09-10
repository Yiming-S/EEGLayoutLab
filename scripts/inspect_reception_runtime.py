"""Read-only runtime digest shared with native forward cache identity (no FEM)."""
import json
from reception_forward_provider import _json_sha, _native_runtime_identity

if __name__ == '__main__':
    identity = _native_runtime_identity()
    print(json.dumps({'schema': 'reception-runtime-digest/1', 'sha256': _json_sha(identity)}))
