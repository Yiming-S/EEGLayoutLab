# Schema parity (phase 0c spike)

Checks that `src/eeglayoutlab/schemas` reproduces Node's `normalizeDesignRequest`
byte for byte ([design 0001](../../docs/design/0001-local-first-architecture.md), decision 4).

- `design_variants.mjs` runs the real Node normalizer (and the `design-submission/1`
  envelope) over the shared fixtures and about 1,300 generated request texts, and records
  JavaScript number spelling, `Math.hypot`, `toPrecision(4)` and `Math.round` on sampled
  doubles. `tests/test_schema_design_parity.py` and `tests/test_schema_spike_app.py` run it
  and compare. Both skip without Pydantic/FastAPI, so the native runtime suite is unchanged.
- `generated/openapi.json` is written by `python -m eeglayoutlab.server.spike`;
  `generated/openapi.d.ts` by `openapi-typescript generated/openapi.json --default-non-nullable false`
  (7.13).
- `design-submission.typecheck.ts` type-checks `designSubmission` from `webapp/lib/design-decision.ts`
  against the generated types. Each `@ts-expect-error` records a current mismatch.

Run from the repository root, with Python 3.11 and `pydantic fastapi httpx pytest` in a separate
environment (not `.runtime/`):

```sh
python -B -m pytest -q -p no:cacheprovider tests/test_schema_design_parity.py tests/test_schema_spike_app.py
node webapp/node_modules/typescript/bin/tsc -p tests/schema_parity/tsconfig.json
```
