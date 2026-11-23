// design-evaluation: the body of POST /api/design-evaluation/jobs, a bare request or a design-submission/1
// envelope. Node's outcome is designSubmission followed by normalizeDesignRequest, as in the service.
import { readFileSync } from 'node:fs';
import { normalizeDesignRequest } from '../../../webapp/server/design-evaluation-server.mjs';
import { designSubmission } from '../../../webapp/server/annotations/electrode-names.mjs';
import { CONDUCTIVITY_SCENARIOS, DATA_PRIOR_LENGTHS_MM, SPATIAL_NOISE_LENGTHS_MM } from '../../../webapp/contracts/scientific-options.mjs';
import { ABSENT, Raw, collector, createRandom, nextUp, raw, toText } from '../support.mjs';

/** Node's option lists, compared with the Python schemas' (tests/test_schema_parity.py). */
export const options = {
  conductivity_scenarios: CONDUCTIVITY_SCENARIOS.map(scenario => scenario.id).filter(Boolean),
  spatial_noise_lengths_mm: [...SPATIAL_NOISE_LENGTHS_MM],
  data_prior_lengths_mm: [...DATA_PRIOR_LENGTHS_MM],
};
export const name = 'design-evaluation';

export function normalize(value) {
  const input = designSubmission(value);
  return {
    request: normalizeDesignRequest(input.request),
    ...(input.electrode_names ? { electrode_names: input.electrode_names } : {}),
    ...(input.source_metadata !== undefined ? { source_metadata: input.source_metadata } : {}),
  };
}

const { random, pick } = createRandom(0x5eed2026);
const { variants, add, addBytes } = collector();
export { variants };

const grid = (spacing = 5, z = () => 0) => Array.from({ length: 64 }, (_, i) => [(i % 8) * spacing, Math.floor(i / 8) * spacing, z(i)]);
const balanced = r => Array.from({ length: 64 }, (_, i) => i % r);
const design = (overrides = {}) => ({
  schema: 'eeg-electrode-design/1', coordinate_system: 'ernie_native_mm', unit: 'mm', name: 'Parity variant',
  xyz_mm: grid(), region_indices: balanced(2), ...overrides,
});
const request = (overrides = {}, designOverrides = {}) => ({
  action: 'evaluate', design: design(designOverrides), radius_mm: 3, seed: 2026, ...overrides,
});
const SPATIAL = { kind: 'spatial', rho: 0.5, length_mm: 20 };
const BRAIN = { kind: 'brain_background', fraction: 0.5 };
const GAINS = [1, 1.5, 0.25, 2.75, 1000, 0.001, 12.34];
const PRIOR = { region_gain: GAINS, rho: 0.3, length_mm: 20 };
const PRIOR_IID = { region_gain: GAINS, rho: 0, length_mm: null };


// Top level
add('base', request());
add('base-pretty', raw(JSON.stringify(request(), null, 2)));
for (const key of ['action', 'design', 'radius_mm', 'seed']) add(`missing-${key}`, request({ [key]: ABSENT }));
for (const key of ['extra', '__proto__', 'constructor', 'toString', 'mode', 'schema'])
  add(`extra-top-${key}`, request({ [key]: 1 }));
for (const [i, value] of ['[]', 'null', '1', '"x"', 'true', '{}'].entries()) add(`top-not-request-${i}`, raw(value));
add('duplicate-seed-last-wins', raw(toText(request()).replace('"seed":2026', '"seed":1,"seed":2026')));
add('duplicate-seed-last-invalid', raw(toText(request()).replace('"seed":2026', '"seed":2026,"seed":"x"')));
add('trailing-garbage', raw(toText(request()) + 'x'));
add('trailing-whitespace', raw(' \n\t' + toText(request()) + ' \r\n'));
add('bom-prefix', raw('﻿' + toText(request())));
add('nan-literal', request({}, { xyz_mm: grid().map((p, i) => i ? p : [raw('NaN'), 0, 0]) }));
add('infinity-literal', request({}, { xyz_mm: grid().map((p, i) => i ? p : [raw('Infinity'), 0, 0]) }));
add('minus-infinity-literal', request({ seed: raw('-Infinity') }));
add('overflow-exponent', request({}, { xyz_mm: grid().map((p, i) => i ? p : [raw('1e400'), 0, 0]) }));
add('unicode-digit-seed', raw(toText(request()).replace('"seed":2026', '"seed":2٠٢٦')));
add('huge-integer-in-dropped-field', request({}, { extra: raw('9'.repeat(5000)) }));
add('huge-integer-seed', request({ seed: raw('1' + '0'.repeat(400)) }));
// Deeper than Python's recursion limit: JSON.parse accepts any depth and the normalizer drops unknown design fields.
add('deep-array-in-dropped-field', request({}, { extra: raw('['.repeat(5000) + ']'.repeat(5000)) }));
add('deep-object-in-dropped-field', request({}, { extra: raw('{"a":'.repeat(3000) + '1' + '}'.repeat(3000)) }));
add('deep-array-seed', request({ seed: raw('['.repeat(5000) + '2026' + ']'.repeat(5000)) }));
add('deep-array-unbalanced', request({}, { extra: raw('['.repeat(5000) + ']'.repeat(4999)) }));

// Action, radius and seed
for (const value of ['perturb', 'Evaluate', 'evaluate ', '', null, 1, true, ['evaluate'], { a: 1 }]) add(`action-${JSON.stringify(value)}`, request({ action: value }));
for (const value of [3, 6, 10, raw('3.0'), raw('6e0'), raw('1e1'), raw('1E1'), raw('0.6e1'), raw('10.0000000000000001'), raw('10.000000000000002'),
  4, 0, -3, '3', true, null, raw('3.5'), [3], raw('-0'), raw('3.00000000000000044')])
  add(`radius-${value instanceof Raw ? value.text : JSON.stringify(value)}`, request({ radius_mm: value }));
for (const value of [0, 1, 9999, 10000, -1, raw('-0'), raw('-0.0'), raw('2026.0'), raw('2.026e3'), raw('202600e-2'), 2026.5, '2026', true, false, null,
  raw('9999.0000000000001'), raw('9999.000000000002'), raw('1e4'), raw('9.999e3'), raw('-1e-400'), raw('1e-400'), [2026], raw('4.9e-324')])
  add(`seed-${value instanceof Raw ? value.text : JSON.stringify(value)}`, request({ seed: value }));

// Design object
for (const value of [null, [], 'x', 1, {}, true]) add(`design-${JSON.stringify(value)}`, request({ design: value }));
for (const [key, values] of Object.entries({
  schema: [ABSENT, 'eeg-electrode-design/2', null, 'EEG-ELECTRODE-DESIGN/1'],
  coordinate_system: [ABSENT, 'mni_mm', null],
  unit: [ABSENT, 'cm', 'MM', null],
})) for (const value of values) add(`design-${key}-${value === ABSENT ? 'absent' : JSON.stringify(value)}`, request({}, { [key]: value }));
const NAMES = {
  absent: ABSENT, null: null, number: 123, true: true, object: { a: 1 }, array: ['x'], empty: '', exact100: 'a'.repeat(100),
  over100: 'b'.repeat(150), emoji60: '😀'.repeat(60), oddEmojiCut: 'a' + '😀'.repeat(60), cjk: '导入布局'.repeat(30),
  controls: '\u0000\u0001\b\f\n\r\t\u001f\u007f\u0080', quotes: '"\\/\'', separators: '  ', combining: 'é é',
  loneHigh: '\ud800x', loneLow: 'x\udc00', reversedPair: '\ude00\ud83d', astral: '\u{10ffff}\u{1f600}', zeroWidth: '​﻿',
};
for (const [label, value] of Object.entries(NAMES)) add(`name-${label}`, request({}, { name: value }));
add('name-escaped-pair', raw(toText(request()).replace('"Parity variant"', '"\\ud83d\\ude00 \\u00e9 \\u0041"')));
add('name-escaped-lone', raw(toText(request()).replace('"Parity variant"', '"\\udbff"')));
for (const [key, value] of Object.entries({ electrode_names: Array.from({ length: 64 }, (_, i) => `E${i}`), source_metadata: { a: 1 }, ['__proto__']: 1, extra: null, mode: 'x' }))
  add(`design-extra-${key}`, request({}, { [key]: value }));
for (const [label, bytes] of Object.entries({
  invalidByte: [0xff], truncatedTwo: [0xc3], encodedSurrogate: [0xed, 0xa0, 0x80], overlong: [0xc0, 0xaf],
  aboveMax: [0xf4, 0x90, 0x80, 0x80], truncatedThree: [0xe2, 0x82], valid: [0xe2, 0x82, 0xac],
})) {
  const [before, after] = toText(request()).split('Parity variant');
  addBytes(`bytes-name-${label}`, [...Buffer.from(before), ...bytes, 0x61, ...Buffer.from(after)]);
}
addBytes('bytes-bom', [0xef, 0xbb, 0xbf, ...Buffer.from(toText(request()))]);

// Coordinates
const withPoint = (index, point) => grid().map((p, i) => (i === index ? point : p));
add('xyz-63', request({}, { xyz_mm: grid().slice(0, 63) }));
add('xyz-65', request({}, { xyz_mm: [...grid(), [100, 100, 100]] }));
add('xyz-not-array', request({}, { xyz_mm: 'x' }));
for (const [label, point] of Object.entries({
  short: [1, 2], long: [100, 100, 100, 0], string: ['100', 0, 0], bool: [true, 100, 100], null: [null, 100, 100], object: { 0: 100, 1: 100, 2: 100 },
  max: [500, 100, 100], min: [-500, 100, 100], over: [raw('500.0000000000001'), 100, 100], under: [raw('-500.00000000000006'), 100, 100],
  exp: [raw('5e2'), raw('1E2'), raw('-1.5e+2')], ints: [100, 200, 300], decimals: [raw('100.0'), raw('200.000'), raw('300e0')],
  minusZero: [raw('-0'), raw('-0.0'), raw('400')], tiny: [raw('400'), raw('1e-7'), raw('1.5e-7')], tinier: [raw('400'), raw('5e-324'), raw('-2.2250738585072014e-308')],
  sixDecimals: [raw('400.000001'), raw('0.000001'), raw('0.0000001')], longDigits: [raw('123.45678901234567890123'), raw('0.1'), raw('0.30000000000000004')],
}))
  add(`xyz-point-${label}`, request({}, { xyz_mm: withPoint(63, point) }));
add('xyz-duplicate', request({}, { xyz_mm: withPoint(1, [0, 0, 0]) }));
add('xyz-duplicate-minus-zero', request({}, { xyz_mm: withPoint(1, [raw('-0.0'), 0, raw('-0')]) }));
add('xyz-near-duplicate', request({}, { xyz_mm: withPoint(1, [nextUp(0), 0, 0]) }));
for (const [label, z] of Object.entries({ tinyZ: i => (i % 3 ? 1e-7 * i : -1.25e-7), subnormalZ: i => 5e-324 * i, smallZ: i => i * 1e-6 + 1e-21 }))
  add(`xyz-${label}`, request({}, { xyz_mm: grid(5, z) }));

// Spacing threshold: 4 - 1e-7 mm, with V8's Math.hypot
const T = 4 - 1e-7;
for (const [label, spacing] of Object.entries({ exact4: 4, threshold: T, belowUlp: nextUp(T, -1), aboveUlp: nextUp(T, 1), clearlyBelow: 4 - 2e-7, wellAbove: 4.5 }))
  add(`spacing-${label}`, request({}, { xyz_mm: grid(spacing) }));
const pairDesign = d => [[0, 0, 0], d, ...grid(10).slice(0, 62).map(([x, y, z]) => [x + 20, y + 20, z])];
const naive = d => Math.sqrt(d[0] * d[0] + d[1] * d[1] + d[2] * d[2]);
let disagreements = 0, nearThreshold = 0;
for (let attempt = 0; attempt < 400000 && (disagreements < 40 || nearThreshold < 60); attempt++) {
  const u = [random() - 0.5, random() - 0.5, random() - 0.5], scale = nextUp(T, Math.floor(random() * 9) - 4) / naive(u);
  const d = u.map(v => v * scale), accepted = !(Math.hypot(...d) < T), naiveAccepted = !(naive(d) < T);
  if (accepted !== naiveAccepted && disagreements < 40) add(`spacing-hypot-differs-${disagreements++}`, request({}, { xyz_mm: pairDesign(d) }));
  else if (accepted === naiveAccepted && nearThreshold < 60 && Math.abs(Math.hypot(...d) - T) <= 4e-15) add(`spacing-near-${nearThreshold++}`, request({}, { xyz_mm: pairDesign(d) }));
}

// Region labels
const counts = sizes => sizes.flatMap((n, region) => Array(n).fill(region));
for (const [label, labels] of Object.entries({
  r1: balanced(1), r2: balanced(2), r3: balanced(3), r4: balanced(4), r6: balanced(6), r6sorted: counts([11, 11, 11, 11, 10, 10]),
  r3sizes: counts([22, 21, 21]), r5: balanced(5), r7: balanced(7), r2unbalanced: counts([33, 31]), r3wrong: counts([22, 22, 20]),
  oneBased: balanced(2).map(v => v + 1), gap: balanced(2).map(v => v * 2), negative: balanced(2).map(v => -v), short: balanced(2).slice(1), long: [...balanced(2), 0],
}))
  add(`regions-${label}`, request({}, { region_indices: labels }));
for (const [label, value] of Object.entries({ float: raw('1.0'), exp: raw('1e0'), minusZero: raw('-0'), minusZeroFloat: raw('-0.0'), string: '1', true: true, null: null, half: 1.5, array: [1] }))
  add(`regions-element-${label}`, request({}, { region_indices: balanced(2).map((v, i) => (i === 1 ? value : v)) }));
add('regions-not-array', request({}, { region_indices: 'x' }));
add('regions-shuffled', request({}, { region_indices: Array.from({ length: 64 }, (_, i) => (i * 37) % 64 < 32 ? 0 : 1) }));

// Noise model
for (const [label, value] of Object.entries({
  absent: ABSENT, null: null, iid: { kind: 'iid' }, iidExtra: { kind: 'iid', rho: 0 }, spatial10: { ...SPATIAL, length_mm: 10 }, spatial20: SPATIAL,
  spatial40: { ...SPATIAL, length_mm: 40 }, spatial30: { ...SPATIAL, length_mm: 30 }, spatialFloatLength: { ...SPATIAL, length_mm: raw('20.0') },
  spatialExpLength: { ...SPATIAL, length_mm: raw('2e1') }, spatialStringLength: { ...SPATIAL, length_mm: '20' }, spatialRhoExp: { ...SPATIAL, rho: raw('5e-1') },
  spatialRhoDigits: { ...SPATIAL, rho: raw('0.50000000000000001') }, spatialRhoNext: { ...SPATIAL, rho: nextUp(0.5) }, spatialRhoString: { ...SPATIAL, rho: '0.5' },
  spatialMissing: { kind: 'spatial', rho: 0.5 }, spatialExtra: { ...SPATIAL, unit: 'mm' }, spatialReordered: { length_mm: 20, rho: 0.5, kind: 'spatial' },
  brain: BRAIN, brainFraction: { ...BRAIN, fraction: 0.25 }, brainTrue: { ...BRAIN, fraction: true }, pink: { kind: 'pink' }, noKind: { rho: 0.5 },
  empty: {}, false: false, zero: 0, emptyString: '', array: [], kindNumber: { kind: 1 }, kindUpper: { kind: 'IID' },
}))
  add(`noise-${label}`, request({ noise_model: value }));
add('noise-brain-perturb', request({ action: 'perturb', noise_model: BRAIN }));
add('noise-spatial-perturb', request({ action: 'perturb', noise_model: SPATIAL }));

// Conductivity scenario and head
for (const value of [ABSENT, null, '', 'skull_x2', 'skull_x0.5', 'skull_x3', 'SKULL_X2', 'skull_x2 ', false, 0, ['skull_x2']])
  for (const action of ['evaluate', 'perturb'])
    add(`scenario-${action}-${value === ABSENT ? 'absent' : JSON.stringify(value)}`, request({ action, conductivity_scenario: value }));
for (const value of [ABSENT, null, '', 'ixi002', 'a', 'a_b-c', 'a'.repeat(40), 'a'.repeat(41), 'IXI002', 'ixi/002', 'ixi002\n', '\nixi002', 'a__b', '-a', 'a-', 'ixi 002', 'ixí002', false, 0, ['ixi002']])
  for (const action of ['evaluate', 'perturb'])
    add(`head-${action}-${value === ABSENT ? 'absent' : JSON.stringify(value)}`, request({ action, head_id: value }));
add('head-with-scenario', request({ head_id: 'ixi002', conductivity_scenario: 'skull_x2' }));
add('head-empty-with-scenario', request({ head_id: '', conductivity_scenario: 'skull_x2' }));
add('head-with-empty-scenario', request({ head_id: 'ixi002', conductivity_scenario: '' }));
add('head-with-noise', request({ head_id: 'ixi002', noise_model: SPATIAL }));

// Robustness
for (const value of [ABSENT, null, '', false, 'standard/1', 0, raw('0.0'), raw('-0'), true, 'standard/2', 'Standard/1', ['standard/1'], {}])
  for (const action of ['evaluate', 'perturb'])
    add(`robustness-${action}-${value === ABSENT ? 'absent' : value instanceof Raw ? value.text : JSON.stringify(value)}`, request({ action, robustness: value }));
add('robustness-with-scenario', request({ robustness: 'standard/1', conductivity_scenario: 'skull_x2' }));
add('robustness-with-head', request({ robustness: 'standard/1', head_id: 'ixi002' }));
add('robustness-with-noise', request({ robustness: 'standard/1', noise_model: BRAIN }));
add('robustness-false-with-head', request({ robustness: false, head_id: 'ixi002' }));

// Data prior
const gains = (i, value) => GAINS.map((g, j) => (j === i ? value : g));
for (const [label, value] of Object.entries({
  absent: ABSENT, null: null, valid: PRIOR, iidPrior: PRIOR_IID, minusZeroRho: { ...PRIOR_IID, rho: raw('-0.0') }, rhoMax: { ...PRIOR, rho: 0.95 },
  rhoOver: { ...PRIOR, rho: 0.96 }, rhoNegative: { ...PRIOR, rho: -0.01 }, rho007: { ...PRIOR, rho: 0.07 }, rho029: { ...PRIOR, rho: 0.29 }, rho057: { ...PRIOR, rho: 0.57 },
  rho0015: { ...PRIOR, rho: 0.015 }, rho0125: { ...PRIOR, rho: 0.125 }, rhoString: { ...PRIOR, rho: '0.3' }, rhoTrue: { ...PRIOR, rho: true }, rhoNull: { ...PRIOR, rho: null },
  rhoZeroLength: { ...PRIOR_IID, length_mm: 10 }, rhoLengthNull: { ...PRIOR, length_mm: null }, lengthFloat: { ...PRIOR, length_mm: raw('20.0') },
  length25: { ...PRIOR, length_mm: 25 }, lengthString: { ...PRIOR, length_mm: '20' }, lengthMissing: { region_gain: GAINS, rho: 0 }, extra: { ...PRIOR, id: 'x' },
  gains6: { ...PRIOR, region_gain: GAINS.slice(1) }, gains8: { ...PRIOR, region_gain: [...GAINS, 1] }, gainZero: { ...PRIOR, region_gain: gains(0, 0) },
  gainTooSmall: { ...PRIOR, region_gain: gains(0, 0.0009999) }, gainTooLarge: { ...PRIOR, region_gain: gains(0, 1000.1) }, gainExp: { ...PRIOR, region_gain: gains(0, raw('1e3')) },
  gainFloatLiteral: { ...PRIOR, region_gain: gains(0, raw('1000.0')) }, gainFiveDigits: { ...PRIOR, region_gain: gains(0, 1.2345) },
  gainFourDigits: { ...PRIOR, region_gain: [1.234, 12.34, 123.4, 9.999, 0.001234, 0.01, 999.9] }, gainTie: { ...PRIOR, region_gain: gains(0, 1.0625) },
  gainNegative: { ...PRIOR, region_gain: gains(0, -1) }, gainString: { ...PRIOR, region_gain: gains(0, '1') }, gainTrue: { ...PRIOR, region_gain: gains(0, true) },
  gainsNotArray: { ...PRIOR, region_gain: 'x' }, empty: {}, false: false, array: [], string: 'eeg-data-prior/1',
}))
  add(`prior-${label}`, request({ data_prior: value }));
add('prior-with-spatial', request({ data_prior: PRIOR, noise_model: SPATIAL }));
add('prior-with-iid', request({ data_prior: PRIOR, noise_model: { kind: 'iid' } }));
add('prior-with-null-noise', request({ data_prior: PRIOR, noise_model: null }));
add('prior-with-head', request({ data_prior: PRIOR, head_id: 'ixi002' }));
add('prior-with-empty-head', request({ data_prior: PRIOR, head_id: '' }));
add('prior-with-scenario', request({ data_prior: PRIOR, conductivity_scenario: 'skull_x2' }));
add('prior-with-robustness', request({ data_prior: PRIOR, robustness: 'standard/1' }));
add('prior-perturb', request({ data_prior: PRIOR, action: 'perturb' }));

// One request per value of Node's option lists, so that a value added on one side only fails parity.
for (const { id } of CONDUCTIVITY_SCENARIOS) if (id) add(`option-scenario-${id}`, request({ conductivity_scenario: id }));
for (const length_mm of SPATIAL_NOISE_LENGTHS_MM) add(`option-noise-length-${length_mm}`, request({ noise_model: { ...SPATIAL, length_mm } }));
for (const length_mm of DATA_PRIOR_LENGTHS_MM) add(`option-prior-length-${length_mm}`, request({ data_prior: { ...PRIOR, length_mm } }));

// Random combinations of every optional field
const POOLS = {
  action: ['evaluate', 'evaluate', 'perturb'],
  radius_mm: [3, 6, 10, raw('6.0'), 4],
  seed: [0, 2026, 9999, raw('2026.0'), 10000, true],
  noise_model: [ABSENT, ABSENT, null, { kind: 'iid' }, SPATIAL, { ...SPATIAL, length_mm: 40 }, BRAIN, { kind: 'pink' }],
  conductivity_scenario: [ABSENT, ABSENT, null, '', 'skull_x2', 'skull_x0.5', 'skull_x3'],
  head_id: [ABSENT, ABSENT, null, '', 'ixi002', 'IXI002'],
  robustness: [ABSENT, ABSENT, null, '', false, 'standard/1', 'standard/1', 0],
  data_prior: [ABSENT, ABSENT, ABSENT, null, PRIOR, PRIOR_IID, { ...PRIOR, rho: 0.015 }],
};
const DESIGNS = [{}, {}, { region_indices: balanced(6) }, { region_indices: balanced(3), name: '😀'.repeat(60) }, { xyz_mm: grid(5, i => i * 1e-7) }, { xyz_mm: grid(3.9) }];
for (let i = 0; i < 800; i++) {
  const fields = Object.fromEntries(Object.entries(POOLS).map(([key, pool]) => [key, pick(pool)]));
  add(`combo-${i}`, request(fields, pick(DESIGNS)));
}

// design-submission/1 envelopes
const LABELS = Array.from({ length: 64 }, (_, i) => `E${i + 1}`);
const envelope = (overrides = {}) => ({ schema: 'design-submission/1', request: request(), electrode_names: LABELS, ...overrides });
add('bare-request', request());
add('bare-request-invalid', request({ seed: -1 }));
add('envelope', envelope());
add('envelope-prior', envelope({ request: request({ data_prior: PRIOR, noise_model: { kind: 'iid' } }) }));
for (const [label, value] of Object.entries({
  spaces: '   ', nbsp: ' ', bom: '﻿', nel: '\u0085', ideographic: '　', lineSeparator: ' ', zeroWidth: '​', ogham: ' ',
  padded: ' Fz ', tab: 'F\tz', del: 'F\u007fz', nul: '\u0000', empty: '', len128: 'x'.repeat(128), len129: 'x'.repeat(129), emoji64: '😀'.repeat(64),
  emoji65: '😀'.repeat(65), loneSurrogate: '\ud800', number: 1, null: null,
}))
  add(`envelope-name-${label}`, envelope({ electrode_names: LABELS.map((n, i) => (i === 5 ? value : n)) }));
add('envelope-duplicate-names', envelope({ electrode_names: LABELS.map((n, i) => (i === 5 ? 'E1' : n)) }));
add('envelope-63-names', envelope({ electrode_names: LABELS.slice(1) }));
add('envelope-names-missing', envelope({ electrode_names: ABSENT }));
add('envelope-request-missing', envelope({ request: ABSENT }));
add('envelope-request-null', envelope({ request: null }));
add('envelope-request-invalid', envelope({ request: request({ radius_mm: 4 }) }));
add('envelope-extra', envelope({ extra: 1 }));
add('envelope-other-schema', envelope({ schema: 'design-submission/2' }));
add('envelope-schema-null', envelope({ schema: null }));

// Shared fixtures (contracts/fixtures/requests.json): generate.mjs checks that Node still gives the recorded outcome.
const corpus = JSON.parse(readFileSync(new URL('../../../contracts/fixtures/requests.json', import.meta.url), 'utf8'));
for (const sample of corpus.cases.filter(sample => sample.service === 'design'))
  add(`fixture-${sample.name}`, raw(JSON.stringify(sample.request)),
    { accepted: sample.valid, canonical: sample.valid ? JSON.stringify({ request: sample.canonical }) : null });

// design-submission/1 envelopes with source_metadata ------------------------------------------------------------
// Node checks a present source_metadata, null included, with validateCoordinateSource and keeps its key order.
import { SOURCES } from './coordinate-source.mjs';

add('envelope-source-absent', envelope({ source_metadata: ABSENT }));
add('envelope-source-null', envelope({ source_metadata: null }));
for (const [id, source] of Object.entries(SOURCES)) add(`envelope-source-${id}`, envelope({ source_metadata: source }));
add('envelope-source-reordered', envelope({ source_metadata: Object.fromEntries(Object.entries(SOURCES.v3Mni).reverse()) }));
add('envelope-source-first', { schema: 'design-submission/1', source_metadata: SOURCES.v2Labels, electrode_names: LABELS, request: request() });
add('envelope-source-invalid-unit', envelope({ source_metadata: { ...SOURCES.v1, unit: 'cm' } }));
add('envelope-source-invalid-labels-head', envelope({ source_metadata: { ...SOURCES.v3Labels, conversion: SOURCES.v3BidsHead.conversion } }));
for (const [label, value] of Object.entries({ empty: {}, array: [], string: 'x', number: 0, false: false }))
  add(`envelope-source-${label}`, envelope({ source_metadata: value }));
add('envelope-source-with-invalid-names', envelope({ source_metadata: SOURCES.v1, electrode_names: LABELS.slice(1) }));
add('envelope-source-with-invalid-request', envelope({ source_metadata: SOURCES.v1, request: request({ seed: -1 }) }));
