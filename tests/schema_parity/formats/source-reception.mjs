// source-reception: the body of POST /api/source-reception/jobs and /lookup, the request of a community task of kind
// source-reception and the request of a reception result. Node's outcome is normalizeReceptionRequest, which hands a
// value without mode to normalizeSourceRequest (v1), as in SourceReceptionService and the community queue's
// source-reception adapter (the service imports both from webapp/server/contracts/source-reception.mjs). Rejected
// variants also record Node's message, which eeglayoutlab.schemas.source_reception.normalize_reception_request must
// raise (tests/service/test_source_request.py).
import { readFileSync } from 'node:fs';
import {
  SOURCE_REGIONS, normalizeReceptionRequest, normalizeSourceRequest,
} from '../../../webapp/server/contracts/source-reception.mjs';
import { ABSENT, collector, createRandom, label, raw, toText } from '../support.mjs';

/** Node's list of source regions, compared with the Python schema's (tests/test_schema_parity.py). */
export const options = { source_regions: [...SOURCE_REGIONS] };
export const name = 'source-reception';
export const normalize = normalizeReceptionRequest;

const { random, rand32, pick } = createRandom(0x5eceb7ed);
const { variants, add, addBytes } = collector();
export { variants };

const RECORD = 'a'.repeat(64);
const HEX = '0123456789abcdef'.repeat(4);
const ATLAS = 'dk40-six-roi-v1';
const V1 = { record_id: RECORD, brain_region: 'frontal', waveform: 'burst', artifact_scale: 1, seed: 2026 };
const COMMON = { record_id: RECORD, waveform: 'burst', artifact_scale: 1, seed: 2026 };
const SINGLE = { ...COMMON, mode: 'single_source', source_index: 2 };
const MULTI = { ...COMMON, mode: 'multi_source', brain_region: 'parietal' };
const CROSS = { ...COMMON, mode: 'cross_region', brain_regions: ['occipital', 'frontal'] };
const atlas = request => ({ ...request, region_definition: ATLAS });
/** The requests every field rule is tried on: v1, each v2 mode, and each v2 mode with the atlas definition. */
const BASES = { v1: V1, single: SINGLE, multi: MULTI, cross: CROSS, singleAtlas: atlas(SINGLE), multiAtlas: atlas(MULTI),
  crossAtlas: atlas(CROSS) };
const MAIN = { v1: V1, single: SINGLE, multi: MULTI, crossAtlas: atlas(CROSS) };
const shuffle = list => list.map(item => [random(), item]).sort((a, b) => a[0] - b[0]).map(([, item]) => item);
const randomHex = () => Array.from({ length: 64 }, () => HEX[rand32() % 16]).join('');
const subsets = Array.from({ length: 63 }, (_, i) => SOURCE_REGIONS.filter((_, bit) => (i + 1) & (1 << bit)));
/** A request text with `from` replaced once by `to`; fails if `from` is not in the text. */
const patch = (request, from, to) => {
  const text = toText(request);
  if (!text.includes(from)) throw new Error(`${from} is not in ${text}`);
  return raw(text.replace(from, to));
};


// Top level
for (const [lbl, request] of Object.entries(BASES)) {
  add(`base-${lbl}`, request);
  add(`base-${lbl}-pretty`, raw(JSON.stringify(request, null, 2)));
}
for (const [i, value] of ['[]', 'null', '1', '0', '-0', '"x"', '""', 'true', 'false', '{}', '[{}]', `[${toText(V1)}]`,
  `[${toText(SINGLE)}]`, '"single_source"', `"${RECORD}"`, '{"mode":null}', '{"mode":"single_source"}', '{"mode":{}}',
  '{"region_definition":"dk40-six-roi-v1"}', `{"request":${toText(V1)}}`, `{"request":${toText(SINGLE)}}`].entries())
  add(`top-not-request-${i}`, raw(value));
for (const [lbl, request] of Object.entries({ v1: V1, single: SINGLE })) {
  add(`trailing-garbage-${lbl}`, raw(toText(request) + 'x'));
  add(`trailing-comma-${lbl}`, raw(toText(request).replace(/}$/, ',}')));
  add(`trailing-whitespace-${lbl}`, raw(' \n\t' + toText(request) + ' \r\n'));
  add(`bom-prefix-${lbl}`, raw('\ufeff' + toText(request)));
  add(`single-quotes-${lbl}`, raw(toText(request).replaceAll('"', "'")));
  add(`two-requests-${lbl}`, raw(toText(request) + toText(request)));
}
add('escaped-region', patch(V1, '"frontal"', '"\\u0066rontal"'));
add('escaped-region-key', patch(V1, '"brain_region"', '"brain\\u005fregion"'));
add('escaped-mode', patch(SINGLE, '"single_source"', '"\\u0073ingle_source"'));
add('escaped-mode-key', patch(SINGLE, '"mode"', '"\\u006dode"'));
add('escaped-atlas', patch(atlas(CROSS), `"${ATLAS}"`, '"\\u0064k40-six-roi-v1"'));
add('escaped-atlas-key', patch(atlas(CROSS), '"region_definition"', '"region\\u005fdefinition"'));
add('escaped-record', patch(V1, `"${RECORD}"`, `"${'\\u0061'.repeat(64)}"`));
add('escaped-cross-item', patch(CROSS, '"occipital"', '"\\u006fccipital"'));
add('escaped-solidus-region', patch(V1, '"frontal"', '"front\\/al"'));
// The UI's key order (use-reception-controller.ts): the common fields with the atlas definition, then mode and the source.
for (const [mode, source] of [['single_source', { source_index: 0 }], ['multi_source', { brain_region: 'central' }],
  ['cross_region', { brain_regions: ['temporal_right', 'frontal'] }]])
  add(`ui-${mode}`, { ...COMMON, region_definition: ATLAS, mode, ...source });

// Record identifier: 64 lowercase hexadecimal digits; paths, shell text and AR never pass
const IDS = {
  lower: RECORD, zeros: '0'.repeat(64), hex: HEX, f: 'f'.repeat(64), upper: 'A'.repeat(64), oneUpper: 'A' + 'a'.repeat(63),
  lastUpper: 'a'.repeat(63) + 'F', mixedHex: HEX.toUpperCase(), short: 'a'.repeat(63), long: 'a'.repeat(65), double: 'a'.repeat(128),
  empty: '', g: 'g' + 'a'.repeat(63), lastG: 'a'.repeat(63) + 'g', space: ' ' + 'a'.repeat(63), padded: ' ' + RECORD,
  trailingSpace: RECORD + ' ', newline: RECORD + '\n', crlf: RECORD + '\r\n', leadingNewline: '\n' + RECORD, nul: RECORD + '\u0000',
  innerNul: 'a'.repeat(32) + '\u0000' + 'a'.repeat(31), dash: 'a'.repeat(32) + '-' + 'a'.repeat(31), fullWidth: 'ａ'.repeat(64),
  arabicDigits: '١'.repeat(64), superscript: '¹'.repeat(64), surrogate: 'a'.repeat(63) + '\ud800', emoji: 'a'.repeat(62) + '😀',
  sha256Prefix: 'sha256:' + RECORD, uuid: '0123abcd-0123-4567-89ab-0123456789ab',
  path: '../../x', absolutePath: '/tmp/a', pathPadded: '../../private'.padEnd(64, 'a'), slash: 'a'.repeat(63) + '/',
  backslash: 'a'.repeat(32) + '\\' + 'a'.repeat(31), windows: 'C:\\Windows\\system32', fileUrl: 'file:///etc/passwd',
  encodedPath: '%2e%2e%2f%2e%2e%2f', home: '~/.ssh/id_rsa', subshell: '$(rm -rf ~)', backticks: '`id`',
  semicolon: RECORD + '; rm -rf /', and: RECORD + ' && ls', pipe: RECORD + '|cat', glob: 'a'.repeat(63) + '*', ar: 'AR',
  arValue: 'ar=90', json: toText(V1),
};
const NON_STRINGS = { null: null, zero: 0, number: 1234, true: true, false: false, array: [RECORD], object: { id: RECORD },
  absent: ABSENT, hexNumber: raw('1' + '0'.repeat(63)) };
for (const [lbl, value] of Object.entries({ ...IDS, ...NON_STRINGS }))
  for (const [base, request] of Object.entries(MAIN)) add(`record-${base}-${lbl}`, { ...request, record_id: value });
for (let i = 0; i < 8; i++) add(`record-random-${i}`, { ...pick(Object.values(BASES)), record_id: randomHex() });

// Source region (v1 and multi_source): one of SOURCE_REGIONS, as a string
const BAD_REGIONS = ['Frontal', 'FRONTAL', ' frontal', 'frontal ', 'frontal\n', 'frontal\u0000', 'frontal\u200b', '\ufefffrontal',
  'ｆｒｏｎｔａｌ', 'fr\u043ental', 'temporal', 'temporal-left', 'temporalLeft', 'temporal_left ', 'left', 'heart', 'limbic',
  'other', 'cross_region', 'single_source', 'frontal,central', '', '../frontal', 'frontal; rm -rf /', '$(id)', '/tmp/a', 'AR',
  null, 0, 1, 5, true, false, ['frontal'], { id: 'frontal' }, ABSENT, raw('NaN')];
for (const value of [...SOURCE_REGIONS, ...BAD_REGIONS]) {
  add(`region-v1-${label(value)}`, { ...V1, brain_region: value });
  add(`region-multi-${label(value)}`, { ...MULTI, brain_region: value });
}
add('region-multi-atlas-each', atlas({ ...MULTI, brain_region: 'temporal_left' }));

// Waveform: burst or rhythm, as a string
for (const value of ['burst', 'rhythm', 'Burst', 'BURST', 'Rhythm', ' burst', 'burst ', 'burst\n', 'búrst', 'ｂｕｒｓｔ', 'bursts',
  'spike', 'sine', 'noise', 'burst && ls', '/bin/sh', '', null, 0, 1, true, ['burst'], { kind: 'burst' }, ABSENT])
  for (const [base, request] of Object.entries(MAIN)) add(`waveform-${base}-${label(value)}`, { ...request, waveform: value });

// Artifact scale: one of 0, 0.5, 1, 2 and 4 (SameValueZero: -0 is 0), as a number
const SCALE_VALUES = [0, 0.5, 1, 2, 4, raw('-0'), raw('0.0'), raw('-0.0'), raw('0e5'), raw('5e-1'), raw('5E-1'), raw('0.5e0'),
  raw('50e-2'), raw('0.50'), raw('0.50000000000000001'), raw('0.5000000000000001'), raw('0.49999999999999999'),
  raw('0.4999999999999999'), raw('1.0'), raw('1e0'), raw('10e-1'), raw('1.0000000000000001'), raw('1.000000000000001'),
  raw('0.99999999999999999'), raw('2.0'), raw('2e0'), raw('0.2e1'), raw('4.0'), raw('4e0'), raw('40e-1'), raw('3.9999999999999999'),
  raw('3.999999999999999'), raw('1e-400'), raw('-1e-400'), raw('1e400'), raw('-1e400'), raw('4' + '0'.repeat(400) + 'e-400'),
  raw('0.' + '0'.repeat(400) + '1'), 0.25, 0.75, 1.5, 3, 8, 16, 100, -1, -0.5, -4, 2 ** 53, raw('.5'), raw('+1'), raw('01'),
  raw('1.'), raw('0x1'), raw('Infinity'), raw('NaN'), '1', '0.5', '0', '', true, false, null, [1], { scale: 1 }, ABSENT];
for (const value of SCALE_VALUES)
  for (const [base, request] of Object.entries(MAIN)) add(`scale-${base}-${label(value)}`, { ...request, artifact_scale: value });
for (const scale of [0, 0.5, 2, 4]) add(`scale-cross-${scale}`, { ...CROSS, artifact_scale: scale });

// Seed: an integer from 0 through 9999
const SEED_VALUES = [0, 1, 42, 2026, 9998, 9999, 10000, 10001, 99999, -1, -2, -9999, 0.5, 1.5, 2026.5, 9998.5, 9999.5,
  raw('-0'), raw('-0.0'), raw('0.0'), raw('1.0'), raw('2026.0'), raw('2.026e3'), raw('2.026E+3'), raw('202600e-2'), raw('9999.0'),
  raw('9.999e3'), raw('99990e-1'), raw('1e4'), raw('1E4'), raw('9999.00000000000001'), raw('9999.0000000001'),
  raw('9998.9999999999999'), raw('9998.999999999'), raw('10000.000000000001'), raw('-0.00000000000000001'), raw('1e-400'),
  raw('-1e-400'), raw('1e400'), raw('-1e400'), raw('9007199254740993'), raw('2026' + '0'.repeat(400)), raw('2026.' + '0'.repeat(400)),
  raw('-'), raw('1e'), '2026', '0', '', true, false, null, [2026], { seed: 2026 }, ABSENT];
for (const value of SEED_VALUES)
  for (const [base, request] of Object.entries(MAIN)) add(`seed-${base}-${label(value)}`, { ...request, seed: value });

// Mode: present (null included) means v2, and only the three modes pass
const MODE_VALUES = ['single_source', 'multi_source', 'cross_region', 'Single_source', 'SINGLE_SOURCE', 'single', 'multi', 'cross',
  'single_source ', ' multi_source', 'cross_region\n', 'single-source', 'singleSource', 'single_sourc\u0435', 'v1', 'v2', 'legacy',
  'source', 'all', '', null, 0, 1, 2, true, false, ['single_source'], { mode: 'single_source' }, '$(id)', '../single_source', ABSENT];
for (const value of MODE_VALUES) {
  for (const [base, request] of Object.entries({ single: SINGLE, multi: MULTI, cross: CROSS, crossAtlas: atlas(CROSS) }))
    add(`mode-${base}-${label(value)}`, { ...request, mode: value });
  add(`mode-v1-fields-${label(value)}`, { ...V1, mode: value });
}

// Atlas definition: when present, exactly dk40-six-roi-v1, checked before the mode and the keys
const DEFINITIONS = [ATLAS, 'dk40-six-roi-v2', 'dk40-six-roi-v0', 'DK40-six-roi-v1', 'dk40-six-roi-v1 ', ' dk40-six-roi-v1',
  'dk40-six-roi-v1\n', 'dk40-six-roi-v1\u0000', 'dk40\u2010six\u2010roi\u2010v1', 'ｄｋ40-six-roi-v1', 'dk40', 'dk40-six-roi', 'desikan',
  'unverified', '', '../../atlas.json', '/etc/passwd', `${ATLAS}; rm -rf /`, null, 0, 1, true, false, [ATLAS], { id: ATLAS }];
for (const value of DEFINITIONS) {
  for (const [base, request] of Object.entries({ single: SINGLE, multi: MULTI, cross: CROSS }))
    add(`definition-${base}-${label(value)}`, { ...request, region_definition: value });
  add(`definition-v1-${label(value)}`, { ...V1, region_definition: value });
  add(`definition-bad-mode-${label(value)}`, { ...SINGLE, mode: 'other', region_definition: value });
  add(`definition-null-mode-${label(value)}`, { ...V1, mode: null, region_definition: value });
  add(`definition-extra-key-${label(value)}`, { ...MULTI, ar: 90, region_definition: value });
}
add('definition-first-in-order', { region_definition: ATLAS, ...CROSS });

// Generation source index (single_source): an integer from 0 through 255
const INDEX_VALUES = [0, 1, 2, 127, 128, 254, 255, 256, 257, 1000, 4096, 4351, -1, -2, -255, 0.5, 1.5, 254.5, 255.5,
  raw('-0'), raw('-0.0'), raw('0.0'), raw('2.0'), raw('255.0'), raw('2.55e2'), raw('2550e-1'), raw('25.5e1'), raw('0e0'),
  raw('255.00000000000001'), raw('255.0000000001'), raw('254.99999999999999'), raw('254.9999999999'), raw('256.00000000000001'),
  raw('-0.00000000000000001'), raw('1e-400'), raw('-1e-400'), raw('1e400'), raw('-1e400'), raw('1' + '0'.repeat(400)),
  '0', '2', '255', '', true, false, null, [2], { index: 2 }, ABSENT];
for (const value of INDEX_VALUES) {
  add(`index-${label(value)}`, { ...SINGLE, source_index: value });
  add(`index-atlas-${label(value)}`, atlas({ ...SINGLE, source_index: value }));
}

// Cross-region selection: one to six distinct regions, written in SOURCE_REGIONS order whatever order is sent
subsets.forEach((regions, i) => {
  add(`cross-subset-${i + 1}`, { ...CROSS, brain_regions: [...regions].reverse() });
  add(`cross-subset-atlas-${i + 1}`, atlas({ ...CROSS, brain_regions: random() < 0.5 ? regions : shuffle(regions) }));
});
for (let i = 0; i < 12; i++) add(`cross-shuffled-${i}`, { ...CROSS, brain_regions: shuffle(SOURCE_REGIONS) });
for (const [lbl, value] of Object.entries({
  empty: [], duplicate: ['frontal', 'frontal'], duplicateApart: ['frontal', 'central', 'parietal', 'frontal'],
  duplicateOfSix: [...SOURCE_REGIONS.slice(0, 5), 'frontal'], seven: [...SOURCE_REGIONS, 'frontal'],
  twelve: [...SOURCE_REGIONS, ...SOURCE_REGIONS], unknown: ['unknown'], unknownWithValid: ['frontal', 'heart'],
  upper: ['Frontal'], spaced: ['frontal '], fullWidth: ['ｆｒｏｎｔａｌ'], path: ['frontal', '../x'], shell: ['$(id)'],
  number: [0], numbers: [0, 1], true: [true], null: [null], nested: [['frontal']], object: [{ id: 'frontal' }],
  commaJoined: ['frontal,central'], emptyString: [''], ar: ['AR'], undefinedHole: raw('[,"frontal"]'),
  nullValue: null, string: 'frontal', emptyStr: '', number0: 0, true0: true, object0: { 0: 'frontal', length: 1 },
  setLike: { frontal: true }, absent: ABSENT,
}))
  add(`cross-invalid-${lbl}`, { ...CROSS, brain_regions: value });
add('cross-all-six-atlas', atlas({ ...CROSS, brain_regions: [...SOURCE_REGIONS].reverse() }));

// Exactly the fields of the version and mode: missing, mixed and extra fields are rejected
for (const [base, request] of Object.entries(BASES))
  for (const key of Object.keys(request)) add(`missing-${base}-${key}`, { ...request, [key]: ABSENT });
const MIXED = {
  singleWithRegion: { ...SINGLE, brain_region: 'frontal' }, singleWithRegions: { ...SINGLE, brain_regions: ['frontal'] },
  singleWithRegionOnly: { ...COMMON, mode: 'single_source', brain_region: 'frontal' },
  singleWithRegionsOnly: { ...COMMON, mode: 'single_source', brain_regions: ['frontal'] },
  multiWithIndex: { ...MULTI, source_index: 0 }, multiWithRegions: { ...MULTI, brain_regions: ['frontal'] },
  multiWithIndexOnly: { ...COMMON, mode: 'multi_source', source_index: 0 },
  multiWithRegionsOnly: { ...COMMON, mode: 'multi_source', brain_regions: ['frontal'] },
  crossWithRegion: { ...CROSS, brain_region: 'frontal' }, crossWithIndex: { ...CROSS, source_index: 0 },
  crossWithRegionOnly: { ...COMMON, mode: 'cross_region', brain_region: 'frontal' },
  crossWithIndexOnly: { ...COMMON, mode: 'cross_region', source_index: 0 },
  allSelectors: { ...COMMON, mode: 'single_source', source_index: 0, brain_region: 'frontal', brain_regions: ['frontal'] },
  v1WithIndex: { ...V1, source_index: 0 }, v1WithRegions: { ...V1, brain_regions: ['frontal'] },
  v1WithoutRegionWithIndex: { ...COMMON, source_index: 0 }, v1WithoutRegionWithRegions: { ...COMMON, brain_regions: ['frontal'] },
};
for (const [lbl, request] of Object.entries(MIXED)) {
  add(`mixed-${lbl}`, request);
  add(`mixed-${lbl}-atlas`, { ...request, region_definition: ATLAS });
}
// Arbitrary coordinates, orientations, AR and file or command fields: AR is a display parameter and cannot start a
// computation, and nothing names a path or a program (check-source-reception.mjs, check-cross-region-contract.mjs).
const EXTRA_KEYS = ['ar', 'AR', 'Ar', 'xyz_mm', 'xyzMm', 'source_xyz_mm', 'normal', 'normals_mri', 'direction', 'orientation',
  'path', 'file', 'command', 'script', 'shell', 'python', 'layout', 'record', 'request', 'identity', 'key', 'schema',
  'schema_version', 'version', 'locale', 'threshold', 'region_count', 'noise_model', 'data_prior', 'head_id', 'radius_mm',
  'patch_count', 'source_indices', 'generation_source_indices', 'Mode', 'mode ', 'MODE', 'region-definition', 'regionDefinition',
  'Record_id', 'recordId', 'brainRegion', 'sourceIndex', '', '0', '-1', '__proto__', 'constructor', 'toString', 'hasOwnProperty',
  'valueOf', 'm\u043ede', 'ｍｏｄｅ', '😀', '\ud800', '\uffff', 'é'];
const EXTRA_VALUES = { one: 1, null: null, string: 'x', ar: 0.9, path: '/tmp/input', shell: 'rm -rf /', coordinates: [[0, 0, 80]] };
for (const key of EXTRA_KEYS)
  for (const [base, request] of Object.entries({ v1: V1, single: SINGLE, multi: MULTI, crossAtlas: atlas(CROSS) }))
    add(`extra-${base}-${JSON.stringify(key)}`, { ...request, [key]: pick(Object.values(EXTRA_VALUES)) });
for (const [lbl, value] of Object.entries(EXTRA_VALUES))
  for (const [base, request] of Object.entries(BASES)) add(`extra-ar-${base}-${lbl}`, { ...request, ar: value });
add('extra-proto-text', raw(toText(SINGLE).replace(/}$/, ',"__proto__":{"source_index":3}}')));
add('extra-proto-mode-text', raw(toText(V1).replace(/}$/, ',"__proto__":{"mode":"single_source"}}')));

// Keys containing commas: Node compares the sorted keys joined with commas, so a key may stand for two fields.
// The fields it hides are then missing, and the request fails on their values instead.
for (const [lbl, request] of Object.entries({
  multiScaleRegion: { 'artifact_scale,brain_region': 1, mode: 'multi_source', record_id: RECORD, seed: 2026, waveform: 'burst' },
  multiSeedWaveform: { artifact_scale: 1, brain_region: 'frontal', mode: 'multi_source', record_id: RECORD, 'seed,waveform': 2026 },
  singleSeedIndex: { artifact_scale: 1, mode: 'single_source', record_id: RECORD, 'seed,source_index': 2026, waveform: 'burst' },
  singleIndexWaveform: { artifact_scale: 1, mode: 'single_source', record_id: RECORD, seed: 2026, 'source_index,waveform': 0 },
  crossScaleRegions: { 'artifact_scale,brain_regions': ['frontal'], mode: 'cross_region', record_id: RECORD, seed: 2026,
    waveform: 'burst' },
  crossRecordDefinition: { ...CROSS, record_id: ABSENT, 'record_id,region_definition': RECORD },
  crossDefinitionSeed: { ...atlas(CROSS), seed: ABSENT, region_definition: ABSENT, 'region_definition,seed': ATLAS },
  modeHidden: { 'brain_regions,mode': 'cross_region', ...COMMON },
  v1Joined: { 'artifact_scale,brain_region': 1, record_id: RECORD, seed: 2026, waveform: 'burst' },
  allInOne: { 'artifact_scale,mode,record_id,seed,source_index,waveform': 'single_source' },
  allInOneWithMode: { mode: 'single_source', 'artifact_scale,record_id,seed,source_index,waveform': 1 },
  trailingComma: { ...SINGLE, ',': 1 },
}))
  add(`comma-key-${lbl}`, request);

// Duplicate keys: JSON.parse keeps the last value at the first key's position
add('duplicate-mode-last-wins', patch(SINGLE, '"mode":"single_source"', '"mode":"multi_source","mode":"single_source"'));
add('duplicate-mode-last-invalid', patch(SINGLE, '"mode":"single_source"', '"mode":"single_source","mode":"multi_source"'));
add('duplicate-mode-null-first', patch(SINGLE, '"mode":"single_source"', '"mode":null,"mode":"single_source"'));
add('duplicate-record-last-wins', patch(V1, '"record_id"', '"record_id":"x","record_id"'));
add('duplicate-record-last-invalid', patch(V1, `"${RECORD}"`, `"${RECORD}","record_id":"x"`));
add('duplicate-index-last-wins', patch(SINGLE, '"source_index":2', '"source_index":256,"source_index":2'));
add('duplicate-index-last-invalid', patch(SINGLE, '"source_index":2', '"source_index":2,"source_index":256'));
add('duplicate-regions-last-wins', patch(CROSS, '"brain_regions":', '"brain_regions":[],"brain_regions":'));
add('duplicate-regions-last-invalid', raw(toText(CROSS).replace(/}$/, ',"brain_regions":["x"]}')));
add('duplicate-definition-last-wins', patch(atlas(MULTI), `"region_definition":"${ATLAS}"`, `"region_definition":"x","region_definition":"${ATLAS}"`));
add('duplicate-definition-last-invalid', raw(toText(atlas(MULTI)).replace(/}$/, ',"region_definition":"x"}')));
add('duplicate-seed-first-position', raw(`{"seed":1,${toText(V1).slice(1)}`));
add('duplicate-scale-last-wins', patch(V1, '"artifact_scale":1', '"artifact_scale":3,"artifact_scale":1'));
add('duplicate-extra-ar', raw(toText(V1).replace('{', '{"ar":1,"ar":2,')));

// Key order: the canonical request is written in Node's order whatever the input order
for (const [base, request] of Object.entries(BASES)) {
  add(`order-${base}-reversed`, Object.fromEntries(Object.entries(request).reverse()));
  for (let i = 0; i < 3; i++) add(`order-${base}-shuffled-${i}`, Object.fromEntries(shuffle(Object.entries(request))));
}

// Node checks in a fixed order, and the first failing rule gives the message.
for (const [lbl, request] of Object.entries({
  v1FieldsOverValues: { ...V1, record_id: 'x', seed: -1, extra: 1 },
  v1ValuesAll: { record_id: 'x', brain_region: 'x', waveform: 'x', artifact_scale: 3, seed: -1 },
  definitionOverMode: { ...SINGLE, mode: 'other', region_definition: 'x' },
  definitionOverKeys: { ...SINGLE, ar: 1, region_definition: 'x' },
  definitionOverValues: { ...SINGLE, record_id: 'x', source_index: -1, region_definition: 'x' },
  modeOverValues: { ...SINGLE, mode: 'other', record_id: 'x' },
  keysOverValues: { ...SINGLE, record_id: 'x', source_index: -1, extra: 1 },
  choiceOverIndex: { ...SINGLE, seed: -1, source_index: -1 },
  choiceOverRegions: { ...CROSS, waveform: 'x', brain_regions: [] },
  choiceOverRegion: { ...MULTI, record_id: 'x', brain_region: 'heart' },
  multiRegionIsChoice: { ...MULTI, brain_region: 'heart' },
  singleIgnoresRegionChoice: { ...COMMON, mode: 'single_source', source_index: 0 },
  crossChoiceBeforeShape: { ...CROSS, artifact_scale: 3, brain_regions: 'frontal' },
}))
  add(`first-${lbl}`, request);

// The requests of the Node tests this format mirrors.
const NODE_REQ = V1;
add('node-test-source-bounded', NODE_REQ);
for (const [lbl, change] of Object.entries({ path: { record_id: '../../x' }, recordArray: { record_id: [RECORD] }, seed: { seed: 1.5 },
  scale: { artifact_scale: -1 }, region: { brain_region: 'heart' }, waveform: { waveform: 'unknown' }, ar: { ar: 90 },
  filePath: { path: '/tmp/a' }, coordinates: { xyzMm: [] } }))
  add(`node-test-source-bounded-${lbl}`, { ...NODE_REQ, ...change });
const nodeCross = brain_regions => ({ ...COMMON, mode: 'cross_region', brain_regions });
for (const [i, regions] of [ABSENT, null, '', 'frontal', [], ['frontal', 'frontal'], ['unknown'], [0], [true], [{ id: 'frontal' }],
  [...SOURCE_REGIONS, 'frontal']].entries())
  add(`node-test-cross-shape-${i}`, nodeCross(regions));
for (const [lbl, extra] of Object.entries({ region: { brain_region: 'frontal' }, index: { source_index: 0 }, ar: { ar: 90 },
  coordinates: { xyz_mm: [] }, path: { path: '/tmp/input' } }))
  add(`node-test-cross-mixed-${lbl}`, { ...nodeCross(['frontal']), ...extra });
add('node-test-legacy-single', { ...COMMON, mode: 'single_source', source_index: 0 });
add('node-test-legacy-multi', { ...COMMON, mode: 'multi_source', brain_region: 'frontal' });
for (const [lbl, other] of Object.entries({ central: nodeCross(['central']), two: nodeCross(['frontal', 'central']),
  seed: { ...nodeCross(['frontal']), seed: 2027 }, waveform: { ...nodeCross(['frontal']), waveform: 'rhythm' },
  scale: { ...nodeCross(['frontal']), artifact_scale: 2 } }))
  add(`node-test-legacy-${lbl}`, other);
const UPGRADE = { record_id: RECORD, mode: 'single_source', source_index: 2, waveform: 'burst', artifact_scale: 1, seed: 2026 };
add('node-test-upgrade', UPGRADE);
for (const [lbl, change] of Object.entries({ ar: { ar: 90 }, index256: { source_index: 256 }, indexNegative: { source_index: -1 },
  region: { brain_region: 'frontal' }, mode: { mode: 'other' }, index3: { source_index: 3 } }))
  add(`node-test-upgrade-${lbl}`, { ...UPGRADE, ...change });
for (const mode of ['single_source', 'multi_source']) {
  const old = { ...COMMON, mode, ...(mode === 'single_source' ? { source_index: 0 } : { brain_region: 'frontal' }) };
  add(`node-test-atlas-${mode}`, atlas(old));
  add(`node-test-atlas-${mode}-unverified`, { ...atlas(old), region_definition: 'unverified' });
}

// Raw bytes: the body is decoded as UTF-8 with replacement before JSON.parse.
for (const [lbl, bytes] of Object.entries({
  invalidByte: [0xff], truncatedTwo: [0xc3], encodedSurrogate: [0xed, 0xa0, 0x80], overlong: [0xc0, 0xaf], valid: [0xe2, 0x82, 0xac],
})) {
  const [before, after] = toText(V1).split(RECORD);
  addBytes(`bytes-record-${lbl}`, [...Buffer.from(before + 'a'.repeat(63)), ...bytes, ...Buffer.from(after)]);
  addBytes(`bytes-key-${lbl}`, [...Buffer.from('{"'), ...bytes, ...Buffer.from(`":1,${toText(SINGLE).slice(1)}`)]);
  addBytes(`bytes-mode-${lbl}`, [...Buffer.from('{"mode":"single_source'), ...bytes, ...Buffer.from(`",${toText(COMMON).slice(1, -1)},"source_index":0}`)]);
  const [head, tail] = toText(atlas(CROSS)).split(ATLAS);
  addBytes(`bytes-definition-${lbl}`, [...Buffer.from(head + ATLAS), ...bytes, ...Buffer.from(tail)]);
  const [left, right] = toText(CROSS).split('"occipital"');
  addBytes(`bytes-cross-item-${lbl}`, [...Buffer.from(left + '"occipital'), ...bytes, ...Buffer.from('"' + right)]);
}
addBytes('bytes-plain', [...Buffer.from(toText(atlas(CROSS)))]);
addBytes('bytes-bom', [0xef, 0xbb, 0xbf, ...Buffer.from(toText(V1))]);

// Shared fixtures (contracts/fixtures/requests.json): generate.mjs checks that Node still gives the recorded outcome.
const corpus = JSON.parse(readFileSync(new URL('../../../contracts/fixtures/requests.json', import.meta.url), 'utf8'));
for (const sample of corpus.cases.filter(sample => sample.service === 'source'))
  add(`fixture-${sample.name}`, raw(JSON.stringify(sample.request)),
    { accepted: sample.valid, canonical: sample.valid ? JSON.stringify(sample.canonical) : null });

// Random requests: mostly valid fields in random key order, so that about a third pass.
const POOLS = {
  record_id: [...Array(17).fill(null), 'A'.repeat(64), 'a'.repeat(63), '../../x'],
  waveform: [...Array(6).fill(['burst', 'rhythm']).flat(), 'Burst', 'spike'],
  artifact_scale: [0, 0.5, 1, 2, 4, 0, 0.5, 1, 2, 4, raw('1.0'), raw('5e-1'), raw('-0'), raw('4e0'), 3, '1', true],
  seed: [0, 1, 2026, 9999, 42, 2026, 7, 31, 5000, 123, raw('2026.0'), raw('9.999e3'), raw('-0'), 10000, -1, 1.5, '2026'],
  mode: [ABSENT, ABSENT, ABSENT, 'single_source', 'single_source', 'single_source', 'multi_source', 'multi_source',
    'multi_source', 'cross_region', 'cross_region', 'cross_region', 'cross_region', null, 'other'],
  region_definition: [ABSENT, ABSENT, ATLAS, ATLAS, ATLAS, ATLAS, 'unverified'],
  ar: [...Array(30).fill(ABSENT), 0.9],
};
const SOURCES = {
  single_source: () => ({ source_index: random() < 0.9 ? rand32() % 256 : pick([256, -1, 0.5, '3', raw('255.0'), true]) }),
  multi_source: () => ({ brain_region: random() < 0.9 ? pick(SOURCE_REGIONS) : pick(['heart', 'Frontal', null]) }),
  cross_region: () => ({ brain_regions: random() < 0.9 ? shuffle(pick(subsets)) : pick([[], ['frontal', 'frontal'],
    [...SOURCE_REGIONS, 'central'], ['x'], 'frontal']) }),
  v1: () => ({ brain_region: random() < 0.9 ? pick(SOURCE_REGIONS) : pick(['heart', 0]) }),
};
for (let i = 0; i < 600; i++) {
  const fields = Object.fromEntries(Object.entries(POOLS).map(([key, pool]) => [key, pick(pool)]));
  if (fields.record_id === null) fields.record_id = randomHex();
  const mode = fields.mode, kind = mode === ABSENT ? 'v1' : SOURCES[mode] ? mode : pick(Object.keys(SOURCES));
  if (mode === ABSENT && random() < 0.9) fields.region_definition = ABSENT;
  const source = random() < 0.95 ? SOURCES[kind]() : { ...SOURCES[pick(Object.keys(SOURCES))]() };
  const request = { ...fields, ...source };
  add(`combo-${i}`, Object.fromEntries(random() < 0.5 ? shuffle(Object.entries(request)) : Object.entries(request)));
}

// Every value without mode takes the v1 path, so normalizeSourceRequest alone gives the same outcome.
for (const variant of variants) {
  if (!variant.text) continue;
  let value;
  try { value = JSON.parse(variant.text); } catch { continue; }
  if (value?.mode !== undefined) continue;
  const outcome = fn => { try { return JSON.stringify(fn(value)); } catch (error) { return `error: ${error.message}`; } };
  if (outcome(normalizeReceptionRequest) !== outcome(normalizeSourceRequest))
    throw new Error(`${variant.name}: normalizeReceptionRequest and normalizeSourceRequest disagree`);
}
