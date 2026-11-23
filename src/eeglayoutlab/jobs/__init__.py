"""Scientific identity, record store and job queue of the local service (design 0001, phase 2); no HTTP.

Request keys must equal the Node host's on the same installation, so these modules port Node's code line by
line: ``nodepath`` (``path.posix``), ``nodefs`` (``fs`` real paths and names), ``runtime`` (root and interpreter
strings), ``integrity`` (file digests), ``fingerprint`` (the interpreter identity off macOS) and ``identity`` (the
design-evaluation identity and key).
Every hashed or stored JSON value goes through ``eeglayoutlab.schemas.jsjson``, never Python's ``json``.
"""
