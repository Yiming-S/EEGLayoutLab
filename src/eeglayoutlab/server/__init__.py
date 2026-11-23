"""Local HTTP service (design 0001, decision 6).

``app.create_app`` builds the service of one process: ``access`` (guard, session cookie, CSRF token) on every
request, then the API (``routes``) or the static interface (``static``). ``workspace`` holds the per-workspace
marker, lock and runtime file; ``openapi`` writes the API document. ``eeglayoutlab serve`` (``cli.main``) runs it.
"""
