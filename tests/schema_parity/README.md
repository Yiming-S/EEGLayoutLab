# Schema parity

Checks that every request format in `eeglayoutlab.schemas.registry` gives exactly the outcome of the Node
normalizer it replaces ([design 0001](../../docs/design/0001-local-first-architecture.md), decision 4):
the same parse result, the same acceptance and the same canonical bytes.

- `generate.mjs` imports one module per format from `formats/`, runs Node's own normalizer over that
  module's variants and writes the corpus. It also writes the reference corpora of `reference.mjs`:
  - `numbers`, `hypot`, `precision` and `round2`: JavaScript number spelling, `Math.hypot`, `toPrecision(4)` and
    `Math.round` on sampled doubles;
  - `keyorder`: `[text, JSON.stringify(JSON.parse(text))]` pairs, whose keys mix array indices (`"0"` to
    `"4294967294"`, which V8 writes first in ascending order) and ordinary keys (`"01"`, `"-1"`, `"1.5"`,
    non-ASCII digits, duplicates, a digit key longer than Python's 4300-digit `int()` limit), fixed and random,
    and texts nested 2,000 and 3,000 levels deep;
  - `paths`: `path.posix` `join`, `dirname`, `resolve`, `relative` and `normalize` on generated paths with dot
    segments, repeated and trailing slashes, absolute parts, empty strings and a leading `//`. `resolve` gets
    an absolute cwd as its first argument; `relative` resolves relative arguments against the recorded `cwd`.
- `tests/test_schema_parity.py` compares the Python schemas with the corpus; `tests/test_schema_service.py`
  sends the same bodies through the FastAPI service and checks the transport rules.
- `tests/service/test_jsjson_order.py` checks `jsjson.stringify` against `keyorder`, and
  `tests/service/test_nodepath.py` checks `eeglayoutlab.jobs.nodepath` against `paths`. The design-evaluation
  variants accepted here are also the requests of the key parity test ([tests/service](../service/README.md)).
- The tests skip without Pydantic, FastAPI, httpx or Node, so the native runtime suite runs unchanged.
  With `EEG_REQUIRE_SCHEMA_PARITY=1`, as in CI, a missing dependency fails the run instead.

## Adding a format

1. Define the schema in `src/eeglayoutlab/schemas/` with the JavaScript rules of `jsjson` and `types`, and an
   explicit canonical form in Node's key order.
2. Add it to `REQUEST_FORMATS` in `registry.py`.
3. Add `formats/<name>.mjs` exporting `name`, `normalize` (the Node functions, unchanged) and `variants`, and
   import it in `generate.mjs`. Cover each rule at and around its bounds, number spellings, UTF-16 strings,
   missing and extra keys, and random combinations. The shared fixtures alone miss most rule errors. Build the
   variants for a list of allowed values from Node's list, and export the lists as `options` so that
   `test_option_lists_match_node` compares them with the Python schema. A normalizer that throws a
   `TypeError`, `RangeError` or `ReferenceError` (a 500 in the host) stops generation. `normalize` may return a
   promise, which `generate.mjs` awaits (the project formats run Node's asynchronous store checks).
4. Regenerate the OpenAPI document and the TypeScript types (see [contracts](../../contracts/README.md)).

## Running

From the repository root, with `pip install -e '.[dev,service]'`:

```sh
python -m pytest tests/test_schema_parity.py tests/test_schema_service.py tests/service -q
```
