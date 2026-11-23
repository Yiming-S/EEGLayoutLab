// coordinate-source: electrode-coordinate-source/1, /2 and /3, the source_metadata of a design-submission/1
// envelope and of electrode-name annotations. Node's outcome is validateCoordinateSource, which returns a copy of
// the input in the input's key order.
import { MNI_COORDINATE_SYSTEMS, MONTAGE_FORMATS, validateCoordinateSource } from '../../../webapp/contracts/coordinate-source.mjs';
import { ABSENT, collector, createRandom, label, nextUp, raw, toText } from '../support.mjs';

/** Node's option lists, compared with the Python schemas' (tests/test_schema_parity.py). */
export const options = { mni_coordinate_systems: [...MNI_COORDINATE_SYSTEMS], montage_formats: [...MONTAGE_FORMATS] };
export const name = 'coordinate-source';
export const normalize = validateCoordinateSource;

const { random, pick } = createRandom(0xc0057ce5);
const { variants, add } = collector();
export { variants };

// --- valid values, shaped as webapp/lib/bids-electrodes.ts, head-frame-import.ts and the label import build them ---
const MAPPING = 'f3c1a9e07b2d4c6f8a1e0d9c7b5a3f2e1d0c9b8a7f6e5d4c3b2a1f0e9d8c7b6a';
const MNI = { method: 'ernie-mni-scalp/1', mapping_id: MAPPING, input_coordinate_system: 'MNI152NLin2009cAsym', input_unit: 'mm', max_surface_distance_mm: 3.27 };
const LABELS = { method: 'cap-labels/1', mapping_id: MAPPING, input_coordinate_system: 'EEG10-20_extended_SPM12', input_unit: null, max_surface_distance_mm: null };
const HEAD = { method: 'head-landmarks-surface/1', mapping_id: MAPPING, input_coordinate_system: 'CTF', input_unit: 'cm', landmark_source: 'coordsystem',
  scale: 1.0412, rotation_deg: 3.2, max_landmark_residual_mm: 4.1, max_surface_distance_mm: 2.5, iterations: 12 };
const FRAME = 'Ernie native frame in millimetres.';
const REGIONS = 'Explicit zero-based EEGLayoutLab regions.';
const common = (format, overrides = {}) => ({
  format, electrodes_file: 'sub-01_electrodes.tsv', coordsystem_file: 'sub-01_coordsystem.json', coordinate_system: 'ernie_native_mm', unit: 'mm',
  coordinate_system_description: FRAME, region_index_base: 0, region_description: REGIONS, ...overrides,
});
const v1 = () => ({ schema: 'electrode-coordinate-source/1', ...common('bids-electrodes/1') });
const v2 = (format, conversion, coordsystem) => ({ schema: 'electrode-coordinate-source/2', ...common(format, { coordsystem_file: coordsystem }), conversion });
const v3 = (format, conversion, coordsystem, assignment) =>
  ({ schema: 'electrode-coordinate-source/3', ...common(format, { coordsystem_file: coordsystem }), conversion, region_assignment: assignment });
const FILE_REGIONS = { method: 'file' };
const BALANCED = count => ({ method: 'balanced-spatial/1', region_count: count });

export const SOURCES = {
  v1: v1(),
  v2Mni: v2('bids-electrodes/1', MNI, 'sub-01_coordsystem.json'),
  v2Labels: v2('electrode-labels/1', LABELS, null),
  v3Native: v3('bids-electrodes/1', null, 'sub-01_coordsystem.json', FILE_REGIONS),
  v3Mni: v3('bids-electrodes/1', MNI, 'sub-01_coordsystem.json', BALANCED(6)),
  v3BidsHead: v3('bids-electrodes/1', HEAD, 'sub-01_coordsystem.json', FILE_REGIONS),
  v3Labels: v3('electrode-labels/1', LABELS, null, BALANCED(4)),
  v3Elc: v3('mne-elc/1', { ...HEAD, input_coordinate_system: 'ASA .elc head frame', input_unit: 'mm', landmark_source: 'file' }, null, BALANCED(2)),
  v3Sfp: v3('eeglab-sfp/1', { ...HEAD, input_coordinate_system: 'BESA/EGI .sfp head frame', input_unit: 'm', landmark_source: 'file' }, null, BALANCED(1)),
  v3SfpNative: v3('eeglab-sfp/1', null, null, BALANCED(3)),
};

const set = (value, key, replacement) => ({ ...value, [key]: replacement });
const setIn = (value, outer, key, replacement) => ({ ...value, [outer]: { ...value[outer], [key]: replacement } });

// Every valid value, as is and in other key orders (the canonical value keeps the input's order).
for (const [id, value] of Object.entries(SOURCES)) {
  add(`valid-${id}`, value);
  add(`reversed-${id}`, Object.fromEntries(Object.entries(value).reverse()));
  const entries = Object.entries(value);
  for (let i = 0; i < 3; i++) {
    const shuffled = entries.map(entry => [random(), entry]).sort((a, b) => a[0] - b[0]).map(([, entry]) => entry);
    add(`shuffled-${id}-${i}`, Object.fromEntries(shuffled));
  }
  for (const outer of ['conversion', 'region_assignment'])
    if (value[outer]) add(`nested-reversed-${id}-${outer}`, set(value, outer, Object.fromEntries(Object.entries(value[outer]).reverse())));
}

// Inputs that are not objects, and other schemas.
for (const [i, text] of ['null', '[]', '"x"', '1', 'true', '{}', toText([SOURCES.v1])].entries()) add(`not-object-${i}`, raw(text));
for (const schema of [ABSENT, null, 1, '', 'electrode-coordinate-source/4', 'electrode-coordinate-source/0', 'Electrode-coordinate-source/1',
  'electrode-coordinate-source/1 ', 'electrode-coordinate-source/3\n'])
  for (const id of ['v1', 'v2Mni', 'v3Mni']) add(`schema-${id}-${label(schema)}`, set(SOURCES[id], 'schema', schema));
// A source labelled with the other versions' schema names (the key sets then differ).
for (const [id, schema] of [['v1', 2], ['v1', 3], ['v2Mni', 1], ['v2Mni', 3], ['v2Labels', 3], ['v3Native', 1], ['v3Native', 2], ['v3Mni', 2]])
  add(`schema-swap-${id}-to-${schema}`, set(SOURCES[id], 'schema', `electrode-coordinate-source/${schema}`));

// Missing and extra keys, top level and nested.
for (const [id, value] of Object.entries(SOURCES)) {
  for (const key of Object.keys(value)) add(`missing-${id}-${key}`, set(value, key, ABSENT));
  for (const key of ['extra', '__proto__', 'constructor', value.conversion === undefined ? 'conversion' : 'region_assignment', 'Unit', 'unit '])
    if (!(key in value)) add(`extra-${id}-${key}`, set(value, key, key === 'conversion' ? MNI : key === 'region_assignment' ? FILE_REGIONS : 'x'));
  for (const outer of ['conversion', 'region_assignment']) {
    if (!value[outer]) continue;
    for (const key of Object.keys(value[outer])) add(`missing-${id}-${outer}-${key}`, setIn(value, outer, key, ABSENT));
    add(`extra-${id}-${outer}`, setIn(value, outer, 'extra', 1));
  }
}
add('extra-v3-file-regions-count', set(SOURCES.v3Native, 'region_assignment', { method: 'file', region_count: 2 }));
add('extra-v3-mni-head-field', set(SOURCES.v3Mni, 'conversion', { ...MNI, iterations: 3 }));
// Two expected keys replaced by one key holding both names, which Node's comma-joined key comparison does not tell
// apart from the pair; their values are then missing.
const merged = (value, a, b) => Object.fromEntries([...Object.entries(value).filter(([key]) => key !== a && key !== b), [`${a},${b}`, value[a]]]);
add('merged-keys-v1-unit', merged(SOURCES.v1, 'region_index_base', 'schema'));
add('merged-keys-v1-system', merged(SOURCES.v1, 'coordinate_system', 'coordinate_system_description'));
add('merged-keys-v3-conversion', merged(SOURCES.v3Native, 'conversion', 'coordinate_system'));
add('merged-keys-v2-mni', set(SOURCES.v2Mni, 'conversion', merged(MNI, 'input_coordinate_system', 'input_unit')));

// Duplicate keys: the last value wins and the key keeps its first position.
const duplicateFirst = (value, key, first) => raw('{' + JSON.stringify(key) + ':' + toText(first) + ',' + toText(value).slice(1));
const duplicateLast = (value, key, last) => raw(toText(value).slice(0, -1) + ',' + JSON.stringify(key) + ':' + toText(last) + '}');
add('duplicate-unit-last-valid', duplicateFirst(SOURCES.v1, 'unit', 'cm'));
add('duplicate-unit-last-invalid', duplicateLast(SOURCES.v1, 'unit', 'cm'));
add('duplicate-schema-first', duplicateFirst(SOURCES.v3Mni, 'schema', 'electrode-coordinate-source/1'));
add('duplicate-conversion-last-null', duplicateLast(SOURCES.v3Mni, 'conversion', null));
add('duplicate-conversion-first-null', duplicateFirst(SOURCES.v3Mni, 'conversion', null));
add('duplicate-region-count', raw(toText(SOURCES.v3Mni).replace('"region_count":6', '"region_count":5,"region_count":6')));

// Literals.
for (const [key, values] of Object.entries({
  format: ['bids-electrodes/1', 'electrode-labels/1', ...MONTAGE_FORMATS, 'bids-electrodes/2', 'BIDS-electrodes/1', '', null, 1],
  coordinate_system: ['ernie_native_mm', 'mni_mm', 'Ernie_native_mm', '', null],
  unit: ['mm', 'cm', 'MM', '', null, 1],
  region_index_base: [0, raw('-0'), raw('-0.0'), raw('0.0'), raw('0e5'), raw('0E-5'), false, '0', null, 1, raw('5e-324'), [0]],
}))
  for (const value of values) for (const id of ['v1', 'v2Labels', 'v3Native', 'v3Elc']) add(`${key}-${id}-${label(value)}`, set(SOURCES[id], key, value));
// Every format with every conversion, and coordsystem_file present or null.
const CONVERSIONS = { null: null, mni: MNI, labels: LABELS, head: HEAD, string: 'x', array: [], empty: {} };
for (const format of ['bids-electrodes/1', 'electrode-labels/1', ...MONTAGE_FORMATS])
  for (const [conversionLabel, conversion] of Object.entries(CONVERSIONS))
    for (const coordsystem of ['sub-01_coordsystem.json', null]) {
      add(`grid-v3-${format}-${conversionLabel}-${label(coordsystem)}`, v3(format, conversion, coordsystem, FILE_REGIONS));
      if (format === 'bids-electrodes/1' || format === 'electrode-labels/1')
        add(`grid-v2-${format}-${conversionLabel}-${label(coordsystem)}`, v2(format, conversion, coordsystem));
    }

// Conversion fields.
for (const [key, values] of Object.entries({
  method: ['ernie-mni-scalp/1', 'cap-labels/1', 'head-landmarks-surface/1', 'ernie-mni-scalp/2', '', null],
  mapping_id: [MAPPING, MAPPING.toUpperCase(), MAPPING.slice(1), MAPPING + 'a', MAPPING + '\n', '\n' + MAPPING.slice(1), MAPPING.replace('f', 'g'),
    MAPPING.slice(0, 63) + 'A', 1, null, ''],
  input_coordinate_system: [...MNI_COORDINATE_SYSTEMS, 'mni152nlin6asym', 'MNI', 'EEG10-20_extended_SPM12', '', null],
  input_unit: ['mm', 'cm', 'm', 'MM', null, ''],
  max_surface_distance_mm: [0, raw('-0'), raw('-0.0'), 3.27, 10, raw('10.0'), raw('1e1'), raw('1E+1'), nextUp(10), raw('10.0000000000000018'), raw('10.0000000000000001'),
    -1e-300, raw('1e400'), raw('-1e400'), true, '5', null, raw('5e-324')],
}))
  for (const value of values)
    for (const id of key === 'method' || key === 'mapping_id' || key === 'input_unit' || key === 'max_surface_distance_mm'
      ? ['v2Mni', 'v2Labels', 'v3BidsHead'] : ['v2Mni', 'v3Mni', 'v2Labels'])
      add(`conversion-${key}-${id}-${label(value)}`, setIn(SOURCES[id], 'conversion', key, value));

// Head registration fields, at and around every bound.
for (const [key, values] of Object.entries({
  input_coordinate_system: ['CTF', 'x'.repeat(64), 'x'.repeat(65), '😀'.repeat(32), 'a' + '😀'.repeat(32), '\ud800', '', '   ', ' ', '﻿', '\u0085',
    'C\tF', 'C\nF', 'C\rF', '\u007f', null, 1],
  input_unit: ['mm', 'cm', 'm', 'km', 'M', null],
  landmark_source: ['coordsystem', 'file', 'File', '', null],
  scale: [0.5, nextUp(0.5, -1), 2, nextUp(2), 1, raw('1.0'), raw('2e0'), raw('5e-1'), 0, raw('-0'), raw('1e400'), true, '1', null],
  rotation_deg: [0, raw('-0'), 180, raw('180.0'), nextUp(180), raw('1.8e2'), -1e-9, 90.5, true, null, '90'],
  max_landmark_residual_mm: [0, 1000, raw('1e3'), raw('1000.0000000000001'), nextUp(1000, 2), -0.5, raw('1e400'), null],
  max_surface_distance_mm: [0, 10, raw('10.0'), raw('1e1'), nextUp(10), raw('-0'), true, '5', null],
  iterations: [0, 1000, 1001, 1.5, raw('12.0'), raw('1e1'), raw('1E3'), raw('1.0e3'), raw('1000.0000000000001'), -1, raw('-0'), raw('-0.0'), true, '12', null,
    raw('1e400'), raw('9'.repeat(400)), 999.9999999999999],
}))
  for (const value of values) for (const id of ['v3BidsHead', 'v3Elc']) add(`head-${key}-${id}-${label(value)}`, setIn(SOURCES[id], 'conversion', key, value));

// Region assignment.
for (const value of [FILE_REGIONS, ...[1, 2, 3, 4, 6, 5, 0, 7, -1].map(BALANCED), BALANCED(raw('2.0')), BALANCED(raw('2e0')), BALANCED(raw('-0')), BALANCED(2.5),
  BALANCED(true), BALANCED('2'), BALANCED(null), BALANCED(raw('6.000000000000001')), BALANCED(raw('1e400')), { method: 'balanced-spatial/2', region_count: 2 },
  { method: 'File' }, { method: null }, null, [], 'file', {}])
  for (const id of ['v3Native', 'v3Sfp']) add(`regions-${id}-${label(value)}`, set(SOURCES[id], 'region_assignment', value));

// Text: descriptions are multiline (tab, LF and CR allowed); file names and head frames are single lines.
const TEXT = max => ({
  exact: 'x'.repeat(max), over: 'x'.repeat(max + 1), emojiExact: '😀'.repeat(max / 2), emojiOver: 'a' + '😀'.repeat(max / 2),
  loneHigh: 'x\ud800', loneLow: '\udc00', reversedPair: '\ude00\ud83d', astral: '\u{10ffff}', empty: '',
  spaces: '   ', nbsp: ' ', bom: '﻿', ideographic: '　', lineSeparator: ' ', paragraphSeparator: ' ', ogham: ' ',
  mongolianVowelSeparator: '᠎', zeroWidth: '​', nel: '\u0085', paddedNel: ' \u0085 ', tab: 'a\tb', lf: 'a\nb', crlf: 'a\r\nb', cr: 'a\rb', onlyCr: '\r', onlyTab: '\t',
  vt: 'a\u000bb', ff: 'a\u000cb', nul: 'a\u0000b', unitSeparator: 'a\u001fb', del: 'a\u007fb', c1: 'a\u0080b', escape: 'a\u001bb',
  number: 1, null: null, array: ['x'], object: { x: 1 },
});
for (const [key, max] of [['coordinate_system_description', 2048], ['region_description', 1024], ['electrodes_file', 200]])
  for (const [textLabel, value] of Object.entries(TEXT(max)))
    for (const id of ['v1', 'v3Labels']) add(`text-${key}-${id}-${textLabel}`, set(SOURCES[id], key, value));
for (const [textLabel, value] of Object.entries(TEXT(200))) add(`text-coordsystem_file-v1-${textLabel}`, set(SOURCES.v1, 'coordsystem_file', value));
for (const [fileLabel, value] of Object.entries({ slash: 'a/b.tsv', backslash: 'a\\b.tsv', dot: '.', dotdot: '..', dots: '...', hidden: '.hidden', trailingSlash: 'dir/',
  padded: ' x.tsv ', unicode: '电极.tsv' }))
  for (const key of ['electrodes_file', 'coordsystem_file']) add(`file-${key}-${fileLabel}`, set(SOURCES.v2Mni, key, value));

// Random combinations of the edits above.
const EDITS = [
  value => set(value, 'unit', pick(['mm', 'mm', 'cm'])),
  value => set(value, 'region_index_base', pick([0, raw('-0'), raw('0.0'), 1])),
  value => set(value, 'electrodes_file', pick(['e.tsv', '😀'.repeat(100), 'a/b', '﻿', 'x'.repeat(201)])),
  value => set(value, 'coordinate_system_description', pick([FRAME, 'a\tb\nc', 'a\u000bb', ' ', 'x'.repeat(2048)])),
  value => set(value, 'coordsystem_file', pick(['c.json', null])),
  value => (value.conversion !== undefined ? set(value, 'conversion', pick([null, MNI, LABELS, HEAD])) : value),
  value => (value.region_assignment ? set(value, 'region_assignment', pick([FILE_REGIONS, BALANCED(pick([1, 2, 5, 6, raw('3.0')]))])) : value),
  value => (value.conversion?.max_surface_distance_mm !== undefined && value.conversion?.max_surface_distance_mm !== null
    ? setIn(value, 'conversion', 'max_surface_distance_mm', pick([0, 9.99, 10, nextUp(10), raw('1e1')])) : value),
  value => Object.fromEntries(Object.entries(value).reverse()),
];
const ids = Object.keys(SOURCES);
for (let i = 0; i < 200; i++) {
  let value = SOURCES[pick(ids)];
  for (let n = 1 + Math.floor(random() * 3); n > 0; n--) value = pick(EDITS)(value);
  add(`combo-${i}`, value);
}
