#!/usr/bin/env node
/**
 * Command-line access to the scientific services of the web application.
 *
 * Requests pass the same normalizers and result validators as the HTTP API, run the same Python
 * workers with the same thread settings, and record the same scientific identity and request key.
 * Nothing is written to the web service's queue or library.
 */
import { createHash } from 'node:crypto';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { basename, dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { normalizeDesignRequest, validateDesignResult } from '../server/design-evaluation-server.mjs';
import { codeIdentity, normalizeRequest as normalizeSearchRequest, validateWorkerResult } from '../server/local-compute-server.mjs';
import { designSubmission } from '../server/annotations/electrode-names.mjs';
import { aggregateStudy, normalizeStudyInput, summarizeStudyCase } from '../server/studies/protocol.mjs';
import { InputIntegrity } from '../server/local-input-integrity.mjs';
import { startPythonWorker } from '../server/jobs/python-worker.mjs';
import { runtimeConfig } from '../server/runtime/config.mjs';
import { runtimeIdentity } from '../server/runtime/python-fingerprint.mjs';
import { scientificContext } from '../server/runtime/scientific-context.mjs';

const RUN_SCHEMA = 'eeglayoutlab-cli-run/1';
const sha = value => createHash('sha256').update(typeof value === 'string' ? value : JSON.stringify(value)).digest('hex');
const readJson = path => JSON.parse(readFileSync(path, 'utf8'));
const writeJson = (path, value) => { mkdirSync(dirname(path), { recursive: true }); writeFileSync(path, JSON.stringify(value, null, 2) + '\n'); };
const stem = path => basename(path).replace(/\.json$/i, '');
const HELP = `EEGLayoutLab command line

  node webapp/scripts/eeglayoutlab.mjs design FILE... [--name NAME] --out DESIGN.json
      Build a design from coordinate files: a BIDS pair (Ernie native or MNI), a 10-05
      name list (name,region), the layout CSV, a design JSON, or a search run from this tool.

  node webapp/scripts/eeglayoutlab.mjs export DESIGN.json --format bids|mni|mne|eeglab|svg --out-dir DIR
      Write the web page's coordinate files or the layout figure (SVG, English text;
      --labels yes|no, by default names are hidden where they would overlap).

  node webapp/scripts/eeglayoutlab.mjs evaluate REQUEST.json... --out-dir DIR
  node webapp/scripts/eeglayoutlab.mjs evaluate --design DESIGN.json --radius 6 --seed 42
      [--action evaluate|perturb] [--noise iid|spatial_10|spatial_20|spatial_40|brain_background]
      [--conductivity skull_x0.5|skull_x2] [--head HEAD_ID] --out-dir DIR
      Score fixed coordinates, as /api/design-evaluation does.

  node webapp/scripts/eeglayoutlab.mjs search REQUEST.json... --out-dir DIR
      Search a layout for a region count and radius, as /api/local-compute does.

  node webapp/scripts/eeglayoutlab.mjs study STUDY.json --out-dir DIR
      Run every case of a robustness study (noise_seeds, grid_displacements or heads)
      and write the same per-case summaries and aggregation as the web study page.

  Options: --root DIR (scientific checkout; default EEG_REPOSITORY_ROOT or the repository)
           --python PATH (default: the managed runtime, else EEG_COMPUTE_PYTHON, else python3)
`;

function parseArgs(argv) {
  const [command, ...rest] = argv, files = [], options = {};
  for (let index = 0; index < rest.length; index++) {
    const value = rest[index];
    if (!value.startsWith('--')) { files.push(value); continue; }
    const name = value.slice(2), next = rest[index + 1];
    if (next === undefined || next.startsWith('--')) throw new Error(`--${name} needs a value`);
    options[name] = next; index++;
  }
  return { command, files, options };
}

function environment(options) {
  const repository = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
  const root = resolve(options.root ?? process.env.EEG_REPOSITORY_ROOT ?? repository);
  const config = runtimeConfig({ repositoryRoot: root, python: options.python });
  return { root, python: config.nativePython, inputs: new InputIntegrity(root) };
}

/** One worker run with the service's transport, thread limits and output bound. */
function runWorker(env, script, request, { threads, timeoutMs, label }) {
  return new Promise((resolvePromise, reject) => {
    let terminal = null, failure = null, stopped = null, lastProgress = -1;
    const limit = String(threads);
    startPythonWorker({
      executable: env.python, args: ['-u', join(env.root, script)],
      options: { cwd: env.root, stdio: ['pipe', 'pipe', 'pipe'], env: { ...process.env, OMP_NUM_THREADS: limit, OPENBLAS_NUM_THREADS: limit,
        MKL_NUM_THREADS: limit, VECLIB_MAXIMUM_THREADS: limit, PYTHONDONTWRITEBYTECODE: '1', PYTHONUNBUFFERED: '1' } },
      input: request, timeoutMs, maxOutputBytes: 8 * 1024 * 1024,
      onEvent: event => {
        if (event.type === 'progress') {
          const percent = Math.floor(100 * (Number(event.progress) || 0));
          if (percent >= lastProgress + 10 || percent === 100) { lastProgress = percent; process.stderr.write(`  ${label}: ${percent}% ${event.message ?? ''}\n`); }
        }
        if (event.type === 'result') terminal = event.result;
        if (event.type === 'error') failure = String(event.message);
      },
      onStderr: text => { if (!failure) failure = text.trim().split('\n').at(-1); },
      onError: error => { failure = error.message; },
      onStop: reason => { stopped = reason; },
      onClose: code => {
        if (stopped) reject(new Error(stopped === 'timeout' ? `time limit of ${timeoutMs / 60000} min reached` : `stopped (${stopped})`));
        else if (code !== 0 || !terminal) reject(new Error(failure ?? `worker exited with code ${code}`));
        else resolvePromise(terminal);
      },
    });
  });
}

async function evaluateOne(env, raw) {
  const { request: body, electrode_names, source_metadata } = designSubmission(raw);
  const request = normalizeDesignRequest(body), context = await scientificContext(env, request);
  const result = await runWorker(env, 'scripts/design_evaluation.py', request, { threads: 1, timeoutMs: 600000, label: request.action });
  validateDesignResult(result, request, context.admission);
  if ((await scientificContext(env, request)).key !== context.key) throw new Error('inputs or code changed during the calculation');
  return { schema: RUN_SCHEMA, service: 'design-evaluation', request, key: context.key, identity: context.identity,
    ...(electrode_names ? { annotation: { electrode_names, ...(source_metadata ? { source_metadata } : {}) } } : {}), result };
}

async function searchOne(env, raw) {
  const request = normalizeSearchRequest(raw), runtime = runtimeIdentity(env.python);
  // The same identity and key format as the web service's radius queue.
  const identity = { version: 'local-radius-queue/1', code: codeIdentity(env.root), threads: 2, ...(runtime ? { runtime } : {}) };
  const result = await runWorker(env, 'scripts/run_local_radius_compute.py', request, { threads: 2, timeoutMs: 180000, label: 'search' });
  validateWorkerResult(result, request);
  for (const [path, digest] of Object.entries(result.provenance?.code_sha256 ?? {}))
    if (identity.code[path] !== digest) throw new Error('scientific code changed during the search');
  if (result.status === 'completed') await env.inputs.verify(result.provenance);
  return { schema: RUN_SCHEMA, service: 'radius-search', request, key: sha(JSON.stringify({ request, identity })), identity, result };
}

async function study(env, input) {
  const normalized = normalizeStudyInput(input), heads = normalized.protocol === 'heads', cases = [], runs = [];
  for (const [index, request] of normalized.requests.entries()) {
    const label = heads ? request.head_id : `seed ${request.seed}, ${request.radius_mm} mm`;
    process.stderr.write(`case ${index + 1}/${normalized.requests.length} (${label})\n`);
    const context = await scientificContext(env, request), identity_sha256 = sha(context.identity);
    if (!heads && cases.length && identity_sha256 !== cases[0].identity_sha256) throw new Error('scientific identity changed between cases');
    try {
      const result = await runWorker(env, 'scripts/design_evaluation.py', request, { threads: 1, timeoutMs: 600000, label });
      validateDesignResult(result, request, context.admission);
      cases.push({ index, request, key: context.key, identity_sha256, status: 'completed', error: null, summary: summarizeStudyCase(result) });
      runs.push({ index, run: { schema: RUN_SCHEMA, service: 'design-evaluation', request, key: context.key, identity: context.identity, result } });
    } catch (error) {
      cases.push({ index, request, key: context.key, identity_sha256, status: 'failed', error: error.message, summary: null });
    }
  }
  const { requests: _requests, ...metadata } = normalized;
  return { runs, study: { schema: 'eeglayoutlab-cli-study/1', ...metadata,
    identity_sha256: heads ? sha(cases.map(entry => entry.identity_sha256)) : cases[0].identity_sha256,
    cases, aggregation: aggregateStudy(normalized.protocol, cases) } };
}

async function mniSurface() {
  const { ERNIE_MNI_MAPPING, verifiedSurface } = await import('../lib/ernie-mni.ts');
  const buffer = path => { const bytes = readFileSync(join(dirname(fileURLToPath(import.meta.url)), '../public', path)); return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength); };
  return verifiedSurface(buffer(ERNIE_MNI_MAPPING.scalp_buffer.file), buffer(ERNIE_MNI_MAPPING.mni_buffer.file));
}

async function exportFiles(path, format, labels) {
  const { validateDesign } = await import('../lib/design-decision.ts'), design = validateDesign(readJson(path));
  if (format === 'bids') return (await import('../lib/bids-electrodes.ts')).exportBIDSElectrodes(design);
  if (format === 'mni') return (await import('../lib/bids-electrodes.ts')).exportMniBIDSElectrodes(design, await mniSurface());
  if (format === 'mne') return [(await import('../lib/montage-files.ts')).exportMneElc(design)];
  if (format === 'eeglab') return [(await import('../lib/montage-files.ts')).exportEeglabSfp(design)];
  if (format === 'svg') {
    const { figureSpacing, layoutFigureSvg } = await import('../lib/layout-figure.ts'), count = Math.max(...design.region_indices) + 1;
    // As on the web page, names are hidden by default where they would overlap.
    const showNames = labels === undefined ? figureSpacing(design) >= 16 : labels === 'yes';
    return [{ name: 'layout.svg', text: layoutFigureSvg(design, {
      title: design.name, subtitle: `64 electrodes · ${count} region${count > 1 ? 's' : ''} · Ernie template head`, region: index => `Region ${index + 1}`,
      caption: ['Head frame from the Ernie template landmarks NAS, LPA and RPA (x toward RPA, y toward NAS); azimuthal equidistant projection by angle from the vertical axis.',
        'The circle is the NAS–LPA–RPA plane; electrodes below it lie outside. Positions are design positions on the template head, not measured positions.'] }, { labels: showNames }) }];
  }
  throw new Error('--format must be bids, mni, mne, eeglab or svg');
}

async function designFrom(files, options) {
  // Coordinate parsers are TypeScript shared with the browser; load them only for this command.
  const { parseBIDSElectrodes, bidsNeedsMniSurface, parseElectrodeLabels } = await import('../lib/bids-electrodes.ts');
  const { parseDesign, validateDesign } = await import('../lib/design-decision.ts');
  const read = path => ({ name: basename(path), text: readFileSync(path, 'utf8') });
  const named = design => validateDesign(options.name ? { ...design, name: options.name } : design);
  if (files.length === 1) {
    const file = read(files[0]), text = file.text.trimStart();
    if (text.startsWith('{')) {
      const value = JSON.parse(text);
      if (value.schema === RUN_SCHEMA && value.service === 'radius-search') {
        const { request, result } = value;
        if (result.status !== 'completed') throw new Error('the search found no layout');
        return named({ schema: 'eeg-electrode-design/1', coordinate_system: 'ernie_native_mm', unit: 'mm',
          name: `search ${request.region_count} regions, ${request.radius_mm} mm, ${request.mode}`, xyz_mm: result.layout.xyzMm, region_indices: result.layout.regionIndices });
      }
      return named(parseDesign(file.text));
    }
    if (text.startsWith('#')) return named(parseDesign(file.text, stem(files[0])));
    return named(parseElectrodeLabels(file));
  }
  const coordinateFiles = files.map(read);
  if (!bidsNeedsMniSurface(coordinateFiles)) return named(parseBIDSElectrodes(coordinateFiles));
  return named(parseBIDSElectrodes(coordinateFiles, await mniSurface()));
}

function requestFromOptions(options) {
  const design = readJson(options.design), action = options.action ?? 'evaluate';
  const noise = { iid: undefined, spatial_10: { kind: 'spatial', rho: 0.5, length_mm: 10 }, spatial_20: { kind: 'spatial', rho: 0.5, length_mm: 20 },
    spatial_40: { kind: 'spatial', rho: 0.5, length_mm: 40 }, brain_background: { kind: 'brain_background', fraction: 0.5 } };
  if (options.noise !== undefined && !(options.noise in noise)) throw new Error(`unknown --noise ${options.noise}`);
  const { electrode_names, source_metadata, ...scientific } = design;
  const request = { action, design: scientific, radius_mm: Number(options.radius ?? 6), seed: Number(options.seed ?? 42),
    ...(noise[options.noise] ? { noise_model: noise[options.noise] } : {}),
    ...(options.conductivity ? { conductivity_scenario: options.conductivity } : {}), ...(options.head ? { head_id: options.head } : {}) };
  return electrode_names ? { schema: 'design-submission/1', request, electrode_names, ...(source_metadata ? { source_metadata } : {}) } : request;
}

async function main(argv) {
  const { command, files, options } = parseArgs(argv);
  if (!command || command === 'help' || command === '--help') { process.stdout.write(HELP); return 0; }
  if (command === 'design') {
    if (!files.length || !options.out) throw new Error('design needs input files and --out');
    const design = await designFrom(files, options);
    writeJson(options.out, design);
    process.stderr.write(`wrote ${options.out} (${design.name})\n`);
    return 0;
  }
  if (!options['out-dir']) throw new Error(`${command} needs --out-dir`);
  if (command === 'export') {
    if (files.length !== 1 || !options.format) throw new Error('export takes one design file and --format');
    if (options.labels !== undefined && !['yes', 'no'].includes(options.labels)) throw new Error('--labels must be yes or no');
    for (const file of await exportFiles(files[0], options.format, options.labels)) {
      mkdirSync(options['out-dir'], { recursive: true }); writeFileSync(join(options['out-dir'], file.name), file.text);
      process.stderr.write(`wrote ${join(options['out-dir'], file.name)}\n`);
    }
    return 0;
  }
  if (!['evaluate', 'search', 'study'].includes(command)) throw new Error(`unknown command ${command}\n\n${HELP}`);
  if (command === 'study' && files.length !== 1) throw new Error('study takes one study file');
  if (command !== 'study' && !files.length && !(command === 'evaluate' && options.design)) throw new Error(`${command} needs request files${command === 'evaluate' ? ' or --design' : ''}`);
  const env = environment(options), outDir = resolve(options['out-dir']);
  process.stderr.write(`scientific root ${env.root}\npython ${env.python}\n`);
  if (command === 'study') {
    const { study: record, runs } = await study(env, readJson(files[0]));
    for (const { index, run } of runs) writeJson(join(outDir, 'cases', `${String(index + 1).padStart(2, '0')}.result.json`), run);
    writeJson(join(outDir, 'study.json'), record);
    process.stderr.write(`wrote ${join(outDir, 'study.json')}: ${record.aggregation.completed_cases}/${record.cases.length} cases completed\n`);
    return record.aggregation.completed_cases === record.cases.length ? 0 : 1;
  }
  const jobs = command === 'evaluate' && options.design ? [['request', requestFromOptions(options)]] : files.map(path => [stem(path), readJson(path)]);
  let failed = 0;
  for (const [name, raw] of jobs) {
    process.stderr.write(`${name}\n`);
    try {
      const run = command === 'evaluate' ? await evaluateOne(env, raw) : await searchOne(env, raw);
      writeJson(join(outDir, `${name}.result.json`), run);
      process.stderr.write(`  wrote ${join(outDir, `${name}.result.json`)} (key ${run.key.slice(0, 12)})\n`);
    } catch (error) {
      failed++;
      writeJson(join(outDir, `${name}.error.json`), { schema: RUN_SCHEMA, request: raw, error: error.message });
      process.stderr.write(`  failed: ${error.message}\n`);
    }
  }
  return failed ? 1 : 0;
}

main(process.argv.slice(2)).then(code => { process.exitCode = code; }, error => { process.stderr.write(`error: ${error.message}\n`); process.exitCode = 2; });
