// project-entry: the body of POST /api/projects/<id>/entries. Node's outcome is ProjectService.body, its attachment
// check (through resolveSnapshot), then ProjectStore.attach's checks of the request before the project is read
// (project-validation.mjs), with the electrode-name annotation Node reads for an evaluation: the kind and its
// scientific reference (a library or editor record, or a signal task receipt), the annotation, the title, the notes
// and the revision. Rejected variants also record Node's message, which
// eeglayoutlab.schemas.projects.normalize_entry must raise (tests/service/test_project_request.py).
import { ABSENT, collector, createRandom, raw } from '../support.mjs';
import { ENTRY_KINDS, ID, KEY, NOT_OBJECTS, REVISIONS, accepted, annotation, attachment, body, store, texts } from './project-validation.mjs';

export const name = 'project-entry';
/** Node's list of entry kinds, compared with the Python schema's (tests/test_schema_parity.py). */
export const options = { entry_kinds: ENTRY_KINDS };
const SIGNAL = 'c'.repeat(64);
export async function normalize(parsed) {
  const input = await body(parsed);
  await attachment(input);
  const record_id = input.kind === 'source' ? SIGNAL : input.record_id;
  const snapshot = { schema: 'research-project-snapshot/1', kind: input.kind, record_id, payload: {},
    ...(input.annotation_id !== undefined ? { electrode_annotation: annotation(input.annotation_id, record_id) } : {}) };
  await accepted(store.attach(ID, KEY, input, snapshot, {}));
  const reference = input.kind === 'source' ? 'receipt_id' : 'record_id';
  return { revision: input.revision, kind: input.kind, [reference]: input[reference],
    ...(input.annotation_id !== undefined ? { annotation_id: input.annotation_id } : {}),
    ...(input.title != null ? { title: input.title.trim() } : {}), ...(input.notes != null ? { notes: input.notes.trim() } : {}) };
}

const { pick, random } = createRandom(0x7e1a2b3c);
const { variants, add } = collector();
export { variants };

const RECORD = 'a'.repeat(64), NAMES = 'b'.repeat(64), RECEIPT = '00000000-0000-4000-8000-0000000000a1';
const BASES = {
  layout: { revision: 1, kind: 'layout', record_id: RECORD },
  named: { revision: 1, kind: 'layout', record_id: RECORD, annotation_id: NAMES },
  editor: { revision: 1, kind: 'editor', record_id: RECORD },
  source: { revision: 1, kind: 'source', receipt_id: RECEIPT },
};
for (const [label, value] of NOT_OBJECTS) add(`body-${label}`, value);
add('empty', {});
for (const kind of ENTRY_KINDS) add(`kind-${kind}`, kind === 'source' ? BASES.source : { ...BASES.layout, kind });
for (const [label, kind] of [['upper', 'Layout'], ['null', null], ['number', 1], ['array', ['layout']], ['absent', ABSENT], ['named', 'named_evaluation'], ['signal', 'signal']])
  add(`kind-${label}`, { ...BASES.layout, kind });
for (const [base, value] of Object.entries(BASES)) {
  add(`${base}-base`, value);
  add(`${base}-full`, { ...value, title: '  Signal A  ', notes: ' Selected ' });
  add(`${base}-nulls`, { ...value, title: null, notes: null });
  for (const extra of ['owner_name', 'workflow', 'summary', 'snapshot', 'payload', ''])
    add(`${base}-extra-${extra || 'empty'}`, { ...value, [extra]: 1 });
  for (const [label, revision] of REVISIONS) add(`${base}-revision-${label}`, { ...value, revision });
}
const HASHES = [['upper', 'A'.repeat(64)], ['short', 'a'.repeat(63)], ['long', 'a'.repeat(65)], ['null', null], ['number', 1],
  ['array', [RECORD]], ['nested', [[RECORD]]], ['object', {}], ['padded', ` ${RECORD}`], ['newline', `${RECORD}\n`], ['empty', '']];
for (const [label, value] of HASHES) {
  add(`layout-record-${label}`, { ...BASES.layout, record_id: value });
  add(`editor-record-${label}`, { ...BASES.editor, record_id: value });
  add(`named-annotation-${label}`, { ...BASES.named, annotation_id: value });
}
add('layout-record-absent', { revision: 1, kind: 'layout' });
add('layout-receipt', { ...BASES.layout, receipt_id: RECEIPT });
add('layout-receipt-null', { ...BASES.layout, receipt_id: null });
add('editor-annotation', { ...BASES.editor, annotation_id: NAMES });
add('editor-annotation-null', { ...BASES.editor, annotation_id: null });
add('source-annotation', { ...BASES.source, annotation_id: NAMES });
add('named-annotation-matches-record', { ...BASES.named, annotation_id: RECORD });
add('named-annotation-array-wrong-kind', { ...BASES.editor, annotation_id: [NAMES] });
const RECEIPTS = [['upper', RECEIPT.toUpperCase()], ['v1', '00000000-0000-1000-8000-0000000000a1'], ['variant', '00000000-0000-4000-c000-0000000000a1'],
  ['short', RECEIPT.slice(1)], ['null', null], ['array', [RECEIPT]], ['number', 1], ['empty', ''], ['sha', RECORD], ['absent', ABSENT]];
for (const [label, value] of RECEIPTS) add(`source-receipt-${label}`, { ...BASES.source, receipt_id: value });
add('source-record', { ...BASES.source, record_id: RECORD });
add('source-record-null', { ...BASES.source, record_id: null });
for (const [label, value] of texts(200)) add(`title-${label}`, { ...BASES.layout, title: value });
for (const [label, value] of texts(8000)) add(`notes-${label}`, { ...BASES.source, notes: value });
add('checks-attachment-before-texts', { ...BASES.editor, annotation_id: NAMES, title: '' });
add('checks-annotation-before-texts', { ...BASES.named, annotation_id: [NAMES], title: '' });
add('checks-texts-before-revision', { ...BASES.named, title: '', revision: 0 });
add('checks-title-before-notes', { ...BASES.layout, title: 1, notes: 1 });
add('duplicate-kind', raw(`{"revision":1,"kind":"source","kind":"layout","record_id":"${RECORD}"}`));

const pools = {
  revision: REVISIONS, kind: [['layout', 'layout'], ['editor', 'editor'], ['source', 'source'], ['bad', 'Layout']],
  record_id: [['record', RECORD], ...HASHES.slice(0, 5), ['absent', ABSENT], ['absent2', ABSENT]],
  receipt_id: [['receipt', RECEIPT], ...RECEIPTS.slice(0, 4), ['absent', ABSENT], ['absent2', ABSENT], ['absent3', ABSENT]],
  annotation_id: [['names', NAMES], ['array', [NAMES]], ['null', null], ['absent', ABSENT], ['absent2', ABSENT], ['absent3', ABSENT]],
  title: [...texts(200), ['absent', ABSENT]], notes: [...texts(8000), ['absent', ABSENT]],
};
for (let i = 0; i < 120; i++) {
  const value = {}, parts = [];
  for (const field of ['revision', 'kind', 'record_id', 'receipt_id', 'annotation_id', 'title', 'notes']) {
    const [label, item] = pick(pools[field]); value[field] = item; parts.push(`${field}:${label}`);
  }
  if (random() < 0.05) value.extra = 1;
  add(`random-${i}-${parts.join('-')}`, value);
}
