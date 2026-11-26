// project-entry-patch: the body of PATCH /api/projects/<id>/entries/<entry>. Node's outcome is ProjectService.body,
// then the checks of ProjectStore.patchEntry before the project is read (project-validation.mjs). Rejected variants
// also record Node's message, which eeglayoutlab.schemas.projects.normalize_entry_patch must raise
// (tests/service/test_project_request.py).
import { ABSENT, collector, createRandom, raw } from '../support.mjs';
import { ENTRY, ID, KEY, NOT_OBJECTS, REVISIONS, accepted, body, store, texts } from './project-validation.mjs';

export const name = 'project-entry-patch';
export async function normalize(parsed) {
  const input = await body(parsed);
  await accepted(store.patchEntry(ID, KEY, ENTRY, input));
  const out = { revision: input.revision };
  for (const field of ['title', 'notes']) if (input[field] !== undefined) out[field] = input[field].trim();
  return out;
}

const { pick, random } = createRandom(0x3e47a9c1);
const { variants, add } = collector();
export { variants };

for (const [label, value] of NOT_OBJECTS) add(`body-${label}`, value);
add('empty', {});
add('revision-only', { revision: 1 });
add('title-only', { title: 'Signal A' });
add('two-without-revision', { title: 'Signal A', notes: 'Selected' });
add('base', { revision: 3, title: 'Renamed signal', notes: 'Selected for comparison' });
add('notes-only', { notes: 'Selected', revision: 2 });
for (const extra of ['owner_name', 'kind', 'record_id', 'annotation_id', 'workflow', 'summary', ''])
  add(`extra-${extra || 'empty'}`, { revision: 1, title: 'Renamed', [extra]: 1 });
add('duplicate-title', raw('{"revision":1,"title":null,"title":"Renamed"}'));
for (const [label, value] of REVISIONS) add(`revision-${label}`, { revision: value, notes: 'n' });
for (const [label, value] of texts(200)) add(`title-${label}`, { revision: 1, title: value });
for (const [label, value] of texts(8000)) add(`notes-${label}`, { revision: 1, notes: value });
add('texts-checked-before-revision', { revision: 0, notes: 1 });

const pools = { revision: REVISIONS, title: [...texts(200), ['absent', ABSENT]], notes: [...texts(8000), ['absent', ABSENT]] };
for (let i = 0; i < 50; i++) {
  const value = {}, parts = [];
  for (const field of ['revision', 'title', 'notes']) {
    if (random() < 0.3) continue;
    const [label, item] = pick(pools[field]); value[field] = item; parts.push(`${field}:${label}`);
  }
  if (random() < 0.1) value.kind = 'layout';
  add(`random-${i}-${parts.join('-')}`, value);
}
