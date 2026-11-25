// robustness-study: the body of POST /api/robustness-studies. Node's outcome is normalizeStudyInput, as in
// RobustnessStudyService.create. Rejected variants also record Node's message, which
// eeglayoutlab.jobs.studies.normalize_study_input must raise (tests/service/test_study_request.py).
import { readFileSync } from 'node:fs';
import { STUDY_PROTOCOLS, nominalMetrics, normalizeStudyInput, trialMetrics } from '../../../webapp/server/studies/protocol.mjs';
import { SOURCES } from './coordinate-source.mjs';
import { ABSENT, collector, createRandom, label, raw, toText } from '../support.mjs';

export const name = 'robustness-study';
export const normalize = normalizeStudyInput;

// The status values: the types of webapp/contracts/robustness-study.ts, which must equal the lists the study store
// checks records with (studies/store.mjs keeps them unexported).
const source = file => readFileSync(new URL(`../../../webapp/${file}`, import.meta.url), 'utf8');
const quoted = (text, quote) => [...text.matchAll(quote === "'" ? /'([^']*)'/g : /"([^"]*)"/g)].map(match => match[1]);
const typeValues = type => quoted(source('contracts/robustness-study.ts').match(new RegExp(`export type ${type} =([^;]*);`))[1], "'");
const storeList = list => quoted(source('server/studies/store.mjs').match(new RegExp(`const ${list} = \\[([^\\]]*)\\]`))[1], '"');
const STUDY_STATUSES = typeValues('StudyStatus'), CASE_STATUSES = typeValues('StudyCaseStatus');
if (JSON.stringify(STUDY_STATUSES) !== JSON.stringify(storeList('statuses')) ||
    JSON.stringify(CASE_STATUSES) !== JSON.stringify(storeList('caseStatuses')))
  throw new Error('robustness-study.ts and studies/store.mjs list different statuses');
if (JSON.stringify(typeValues('StudyProtocol')) !== JSON.stringify(STUDY_PROTOCOLS))
  throw new Error('robustness-study.ts and studies/protocol.mjs list different protocols');

/** Node's lists, compared with eeglayoutlab.jobs.studies (tests/test_schema_parity.py). */
export const options = {
  protocols: [...STUDY_PROTOCOLS], study_statuses: STUDY_STATUSES, case_statuses: CASE_STATUSES,
  nominal_metrics: [...nominalMetrics], trial_metrics: [...trialMetrics],
};

const { random, rand32, pick } = createRandom(0x57d1e5ed);
const { variants, add, addBytes } = collector();
export { variants };

const grid = (spacing = 6, z = () => 0) => Array.from({ length: 64 }, (_, i) => [(i % 8) * spacing, Math.floor(i / 8) * spacing, z(i)]);
const balanced = r => Array.from({ length: 64 }, (_, i) => i % r);
const DESIGN = {
  schema: 'eeg-electrode-design/1', coordinate_system: 'ernie_native_mm', unit: 'mm', name: 'Original scientific name',
  xyz_mm: grid(), region_indices: balanced(2),
};
const design = (overrides = {}) => ({ ...DESIGN, ...overrides });
const NAMES = Array.from({ length: 64 }, (_, i) => `Channel ${i + 1}`);
const seeds = (list, radius = 6) => list.map(seed => ({ seed, radius_mm: radius }));
const study = (overrides = {}) => ({ protocol: 'noise_seeds', design: DESIGN, cases: seeds([42, 43]), ...overrides });
const gridStudy = (overrides = {}) =>
  study({ protocol: 'grid_displacements', cases: [{ seed: 42, radius_mm: 3 }, { seed: 42, radius_mm: 10 }], ...overrides });
const HEADS = ['ernie_xh', 'ixi002', 'ixi012', 'ixi025', 'a', 'a_b-c', 'mni152', 'h7', 'h8', 'h9', 'h10', 'h11', 'h12', 'h13'];
const headCases = (count = 2, seed = 42, radius = 6) => HEADS.slice(0, count).map(head_id => ({ head_id, seed, radius_mm: radius }));
const headStudy = (overrides = {}) => study({ protocol: 'heads', cases: headCases(), ...overrides });
const BUILDERS = { noise: study, grid: gridStudy, heads: headStudy };
/** The study with case `at` replaced (written with toText, so it may hold Raw values or ABSENT). */
const withCase = (build, at, value) => {
  const base = build();
  return { ...base, cases: base.cases.map((entry, i) => (i === at ? value : entry)) };
};
const shuffle = list => list.map(item => [random(), item]).sort((a, b) => a[0] - b[0]).map(([, item]) => item);
/** A variant-name label, shortened for long number spellings. */
const short = value => (label(value).length > 24 ? `${label(value).slice(0, 12)}…${label(value).length}` : label(value));

// Top level
add('base-noise', study());
add('base-grid', gridStudy());
add('base-heads', headStudy());
add('base-pretty', raw(JSON.stringify(study({ title: 'Pretty', notes: 'n' }), null, 2)));
add('base-reordered', Object.fromEntries(Object.entries(study({ title: 'T', notes: 'N' })).reverse()));
for (let i = 0; i < 3; i++)
  add(`base-shuffled-${i}`, Object.fromEntries(shuffle(Object.entries(headStudy({ title: 'T', notes: 'N', noise_model: { kind: 'iid' } })))));
for (const [i, value] of ['[]', 'null', '1', '0', '"x"', '""', 'true', 'false', '{}', '[{}]', `[${toText(study())}]`, '"noise_seeds"'].entries())
  add(`top-not-study-${i}`, raw(value));
add('trailing-garbage', raw(toText(study()) + 'x'));
add('trailing-whitespace', raw(' \n\t' + toText(study()) + ' \r\n'));
add('bom-prefix', raw('﻿' + toText(study())));
add('escaped-protocol', raw(toText(study()).replace('"noise_seeds"', '"\\u006eoise_seeds"')));
add('escaped-key', raw(toText(study()).replace('"cases"', '"\\u0063ases"')));
add('duplicate-protocol-last-wins', raw(toText(study()).replace('"protocol":"noise_seeds"', '"protocol":"x","protocol":"noise_seeds"')));
add('duplicate-cases-last-wins', raw(toText(study()).replace('"cases":', '"cases":[],"cases":')));
add('duplicate-cases-last-empty', raw(toText(study()).replace(/}$/, ',"cases":[]}')));

// Fields: only the seven study fields; each optional one may be left out
for (const key of ['protocol', 'design', 'cases', 'title', 'notes', 'noise_model', 'conductivity_scenario'])
  add(`missing-${key}`, study({ title: 'T', notes: 'N', noise_model: { kind: 'iid' }, conductivity_scenario: '', [key]: ABSENT }));
for (const key of ['requests', 'annotation', 'action', 'radius_mm', 'seed', 'head_id', 'electrode_names', 'source_metadata', 'identity',
  'owner', 'id', 'status', 'robustness', 'data_prior', '__proto__', 'constructor', 'toString', '', 'Protocol', 'protocol ', 'cases,design', 'title,notes'])
  for (const [lbl, value] of Object.entries({ one: 1, null: null }))
    add(`extra-${JSON.stringify(key)}-${lbl}`, study({ [key]: value }));
add('extra-and-bad-protocol', study({ extra: 1, protocol: 'x' }));

// Protocol: one of Node's three, as a string
for (const value of [...STUDY_PROTOCOLS, 'Noise_seeds', 'NOISE_SEEDS', 'noise_seeds ', ' heads', 'heads\u0000', 'noise-seeds', 'grid', 'evaluate',
  'perturb', 'head', '', null, 0, 1, true, ['heads'], { protocol: 'heads' }, ABSENT]) {
  add(`protocol-${label(value)}-noise-cases`, study({ protocol: value }));
  add(`protocol-${label(value)}-head-cases`, headStudy({ protocol: value }));
}

// Cases: an array of 1 to 12
for (const [lbl, value] of Object.entries({
  null: null, object: { 0: { seed: 42, radius_mm: 6 } }, lengthObject: { length: 1 }, string: 'x', number: 1, true: true, empty: [],
  emptyString: '', nested: [seeds([42])], pairs: [[42, 6]], commaString: 'radius_mm,seed',
}))
  for (const [kind, build] of Object.entries(BUILDERS)) add(`cases-${lbl}-${kind}`, build({ cases: value }));
for (const count of [...Array.from({ length: 13 }, (_, i) => i + 1), 24]) {
  add(`cases-count-${count}-noise`, study({ cases: seeds(Array.from({ length: count }, (_, i) => i * 7)) }));
  add(`cases-count-${count}-grid`, gridStudy({ cases: Array.from({ length: count }, (_, i) => ({ seed: Math.floor(i / 3), radius_mm: [3, 6, 10][i % 3] })) }));
  add(`cases-count-${count}-heads`, headStudy({ cases: headCases(Math.min(count, HEADS.length)) }));
}
add('cases-count-13-heads-repeated', headStudy({ cases: [...headCases(12), headCases(1)[0]] }));
add('cases-count-13-invalid-cases', study({ cases: Array.from({ length: 13 }, () => null) }));

// A case is exactly {seed, radius_mm}, or {head_id, seed, radius_mm} in a cross-head study
const CASE_VALUES = {
  null: null, zero: 0, one: 1, emptyString: '', string: 'x', true: true, false: false, array: [], pair: [42, 6], empty: {},
  onlySeed: { seed: 42 }, onlyRadius: { radius_mm: 6 }, extra: { seed: 44, radius_mm: 6, extra: 1 }, extraNull: { seed: 44, radius_mm: 6, x: null },
  head: { head_id: 'ixi025', seed: 42, radius_mm: 6 }, headNull: { head_id: null, seed: 42, radius_mm: 6 }, design: { seed: 44, radius_mm: 6, design: DESIGN },
  action: { seed: 44, radius_mm: 6, action: 'evaluate' }, proto: { seed: 44, radius_mm: 6, ['__proto__']: 1 }, upper: { Seed: 44, radius_mm: 6 },
  radius: { seed: 44, radius: 6 }, commaKey: { 'radius_mm,seed': 6 }, commaKeyExtra: { 'radius_mm,seed': 6, radius_mm: 6 },
  commaHeadSeed: { 'head_id,radius_mm': 'ixi025', seed: 42 }, commaHeadRadius: { head_id: 'ixi025', 'radius_mm,seed': 6 },
  commaHeadAll: { 'head_id,radius_mm,seed': 'ixi025' }, leadingComma: { ',seed': 42, radius_mm: 6 }, emptyKey: { '': 1, seed: 44, radius_mm: 6 },
  reversed: { radius_mm: 6, seed: 44 }, headReversed: { radius_mm: 6, seed: 42, head_id: 'ixi025' },
};
for (const [lbl, value] of Object.entries(CASE_VALUES))
  for (const [kind, build] of Object.entries(BUILDERS))
    for (const at of [0, 1]) add(`case-${at}-${lbl}-${kind}`, withCase(build, at, value));
for (const order of [['head_id', 'seed', 'radius_mm'], ['seed', 'head_id', 'radius_mm'], ['radius_mm', 'seed', 'head_id'], ['seed', 'radius_mm', 'head_id']])
  add(`case-head-key-order-${order.join('-')}`, headStudy({ cases: headCases(3).map(entry => Object.fromEntries(order.map(key => [key, entry[key]]))) }));
add('case-duplicate-seed-last-wins', raw(toText(study()).replace('{"seed":42,', '{"seed":43,"seed":42,')));
add('case-duplicate-seed-last-repeats', raw(toText(study()).replace('{"seed":42,', '{"seed":42,"seed":43,')));
add('case-duplicate-head-last-wins', raw(toText(headStudy()).replace('{"head_id":"ernie_xh",', '{"head_id":"ixi002","head_id":"ernie_xh",')));

// Title and notes: strings; null or absent means the default; the title is trimmed and not blank
const TITLES = {
  absent: ABSENT, null: null, empty: '', space: ' ', whitespace: '\t\n\r\v\f', nbsp: ' ', bom: '﻿', ideographic: '　',
  lineSeparator: ' ', zeroWidth: '​', mongolian: '᠎', nel: '\u0085', nul: '\u0000', x: 'x', padded: ' x ', tabs: '\tTitle\n',
  exact200: 'a'.repeat(200), over200: 'a'.repeat(201), padded200: ' '.repeat(10) + 'a'.repeat(190), padded201: ' '.repeat(11) + 'a'.repeat(190),
  emoji199: 'a'.repeat(198) + '😀', emoji201: 'a'.repeat(199) + '😀', emoji100: '😀'.repeat(100), emoji101: '😀'.repeat(101),
  cjk: '稳健性研究', default: 'Robustness study', zero: 0, one: 1, true: true, false: false, array: [], list: ['t'], object: {},
};
for (const [lbl, value] of Object.entries(TITLES)) {
  add(`title-${lbl}`, study({ title: value }));
  add(`notes-${lbl}`, study({ notes: value }));
}
for (const [lbl, value] of Object.entries({ exact2000: 'x'.repeat(2000), over2000: 'x'.repeat(2001), emoji1000: '😀'.repeat(1000),
  emoji1001: '😀'.repeat(1000) + 'x', blank2000: ' '.repeat(2000), newline: '\n' }))
  add(`notes-${lbl}`, study({ notes: value }));
add('title-lone-high', raw(toText(study({ title: 'T' })).replace('"title":"T"', '"title":"\\ud800"')));
add('title-lone-low', raw(toText(study({ title: 'T' })).replace('"title":"T"', '"title":" \\udc00x "')));
add('title-escaped-pair', raw(toText(study({ title: 'T' })).replace('"title":"T"', `"title":"${'a'.repeat(199)}\\ud83d\\ude00"`)));
add('notes-lone-surrogates', raw(toText(study({ notes: 'N' })).replace('"notes":"N"', '"notes":"\\udbff\\udfff\\ud800"')));
add('title-and-notes-invalid', study({ title: '', notes: 1 }));
add('title-invalid-and-cases-invalid', study({ title: '', cases: [] }));
add('title-invalid-and-heads-scenario', headStudy({ title: 1, conductivity_scenario: 'skull_x2' }));

// Noise model: one for every case; independent noise is left out
const NOISE = {
  absent: ABSENT, null: null, iid: { kind: 'iid' }, spatial10: { kind: 'spatial', rho: 0.5, length_mm: 10 }, spatial20: { kind: 'spatial', rho: 0.5, length_mm: 20 },
  spatial40: { kind: 'spatial', rho: 0.5, length_mm: 40 }, spatialReordered: { length_mm: 20, kind: 'spatial', rho: 0.5 },
  spatialFloat: { kind: 'spatial', rho: raw('0.50'), length_mm: raw('2e1') }, spatialRho: { kind: 'spatial', rho: 0.25, length_mm: 20 },
  spatialLength: { kind: 'spatial', rho: 0.5, length_mm: 30 }, brain: { kind: 'brain_background', fraction: 0.5 },
  brainFraction: { kind: 'brain_background', fraction: 1 }, iidExtra: { kind: 'iid', x: 1 }, other: { kind: 'other' }, string: 'iid',
  array: [], empty: {}, zero: 0, false: false, emptyString: '',
};
for (const [lbl, value] of Object.entries(NOISE))
  for (const [kind, build] of Object.entries(BUILDERS)) add(`noise-${lbl}-${kind}`, build({ noise_model: value }));

// Conductivity scenario: Ernie evaluations only; any value fails a cross-head study, null and '' included
const SCENARIOS = { absent: ABSENT, null: null, empty: '', skull_x2: 'skull_x2', 'skull_x0.5': 'skull_x0.5', skull_x3: 'skull_x3', upper: 'SKULL_X2',
  zero: 0, false: false, array: ['skull_x2'], object: {} };
for (const [lbl, value] of Object.entries(SCENARIOS))
  for (const [kind, build] of Object.entries(BUILDERS)) add(`scenario-${lbl}-${kind}`, build({ conductivity_scenario: value }));
add('scenario-with-spatial-noise', study({ conductivity_scenario: 'skull_x0.5', noise_model: NOISE.spatial40 }));
add('scenario-with-bad-noise', study({ conductivity_scenario: 'skull_x9', noise_model: NOISE.other }));

// Head packages: one per case, a non-empty string; the design-evaluation rules then check it
const HEAD_IDS = {
  ernie_xh: 'ernie_xh', ixi002: 'ixi002', a: 'a', dashed: 'a_b-c', exact40: 'a'.repeat(40), over40: 'a'.repeat(41), empty: '', upper: 'IXI002',
  slash: 'IXI/002', doubleUnderscore: 'a__b', trailingDash: 'a-', leadingDash: '-a', space: 'a b', newline: 'ixi002\n', dot: 'ixi.002',
  zero: 0, null: null, true: true, array: [], list: ['ixi002'], object: {}, absent: ABSENT,
};
for (const [lbl, value] of Object.entries(HEAD_IDS))
  for (const at of [0, 1]) add(`head-${at}-${lbl}`, withCase(headStudy, at, { head_id: value, seed: 42, radius_mm: 6 }));
add('heads-repeated', headStudy({ cases: [headCases(1)[0], headCases(1)[0]] }));
add('heads-repeated-late', headStudy({ cases: [...headCases(5), headCases(3)[2]] }));
add('heads-other-seed', headStudy({ cases: [{ head_id: 'ernie_xh', seed: 42, radius_mm: 6 }, { head_id: 'ixi002', seed: 7, radius_mm: 6 }] }));
add('heads-repeated-and-other-seed', headStudy({ cases: [{ head_id: 'ixi002', seed: 42, radius_mm: 6 }, { head_id: 'ixi002', seed: 43, radius_mm: 6 }] }));
add('heads-other-radius', headStudy({ cases: [{ head_id: 'ixi002', seed: 42, radius_mm: 6 }, { head_id: 'ixi012', seed: 42, radius_mm: 3 }] }));
add('heads-other-seed-and-radius', headStudy({ cases: [{ head_id: 'ixi002', seed: 42, radius_mm: 6 }, { head_id: 'ixi012', seed: 43, radius_mm: 3 }] }));
add('heads-seed-minus-zero', headStudy({ cases: [{ head_id: 'ixi002', seed: 0, radius_mm: 6 }, { head_id: 'ixi012', seed: raw('-0'), radius_mm: 6 }] }));
add('heads-seed-spellings', headStudy({ cases: [{ head_id: 'ixi002', seed: 42, radius_mm: 6 }, { head_id: 'ixi012', seed: raw('4.2e1'), radius_mm: raw('6.0') }] }));
add('heads-one', headStudy({ cases: headCases(1) }));
add('heads-twelve-radius-ten', headStudy({ cases: headCases(12, 9999, 10) }));
add('heads-perturbation-radius', headStudy({ cases: headCases(3, 0, 3) }));

// Seeds and radii of each case: the design-evaluation rules
const RADII = [3, 6, 10, raw('6.0'), raw('6e0'), raw('0.6e1'), raw('-0'), 0, 4, -6, '6', null, true, [6], raw('6.000000000000001'), raw('6.0000000000000001'), ABSENT];
const SEEDS = [0, 1, 9999, 10000, -1, raw('-0'), raw('42.0'), raw('4.2e1'), 2.5, '42', null, true, [42], raw('1e400'), raw('9999.0000000000001'),
  raw('1' + '0'.repeat(400)), ABSENT];
for (const value of RADII) {
  add(`radius-${short(value)}-noise`, study({ cases: [{ seed: 42, radius_mm: value }, { seed: 43, radius_mm: value }] }));
  add(`radius-${short(value)}-grid`, withCase(gridStudy, 1, { seed: 42, radius_mm: value }));
  add(`radius-${short(value)}-heads`, withCase(headStudy, 0, { head_id: 'ernie_xh', seed: 42, radius_mm: value }));
}
for (const value of SEEDS) {
  add(`seed-${short(value)}-noise`, withCase(study, 1, { seed: value, radius_mm: 6 }));
  add(`seed-${short(value)}-grid`, withCase(gridStudy, 0, { seed: value, radius_mm: 3 }));
  add(`seed-${short(value)}-heads`, headStudy({ cases: headCases(2).map(entry => ({ ...entry, seed: value })) }));
}

// Unique seed/radius pairs; noise-seed (and cross-head) studies hold the radius fixed
add('pairs-repeated', study({ cases: seeds([42, 42]) }));
add('pairs-repeated-late', study({ cases: seeds([1, 2, 3, 4, 5, 3]) }));
add('pairs-minus-zero', study({ cases: [{ seed: 0, radius_mm: 6 }, { seed: raw('-0'), radius_mm: 6 }] }));
add('pairs-float-spelling', study({ cases: [{ seed: 42, radius_mm: 6 }, { seed: raw('42.0'), radius_mm: raw('6e0') }] }));
add('pairs-other-radius', study({ cases: [{ seed: 42, radius_mm: 3 }, { seed: 43, radius_mm: 6 }] }));
add('pairs-same-seed-other-radius', study({ cases: [{ seed: 42, radius_mm: 3 }, { seed: 42, radius_mm: 6 }] }));
add('pairs-repeated-and-other-radius', study({ cases: [{ seed: 42, radius_mm: 3 }, { seed: 42, radius_mm: 3 }, { seed: 1, radius_mm: 6 }] }));
add('grid-repeated', gridStudy({ cases: [{ seed: 42, radius_mm: 3 }, { seed: 42, radius_mm: 3 }] }));
add('grid-same-radius', gridStudy({ cases: [{ seed: 42, radius_mm: 3 }, { seed: 43, radius_mm: 3 }] }));
add('grid-all-pairs', gridStudy({ cases: [0, 1, 2, 3].flatMap(seed => [3, 6, 10].map(radius_mm => ({ seed, radius_mm }))) }));
add('grid-reordered-pairs', gridStudy({ cases: [{ radius_mm: 10, seed: 9 }, { radius_mm: 3, seed: 9 }, { radius_mm: 6, seed: 0 }] }));

// The design: normalizeDesignRequest's rules, run for each case in turn
const DESIGNS = {
  absent: ABSENT, null: null, array: [], string: 'x', empty: {}, number: 1, schema: design({ schema: 'eeg-electrode-design/2' }),
  frame: design({ coordinate_system: 'mni_mm' }), unit: design({ unit: 'cm' }), points63: design({ xyz_mm: grid().slice(0, 63) }),
  duplicatePoint: design({ xyz_mm: grid().map((p, i) => (i === 1 ? [0, 0, 0] : p)) }), spacing: design({ xyz_mm: grid(3.9) }),
  regions: design({ region_indices: balanced(5) }), unbalanced: design({ region_indices: grid().map((_, i) => (i < 40 ? 0 : 1)) }),
  labels63: design({ region_indices: balanced(2).slice(0, 63) }), six: design({ region_indices: balanced(6) }), one: design({ region_indices: balanced(1) }),
  nameNumber: design({ name: 7 }), nameAbsent: design({ name: ABSENT }), name150: design({ name: 'n'.repeat(150) }),
  nameEmoji: design({ name: 'a' + '😀'.repeat(60) }), extraFields: design({ extra: [1, 2], electrode_count: 64 }),
  floats: design({ xyz_mm: grid().map(p => p.map(v => raw(`${v}.0`))), region_indices: balanced(2).map(v => raw(`${v}e0`)) }),
  minusZero: design({ xyz_mm: grid().map((p, i) => (i === 0 ? [raw('-0'), 0, raw('-0.0')] : p)) }),
};
for (const [lbl, value] of Object.entries(DESIGNS))
  for (const [kind, build] of Object.entries(BUILDERS)) add(`design-${lbl}-${kind}`, build({ design: value }));

// Node checks in a fixed order, and the first failing rule gives the message.
add('first-case-shape-over-design', study({ design: null, cases: [{ seed: 42 }, { seed: 43, radius_mm: 6 }] }));
add('first-design-over-late-case-shape', study({ design: null, cases: [{ seed: 42, radius_mm: 6 }, { seed: 43 }] }));
add('first-head-over-design', headStudy({ design: null, cases: [{ head_id: 'IXI/002', seed: 42, radius_mm: 6 }] }));
add('first-head-package-over-design', headStudy({ design: null, cases: [{ head_id: '', seed: 42, radius_mm: 6 }] }));
add('first-design-over-radius', study({ design: design({ unit: 'cm' }), cases: seeds([42], 4) }));
add('first-noise-over-design', study({ design: null, noise_model: NOISE.other }));
add('first-scenario-over-design', gridStudy({ design: null, conductivity_scenario: 'skull_x2' }));
add('first-noise-over-scenario', gridStudy({ noise_model: NOISE.other, conductivity_scenario: 'skull_x2' }));
add('first-late-seed', study({ cases: [{ seed: 1, radius_mm: 6 }, { seed: 2, radius_mm: 6 }, { seed: -2, radius_mm: 6 }] }));
add('first-late-seed-over-repeat', study({ cases: [{ seed: 1, radius_mm: 6 }, { seed: 1, radius_mm: 6 }, { seed: -2, radius_mm: 6 }] }));
add('first-late-head-over-repeat', headStudy({ cases: [...headCases(2), headCases(1)[0], { head_id: 'X', seed: 42, radius_mm: 6 }] }));
add('first-repeat-over-names', study({ cases: seeds([1, 1]), design: design({ electrode_names: NAMES.slice(1) }) }));
add('first-radius-over-names', study({ cases: [{ seed: 1, radius_mm: 3 }, { seed: 2, radius_mm: 6 }], design: design({ electrode_names: null }) }));
add('first-names-over-source', study({ design: design({ electrode_names: [], source_metadata: null }) }));
add('first-source-after-names', study({ design: design({ electrode_names: NAMES, source_metadata: {} }) }));

// Presentation metadata in the design: electrode names and the coordinate source stay out of every request
const NAME_LISTS = {
  valid: NAMES, absent: ABSENT, null: null, empty: [], names63: NAMES.slice(1), names65: [...NAMES, 'Extra'], repeated: [...NAMES.slice(1), NAMES[0]],
  blank: NAMES.map((n, i) => (i === 5 ? ' ' : n)), ideographicBlank: NAMES.map((n, i) => (i === 63 ? '　' : n)),
  long128: NAMES.map((n, i) => (i ? n : 'n'.repeat(128))), long129: NAMES.map((n, i) => (i ? n : 'n'.repeat(129))),
  emoji64: NAMES.map((n, i) => (i ? n : '😀'.repeat(64))), emoji65: NAMES.map((n, i) => (i ? n : '😀'.repeat(64) + 'x')),
  control: NAMES.map((n, i) => (i ? n : 'E\u0001')), delete: NAMES.map((n, i) => (i ? n : 'E\u007f')), nel: NAMES.map((n, i) => (i ? n : 'E\u0085')),
  number: NAMES.map((n, i) => (i ? n : 1)), nullName: NAMES.map((n, i) => (i ? n : null)), defaults: Array.from({ length: 64 }, (_, i) => `E${i + 1}`),
  string: 'Fp1', object: { 0: 'Fp1' },
};
for (const [lbl, value] of Object.entries(NAME_LISTS)) {
  add(`names-${lbl}`, study({ design: design({ electrode_names: value }) }));
  add(`names-${lbl}-with-source`, headStudy({ design: design({ electrode_names: value, source_metadata: SOURCES.v1 }) }));
}
for (const [id, value] of Object.entries(SOURCES)) {
  add(`source-${id}`, gridStudy({ design: design({ source_metadata: value }) }));
  add(`source-${id}-before-names`, study({ design: { ...design(), source_metadata: value, electrode_names: NAMES } }));
}
add('source-reordered', study({ design: design({ source_metadata: Object.fromEntries(Object.entries(SOURCES.v3Mni).reverse()) }) }));
for (const [lbl, value] of Object.entries({ null: null, empty: {}, string: 'x', array: [], invalidUnit: { ...SOURCES.v1, unit: 'cm' } }))
  add(`source-${lbl}`, study({ design: design({ source_metadata: value }) }));
add('source-with-default-names', study({ design: design({ source_metadata: SOURCES.v2Labels, electrode_names: NAME_LISTS.defaults }) }));

// The Node test this format mirrors (check-robustness-studies.mjs: protocols preserve normalized requests, cross-head
// studies evaluate one head per case at one radius).
add('node-test-names', study({ cases: seeds([42], 6), design: design({ electrode_names: NAMES.map((_, i) => `Channel ${i + 1}`) }) }));
add('node-test-grid', gridStudy());
for (const [lbl, value] of Object.entries({
  repeated: study({ cases: seeds([42, 42]) }), thirteen: study({ cases: seeds(Array.from({ length: 13 }, (_, i) => i)) }),
  otherRadius: study({ cases: [{ seed: 42, radius_mm: 3 }, { seed: 43, radius_mm: 6 }] }), negativeSeed: study({ cases: seeds([-1]) }),
  headScenario: headStudy({ cases: headCases(1), conductivity_scenario: 'skull_x2' }),
  headInNoise: study({ cases: [{ head_id: 'ixi002', seed: 42, radius_mm: 6 }] }),
}))
  add(`node-test-${lbl}`, value);

// Raw bytes: the body is decoded as UTF-8 with replacement before JSON.parse.
for (const [lbl, bytes] of Object.entries({
  invalidByte: [0xff], truncatedTwo: [0xc3], encodedSurrogate: [0xed, 0xa0, 0x80], overlong: [0xc0, 0xaf], valid: [0xe2, 0x82, 0xac],
})) {
  const [before, after] = toText(study({ title: 'Title' })).split('Title');
  addBytes(`bytes-title-${lbl}`, [...Buffer.from(before), ...bytes, ...Buffer.from(after)]);
  const [head, tail] = toText(headStudy()).split('ixi002');
  addBytes(`bytes-head-${lbl}`, [...Buffer.from(head + 'ixi'), ...bytes, ...Buffer.from('002' + tail)]);
  const [left, right] = toText(study()).split('Original');
  addBytes(`bytes-name-${lbl}`, [...Buffer.from(left), ...bytes, ...Buffer.from(right)]);
}
addBytes('bytes-plain', [...Buffer.from(toText(gridStudy()))]);
addBytes('bytes-bom', [0xef, 0xbb, 0xbf, ...Buffer.from(toText(study()))]);

// Random studies: valid choices in random key order, each field invalid now and then, so that about a third pass.
/** A value of `valid`, or of `invalid` with probability `p`. */
const choose = (valid, invalid, p = 0.04) => (random() < p ? pick(invalid) : pick(valid));
const RANDOM_DESIGNS = [[DESIGN, DESIGN, DESIGN, DESIGNS.floats, DESIGNS.six, DESIGNS.one, DESIGNS.name150, DESIGNS.minusZero], [DESIGNS.spacing, DESIGNS.unit, null]];
const RANDOM_NOISE = [[ABSENT, ABSENT, ABSENT, NOISE.iid, NOISE.null, NOISE.spatial10, NOISE.spatial40, NOISE.spatialReordered, NOISE.brain], [NOISE.other, NOISE.array]];
const RANDOM_SCENARIOS = [[ABSENT, ABSENT, ABSENT, '', null, 'skull_x2', 'skull_x0.5'], ['skull_x9', 0]];
const RANDOM_TITLES = [[ABSENT, ABSENT, 'Study', ' Padded ', null, '😀'.repeat(100), '　Title'], ['', 'a'.repeat(201), 3]];
const RANDOM_NOTES = [[ABSENT, ABSENT, ABSENT, '', 'Notes', null, 'x'.repeat(2000)], ['x'.repeat(2001), 0]];
const RANDOM_SEEDS = [[42, 43, 0, 9999, 7, raw('42.0'), raw('-0'), raw('4.2e1')], [-1, 10000, '1', 2.5]];
const RANDOM_RADII = [[3, 6, 10, raw('6.0'), raw('1e1')], [4, '6', null]];
const RANDOM_HEADS = ['', 'IXI/002', null, 'a'.repeat(41)];
const RANDOM_NAMES = [[ABSENT, ABSENT, ABSENT, NAMES, NAME_LISTS.defaults, NAME_LISTS.emoji64], [NAME_LISTS.names63, NAME_LISTS.repeated, null]];
const RANDOM_SOURCES = [[ABSENT, ABSENT, ABSENT, SOURCES.v1, SOURCES.v3Mni, SOURCES.v2Labels, SOURCES.v3Elc], [null, {}]];
for (let i = 0; i < 260; i++) {
  const protocol = choose(STUDY_PROTOCOLS, ['other', 'Heads'], 0.02), heads = protocol === 'heads' ? random() >= 0.03 : random() < 0.03;
  const count = random() < 0.9 ? 1 + (rand32() % 5) : pick([6, 8, 12, 13]);
  const seed = choose(...RANDOM_SEEDS), radius = choose(...RANDOM_RADII), start = rand32() % HEADS.length;
  const cases = Array.from({ length: count }, (_, j) => {
    // Grid pairs repeat now and then; noise seeds are distinct unless a random seed repeats one.
    const entry = protocol === 'grid_displacements' && random() < 0.85
      ? { seed: Math.floor(j / 3) + (random() < 0.05 ? 1 : 0), radius_mm: [3, 6, 10][j % 3] }
      : { seed: heads ? (random() < 0.97 ? seed : choose(...RANDOM_SEEDS)) : random() < 0.95 ? 100 + j : choose(...RANDOM_SEEDS),
        radius_mm: random() < 0.97 ? radius : choose(...RANDOM_RADII) };
    if (heads) entry.head_id = random() < 0.97 ? HEADS[(start + j) % HEADS.length] : pick(RANDOM_HEADS);
    if (random() < 0.01) entry.extra = 1;
    return Object.fromEntries(random() < 0.4 ? shuffle(Object.entries(entry)) : Object.entries(entry));
  });
  const base = choose(...RANDOM_DESIGNS), names = choose(...RANDOM_NAMES), metadata = choose(...RANDOM_SOURCES);
  const fields = {
    protocol,
    design: base && { ...base, ...(names === ABSENT ? {} : { electrode_names: names }), ...(metadata === ABSENT ? {} : { source_metadata: metadata }) },
    cases, title: choose(...RANDOM_TITLES), notes: choose(...RANDOM_NOTES), noise_model: choose(...RANDOM_NOISE),
    conductivity_scenario: protocol === 'noise_seeds' ? choose(...RANDOM_SCENARIOS) : random() < 0.97 ? ABSENT : choose(...RANDOM_SCENARIOS),
    ...(random() < 0.01 ? { extra: 1 } : {}),
  };
  add(`combo-${i}`, Object.fromEntries(random() < 0.5 ? shuffle(Object.entries(fields)) : Object.entries(fields)));
}
