'use client';
import { useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { useLanguage } from '@/components/language-provider';
import { RuntimeMessage } from '@/components/runtime-message';
import { projectRequest, type ProjectAccess, type ResearchProject } from '@/client/projects';
import { prepareProjectDelivery } from './project-delivery-download';

type Prepared = Awaited<ReturnType<typeof prepareProjectDelivery>>;
function download(content: string, filename: string, mediaType: string) {
  const href = URL.createObjectURL(new Blob([content], { type: mediaType }));
  const link = document.createElement('a'); link.href = href; link.download = filename; link.click();
  setTimeout(() => URL.revokeObjectURL(href), 1000);
}

export function ProjectDeliveryPanel({ project, access }: { project: ResearchProject; access: ProjectAccess }) {
  const { tx } = useLanguage();
  const [prepared, setPrepared] = useState<Prepared | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const running = useRef<AbortController | null>(null);
  useEffect(() => () => { running.current?.abort(); running.current = null; }, [project.id, project.revision, access.access_key]);
  const save = (kind: 'package' | 'readme', value: Prepared) => {
    if (kind === 'readme') download(value.readme.content, `eeg-project-${project.id}-README.md`, value.readme.media_type);
    else download(value.text, value.filename, 'application/json');
  };
  const prepare = (kind: 'package' | 'readme') => {
    if (prepared) { save(kind, prepared); return; }
    const controller = new AbortController(); running.current = controller; setBusy(true); setError('');
    void (async () => {
      const bundle = await projectRequest(access, '/export', { signal: controller.signal, timeoutMs: 120000 });
      const result = await prepareProjectDelivery(bundle, project, access.access_key, controller.signal);
      if (controller.signal.aborted) return;
      setPrepared(result); save(kind, result);
    })().catch(caught => {
      if (!controller.signal.aborted) setError(caught instanceof Error ? caught.message : '项目交付包无法下载');
    }).finally(() => {
      if (running.current === controller) { running.current = null; setBusy(false); }
    });
  };
  return <section id="project-delivery" className="lab-panel space-y-4" aria-label={tx('项目交付包')}>
    <h2 className="text-lg font-semibold">{tx('项目交付包')}</h2>
    <p className="max-w-4xl text-sm text-muted-foreground">{tx('交付包包含项目说明、已保存的科学副本、方案选择与比较条件，以及记录中的模型、数据和运行环境标识。当前服务端版本另行列出。')}</p>
    <p className="max-w-4xl text-sm text-muted-foreground">{tx('大型模型数据通过清单和校验值引用，不重复打包。导出不重新计算科学结果。')}</p>
    <div className="flex flex-wrap gap-3">
      <Button type="button" disabled={busy || !project.entries.length} onClick={() => prepare('package')}>{tx('下载项目交付包')}</Button>
      <Button type="button" variant="outline" disabled={busy || !project.entries.length} onClick={() => prepare('readme')}>{tx('下载交付说明')}</Button>
      {busy && <Button type="button" variant="outline" onClick={() => { running.current?.abort(); running.current = null; setBusy(false); }}>{tx('取消下载准备')}</Button>}
    </div>
    {!project.entries.length && <p className="text-sm text-muted-foreground">{tx('先将已完成的实验保存到项目，再导出交付包。')}</p>}
    {busy && <output className="block text-sm">{tx('正在读取并校验交付文件…')}</output>}
    {error && <p role="alert" className="text-sm text-red-800"><RuntimeMessage message={error} /></p>}
    {prepared && <dl className="grid gap-3 rounded-lg border p-3 text-sm sm:grid-cols-3">
      <div><dt className="text-muted-foreground">{tx('交付文件数')}</dt><dd>{prepared.bundle.files.length}</dd></div>
      <div><dt className="text-muted-foreground">{tx('文件总大小')}</dt><dd>{(prepared.totalBytes / 1048576).toFixed(2)} MiB</dd></div>
      <div><dt className="text-muted-foreground">{tx('项目版本')}</dt><dd>{project.revision}</dd></div>
      <div className="sm:col-span-3"><dt className="text-muted-foreground">{tx('交付清单 SHA-256')}</dt><dd className="break-all font-mono text-xs">{prepared.bundle.manifest_sha256}</dd></div>
    </dl>}
    <p className="text-xs text-muted-foreground">{tx('项目访问凭据单独保存和分享，不随交付包导出。')}</p>
  </section>;
}
