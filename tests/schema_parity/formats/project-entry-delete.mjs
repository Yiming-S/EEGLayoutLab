// project-entry-delete: the body of DELETE /api/projects/<id>/entries/<entry> when the request has no If-Match
// header. Node's outcome is ProjectService.body, then the revision ProjectStore.detach checks before the project is
// read (project-validation.mjs); other keys are ignored. Rejected variants also record Node's message, which
// eeglayoutlab.schemas.projects.normalize_entry_delete must raise (tests/service/test_project_request.py).
import { collector, raw } from '../support.mjs';
import { ENTRY, ID, KEY, NOT_OBJECTS, REVISIONS, accepted, body, store } from './project-validation.mjs';

export const name = 'project-entry-delete';
export async function normalize(parsed) {
  const input = await body(parsed);
  await accepted(store.detach(ID, KEY, ENTRY, input.revision));
  return { revision: input.revision };
}

const { variants, add } = collector();
export { variants };

for (const [label, value] of NOT_OBJECTS) add(`body-${label}`, value);
add('empty', {});
for (const [label, value] of REVISIONS) add(`revision-${label}`, { revision: value });
add('extra-keys', { revision: 2, title: 'ignored', kind: 'layout' });
add('extra-first', { reason: 'cleanup', revision: 4 });
add('extra-proto', raw('{"__proto__":{"revision":1},"revision":3}'));
add('extra-proto-only', raw('{"__proto__":{"revision":1}}'));
add('duplicate-revision', raw('{"revision":0,"revision":5}'));
add('nested-revision', { entry: { revision: 1 } });
