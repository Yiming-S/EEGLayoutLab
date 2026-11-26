#!/usr/bin/env node
/**
 * Generates the third-party license inventory and verbatim license texts for npm packages
 * bundled into the static browser client (`webapp/dist/client`), excluding TypeScript-only
 * `@types/*` declarations and build-only CLI/server dependencies (`@img/sharp*`, `sharp`,
 * `caniuse-lite`, `@vercel/og`, `satori`, `vite*`, `oxlint*`, `playwright`, `typescript`).
 */
import { existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const WEBAPP_DIR = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const LICENSE_FILE_RE = /^(?:LICEN[CS]E|COPYING)(?:\..+)?$/i;

// Build-only sub-dependencies of `vinext` (Node server/OG/Rollup build plugins, never shipped in dist/client).
const VINEXT_CLIENT_SHIM_DEPS = new Set(['@unpic/react', 'web-vitals']);
const FORBIDDEN_LICENSE_RE = /\b(?:LGPL|AGPL|GPL|CC-BY)\b/i;

function resolveLockKey(packages, parentKey, depName) {
  let cursor = parentKey;
  while (cursor) {
    const candidate = `${cursor}/node_modules/${depName}`;
    if (candidate in packages) return candidate;
    const idx = cursor.lastIndexOf('/node_modules/');
    cursor = idx > 0 ? cursor.slice(0, idx) : '';
  }
  const top = `node_modules/${depName}`;
  return top in packages ? top : null;
}

const compareCodeUnits = (a, b) => (a < b ? -1 : a > b ? 1 : 0);

function findLicenseText(pkgDir) {
  if (!existsSync(pkgDir)) return null;
  const entries = readdirSync(pkgDir).filter(name => LICENSE_FILE_RE.test(name)).sort(compareCodeUnits);
  if (!entries.length) return null;
  return entries.map(name => readFileSync(join(pkgDir, name), 'utf8').trim()).join('\n\n');
}

export function collectBundledWebPackages(webappDir = WEBAPP_DIR) {
  const pkgJson = JSON.parse(readFileSync(join(webappDir, 'package.json'), 'utf8'));
  const lockJson = JSON.parse(readFileSync(join(webappDir, 'package-lock.json'), 'utf8'));
  const packages = lockJson.packages ?? {};

  const roots = Object.keys(pkgJson.dependencies ?? {}).filter(name => !name.startsWith('@types/'));
  const visited = new Set();
  const queue = roots.map(name => `node_modules/${name}`);

  while (queue.length > 0) {
    const key = queue.shift();
    if (!key || visited.has(key) || !(key in packages)) continue;
    const pkgName = key.replace(/^.*node_modules\//, '');
    if (pkgName.startsWith('@types/')) continue;
    visited.add(key);

    const entry = packages[key];
    const rawDeps = Object.keys(entry.dependencies ?? {});
    const childNames = pkgName === 'vinext'
      ? rawDeps.filter(dep => VINEXT_CLIENT_SHIM_DEPS.has(dep))
      : rawDeps;
    for (const dep of childNames) {
      if (dep.startsWith('@types/')) continue;
      const resolvedKey = resolveLockKey(packages, key, dep);
      if (!resolvedKey) throw new Error(`Cannot resolve bundled dependency ${dep} from ${key}`);
      queue.push(resolvedKey);
    }
  }

  const records = [...visited].sort(compareCodeUnits).map(key => {
    const info = packages[key];
    const name = key.replace(/^.*node_modules\//, '');
    const version = info.version ?? '';
    const pkgDir = join(webappDir, key);
    const pkgManifest = existsSync(join(pkgDir, 'package.json'))
      ? JSON.parse(readFileSync(join(pkgDir, 'package.json'), 'utf8'))
      : {};
    const license = String(info.license ?? pkgManifest.license ?? '').trim();
    if (!license) throw new Error(`Missing license field for bundled package ${name}@${version} (${key})`);
    if (FORBIDDEN_LICENSE_RE.test(license)) {
      throw new Error(`Unexpected copyleft/CC license in client bundle closure: ${name}@${version} (${license})`);
    }
    const licenseText = findLicenseText(pkgDir)
      ?? `Declared SPDX license in package.json: ${license} (no standalone LICENSE file shipped in npm tarball; see standard ${license} license text in sibling entries of this file).`;
    return { key, name, version, license, licenseText };
  });

  return records;
}

export function formatThirdPartyWebLicenses(records) {
  const lines = [
    'EEG Layout Lab — Bundled Web Interface Third-Party Notices',
    '==========================================================',
    '',
    'The following npm packages from webapp/package-lock.json are part of the',
    'runtime browser client bundle exported to webapp/dist/client. Build-only',
    'toolchains, linters, test runners, TypeScript type declarations, and',
    'native image-processing helpers (@img/sharp*, caniuse-lite) are not',
    'bundled in webapp/dist/client and are excluded.',
    '',
    'Summary of bundled packages:',
    '',
    ...records.map(r => `- ${r.name}@${r.version} (${r.license})`),
    '',
  ];
  for (const r of records) {
    lines.push(
      '------------------------------------------------------------------------',
      `${r.name}@${r.version} — ${r.license}`,
      '------------------------------------------------------------------------',
      '',
      r.licenseText,
      '',
    );
  }
  return lines.join('\n');
}

function parseCliArgs(argv) {
  let out = null;
  let webappDir = WEBAPP_DIR;
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--out') {
      out = argv[++i];
      if (!out) throw new Error('--out requires a file path');
    } else if (argv[i] === '--webapp-dir') {
      webappDir = resolve(argv[++i]);
    } else {
      throw new Error(`Unknown argument: ${argv[i]}`);
    }
  }
  return { out, webappDir };
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const { out, webappDir } = parseCliArgs(process.argv.slice(2));
  const records = collectBundledWebPackages(webappDir);
  const text = formatThirdPartyWebLicenses(records);
  if (out) {
    const target = resolve(out);
    mkdirSync(dirname(target), { recursive: true });
    writeFileSync(target, text, 'utf8');
    console.log(`wrote ${target} (${records.length} bundled npm packages)`);
  } else {
    process.stdout.write(text);
  }
}
