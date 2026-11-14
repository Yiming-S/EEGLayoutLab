# Shared data contracts

Versioned wire definitions and test fixtures belong here. They do not import the
web framework, Three.js, the Node server, or Python workflows.

`layout.ts` defines browser-safe layout types. The current request formats and
their compatibility rules are documented in [API formats](api-formats.md).
The executable fixtures in [requests.json](fixtures/requests.json) are consumed
by both `webapp/scripts/check-api-contracts.mjs` and `tests/test_api_contracts.py`.

The existing service and Python validators remain authoritative. No schema
generator or new runtime validation dependency is introduced by this extraction.
Request fixtures assert the HTTP normalizer's exact canonical JSON and the
Python validator's result for that canonical request. These can intentionally
differ: the radius worker adds an empty `mask_codes` array for a free-domain
request, while the HTTP representation omits it.

To change a wire format, state its compatibility/version policy and update the
shared valid and invalid examples. Keep scientific input and result checks at
their existing boundaries. Numerical protocol changes require separate
scientific identity and regression review.
