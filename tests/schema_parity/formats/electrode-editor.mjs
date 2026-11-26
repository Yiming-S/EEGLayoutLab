// electrode-editor: the body of POST /api/electrode-editor/jobs and the request of an editor cache record.
// Node's outcome is normalizeEditorRequest, as in ElectrodeEditorService.normalize and the community queue's
// electrode-editor adapter. Rejected variants also record Node's message, which
// eeglayoutlab.schemas.electrode_editor.normalize_editor_request must raise (tests/service/test_editor_request.py).
import { normalizeEditorRequest } from '../../../webapp/server/electrode-editor-server.mjs';
import { ABSENT, collector, createRandom, label, raw, toText } from '../support.mjs';

export const name = 'electrode-editor';
export const normalize = normalizeEditorRequest;

const { random, rand32, pick } = createRandom(0xed170126);
const { variants, add, addBytes } = collector();
export { variants };

const PARENT = 'a'.repeat(64);
const DIGEST = 'b'.repeat(64);
const HEX = '0123456789abcdef'.repeat(4);
const slots = (count = 64, enabled = () => true, index = i => i) =>
  Array.from({ length: count }, (_, i) => ({ bank_index: index(i), enabled: enabled(i) }));
const PREPARE = { action: 'prepare', parent_id: PARENT };
const EVALUATE = { action: 'evaluate', parent_id: PARENT, parent_digest: DIGEST, seed: 2026, slots: slots() };
const prepare = (overrides = {}) => ({ ...PREPARE, ...overrides });
const evaluate = (overrides = {}) => ({ ...EVALUATE, ...overrides });
/** The 64 slots with slot `at` replaced by `slot` (written with toText, so it may hold Raw values or ABSENT). */
const withSlot = (at, slot) => evaluate({ slots: slots().map((s, i) => (i === at ? slot : s)) });
const shuffle = list => list.map(item => [random(), item]).sort((a, b) => a[0] - b[0]).map(([, item]) => item);
const randomHex = () => Array.from({ length: 64 }, () => HEX[rand32() % 16]).join('');


// Top level
add('base-prepare', PREPARE);
add('base-evaluate', EVALUATE);
add('base-evaluate-pretty', raw(JSON.stringify(EVALUATE, null, 2)));
add('base-prepare-hex', prepare({ parent_id: HEX }));
for (const [i, value] of ['[]', 'null', '1', '0', '"x"', '""', 'true', 'false', '{}', '[{}]', `[${toText(PREPARE)}]`,
  `[${toText(EVALUATE)}]`, '"prepare"', `"${PARENT}"`].entries())
  add(`top-not-request-${i}`, raw(value));
add('trailing-garbage', raw(toText(PREPARE) + 'x'));
add('trailing-comma', raw(toText(PREPARE).replace(/}$/, ',}')));
add('trailing-whitespace', raw(' \n\t' + toText(EVALUATE) + ' \r\n'));
add('bom-prefix', raw('﻿' + toText(PREPARE)));
add('single-quotes', raw(toText(PREPARE).replaceAll('"', "'")));
add('escaped-action', raw(toText(PREPARE).replace('"prepare"', '"\\u0070repare"')));
add('escaped-evaluate', raw(toText(EVALUATE).replace('"evaluate"', '"\\u0065valuate"')));
add('escaped-parent', raw(toText(PREPARE).replace(`"${PARENT}"`, `"${'\\u0061'.repeat(64)}"`)));
add('escaped-key', raw(toText(PREPARE).replace('"parent_id"', '"parent\\u005fid"')));
add('escaped-slot-key', raw(toText(EVALUATE).replace('"enabled"', '"\\u0065nabled"')));

// Action: prepare or evaluate, as a string; anything else fails before the fields are looked at
for (const value of ['prepare', 'evaluate', 'Prepare', 'PREPARE', 'Evaluate', 'EVALUATE', ' prepare', 'prepare ', 'evaluate\n',
  'prepare\u0000', 'perturb', 'edit', 'lookup', 'run', '', null, 0, 1, true, false, ['prepare'], { action: 'prepare' }, ABSENT,
  raw('NaN')]) {
  add(`action-prepare-${label(value)}`, prepare({ action: value }));
  add(`action-evaluate-${label(value)}`, evaluate({ action: value }));
}

// Parent identifier: 64 lowercase hexadecimal digits
const IDS = {
  lower: PARENT, zeros: '0'.repeat(64), hex: HEX, f: 'f'.repeat(64), upper: 'A'.repeat(64), oneUpper: 'A' + 'a'.repeat(63),
  lastUpper: 'a'.repeat(63) + 'F', mixedHex: HEX.toUpperCase(), short: 'a'.repeat(63), long: 'a'.repeat(65), double: 'a'.repeat(128),
  empty: '', g: 'g' + 'a'.repeat(63), lastG: 'a'.repeat(63) + 'g', space: ' ' + 'a'.repeat(63), padded: ' ' + PARENT,
  trailingSpace: PARENT + ' ', newline: PARENT + '\n', crlf: PARENT + '\r\n', leadingNewline: '\n' + PARENT, nul: PARENT + '\u0000',
  innerNul: 'a'.repeat(32) + '\u0000' + 'a'.repeat(31), path: '../../private', pathPadded: '../../private'.padEnd(64, 'a'),
  dash: 'a'.repeat(32) + '-' + 'a'.repeat(31), fullWidth: 'ａ'.repeat(64), arabicDigits: '١'.repeat(64),
  superscript: '¹'.repeat(64), surrogate: 'a'.repeat(63) + '\ud800', emoji: 'a'.repeat(62) + '😀',
  sha256Prefix: 'sha256:' + 'a'.repeat(64), uuid: '0123abcd-0123-4567-89ab-0123456789ab',
};
const NON_STRINGS = { null: null, zero: 0, number: 1234, true: true, false: false, array: [PARENT], object: { id: PARENT }, absent: ABSENT,
  hexNumber: raw('1' + '0'.repeat(63)) };
for (const [lbl, value] of Object.entries({ ...IDS, ...NON_STRINGS })) {
  add(`parent-prepare-${lbl}`, prepare({ parent_id: value }));
  add(`parent-evaluate-${lbl}`, evaluate({ parent_id: value }));
  add(`digest-${lbl}`, evaluate({ parent_digest: value }));
}
for (let i = 0; i < 12; i++) add(`parent-random-${i}`, evaluate({ parent_id: randomHex(), parent_digest: randomHex() }));
add('parent-equals-digest', evaluate({ parent_digest: PARENT }));

// A preparation has exactly action and parent_id
for (const key of ['parent_digest', 'seed', 'slots', 'ar', 'AR', 'locale', 'region_count', 'request', 'Action', 'action ', 'parent_ID',
  'parentId', 'id', '', '0', '__proto__', 'constructor', 'toString', 'hasOwnProperty', 'valueOf', 'action,parent_id', ',',
  'parent_id,seed'])
  for (const [lbl, value] of Object.entries({ one: 1, null: null, string: 'x', valid: key === 'seed' ? 2026 : key === 'slots' ? slots() : DIGEST }))
    add(`prepare-extra-${JSON.stringify(key)}-${lbl}`, prepare({ [key]: value }));
add('prepare-all-evaluate-fields', prepare({ parent_digest: DIGEST, seed: 2026, slots: slots() }));
add('prepare-reordered', { parent_id: PARENT, action: 'prepare' });
add('prepare-duplicate-action-last-wins', raw(toText(PREPARE).replace('"action":"prepare"', '"action":"evaluate","action":"prepare"')));
add('prepare-duplicate-action-last-evaluate', raw(toText(PREPARE).replace('"action":"prepare"', '"action":"prepare","action":"evaluate"')));
add('prepare-duplicate-parent-last-wins', raw(toText(PREPARE).replace('"parent_id"', `"parent_id":"x","parent_id"`)));
add('prepare-duplicate-parent-last-invalid', raw(toText(PREPARE).replace(`"${PARENT}"`, `"${PARENT}","parent_id":"x"`)));
add('prepare-comma-key-only', { action: 'prepare', 'parent_id,x': PARENT });
add('prepare-comma-key-both', { 'action,parent_id': 'prepare' });

// An evaluation has exactly action, parent_id, parent_digest, seed and slots
for (const key of ['parent_digest', 'seed', 'slots']) add(`evaluate-missing-${key}`, evaluate({ [key]: ABSENT }));
for (const key of ['ar', 'AR', 'locale', 'threshold', 'command', 'script', 'radius_mm', 'region_count', 'noise_model', 'electrode_count',
  'request', 'identity', 'parent', 'Seed', 'slots ', 'parentDigest', '', '0', '__proto__', 'constructor', 'toString', 'valueOf',
  'parent_digest,parent_id', 'seed,slots', ','])
  for (const [lbl, value] of Object.entries({ one: 1, null: null, string: 'x' }))
    add(`evaluate-extra-${JSON.stringify(key)}-${lbl}`, evaluate({ [key]: value }));
add('evaluate-comma-key-digest', { action: 'evaluate', parent_id: PARENT, 'parent_digest,seed': DIGEST, slots: slots() });
add('evaluate-comma-key-all', { action: 'evaluate', parent_id: PARENT, 'parent_digest,seed,slots': DIGEST });
add('evaluate-duplicate-seed-last-wins', raw(toText(EVALUATE).replace('"seed":2026', '"seed":9,"seed":2026')));
add('evaluate-duplicate-seed-last-invalid', raw(toText(EVALUATE).replace('"seed":2026', '"seed":2026,"seed":9')));
add('evaluate-duplicate-slots-last-wins', raw(toText(EVALUATE).replace('"slots":', `"slots":[],"slots":`)));
add('evaluate-duplicate-slots-last-invalid', raw(toText(EVALUATE).replace(/}$/, ',"slots":[]}')));
add('evaluate-duplicate-digest', raw(toText(EVALUATE).replace('"parent_digest"', `"parent_digest":"x","parent_digest"`)));
add('evaluate-proto-key', raw(toText(EVALUATE).replace(/}$/, ',"__proto__":{"x":1}}')));

// Key order: the canonical request is written in Node's order whatever the input order
const ORDERED = evaluate({ slots: slots(64, i => i % 3 !== 0, i => 1000 + 7 * i) });
add('order-evaluate', ORDERED);
add('order-evaluate-reversed', Object.fromEntries(Object.entries(ORDERED).reverse()));
for (let i = 0; i < 4; i++) add(`order-evaluate-shuffled-${i}`, Object.fromEntries(shuffle(Object.entries(ORDERED))));
add('order-slot-keys-reversed', evaluate({ slots: slots().map(s => ({ enabled: s.enabled, bank_index: s.bank_index })) }));
add('order-slot-keys-mixed', evaluate({ slots: slots().map((s, i) => (i % 2 ? { enabled: s.enabled, bank_index: s.bank_index } : s)) }));

// Seed: exactly the number 2026
for (const value of [2026, 2025, 2027, 0, 1, 9, -2026, 20260, 9999, raw('2026.0'), raw('2026.00'), raw('2.026e3'), raw('2.026E+3'),
  raw('2026e0'), raw('202600e-2'), raw('20260e-1'), raw('0.2026e4'), raw('2026.0000000000001'), raw('2026.000000000001'),
  raw('2025.9999999999999'), raw('2025.999999999999'), raw('-0'), raw('1e400'), raw('-1e400'), raw('1e-400'), 2026.5, '2026', '',
  true, false, null, [2026], { seed: 2026 }, ABSENT])
  add(`seed-${label(value)}`, evaluate({ seed: value }));
add('seed-long-zeros', evaluate({ seed: raw('2026.' + '0'.repeat(400)) }));
add('seed-huge-integer', evaluate({ seed: raw('2026' + '0'.repeat(400)) }));

// Slots: an array of exactly 64
for (const count of [0, 1, 2, 32, 62, 63, 64, 65, 66, 128])
  add(`slots-count-${count}`, evaluate({ slots: slots(count) }));
for (const [lbl, value] of Object.entries({
  null: null, object: { ...slots() }, lengthObject: { length: 64 }, string: 'x'.repeat(64), number: 64, true: true, false: false,
  empty: '', nested: [slots()], arrayOfArrays: slots().map(s => [s.bank_index, s.enabled]),
}))
  add(`slots-${lbl}`, evaluate({ slots: value }));

// A slot is {bank_index, enabled}, nothing else
for (const at of [0, 31, 63])
  for (const [lbl, value] of Object.entries({
    null: null, false: false, true: true, zero: 0, one: 1, emptyString: '', string: 'x', twoChars: 'ab', array: [], pair: [at, true],
    empty: {}, onlyIndex: { bank_index: at }, onlyEnabled: { enabled: true }, extra: { bank_index: at, enabled: true, region: 0 },
    extraNull: { bank_index: at, enabled: true, label: null }, proto: { bank_index: at, enabled: true, ['__proto__']: 1 },
    commaKey: { 'bank_index,enabled': at }, commaKeyEnabled: { 'bank_index,enabled': true, enabled: true },
    upper: { Bank_index: at, enabled: true }, index: { index: at, enabled: true }, active: { bank_index: at, active: true },
    stringKey: { bank_index: at, enabled: true, '': 1 },
  }))
    add(`slot-${at}-${lbl}`, withSlot(at, value));
add('slot-duplicate-enabled-last-wins', raw(toText(EVALUATE).replace('{"bank_index":0,"enabled":true}', '{"bank_index":0,"enabled":7,"enabled":true}')));
add('slot-duplicate-index-last-invalid', raw(toText(EVALUATE).replace('{"bank_index":0,"enabled":true}', '{"bank_index":0,"enabled":true,"bank_index":-1}')));

// Bank index: an integer in [0, 1000000]
for (const value of [0, 1, 63, 64, 999999, 1000000, 1000001, 1000002, 2000000, -1, -2, -1000000, 0.5, 1.5, 999999.5, 1e21,
  2 ** 31, 2 ** 32, raw('-0'), raw('-0.0'), raw('0.0'), raw('1.0'), raw('1e0'), raw('10e-1'), raw('1e6'), raw('1E6'), raw('1e+6'),
  raw('1000000.0'), raw('1000000.00000000001'), raw('1000000.0000000001'), raw('999999.99999999999'), raw('999999.9999999999'),
  raw('1.0000000000000001'), raw('1.000000000000001'), raw('-0.00000000000000001'), raw('1e-400'), raw('-1e-400'), raw('1e400'),
  raw('-1e400'), raw('9007199254740993'), raw('1' + '0'.repeat(400)), '0', '1', '', true, false, null, [1], { index: 1 }, ABSENT])
  for (const at of [0, 63])
    add(`bank-index-${at}-${label(value)}`, withSlot(at, { bank_index: value, enabled: true }));
// Indices need not be distinct or in the parent's regions here: the worker checks them against the parent's data.
add('bank-index-all-zero', evaluate({ slots: slots(64, () => true, () => 0) }));
add('bank-index-all-max', evaluate({ slots: slots(64, () => true, () => 1000000) }));
add('bank-index-descending', evaluate({ slots: slots(64, () => true, i => 1000000 - i) }));
add('bank-index-float-spellings', evaluate({ slots: slots(64, () => true, i => raw(`${i}.0`)) }));
add('bank-index-exponent-spellings', evaluate({ slots: slots(64, () => true, i => raw(`${i * 10}e-1`)) }));

// Enabled: a boolean
for (const value of [true, false, 0, 1, raw('1.0'), 'true', 'false', '', null, [], [true], {}, ABSENT])
  for (const at of [0, 63])
    add(`enabled-${at}-${label(value)}`, withSlot(at, { bank_index: at, enabled: value }));

// At least two active electrodes; the inactive slots keep their identities
for (const count of [0, 1, 2, 3, 4, 8, 32, 56, 62, 63, 64]) {
  add(`active-first-${count}`, evaluate({ slots: slots(64, i => i < count) }));
  add(`active-last-${count}`, evaluate({ slots: slots(64, i => i >= 64 - count) }));
}
for (const pair of [[0, 63], [31, 32], [5, 6], [62, 63]])
  add(`active-pair-${pair.join('-')}`, evaluate({ slots: slots(64, i => pair.includes(i)) }));
for (const at of [0, 40, 63]) add(`active-only-${at}`, evaluate({ slots: slots(64, i => i === at) }));
add('active-one-and-truthy-number', evaluate({ slots: slots(64, i => (i === 0 ? true : i === 1 ? 1 : false)) }));

// Node checks in a fixed order, and the first failing rule gives the message.
add('first-request-over-fields', { action: 'other', parent_id: 'x', seed: 1, slots: [], extra: 1 });
add('first-request-parent-over-fields', { action: 'prepare', parent_id: 'x', extra: 1 });
add('first-request-evaluate-parent', evaluate({ parent_id: 'x', parent_digest: 'x', seed: 1, slots: [] }));
add('first-preparation-fields', prepare({ parent_digest: 'x', slots: [] }));
add('first-protocol-fields-over-slots', evaluate({ extra: 1, slots: [] }));
add('first-protocol-digest-over-slots', evaluate({ parent_digest: 'x', slots: slots(64, () => false) }));
add('first-protocol-seed-over-slots', evaluate({ seed: 1, slots: slots(3) }));
add('first-slots-over-active', evaluate({ slots: [...slots(63, () => false), null] }));
add('first-slots-count-over-active', evaluate({ slots: slots(65, () => false) }));
add('first-slots-late-bad-slot', evaluate({ slots: slots(64, () => false, i => (i === 63 ? -1 : i)) }));

// The requests of the Node test this format mirrors (check-electrode-editor.mjs: protocol permits unbalanced deletion,
// not arbitrary code, thresholds or added slots).
const NODE_TEST = evaluate({ slots: slots(64, i => i !== 0) });
add('node-test-unbalanced-deletion', NODE_TEST);
for (const [lbl, patch] of Object.entries({ ar: { ar: 32 }, locale: { locale: 'en' }, seed: { seed: 9 }, noSlots: { slots: [] },
  addedSlot: { slots: [...NODE_TEST.slots, NODE_TEST.slots[0]] }, path: { parent_id: '../../private' } }))
  add(`node-test-${lbl}`, { ...NODE_TEST, ...patch });

// Raw bytes: the body is decoded as UTF-8 with replacement before JSON.parse.
for (const [lbl, bytes] of Object.entries({
  invalidByte: [0xff], truncatedTwo: [0xc3], encodedSurrogate: [0xed, 0xa0, 0x80], overlong: [0xc0, 0xaf], valid: [0xe2, 0x82, 0xac],
})) {
  const [before, after] = toText(PREPARE).split(PARENT);
  addBytes(`bytes-parent-${lbl}`, [...Buffer.from(before + 'a'.repeat(63)), ...bytes, ...Buffer.from(after)]);
  addBytes(`bytes-key-${lbl}`, [...Buffer.from('{"'), ...bytes, ...Buffer.from(`":1,${toText(PREPARE).slice(1)}`)]);
  addBytes(`bytes-action-${lbl}`, [...Buffer.from('{"action":"prepare'), ...bytes, ...Buffer.from(`","parent_id":"${PARENT}"}`)]);
}
addBytes('bytes-plain', [...Buffer.from(toText(EVALUATE))]);
addBytes('bytes-bom', [0xef, 0xbb, 0xbf, ...Buffer.from(toText(PREPARE))]);

// Random requests: mostly valid fields in random key order, so that about a third pass.
const SEEDS = [2026, 2026, 2026, 2026, 2026, 2026, raw('2026.0'), raw('2.026e3'), 2025, '2026'];
const ACTIVE = [() => true, () => random() < 0.7, () => random() < 0.5, () => random() < 0.05, () => false];
const INDEX = [i => i, i => rand32() % 1000001, () => rand32() % 1000001, i => raw(`${i}.0`), () => pick([-1, 1000001, 0.5])];
for (let i = 0; i < 400; i++) {
  const enabled = pick(ACTIVE), index = random() < 0.9 ? pick(INDEX.slice(0, 4)) : INDEX[4];
  const count = random() < 0.9 ? 64 : pick([0, 2, 63, 65]);
  const fields = {
    action: random() < 0.95 ? 'evaluate' : pick(['prepare', 'Evaluate']),
    parent_id: random() < 0.95 ? randomHex() : randomHex().toUpperCase(),
    parent_digest: random() < 0.95 ? randomHex() : randomHex().slice(1),
    seed: pick(SEEDS),
    slots: slots(count, enabled, index),
    ...(random() < 0.05 ? { extra: 1 } : {}),
  };
  add(`combo-${i}`, Object.fromEntries(random() < 0.4 ? shuffle(Object.entries(fields)) : Object.entries(fields)));
}
for (let i = 0; i < 60; i++) {
  const fields = { action: random() < 0.9 ? 'prepare' : 'evaluate', parent_id: random() < 0.85 ? randomHex() : pick(Object.values(IDS)),
    ...(random() < 0.1 ? { parent_digest: randomHex() } : {}) };
  add(`combo-prepare-${i}`, Object.fromEntries(random() < 0.5 ? shuffle(Object.entries(fields)) : Object.entries(fields)));
}
