import { normalizeReceptionRequest } from './reception-v2-support.mjs';

export function communityAdapters(queue, normalizeRadius) {
  const adapter = (service, normalize, context) => ({
    async prepare(raw) { const request = normalize(raw), ctx = await context(request); return { request, key: ctx.key, ctx }; },
    lookup: p => service.lookup(p.request, p.ctx),
    start: r => service.submit(r),
    get: id => { const j = service.jobs.get(id); return j ? service.view(j) : null; },
    busy: () => Boolean(service.active || service.submitting),
    pid: () => service.active?.child?.pid,
    cancel: id => service.cancel(id),
  });
  return {
    'local-compute': adapter(queue, normalizeRadius, r => queue.identityFor(r)),
    'source-reception': { ...adapter(queue.sources, normalizeReceptionRequest, r => queue.sources.context(r)),
      savedResult: (key, request) => queue.sources.savedResult(key, request) },
    'design-evaluation': adapter(queue.designTests, r => queue.designTests.normalize(r), r => queue.designTests.context(r)),
    'electrode-editor': adapter(queue.editor, r => queue.editor.normalize(r), r => queue.editor.context(r)),
  };
}
