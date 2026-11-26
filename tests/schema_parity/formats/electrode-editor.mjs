// electrode-editor: the body of POST /api/electrode-editor/jobs and /lookup, for 'prepare' and 'evaluate' actions.
// Node's outcome is normalizeEditorRequest (webapp/server/electrode-editor-server.mjs).
import { normalizeEditorRequest } from '../../../webapp/server/electrode-editor-server.mjs';
import { ABSENT, collector, createRandom, label, raw, toText } from '../support.mjs';

export const name = 'electrode-editor';
export const normalize = normalizeEditorRequest;

const { pick } = createRandom(0xed170426);
const { variants, add } = collector();
export { variants };

const PARENT = 'a'.repeat(64);
const DIGEST = 'b'.repeat(64);
const slots = (overrides = {}) =>
  Array.from({ length: 64 }, (_, i) => ({ bank_index: i * 10, enabled: true, ...(overrides[i] || {}) }));
const prepareReq = (overrides = {}) => ({ action: 'prepare', parent_id: PARENT, ...overrides });
const evalReq = (overrides = {}) => ({
  action: 'evaluate', parent_id: PARENT, parent_digest: DIGEST, seed: 2026, slots: slots(), ...overrides,
});

// Valid prepare and evaluate requests
add('prepare-valid', prepareReq());
add('prepare-reordered', { parent_id: PARENT, action: 'prepare' });
add('prepare-pretty', raw(JSON.stringify(prepareReq(), null, 2)));
add('evaluate-valid', evalReq());
add('evaluate-reordered', { slots: slots(), seed: 2026, parent_digest: DIGEST, parent_id: PARENT, action: 'evaluate' });
add('evaluate-two-active', evalReq({ slots: Array.from({ length: 64 }, (_, i) => ({ bank_index: i, enabled: i < 2 })) }));
add('evaluate-unbalanced-deletion', evalReq({ slots: Array.from({ length: 64 }, (_, i) => ({ bank_index: i * 3, enabled: i < 5 || i === 63 })) }));
add('evaluate-duplicate-bank-indices', evalReq({ slots: Array.from({ length: 64 }, (_, i) => ({ bank_index: 42, enabled: i < 10 })) }));
add('evaluate-bank-bounds', evalReq({
  slots: Array.from({ length: 64 }, (_, i) => ({ bank_index: i === 0 ? 0 : i === 63 ? 1000000 : i, enabled: true })),
}));
add('evaluate-float-integers', evalReq({
  seed: raw('2026.0'),
  slots: Array.from({ length: 64 }, (_, i) => ({
    bank_index: i === 0 ? raw('-0.0') : i === 1 ? raw('1e6') : raw(`${i}.0`),
    enabled: i % 2 === 0,
  })),
}));
add('evaluate-slot-keys-reordered', evalReq({
  slots: Array.from({ length: 64 }, (_, i) => ({ enabled: i < 16, bank_index: i })),
}));

// Non-object and syntax edge cases
for (const [i, text] of ['null', '[]', '1', '"prepare"', 'true', '{}'].entries()) {
  add(`top-not-request-${i}`, raw(text));
}
add('trailing-garbage', raw(toText(prepareReq()) + 'x'));
add('bom-prefix', raw('\ufeff' + toText(prepareReq())));
add('duplicate-seed-last-valid', raw(toText(evalReq()).replace('"seed":2026', '"seed":1,"seed":2026')));
add('duplicate-seed-last-invalid', raw(toText(evalReq()).replace('"seed":2026', '"seed":2026,"seed":2025')));
add('deep-array-seed', evalReq({ seed: raw('['.repeat(4000) + '2026' + ']'.repeat(4000)) }));

// Action and Hex IDs
for (const action of [ABSENT, null, '', 'delete', 'Prepare', 'evaluate ', 1, true, ['prepare'], {}]) {
  add(`action-${label(action)}`, prepareReq({ action }));
}
const BAD_IDS = {
  absent: ABSENT, null: null, empty: '', short: 'a'.repeat(63), long: 'a'.repeat(65),
  upper: 'A'.repeat(64), lastUpper: 'a'.repeat(63) + 'F', nonHex: 'g' + 'a'.repeat(63),
  newline: PARENT + '\n', leadingSpace: ' ' + PARENT.slice(1), number: 123, array: [PARENT],
};
for (const [idLabel, value] of Object.entries(BAD_IDS)) {
  add(`prepare-parent-${idLabel}`, prepareReq({ parent_id: value }));
  add(`evaluate-parent-${idLabel}`, evalReq({ parent_id: value }));
  add(`evaluate-digest-${idLabel}`, evalReq({ parent_digest: value }));
}

// Prepare field strictness
for (const extra of ['seed', 'slots', 'parent_digest', 'extra', '__proto__', 'code']) {
  add(`prepare-extra-${extra}`, prepareReq({ [extra]: extra === 'seed' ? 2026 : 1 }));
}
add('prepare-merged-key', { 'action,parent_id': 1, action: 'prepare', parent_id: PARENT });

// Evaluate protocol and seed
for (const missing of ['parent_digest', 'seed', 'slots']) {
  add(`evaluate-missing-${missing}`, evalReq({ [missing]: ABSENT }));
}
for (const extra of ['code', 'threshold', 'radius_mm', 'extra', '__proto__']) {
  add(`evaluate-extra-${extra}`, evalReq({ [extra]: 1 }));
}
for (const seed of [0, 2025, 2027, 2026.5, '2026', true, false, null, [2026], raw('1e400'), raw('NaN')]) {
  add(`evaluate-seed-${label(seed)}`, evalReq({ seed }));
}

// Slot bounds and active count
add('slots-not-array', evalReq({ slots: 'x' }));
add('slots-null', evalReq({ slots: null }));
add('slots-63', evalReq({ slots: slots().slice(0, 63) }));
add('slots-65', evalReq({ slots: [...slots(), { bank_index: 64, enabled: true }] }));
add('slots-zero-active', evalReq({ slots: Array.from({ length: 64 }, (_, i) => ({ bank_index: i, enabled: false })) }));
add('slots-one-active', evalReq({ slots: Array.from({ length: 64 }, (_, i) => ({ bank_index: i, enabled: i === 12 })) }));

const BAD_SLOTS = {
  nullSlot: null,
  arraySlot: [0, true],
  emptySlot: {},
  extraXyz: { bank_index: 0, enabled: true, xyz_mm: [0, 0, 0] },
  missingBank: { enabled: true },
  missingEnabled: { bank_index: 0 },
  mergedKey: { 'bank_index,enabled': 1 },
  negativeBank: { bank_index: -1, enabled: true },
  overMaxBank: { bank_index: 1000001, enabled: true },
  fractionalBank: { bank_index: 3.5, enabled: true },
  nearIntBank: { bank_index: raw('1000000.0000000002'), enabled: true },
  stringBank: { bank_index: '0', enabled: true },
  boolBank: { bank_index: true, enabled: true },
  nullBank: { bank_index: null, enabled: true },
  infBank: { bank_index: raw('1e400'), enabled: true },
  intEnabled: { bank_index: 0, enabled: 1 },
  stringEnabled: { bank_index: 0, enabled: 'true' },
  nullEnabled: { bank_index: 0, enabled: null },
};
for (const [slotLabel, bad] of Object.entries(BAD_SLOTS)) {
  add(`slot-bad-${slotLabel}`, evalReq({ slots: slots().map((s, i) => (i === 7 ? bad : s)) }));
}

// Deterministic random combinations
const ACTIONS = ['prepare', 'evaluate', 'evaluate', 'invalid'];
const IDS = [PARENT, '0123456789abcdef'.repeat(4), 'A'.repeat(64), 'short'];
const SEEDS = [2026, raw('2026.0'), 2025, true];
for (let i = 0; i < 120; i++) {
  const action = pick(ACTIONS);
  if (action === 'prepare') {
    const req = { action, parent_id: pick(IDS) };
    if (pick([true, false, false, false])) req.extra = 1;
    add(`combo-prepare-${i}`, req);
  } else {
    const activeCount = pick([0, 1, 2, 16, 32, 64]);
    const builtSlots = Array.from({ length: pick([64, 64, 64, 63]) }, (_, idx) => ({
      bank_index: pick([idx, 0, 1000000, raw('10.0'), -1]),
      enabled: idx < activeCount,
    }));
    add(`combo-eval-${i}`, {
      action,
      parent_id: pick(IDS),
      parent_digest: pick(IDS),
      seed: pick(SEEDS),
      slots: builtSlots,
    });
  }
}
