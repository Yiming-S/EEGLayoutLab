# EEG Layout Lab web application

The complete setup is in the [root README](../README.md). This directory contains the browser interface and local Node host; Python workers, scientific code, numerical inputs, and new results live in the parent checkout.

Node.js 22.13.0 or newer is required. After the data bundle and runtime are installed, run here:

```sh
npm ci
npm run dev
```

Open [http://127.0.0.1:3000](http://127.0.0.1:3000). For a built local application:

```sh
npm run build
npm start
```

These entry points include the same-origin local computation service. The application uses React, TypeScript, Three.js, and Vinext; it is not a desktop bundle.

| Directory | Contents |
| --- | --- |
| `app/` | Routes |
| `features/` | Feature workspaces and state controllers |
| `components/` and `lib/` | Shared views, types, pure logic, and translations |
| `server/` | Local HTTP and computation services |
| `scripts/` | Checks, host entry points, and compatibility exports |
| `public/` | Versioned display geometry and compact data exports |

Routes include `/` and `/library` for records, `/design` for radius design, `/electrodes` for editing, `/coordinates` for import, `/decision` for comparison, `/reception` for simulation, and `/guide` and `/method` for in-application documentation.

See [architecture](../docs/architecture.md) for process boundaries and [contributing](../CONTRIBUTING.md) for unit, type, build, and browser checks.
