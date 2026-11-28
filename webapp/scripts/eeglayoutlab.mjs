#!/usr/bin/env node
/**
 * Command-line access to the scientific services of the web application.
 *
 * Requests pass the same normalizers and result validators as the HTTP API, run the same Python
 * workers with the same thread settings, and record the same scientific identity and request key.
 * Nothing is written to the web service's queue or library.
 */
import { createHash } from 'node:crypto';
import { mkdirSync, readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs';
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
import { DATA_PRIOR_FILES, DATA_PRIOR_REGIONS, dataPriorFromFile, robustnessSummary } from '../contracts/scientific-options.mjs';
import { DEFAULT_OBJECTIVES, PARETO_OBJECTIVES, paretoAnalysis, summaryObjectives } from '../lib/pareto.ts';
import { SUMMARY_SCHEMA, channelSubsets } from '../lib/channel-subset.ts';

const RUN_SCHEMA = 'eeglayoutlab-cli-run/1';
const sha = value => createHash('sha256').update(typeof value === 'string' ? value : JSON.stringify(value)).digest('hex');
const readJson = path => JSON.parse(readFileSync(path, 'utf8'));
const writeJson = (path, value) => { mkdirSync(dirname(path), { recursive: true }); writeFileSync(path, JSON.stringify(value, null, 2) + '\n'); };
const stem = path => basename(path).replace(/\.json$/i, '');
const fileSha = path => createHash('sha256').update(readFileSync(path)).digest('hex');

/** Files named, with each directory replaced by the covariance summaries it holds. */
function summaryFiles(paths) {
  return paths.flatMap(path => {
    if (!statSync(path).isDirectory()) return [resolve(path)];
    return readdirSync(path).filter(name => name.endsWith('.json')).sort().map(name => resolve(path, name))
      .filter(file => { try { return readJson(file).schema === SUMMARY_SCHEMA; } catch { return false; } });
  });
}

/** Adds a data prior to a request or design submission; it replaces the noise model. */
function withDataPrior(raw, prior) {
  if (!prior) return raw;
  const request = raw.schema === 'design-submission/1' ? raw.request : raw;
  if (request.noise_model) throw new Error('--data-prior replaces the noise model; remove noise_model from the request');
  const merged = { ...request, data_prior: prior };
  return raw.schema === 'design-submission/1' ? { ...raw, request: merged } : merged;
}
const HELP = `EEGLayoutLab command line

  node webapp/scripts/eeglayoutlab.mjs design FILE... [--name NAME] [--regions 1|2|3|4|6] [--unit mm|cm|m] --out DESIGN.json
      Build a design from coordinate files: a BIDS pair (Ernie native, MNI, or a head frame
      such as CapTrak with NAS/LPA/RPA landmarks), an MNE .elc or EEGLAB .sfp file, a 10-05
      name list, the layout CSV, a design JSON, or a search run from this tool. Head-frame,
      .elc and .sfp coordinates are registered onto Ernie's scalp by their landmarks.
      --regions assigns balanced spatial regions to files without a region column;
      --unit gives the unit of an .sfp file, which declares none.

  node webapp/scripts/eeglayoutlab.mjs export DESIGN.json --format bids|mni|mne|eeglab|svg --out-dir DIR
      Write the web page's coordinate files or the layout figure (SVG, English text;
      --labels yes|no, by default names are hidden where they would overlap).

  node webapp/scripts/eeglayoutlab.mjs evaluate REQUEST.json... --out-dir DIR
  node webapp/scripts/eeglayoutlab.mjs evaluate --design DESIGN.json --radius 6 --seed 42
      [--action evaluate|perturb] [--noise iid|spatial_10|spatial_20|spatial_40|brain_background]
      [--conductivity skull_x0.5|skull_x2] [--head HEAD_ID] [--robustness standard/1]
      [--data-prior PRIOR.json] --out-dir DIR
      Score fixed coordinates, as /api/design-evaluation does. --robustness adds electrode
      dropout, unequal electrode noise and cap re-placement (evaluate on Ernie only).
      --data-prior applies a prior from the prior command (replaces --noise; Ernie only).

  node webapp/scripts/eeglayoutlab.mjs search REQUEST.json... [--data-prior PRIOR.json] --out-dir DIR
      Search a layout for a region count and radius, as /api/local-compute does.

  node webapp/scripts/eeglayoutlab.mjs eeg-summary RECORDING... [--band 1,40] [--epoch 2] [--label TEXT] --out-dir DIR
      Covariance summary of recorded EEG (EDF/EDF+C, BDF, BrainVision .vhdr, EEGLAB .set):
      10-05 channels on Ernie, band-pass and notch, average reference, artifact epochs removed.
      Only the summary leaves this step; the recording is read in place.

  node webapp/scripts/eeglayoutlab.mjs prior SUMMARY.json|DIR... --out PRIOR.json
      Fit region source power and noise structure to summaries, with leave-one-out shrinkage
      toward the area prior when there are three or more.

  node webapp/scripts/eeglayoutlab.mjs channels SUMMARY.json|DIR... [--test FILE,...|DIR] [--prior PRIOR.json]
      [--counts 8,16,24,32] [--draws 200] [--seed 1] [--figure FIGURE.svg] --out SUBSET.json
      Choose channel subsets that best reconstruct all recorded channels: greedy on the data,
      greedy on the prior's model (with --prior), the 10-20 subset and random subsets,
      scored on the training summaries and on held-out --test summaries. --figure also writes
      the error against subset size as an SVG figure.

  node webapp/scripts/eeglayoutlab.mjs pareto RUN.result.json... [--objectives LIST] --out PARETO.json
      Rank evaluate and search results by Pareto dominance. LIST is comma-separated from
      field, sensitivity, localization, p90, area, dropout, impedance, replacement
      (default field,sensitivity,localization). All inputs must share one evaluation condition.

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
  // A data prior adds its files to the code identity, as the web service does.
  const priorFiles = request.data_prior ? Object.fromEntries(DATA_PRIOR_FILES.map(path => [path, fileSha(join(env.root, path))])) : {};
  const identity = { version: 'local-radius-queue/1', code: { ...codeIdentity(env.root), ...priorFiles }, threads: 2, ...(runtime ? { runtime } : {}) };
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
  const regionCount = options.regions === undefined ? undefined : Number(options.regions);
  if (regionCount !== undefined && ![1, 2, 3, 4, 6].includes(regionCount)) throw new Error('--regions must be 1, 2, 3, 4 or 6');
  if (options.unit !== undefined && !['mm', 'cm', 'm'].includes(options.unit)) throw new Error('--unit must be mm, cm or m');
  const importOptions = { regionCount };
  if (files.length === 1 && /\.(elc|sfp)$/i.test(files[0])) {
    const { parseMontageFile } = await import('../lib/head-frame-import.ts');
    return named(parseMontageFile(read(files[0]), await mniSurface(), { ...importOptions, unit: options.unit }));
  }
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
    return named(parseElectrodeLabels(file, importOptions));
  }
  const coordinateFiles = files.map(read);
  if (!bidsNeedsMniSurface(coordinateFiles)) return named(parseBIDSElectrodes(coordinateFiles, undefined, importOptions));
  return named(parseBIDSElectrodes(coordinateFiles, await mniSurface(), importOptions));
}

function requestFromOptions(options) {
  const design = readJson(options.design), action = options.action ?? 'evaluate';
  const noise = { iid: undefined, spatial_10: { kind: 'spatial', rho: 0.5, length_mm: 10 }, spatial_20: { kind: 'spatial', rho: 0.5, length_mm: 20 },
    spatial_40: { kind: 'spatial', rho: 0.5, length_mm: 40 }, brain_background: { kind: 'brain_background', fraction: 0.5 } };
  if (options.noise !== undefined && !(options.noise in noise)) throw new Error(`unknown --noise ${options.noise}`);
  const { electrode_names, source_metadata, ...scientific } = design;
  const request = { action, design: scientific, radius_mm: Number(options.radius ?? 6), seed: Number(options.seed ?? 42),
    ...(noise[options.noise] ? { noise_model: noise[options.noise] } : {}),
    ...(options.conductivity ? { conductivity_scenario: options.conductivity } : {}), ...(options.head ? { head_id: options.head } : {}),
    ...(options.robustness ? { robustness: options.robustness } : {}) };
  return electrode_names ? { schema: 'design-submission/1', request, electrode_names, ...(source_metadata ? { source_metadata } : {}) } : request;
}

/** Objective values of a command-line run, as the library computes them for saved records. */
function runObjectives(path) {
  const run = readJson(path);
  if (run?.schema !== RUN_SCHEMA || !run.result) throw new Error(`${path} is not an evaluate or search result of this tool`);
  const { request, result } = run;
  if (run.service === 'design-evaluation') {
    if (request.action !== 'evaluate') throw new Error(`${path}: perturbation runs have no single nominal score`);
    return { name: request.design.name, condition: { noise: request.noise_model ?? null, scenario: request.conductivity_scenario ?? null, head: request.head_id ?? null, prior: request.data_prior ?? null },
      values: summaryObjectives({ metrics: result.nominal, geometry: null, robustness: result.robustness ? robustnessSummary(result.robustness) : undefined }) };
  }
  if (run.service === 'radius-search') {
    if (result.status !== 'completed') throw new Error(`${path}: the search found no layout`);
    return { name: `search ${request.region_count} regions, ${request.radius_mm} mm, ${request.mode}`, condition: { noise: request.noise_model ?? null, scenario: null, head: null, prior: request.data_prior ?? null },
      values: summaryObjectives({ metrics: result.metrics, geometry: result.geometry }) };
  }
  throw new Error(`${path}: unknown service ${run.service}`);
}

function pareto(files, list) {
  const objectives = list ? list.split(',').map(value => value.trim()) : DEFAULT_OBJECTIVES;
  const unknown = objectives.filter(id => !PARETO_OBJECTIVES.some(o => o.id === id));
  if (unknown.length) throw new Error(`unknown objective ${unknown.join(', ')}`);
  const items = files.map(file => ({ file, ...runObjectives(file) }));
  if (new Set(items.map(item => JSON.stringify(item.condition))).size > 1)
    throw new Error('the results use different noise models, data priors, conductivity scenarios or heads; compare one condition at a time');
  const analysis = paretoAnalysis(items.map(item => ({ item, values: item.values })), objectives);
  return { schema: 'eeglayoutlab-cli-pareto/1', objectives: analysis.objectives.map(o => o.id),
    directions: Object.fromEntries(analysis.objectives.map(o => [o.id, o.direction])), condition: items[0].condition,
    rows: analysis.rows.map(row => ({ file: row.item.file, name: row.item.name, rank: row.rank, dominated_by: row.dominated_by,
      values: Object.fromEntries(analysis.objectives.map((o, k) => [o.id, row.values[k]])) })),
    excluded: analysis.excluded.map(item => ({ file: item.file, name: item.name, missing: objectives.filter(id => !Number.isFinite(item.values[id])) })) };
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
  if (command === 'pareto') {
    if (files.length < 2 || !options.out) throw new Error('pareto needs at least two result files and --out');
    const report = pareto(files, options.objectives);
    writeJson(options.out, report);
    for (const row of report.rows) process.stdout.write(`${row.rank}\t${row.name}\t${report.objectives.map(o => row.values[o]).join('\t')}\n`);
    process.stderr.write(`wrote ${options.out}: ${report.rows.filter(row => row.rank === 1).length} of ${report.rows.length} on the front\n`);
    return 0;
  }
  if (command === 'channels') {
    if (!files.length || !options.out) throw new Error('channels needs training summaries and --out');
    const list = value => value.split(',').map(item => item.trim()).filter(Boolean);
    const numbers = value => list(value).map(Number);
    const report = channelSubsets({ training: summaryFiles(files).map(readJson), test: options.test ? summaryFiles(list(options.test)).map(readJson) : [],
      prior: options.prior ? readJson(options.prior) : undefined, counts: options.counts ? numbers(options.counts) : undefined,
      draws: options.draws === undefined ? undefined : Number(options.draws), seed: options.seed === undefined ? undefined : Number(options.seed) });
    writeJson(options.out, report);
    if (options.figure) {
      const { channelSubsetFigureSvg } = await import('../lib/channel-subset-figure.ts'), heldOut = report.test.length > 0, standard = report.standard_10_20;
      mkdirSync(dirname(resolve(options.figure)), { recursive: true });
      writeFileSync(options.figure, channelSubsetFigureSvg(report, {
        title: 'Reconstruction error of channel subsets',
        subtitle: [heldOut ? 'Mean held-out error' : 'Training error', `${report.universe.length} shared channels`, `${report.band_hz[0]}–${report.band_hz[1]} Hz`].join(' · '),
        xLabel: 'Channels in the subset', yLabel: 'Unexplained variance (lower is better)',
        names: { data: 'Greedy on the data', data_prior: 'Greedy on the data-prior model', area_prior: 'Greedy on the area-prior model',
          random: 'Random subsets, median and P10–P90', standard: standard ? `10-20 system (${standard.count})` : '' },
        channels: count => `${count} channels`,
        caption: ['Error is the unexplained variance fraction of the average-referenced shared channels. Each subset is recorded against one of its own channels; the reconstructor is fitted on the training summaries.',
          heldOut ? 'Curves are the mean held-out error; the band is the P10–P90 of the random subsets\' mean held-out error over draws. The data-greedy curve includes the size of the 10-20 subset.'
            : 'Without held-out summaries the curves are training errors, optimistic for greedy selection on the data; the band is the P10–P90 of the random subsets\' training error.'],
      }));
      process.stderr.write(`wrote ${options.figure}\n`);
    }
    const cell = row => `${row.train_error.toFixed(3)}${row.test_error ? `/${row.test_error.mean.toFixed(3)}` : ''}`;
    process.stdout.write(`count\t${Object.keys(report.methods).join('\t')}\trandom median\n`);
    report.counts.forEach((count, k) => process.stdout.write(`${count}\t${Object.values(report.methods).map(m => cell(m.counts[k])).join('\t')}\t` +
      `${report.random.counts[k].train_error.median.toFixed(3)}${report.random.counts[k].test_error_mean ? `/${report.random.counts[k].test_error_mean.median.toFixed(3)}` : ''}\n`));
    const standard = report.standard_10_20;
    if (standard) process.stdout.write(`10-20 (${standard.count})\t${cell(standard)}${standard.data_same_count ? `\tdata greedy ${cell(standard.data_same_count)}` : ''}\n`);
    const left = [[report.training_skipped.length, 'training'], [report.test_skipped.length, 'held-out']].filter(([count]) => count)
      .map(([count, role]) => `${count} ${role} summaries lack a channel and were left out`).join('; ');
    process.stderr.write(`wrote ${options.out}: ${report.universe.length} channels, ${report.training.length} training and ${report.test.length} held-out summaries` +
      `${left ? ` (${left})` : ''}; errors are training/held-out\n`);
    return 0;
  }
  if (command === 'prior') {
    if (!files.length || !options.out) throw new Error('prior needs summary files and --out');
    const env = environment(options), inputs = summaryFiles(files);
    if (!inputs.length) throw new Error('no covariance summaries found');
    process.stderr.write(`scientific root ${env.root}\npython ${env.python}\n${inputs.length} summaries\n`);
    const prior = await runWorker(env, 'scripts/eeg_data.py', { action: 'prior', files: inputs }, { threads: 4, timeoutMs: 3600000, label: 'prior' });
    dataPriorFromFile(prior);
    writeJson(options.out, prior);
    const { request, fit } = prior, held = fit.held_out;
    process.stdout.write(DATA_PRIOR_REGIONS.map((region, k) => `${region}\t${request.region_gain[k]}`).join('\n') + '\n' +
      `noise\t${request.rho ? `rho ${request.rho}, L ${request.length_mm} mm` : 'independent'}\n` +
      (held ? `held-out\t${held.prior_better_count}/${held.summaries} better than the area prior, shrinkage ${held.selected_shrinkage}\n` : 'held-out\tnot run (fewer than 3 summaries)\n'));
    process.stderr.write(`wrote ${options.out} (${prior.channels.length} channels, id ${prior.id})\n`);
    return 0;
  }
  if (!['eeg-summary', 'export', 'evaluate', 'search', 'study'].includes(command)) throw new Error(`unknown command ${command}\n\n${HELP}`);
  if (!options['out-dir']) throw new Error(`${command} needs --out-dir`);
  if (command === 'eeg-summary') {
    if (!files.length) throw new Error('eeg-summary needs recording files');
    if (options.label !== undefined && files.length > 1) throw new Error('--label applies to a single recording');
    const band = options.band === undefined ? [1, 40] : options.band.split(',').map(Number);
    const epoch = options.epoch === undefined ? 2 : Number(options.epoch);
    const outDir = resolve(options['out-dir']);
    // Recordings with the same name in different folders would write the same summary file.
    const names = files.map(file => basename(file).replace(/\.(edf|bdf|rec|vhdr|set)$/i, ''));
    // Case-insensitive, as on macOS and Windows file systems.
    const clash = names.find((name, k) => names.findIndex(other => other.toLowerCase() === name.toLowerCase()) !== k);
    if (clash !== undefined) throw new Error(`two recordings would both write ${clash}.summary.json; run them into different --out-dir folders`);
    const env = environment(options);
    process.stderr.write(`scientific root ${env.root}\npython ${env.python}\n`);
    let failed = 0;
    for (const [k, file] of files.entries()) {
      const name = names[k];
      process.stderr.write(`${name}\n`);
      try {
        const summary = await runWorker(env, 'scripts/eeg_data.py', { action: 'summary', path: resolve(file), band_hz: band, epoch_s: epoch, label: options.label ?? null },
          { threads: 1, timeoutMs: 1800000, label: 'summary' });
        writeJson(join(outDir, `${name}.summary.json`), summary);
        process.stderr.write(`  wrote ${join(outDir, `${name}.summary.json`)} (${summary.channels.length} channels, ${summary.epochs.used}/${summary.epochs.analysed} epochs)\n`);
      } catch (error) {
        failed++;
        process.stderr.write(`  failed: ${error.message}\n`);
      }
    }
    return failed ? 1 : 0;
  }
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
  const prior = options['data-prior'] ? dataPriorFromFile(readJson(options['data-prior'])) : undefined;
  const jobs = (command === 'evaluate' && options.design ? [['request', requestFromOptions(options)]] : files.map(path => [stem(path), readJson(path)]))
    .map(([name, raw]) => [name, withDataPrior(raw, prior)]);
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
