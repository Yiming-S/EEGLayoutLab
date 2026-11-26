// project-create: the body of POST /api/projects. Node's outcome is ProjectService.body, then the checks of
// ProjectStore.create before its serialized operation (project-validation.mjs); the canonical value is the
// project's {title, owner_name, notes} as the store saves them. Rejected variants also record Node's message, which
// eeglayoutlab.schemas.projects.normalize_create must raise (tests/service/test_project_request.py).
import { ABSENT, collector, createRandom, raw } from '../support.mjs';
import { NOT_OBJECTS, accepted, body, store, texts } from './project-validation.mjs';

export const name = 'project-create';
export async function normalize(parsed) {
  const input = await body(parsed);
  await accepted(store.create(input));
  return { title: input.title.trim(), owner_name: input.owner_name.trim(), notes: (input.notes ?? '').trim() };
}

const { pick, random } = createRandom(0x9c0e47a1);
const { variants, add, addBytes } = collector();
export { variants };

const BASE = { title: 'Study A', owner_name: 'Researcher' };
for (const [label, value] of NOT_OBJECTS) add(`body-${label}`, value);
add('base', BASE);
add('base-notes', { ...BASE, notes: 'Original study' });
add('base-reordered', { notes: 'n', owner_name: 'R', title: 'T' });
add('base-notes-null', { ...BASE, notes: null });
add('empty', {});
for (const extra of ['revision', 'workflow', 'Title', 'owner', 'entries', 'access_key', 'owner_key_hash', ''])
  add(`extra-${extra || 'empty'}`, { ...BASE, [extra]: 1 });
add('extra-proto', raw('{"__proto__":{},"title":"Study A","owner_name":"Researcher"}'));
add('duplicate-title', raw('{"title":"","title":"Study B","owner_name":"Researcher"}'));
add('missing-title', { owner_name: 'Researcher' });
add('missing-owner', { title: 'Study A' });
for (const [label, value] of texts(200)) add(`title-${label}`, { ...BASE, title: value });
for (const [label, value] of texts(120)) add(`owner-${label}`, { ...BASE, owner_name: value });
for (const [label, value] of texts(8000)) add(`notes-${label}`, { ...BASE, notes: value });
add('owner-and-title-invalid', { title: '', owner_name: '' });
add('title-valid-notes-invalid-owner', { title: 'T', owner_name: 1, notes: 'a\u0000' });
addBytes('bytes-invalid-utf8-title', Buffer.concat([Buffer.from('{"title":"Study '), Buffer.from([0xff, 0xc3]), Buffer.from('","owner_name":"R"}')]));
addBytes('bytes-invalid-utf8-control', Buffer.concat([Buffer.from('{"title":"a'), Buffer.from([0x01]), Buffer.from('","owner_name":"R"}')]));

// Random combinations of the three fields.
const pools = { title: texts(200), owner_name: texts(120), notes: [...texts(8000), ['absent', ABSENT]] };
for (let i = 0; i < 60; i++) {
  const value = {}, parts = [];
  for (const field of ['title', 'owner_name', 'notes']) {
    const [label, item] = pick(pools[field]); value[field] = item; parts.push(label);
  }
  if (random() < 0.1) value.extra = true;
  add(`random-${i}-${parts.join('-')}`, value);
}
