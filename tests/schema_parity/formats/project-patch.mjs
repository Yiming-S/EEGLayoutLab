// project-patch: the body of PATCH /api/projects/<id>. Node's outcome is ProjectService.body, then the checks of
// ProjectStore.patch before the project is read (project-validation.mjs): the fields, at least one change, the texts
// and the revision. The comparison settings are passed through: the store checks them against the project's entries
// (tests/service/test_projects.py). Rejected variants also record Node's message, which
// eeglayoutlab.schemas.projects.normalize_patch must raise (tests/service/test_project_request.py).
import { ABSENT, collector, createRandom, raw } from '../support.mjs';
import { ID, KEY, NOT_OBJECTS, REVISIONS, accepted, body, store, texts } from './project-validation.mjs';

export const name = 'project-patch';
export async function normalize(parsed) {
  const input = await body(parsed);
  await accepted(store.patch(ID, KEY, input));
  const out = { revision: input.revision };
  for (const field of ['title', 'owner_name', 'notes']) if (input[field] !== undefined) out[field] = input[field].trim();
  if (input.workflow !== undefined) out.workflow = input.workflow;
  return out;
}

const { pick, random } = createRandom(0x9a7c4e11);
const { variants, add } = collector();
export { variants };

const LINK = `/decision?a=${'1'.repeat(64)}&b=${'2'.repeat(64)}&ar=90`;
const WORKFLOWS = [
  ['null', null], ['empty', {}], ['number', 5], ['string', LINK], ['array', []],
  ['valid', { reference_entry_id: '00000000-0000-4000-8000-000000000003', candidate_entry_id: '00000000-0000-4000-8000-000000000004', comparison_href: LINK }],
  ['nulls', { reference_entry_id: null, candidate_entry_id: null, comparison_href: null }],
  ['extra', { reference_entry_id: null, scientific_result: { score: 1 } }], ['hrefNumber', { comparison_href: 0 }],
  ['external', { comparison_href: 'https://example.org/decision' }], ['nested', { comparison_href: [[LINK]] }],
];
for (const [label, value] of NOT_OBJECTS) add(`body-${label}`, value);
add('empty', {});
add('revision-only', { revision: 1 });
add('title-only', { title: 'Renamed' });
add('two-without-revision', { title: 'Renamed', notes: 'Notes' });
add('base', { revision: 1, title: 'Renamed' });
add('all', { revision: 3, title: ' T ', owner_name: ' R ', notes: ' N ', workflow: WORKFLOWS[5][1] });
add('reordered', { notes: 'N', revision: 2 });
for (const extra of ['kind', 'entries', 'schema', 'id', 'access_key', 'Revision', ''])
  add(`extra-${extra || 'empty'}`, { revision: 1, title: 'Renamed', [extra]: 1 });
add('extra-proto', raw('{"__proto__":{},"revision":1}'));
add('duplicate-title', raw('{"revision":1,"title":"","title":"Renamed"}'));
add('duplicate-revision', raw('{"revision":"1","revision":1,"notes":""}'));
for (const [label, value] of REVISIONS) add(`revision-${label}`, { revision: value, title: 'Renamed' });
for (const [label, value] of texts(200)) add(`title-${label}`, { revision: 1, title: value });
for (const [label, value] of texts(120)) add(`owner-${label}`, { revision: 1, owner_name: value });
for (const [label, value] of texts(8000)) add(`notes-${label}`, { revision: 1, notes: value });
for (const [label, value] of WORKFLOWS) add(`workflow-${label}`, { revision: 1, workflow: value });
add('workflow-bad-revision', { revision: 0, workflow: WORKFLOWS[5][1] });
add('texts-checked-before-revision', { revision: 0, title: '' });

const pools = { revision: REVISIONS, title: [...texts(200), ['absent', ABSENT]], owner_name: [...texts(120), ['absent', ABSENT]],
  notes: [...texts(8000), ['absent', ABSENT]], workflow: [...WORKFLOWS, ['absent', ABSENT], ['absent2', ABSENT]] };
for (let i = 0; i < 80; i++) {
  const value = {}, parts = [];
  for (const field of ['revision', 'title', 'owner_name', 'notes', 'workflow']) {
    if (random() < 0.4) continue;
    const [label, item] = pick(pools[field]); value[field] = item; parts.push(`${field}:${label}`);
  }
  add(`random-${i}-${parts.join('-')}`, value);
}
