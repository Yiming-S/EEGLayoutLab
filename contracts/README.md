# Shared data contracts

Versioned wire definitions and test fixtures belong here. They do not import the
web framework, Three.js, the Node server, or Python workflows.

`layout.ts` defines browser-safe layout types. The current request formats and
their compatibility rules are documented in [API formats](api-formats.md).
The executable fixtures in [requests.json](fixtures/requests.json) are consumed
by both `webapp/scripts/check-api-contracts.mjs` and `tests/test_api_contracts.py`.

The existing service and Python validators remain authoritative. Request
fixtures assert the HTTP normalizer's exact canonical JSON and the Python
validator's result for that canonical request. These can intentionally differ:
the radius worker adds an empty `mask_codes` array for a free-domain request,
while the HTTP representation omits it.

## Generated request types

The request formats are being moved to one definition in the Python package
`eeglayoutlab.schemas` ([design 0001](../docs/design/0001-local-first-architecture.md),
decision 4). Every format in `eeglayoutlab.schemas.registry` reproduces the Node
normalizer exactly; the tests in [`tests/schema_parity`](../tests/schema_parity/README.md)
compare them on generated variants and, for design evaluation and the radius search,
also on the shared fixtures. The radius search (`radius-search`) also reproduces
Node's rejection messages (`eeglayoutlab.schemas.radius_search.normalize_request`).
The Node host remains in service until phase 4.

[`generated/openapi.json`](generated/openapi.json) is written from those schemas, and
[`generated/openapi.d.ts`](generated/openapi.d.ts) from that document. Do not edit
either file. After changing a schema, regenerate both from the repository root:

```sh
python -m eeglayoutlab.server.openapi contracts/generated/openapi.json
cd webapp && npm run generate:api-types
```

`tests/test_schema_service.py` and `webapp/scripts/check-api-types.mjs` fail while
either file is out of date. The interface imports the request types through
`webapp/lib/api-types.ts`, and the coordinate-source types through
`webapp/contracts/coordinate-source.ts`.

The document describes the canonical form of each request, which the interface
sends. The service also accepts the spellings Node accepts for a default value
(`''` for `conductivity_scenario` and `head_id`, `false` or `''` for `robustness`,
any value for `design.name`, where a non-string means the default name; in a radius
search, `null` or `{"kind": "iid"}` for `noise_model`, `null` for `data_prior` and
an empty `mask_codes` in a free mode), so a request can be valid for the service
without being valid for the document.

## Changing a format

To change a wire format, state its compatibility/version policy and update the
shared valid and invalid examples. Keep scientific input and result checks at
their existing boundaries. Numerical protocol changes require separate
scientific identity and regression review.
