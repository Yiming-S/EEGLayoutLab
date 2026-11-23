"""EEGLayoutLab application package: request schemas and the local service (docs/design/0001-local-first-architecture.md).

The science code stays in ``compact_eeg`` until 1.0 (design 0001, decision 3).
"""

API_VERSION = '1'
"""Sent as ``X-EEG-API-Version`` and recorded in the OpenAPI document, as by the Node host."""
