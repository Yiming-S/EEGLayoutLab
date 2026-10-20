# Contributing

This repository contains the application and the scientific code it uses. Begin with the [source setup instructions](docs/source-installation.md), [architecture](docs/architecture.md), and [model definitions](docs/model-and-metrics.md). Preparation for the planned hosted version is tracked in [Server deployment preparation](docs/server-deployment.md).

## Change boundaries

Place UI behavior in the appropriate feature or shared component, HTTP and persistence behavior in `webapp/server/`, and scientific implementation in `src/compact_eeg/`. Keep browser modules independent of server-only imports. The small Python and Node compatibility entry points are part of the application's import and execution paths.

Preserve frozen data files and result provenance. New numerical assumptions require a new identity and an explicit description of the changed source model, geometry, noise, metric, or search budget. Do not change saved hashes or record IDs to force cache compatibility.

Coordinate changes must state their units and reference frame. Keep coordinate and region-label ordering together. Imported coordinates must already be registered to the Ernie subject space; the application does not perform a general anatomical registration.

Do not commit installed environments, large installed data, local result caches, credentials, build outputs, screenshots from test runs, or machine-specific filesystem paths. Changes to external assets must preserve their attribution and applicable terms.

## Verification

From the repository root, using the project runtime:

```sh
.runtime/simnibs-4.6.0/bin/python scripts/check_environment.py
python3 scripts/data_bundle.py verify
.runtime/simnibs-4.6.0/bin/python -B -m pytest tests -q -p no:cacheprovider
```

The Python development dependency is available through the project extra when preparing a separate development environment:

```sh
python -m pip install -e '.[dev]'
```

Use the interpreter of the environment being prepared. The base project installation alone is not the full SimNIBS native runtime.

From `webapp`:

```sh
npm run lint
npx tsc --noEmit
npm run test:unit
npm run build
```

For real-data HTTP integration, use an idle checkout with its data bundle and native runtime installed. Start the built local application on a separate loopback port in one terminal, from `webapp`:

```sh
PORT=3101 npm start
```

In a second terminal, also from `webapp`, point the integration command at that exact server:

```sh
EEG_TEST_URL=http://127.0.0.1:3101 npm run test:integration
```

This check submits real jobs against the existing forward bank: layout design, removal of one active electrode, fixed-coordinate evaluation, a six-source reception scenario, and cached replay. It checks HTTP routes and record loading as well. It can write new job records and caches under `results/v2/`; a separate port does not create a separate data directory. It does not automate browser interactions or run a new native FEM solve. Keep other computation on that checkout idle during the check.

To also test a new native-FEM coordinate request and native single/multi-source scenarios:

```sh
EEG_TEST_URL=http://127.0.0.1:3101 npm run test:integration -- --native
```

The native option can take several minutes on a cache miss. See the [recorded checkout verification](docs/verification.md) for the measured scope and outcomes.

For browser checks, start the application, install the browser once, and run:

```sh
npm exec playwright install chromium
npm run test:viewer
```

Browser checks can write screenshots and diagnostics. Existing-bank Python integrations are opt-in; tests that require real inputs or native capabilities must be reported as skipped when not run. Explicitly submitting a computation is different from a read-only or synthetic test and can create new scientific records.

## Review information

Describe the concrete behavior before and after the change. Include the checks performed, failures or skipped integrations, and any impact on scientific assumptions or cache identities. For a numerical change, identify the data and runtime used and compare results under matching conditions. Avoid treating a successful build as validation of a new scientific claim.

The repository has not yet been independently installed and tested on a second Mac. A portability contribution should record the machine architecture, OS version, runtime installation outcome, and which operations were actually exercised.

## Licensing

© 2026 Yiming Shen. A general license for the original code has not been selected. This document does not establish an open-source licensing grant or a contributor license agreement. Third-party components retain the terms listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
