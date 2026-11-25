// radius-search: the body of POST /api/local-compute/jobs and /lookup, and the request of a radius cache record.
// Node's outcome is normalizeRequest, as in computeMiddleware and the community queue's local-compute adapter.
// Rejected variants also record Node's message, which eeglayoutlab.schemas.radius_search.normalize_request must
// raise (tests/service/test_radius_search.py).
import { readFileSync } from 'node:fs';
import { MASK_CODES, normalizeRequest } from '../../../webapp/server/local-compute-server.mjs';
import { DATA_PRIOR_LENGTHS_MM, ELECTRODE_COUNTS, SPATIAL_NOISE_LENGTHS_MM } from '../../../webapp/contracts/scientific-options.mjs';
import { ABSENT, Raw, collector, createRandom, label, nextUp, raw, toText } from '../support.mjs';

/** Node's option lists, compared with the Python schema's (tests/test_schema_parity.py). */
export const options = {
  mask_codes: [...MASK_CODES],
  spatial_noise_lengths_mm: [...SPATIAL_NOISE_LENGTHS_MM],
  data_prior_lengths_mm: [...DATA_PRIOR_LENGTHS_MM],
  electrode_counts: [...ELECTRODE_COUNTS],
};
export const name = 'radius-search';
export const normalize = normalizeRequest;

const { random, pick } = createRandom(0x7ad105ea);
const { variants, add, addBytes } = collector();
export { variants };

const FREE = { region_count: 2, radius_mm: 30, mode: 'whole_surface' };
const PRESET = { region_count: 2, radius_mm: 35, mode: 'preset', mask_codes: ['PL', 'PR'] };
const free = (overrides = {}) => ({ ...FREE, ...overrides });
const preset = (overrides = {}) => ({ ...PRESET, ...overrides });
const SPATIAL = { kind: 'spatial', rho: 0.5, length_mm: 20 };
const BRAIN = { kind: 'brain_background', fraction: 0.5 };
const GAINS = [1, 1.5, 0.25, 2.75, 1000, 0.001, 12.34];
const PRIOR = { region_gain: GAINS, rho: 0.3, length_mm: 20 };
const PRIOR_IID = { region_gain: GAINS, rho: 0, length_mm: null };
const shuffle = list => list.map(item => [random(), item]).sort((a, b) => a[0] - b[0]).map(([, item]) => item);
const masks = count => Array.from({ length: count }, () => pick(MASK_CODES));


// Top level
add('base', free());
add('base-pretty', raw(JSON.stringify(free(), null, 2)));
add('base-low-hair', free({ mode: 'low_hair' }));
add('base-preset', preset());
for (const [i, value] of ['[]', 'null', '1', '0', '"x"', '""', 'true', 'false', '{}', `[${toText(FREE)}]`].entries())
  add(`top-not-request-${i}`, raw(value));
for (const key of ['region_count', 'radius_mm', 'mode']) {
  add(`missing-${key}`, free({ [key]: ABSENT }));
  add(`preset-missing-${key}`, preset({ [key]: ABSENT }));
}
// Every other field is rejected; AR is a display parameter and cannot start a computation (check-local-compute.mjs).
for (const key of ['AR', 'ar', 'command', 'seed', 'extra', 'layout', 'request', 'schema', 'region_definition', 'total_electrodes',
  'mask', 'masks', 'mask_code', 'noise', 'prior', 'Region_count', 'region_count ', 'radius', '', '__proto__', 'constructor',
  'toString', 'hasOwnProperty', 'valueOf'])
  add(`extra-${JSON.stringify(key)}`, free({ [key]: 1 }));
for (const [lbl, value] of Object.entries({ fraction: 0.9, null: null, false: false, object: {}, array: [] })) {
  add(`extra-AR-${lbl}`, free({ AR: value }));
  add(`preset-extra-AR-${lbl}`, preset({ AR: value }));
}
add('duplicate-region-count-last-wins', raw(toText(free()).replace('"region_count":2', '"region_count":5,"region_count":2')));
add('duplicate-region-count-last-invalid', raw(toText(free()).replace('"region_count":2', '"region_count":2,"region_count":5')));
add('duplicate-masks-last-wins', raw(toText(preset()).replace('"mask_codes":', '"mask_codes":["PL"],"mask_codes":')));
add('duplicate-masks-last-invalid', raw(toText(preset()).replace('"mask_codes":["PL","PR"]', '"mask_codes":["PL","PR"],"mask_codes":[]')));
add('duplicate-extra', raw(toText(free()).replace('{', '{"AR":1,"AR":2,')));
add('trailing-garbage', raw(toText(free()) + 'x'));
add('trailing-comma', raw(toText(free()).replace(/}$/, ',}')));
add('trailing-whitespace', raw(' \n\t' + toText(free()) + ' \r\n'));
add('bom-prefix', raw('﻿' + toText(free())));
add('single-quotes', raw(toText(free()).replaceAll('"', "'")));
add('nan-radius', free({ radius_mm: raw('NaN') }));
add('infinity-radius', free({ radius_mm: raw('Infinity') }));
add('escaped-mode', raw(toText(free()).replace('"whole_surface"', '"\\u0077hole_surface"')));
add('escaped-mask', raw(toText(preset()).replace('"PL"', '"\\u0050L"')));
add('escaped-key', raw(toText(free()).replace('"radius_mm"', '"radius\\u005fmm"')));

// Key order: the canonical request is written in Node's order whatever the input order.
const FULL = { region_count: 3, radius_mm: 40, mode: 'preset', mask_codes: ['FL', 'FM', 'FR'], noise_model: { length_mm: 40, kind: 'spatial', rho: 0.5 } };
const FULL_PRIOR = { region_count: 6, radius_mm: 80, mode: 'low_hair', mask_codes: [], data_prior: { rho: 0, length_mm: null, region_gain: GAINS } };
for (const [id, value] of Object.entries({ noise: FULL, prior: FULL_PRIOR })) {
  add(`order-${id}`, value);
  add(`order-${id}-reversed`, Object.fromEntries(Object.entries(value).reverse()));
  for (let i = 0; i < 3; i++) add(`order-${id}-shuffled-${i}`, Object.fromEntries(shuffle(Object.entries(value))));
}

// Region count: 1, 2, 3, 4 or 6, as a number
for (const value of [0, 1, 2, 3, 4, 5, 6, 7, 8, 12, 64, -1, -2, 2.5, raw('-0'), raw('-0.0'), raw('2.0'), raw('2e0'), raw('0.2e1'), raw('20e-1'),
  raw('6E0'), raw('2.0000000000000001'), raw('2.000000000000001'), raw('1.9999999999999999'), raw('1e400'), raw('-1e400'), raw('1e-400'),
  '2', '', true, false, null, [2], {}, ABSENT])
  add(`region-count-${label(value)}`, free({ region_count: value }));
add('region-count-huge-integer', free({ region_count: raw('1' + '0'.repeat(400)) }));
add('region-count-two-with-long-zeros', free({ region_count: raw('2.' + '0'.repeat(400)) }));

// Radius: 15-80 mm in steps of 5, as an integer
for (let radius = 0; radius <= 100; radius++) add(`radius-${radius}`, free({ radius_mm: radius }));
for (const value of [raw('15.0'), raw('1.5e1'), raw('150e-1'), raw('80.0'), raw('8e1'), raw('8E+1'), raw('3e1'), raw('30.000000000000001'),
  raw('80.00000000000001'), raw('79.99999999999999'), raw('15.000000000000002'), raw('14.999999999999998'), raw('-0'), raw('-0.0'),
  raw('1e400'), raw('1e-400'), 30.5, 32.5, 17.5, -15, -30, 105, 1000, 9999, 1e21, '30', '', true, null, [30], {}, ABSENT])
  add(`radius-${label(value)}`, free({ radius_mm: value }));
add('radius-huge-integer', free({ radius_mm: raw('3' + '0'.repeat(400)) }));
for (const radius of [15, 50, 80]) add(`radius-preset-${radius}`, preset({ radius_mm: radius }));

// Mode
for (const value of ['whole_surface', 'low_hair', 'preset', 'WHOLE_SURFACE', 'Whole_surface', 'whole_surface ', ' low_hair', 'whole-surface',
  'lowhair', 'low hair', 'free', 'other', 'area', 'strict_area', 'whole_surface\u0000', 'рreset', '', null, 0, 1, true, false,
  ['whole_surface'], { mode: 'whole_surface' }, ABSENT])
  add(`mode-${label(value)}`, free({ mode: value }));

// A free mode accepts no mask_codes or an empty list, and drops it
for (const mode of ['whole_surface', 'low_hair'])
  for (const [lbl, value] of Object.entries({
    absent: ABSENT, empty: [], null: null, one: ['PL'], two: ['PL', 'PR'], emptyCode: [''], nullCode: [null], nested: [[]], string: 'PL',
    emptyString: '', object: {}, lengthObject: { length: 0 }, zero: 0, false: false, true: true,
  }))
    add(`free-masks-${mode}-${lbl}`, free({ mode, mask_codes: value }));

// Preset: exactly region_count codes from MASK_CODES, repeats allowed, order kept
for (const code of MASK_CODES) {
  add(`option-mask-${code}`, preset({ region_count: 1, mask_codes: [code] }));
  const fullWidth = [...code].map(c => String.fromCharCode(c.charCodeAt(0) + 0xfee0)).join('');
  for (const [lbl, spelling] of Object.entries({
    lower: code.toLowerCase(), padded: ` ${code}`, trailing: `${code} `, superior: `${code}_superior`, doubled: code + code,
    nul: `${code}\u0000`, fullWidth,
  }))
    add(`preset-mask-${code}-${lbl}`, preset({ region_count: 1, mask_codes: [spelling] }));
}
for (const [i, codes] of [['FR', 'OL'], ['PL', 'PL'], ['FR', 'PL', 'FM'], ['OR', 'PL', 'FR', 'AL', 'FM', 'PR'], ['AR', 'AR', 'AR', 'AR'],
  ['PL_superior', 'PR'], [...MASK_CODES], ['OR', 'OL', 'FR', 'FM', 'FL', 'AR', 'AL', 'PR', 'PL'].slice(0, 6)].entries())
  add(`preset-masks-${i}`, preset({ region_count: codes.length, mask_codes: codes }));
for (const count of [1, 2, 3, 4, 5, 6]) {
  const codes = Array.from({ length: count + 1 }, (_, i) => MASK_CODES[(count + i) % MASK_CODES.length]);
  add(`preset-count-${count}`, preset({ region_count: count, mask_codes: codes.slice(0, count) }));
  add(`preset-count-${count}-short`, preset({ region_count: count, mask_codes: codes.slice(0, count - 1) }));
  add(`preset-count-${count}-long`, preset({ region_count: count, mask_codes: codes }));
}
add('preset-count-float', preset({ region_count: raw('2.0') }));
add('preset-count-exponent', preset({ region_count: raw('3e0'), mask_codes: ['FL', 'FM', 'FR'] }));
for (const [lbl, value] of Object.entries({
  absent: ABSENT, null: null, empty: [], string: 'PL,PR', object: { 0: 'PL', 1: 'PR' }, number: 2, true: true, numberCode: ['PL', 1],
  nullCode: ['PL', null], nestedCode: ['PL', ['PR']], objectCode: ['PL', { code: 'PR' }], emptyCode: ['PL', ''],
}))
  add(`preset-masks-${lbl}`, preset({ mask_codes: value }));
for (let i = 0; i < 40; i++) {
  const count = pick([1, 2, 3, 4, 6]);
  add(`preset-random-${i}`, preset({ region_count: count, mask_codes: masks(random() < 0.8 ? count : pick([0, 1, 2, 3, 4, 5, 6, 7])) }));
}

// Noise model: the spatial presets; independent noise is dropped and brain background is for design evaluation only
for (const [lbl, value] of Object.entries({
  absent: ABSENT, null: null, iid: { kind: 'iid' }, iidExtra: { kind: 'iid', rho: 0 }, iidNullExtra: { kind: 'iid', length_mm: null },
  iidProto: { kind: 'iid', ['__proto__']: null }, spatial10: { ...SPATIAL, length_mm: 10 }, spatial20: SPATIAL, spatial40: { ...SPATIAL, length_mm: 40 },
  spatial5: { ...SPATIAL, length_mm: 5 }, spatial15: { ...SPATIAL, length_mm: 15 }, spatial30: { ...SPATIAL, length_mm: 30 },
  spatialZeroLength: { ...SPATIAL, length_mm: 0 }, spatialFloatLength: { ...SPATIAL, length_mm: raw('20.0') }, spatialExpLength: { ...SPATIAL, length_mm: raw('2e1') },
  spatialNearLength: { ...SPATIAL, length_mm: raw('20.000000000000004') }, spatialStringLength: { ...SPATIAL, length_mm: '20' },
  spatialNullLength: { ...SPATIAL, length_mm: null }, spatialRhoExp: { ...SPATIAL, rho: raw('5e-1') }, spatialRhoDigits: { ...SPATIAL, rho: raw('0.50000000000000001') },
  spatialRhoNext: { ...SPATIAL, rho: nextUp(0.5) }, spatialRhoPrevious: { ...SPATIAL, rho: nextUp(0.5, -1) }, spatialRhoQuarter: { ...SPATIAL, rho: 0.25 },
  spatialRhoString: { ...SPATIAL, rho: '0.5' }, spatialRhoTrue: { ...SPATIAL, rho: true }, spatialMissingLength: { kind: 'spatial', rho: 0.5 },
  spatialMissingRho: { kind: 'spatial', length_mm: 20 }, spatialExtra: { ...SPATIAL, unit: 'mm' }, spatialProto: { ...SPATIAL, ['__proto__']: 1 },
  spatialReordered: { length_mm: 20, rho: 0.5, kind: 'spatial' }, brain: BRAIN, brainReordered: { fraction: 0.5, kind: 'brain_background' },
  brainFraction: { ...BRAIN, fraction: 0.25 }, brainFractionExp: { ...BRAIN, fraction: raw('5E-1') }, brainTrue: { ...BRAIN, fraction: true },
  brainExtra: { ...BRAIN, rho: 0.5 }, brainMissing: { kind: 'brain_background' }, pink: { kind: 'pink' }, noKind: { rho: 0.5 }, empty: {},
  false: false, true: true, zero: 0, one: 1, emptyString: '', string: 'spatial', array: [], arraySpatial: [SPATIAL], kindNumber: { kind: 1 },
  kindNull: { kind: null }, kindUpper: { kind: 'IID' }, kindSpatialUpper: { ...SPATIAL, kind: 'Spatial' },
  // Node compares the sorted names joined with commas, so a name that contains a comma can match them.
  commaKindLength: { 'kind,length_mm': 'spatial', rho: 0.5 }, commaLengthRho: { kind: 'spatial', 'length_mm,rho': 20 },
  commaAll: { 'kind,length_mm,rho': 'spatial' }, commaFractionKind: { 'fraction,kind': 'brain_background' },
}))
  add(`noise-${lbl}`, free({ noise_model: value }));
add('noise-spatial-preset', preset({ noise_model: { ...SPATIAL, length_mm: 40 } }));
add('noise-iid-preset', preset({ noise_model: { kind: 'iid' } }));
add('noise-brain-before-region-count', free({ noise_model: BRAIN, region_count: 5 }));

// Data prior: the request value of an eeg-data-prior/1 file, rejected and never rounded
const gains = (i, value) => GAINS.map((g, j) => (j === i ? value : g));
for (const [lbl, value] of Object.entries({
  absent: ABSENT, null: null, valid: PRIOR, iidPrior: PRIOR_IID, reordered: { length_mm: 20, rho: 0.3, region_gain: GAINS },
  minusZeroRho: { ...PRIOR_IID, rho: raw('-0.0') }, tinyRho: { ...PRIOR_IID, rho: raw('1e-400') }, tinyRhoLength: { ...PRIOR, rho: raw('1e-400') },
  rhoMax: { ...PRIOR, rho: 0.95 }, rhoAboveMax: { ...PRIOR, rho: nextUp(0.95) }, rhoOver: { ...PRIOR, rho: 0.96 }, rhoNegative: { ...PRIOR, rho: -0.01 },
  rhoOne: { ...PRIOR, rho: 1 }, rho007: { ...PRIOR, rho: 0.07 }, rho029: { ...PRIOR, rho: 0.29 }, rho057: { ...PRIOR, rho: 0.57 },
  rho0015: { ...PRIOR, rho: 0.015 }, rho0125: { ...PRIOR, rho: 0.125 }, rhoTrailingZero: { ...PRIOR, rho: raw('0.30') }, rhoExp: { ...PRIOR, rho: raw('3e-1') },
  rhoString: { ...PRIOR, rho: '0.3' }, rhoTrue: { ...PRIOR, rho: true }, rhoNull: { ...PRIOR, rho: null }, rhoArray: { ...PRIOR, rho: [0.3] },
  rhoZeroLength: { ...PRIOR_IID, length_mm: 10 }, rhoLengthNull: { ...PRIOR, length_mm: null }, lengthFloat: { ...PRIOR, length_mm: raw('20.0') },
  length25: { ...PRIOR, length_mm: 25 }, length0: { ...PRIOR, length_mm: 0 }, lengthString: { ...PRIOR, length_mm: '20' }, lengthFalse: { ...PRIOR_IID, length_mm: false },
  lengthZeroWithZeroRho: { ...PRIOR_IID, length_mm: 0 }, lengthMissing: { region_gain: GAINS, rho: 0 }, extra: { ...PRIOR, id: 'x' },
  proto: { ...PRIOR, ['__proto__']: 1 }, commaLengthGain: { 'length_mm,region_gain': 20, rho: 0.3 }, commaGainRho: { length_mm: 20, 'region_gain,rho': GAINS },
  commaAll: { 'length_mm,region_gain,rho': GAINS }, gains6: { ...PRIOR, region_gain: GAINS.slice(1) }, gains8: { ...PRIOR, region_gain: [...GAINS, 1] },
  gainZero: { ...PRIOR, region_gain: gains(0, 0) }, gainMin: { ...PRIOR, region_gain: gains(0, 0.001) }, gainBelowMin: { ...PRIOR, region_gain: gains(0, nextUp(0.001, -1)) },
  gainTooSmall: { ...PRIOR, region_gain: gains(0, 0.0009999) }, gainTooLarge: { ...PRIOR, region_gain: gains(0, 1000.1) },
  gainRoundsToMax: { ...PRIOR, region_gain: gains(1, 999.95) }, gainExp: { ...PRIOR, region_gain: gains(0, raw('1e3')) },
  gainFloatLiteral: { ...PRIOR, region_gain: gains(0, raw('1000.0')) }, gainFiveDigits: { ...PRIOR, region_gain: gains(0, 1.2345) },
  gainFourDigits: { ...PRIOR, region_gain: [1.234, 12.34, 123.4, 9.999, 0.001234, 0.01, 999.9] }, gainTie: { ...PRIOR, region_gain: gains(0, 1.0625) },
  gainNegative: { ...PRIOR, region_gain: gains(0, -1) }, gainString: { ...PRIOR, region_gain: gains(0, '1') }, gainTrue: { ...PRIOR, region_gain: gains(0, true) },
  gainNull: { ...PRIOR, region_gain: gains(6, null) }, gainNested: { ...PRIOR, region_gain: gains(3, [1]) }, gainsObject: { ...PRIOR, region_gain: { ...GAINS } },
  gainsNotArray: { ...PRIOR, region_gain: 'x' }, empty: {}, false: false, zero: 0, array: [], string: 'eeg-data-prior/1',
}))
  add(`prior-${lbl}`, free({ data_prior: value }));
add('prior-with-spatial', free({ data_prior: PRIOR, noise_model: SPATIAL }));
add('prior-with-iid', free({ data_prior: PRIOR, noise_model: { kind: 'iid' } }));
add('prior-with-null-noise', free({ data_prior: PRIOR, noise_model: null }));
add('prior-with-brain', free({ data_prior: PRIOR, noise_model: BRAIN }));
add('prior-with-pink', free({ data_prior: PRIOR, noise_model: { kind: 'pink' } }));
add('prior-invalid-with-spatial', free({ data_prior: { ...PRIOR, rho: 0.96 }, noise_model: SPATIAL }));
add('prior-preset', preset({ data_prior: PRIOR_IID }));
add('prior-preset-iid-noise', preset({ data_prior: PRIOR, noise_model: { kind: 'iid' }, mask_codes: ['OL', 'OR'] }));

// One request per value of Node's option lists, so that a value added on one side only fails parity.
for (const length_mm of SPATIAL_NOISE_LENGTHS_MM) add(`option-noise-length-${length_mm}`, free({ noise_model: { ...SPATIAL, length_mm } }));
for (const length_mm of DATA_PRIOR_LENGTHS_MM) add(`option-prior-length-${length_mm}`, free({ data_prior: { ...PRIOR, length_mm } }));

// Node checks in a fixed order, and the first failing rule gives the message.
add('first-unknown-field', free({ AR: 1, noise_model: 'x', data_prior: 'x', region_count: 5, radius_mm: 1, mode: 'x' }));
add('first-noise', free({ noise_model: 'x', data_prior: 'x', region_count: 5, radius_mm: 1, mode: 'x' }));
add('first-prior', free({ data_prior: 'x', region_count: 5, radius_mm: 1, mode: 'x' }));
add('first-prior-noise', free({ data_prior: PRIOR, noise_model: SPATIAL, region_count: 5 }));
add('first-region-count', free({ region_count: 5, radius_mm: 1, mode: 'x', mask_codes: 'x' }));
add('first-radius', free({ radius_mm: 1, mode: 'x', mask_codes: 'x' }));
add('first-mode', free({ mode: 'x', mask_codes: 'x' }));

// The requests of the Node tests that this format mirrors (check-local-compute.mjs, check-lab-workflow.mjs, check-data-prior.mjs).
const LOCAL = { region_count: 2, radius_mm: 35, mode: 'preset', mask_codes: ['PL', 'PR'] };
add('local-compute-request', LOCAL);
for (const [lbl, value] of Object.entries({
  radius9999: { ...LOCAL, radius_mm: 9999 }, radius36: { ...LOCAL, radius_mm: 36 }, regions5: { ...LOCAL, region_count: 5 },
  subdividedMask: { ...LOCAL, mask_codes: ['PL_superior', 'PR'] }, command: { ...LOCAL, command: 'anything' }, AR: { ...LOCAL, AR: 0.9 },
  emptyMask: { region_count: 1, radius_mm: 15, mode: 'whole_surface', mask_codes: [] },
}))
  add(`local-compute-${lbl}`, value);
add('data-prior-search', free({ data_prior: PRIOR }));
add('data-prior-search-with-spatial', free({ data_prior: PRIOR, noise_model: SPATIAL }));
add('allocation-adaptive-preset', preset({ allocation_mode: 'adaptive' }));
add('allocation-adaptive-free', free({ allocation_mode: 'adaptive' }));
add('allocation-balanced-dropped', preset({ allocation_mode: 'balanced' }));
add('allocation-null-dropped', preset({ allocation_mode: null }));
add('allocation-single-rejected', free({ region_count: 1, allocation_mode: 'adaptive' }));
add('allocation-invalid-rejected', preset({ allocation_mode: 'free' }));
add('objective-composite-preset', preset({ objective_mode: 'composite' }));
add('objective-composite-adaptive', preset({ allocation_mode: 'adaptive', objective_mode: 'composite' }));
add('objective-min-dropped', preset({ objective_mode: 'min' }));
add('objective-null-dropped', preset({ objective_mode: null }));
add('objective-invalid-rejected', preset({ objective_mode: 'shannon' }));
for (const count of ELECTRODE_COUNTS) {
  add(`option-electrode-count-${count}`, preset({ electrode_count: count }));
}
for (const [lbl, value] of Object.entries({
  absent: ABSENT, null: null, default64: 64, float16: raw('16.0'), exp24: raw('2.4e1'), nonStep20: 20, zero: 0, negative: -16,
  half: 16.5, string16: '16', boolTrue: true, array16: [16], obj: {},
}))
  add(`electrode-count-${lbl}`, preset({ electrode_count: value }));
add('electrode-count-r6-8-rejected', free({ region_count: 6, electrode_count: 8 }));
add('electrode-count-r6-12-accepted', free({ region_count: 6, electrode_count: 12 }));
add('electrode-count-r4-adaptive-12-rejected', free({ region_count: 4, allocation_mode: 'adaptive', electrode_count: 12 }));
add('electrode-count-r4-adaptive-16-accepted', free({ region_count: 4, allocation_mode: 'adaptive', electrode_count: 16 }));
add('electrode-count-r6-adaptive-16-rejected', free({ region_count: 6, allocation_mode: 'adaptive', electrode_count: 16 }));
add('electrode-count-r6-adaptive-24-accepted', free({ region_count: 6, allocation_mode: 'adaptive', electrode_count: 24 }));
add('electrode-count-full-order-shuffled', {
  electrode_count: 24, objective_mode: 'composite', allocation_mode: 'adaptive',
  noise_model: SPATIAL, mask_codes: ['PL', 'FM'], mode: 'preset', radius_mm: 30, region_count: 2,
});

// Raw bytes: the body is decoded as UTF-8 with replacement before JSON.parse.
for (const [lbl, bytes] of Object.entries({
  invalidByte: [0xff], truncatedTwo: [0xc3], encodedSurrogate: [0xed, 0xa0, 0x80], overlong: [0xc0, 0xaf], valid: [0xe2, 0x82, 0xac],
})) {
  const [before, after] = toText(free()).split('whole_surface');
  addBytes(`bytes-mode-${lbl}`, [...Buffer.from(before), ...Buffer.from('whole_surface'), ...bytes, ...Buffer.from(after)]);
  addBytes(`bytes-key-${lbl}`, [...Buffer.from('{"'), ...bytes, ...Buffer.from(`":1,${toText(free()).slice(1)}`)]);
}
addBytes('bytes-plain', [...Buffer.from(toText(preset()))]);
addBytes('bytes-bom', [0xef, 0xbb, 0xbf, ...Buffer.from(toText(free()))]);

// Shared fixtures (contracts/fixtures/requests.json): generate.mjs checks that Node still gives the recorded outcome.
const corpus = JSON.parse(readFileSync(new URL('../../../contracts/fixtures/requests.json', import.meta.url), 'utf8'));
for (const sample of corpus.cases.filter(sample => sample.service === 'radius'))
  add(`fixture-${sample.name}`, raw(JSON.stringify(sample.request)),
    { accepted: sample.valid, canonical: sample.valid ? JSON.stringify(sample.canonical) : null });

// Random combinations of every field, in random key order; each field is mostly valid, so that about a third pass.
const COUNT = Symbol('codes for the region count');
const SHORT = Symbol('one code too few');
const POOLS = {
  region_count: [1, 2, 3, 4, 6, 1, 2, 3, 4, 6, raw('2.0'), raw('6e0'), 5, true],
  radius_mm: [15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, raw('40.0'), raw('8e1'), 36, '30'],
  mode: ['whole_surface', 'whole_surface', 'low_hair', 'low_hair', 'preset', 'preset', 'preset', 'preset', 'other'],
  mask_codes: null,
  noise_model: [ABSENT, ABSENT, ABSENT, ABSENT, null, { kind: 'iid' }, SPATIAL, { ...SPATIAL, length_mm: 40 }, { ...SPATIAL, length_mm: 10 }, BRAIN, { kind: 'pink' }],
  data_prior: [ABSENT, ABSENT, ABSENT, ABSENT, ABSENT, null, PRIOR, PRIOR_IID, { ...PRIOR, length_mm: 5 }, { ...PRIOR, rho: 0.015 }],
  AR: [...Array(15).fill(ABSENT), 0.9],
};
const MASK_POOLS = {
  preset: [COUNT, COUNT, COUNT, COUNT, COUNT, COUNT, SHORT, ['XX'], ABSENT],
  free: [ABSENT, ABSENT, ABSENT, ABSENT, [], [], [], null, ['PL']],
};
for (let i = 0; i < 600; i++) {
  const fields = Object.fromEntries(Object.entries(POOLS).map(([key, pool]) => [key, pool && pick(pool)]));
  const count = fields.region_count instanceof Raw ? Number(fields.region_count.text) : typeof fields.region_count === 'number' ? fields.region_count : 2;
  fields.mask_codes = pick(MASK_POOLS[fields.mode === 'preset' ? 'preset' : 'free']);
  if (fields.mask_codes === COUNT) fields.mask_codes = masks(count);
  if (fields.mask_codes === SHORT) fields.mask_codes = masks(count - 1);
  add(`combo-${i}`, Object.fromEntries(random() < 0.3 ? shuffle(Object.entries(fields)) : Object.entries(fields)));
}
