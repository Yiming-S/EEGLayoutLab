export type DeliveryFile = { path: string; media_type: string; encoding: 'utf-8' | 'utf8'; size_bytes: number; sha256: string; content: string };
export type ResearchDelivery = {
  schema: 'eeg-research-delivery/1'; project: { id: string; revision: number }; files: DeliveryFile[];
  manifest_sha256: string; scientific_results_recomputed: false;
  [key: string]: unknown;
};
const object = (value: unknown): value is Record<string, unknown> => Boolean(value && typeof value === 'object' && !Array.isArray(value));
const sha = /^[a-f0-9]{64}$/;
const cancelled = (signal?: AbortSignal) => { if (signal?.aborted) throw new DOMException('Aborted', 'AbortError'); };
const digest = async (bytes: Uint8Array<ArrayBuffer>) => [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))].map(byte => byte.toString(16).padStart(2, '0')).join('');

/** Verify delivered UTF-8 bytes without reserializing any scientific file. */
export async function prepareProjectDelivery(value: unknown, project: { id: string; revision: number }, signal?: AbortSignal) {
  cancelled(signal);
  if (!object(value) || value.schema !== 'eeg-research-delivery/1' || !object(value.project) || value.project.id !== project.id ||
      value.scientific_results_recomputed !== false || typeof value.manifest_sha256 !== 'string' || !sha.test(value.manifest_sha256) || !Array.isArray(value.files))
    throw new Error('项目交付包格式无效');
  if (value.project.revision !== project.revision) throw new Error('项目已更新，请重新读取后再导出。');
  const paths = new Set<string>(), files: DeliveryFile[] = [];
  let totalBytes = 0;
  for (const row of value.files) {
    cancelled(signal);
    if (!object(row) || typeof row.path !== 'string' || !row.path || row.path.startsWith('/') || row.path.includes('\\') ||
        row.path.split('/').some(part => !part || part === '.' || part === '..') || /\p{Cc}/u.test(row.path) || paths.has(row.path) ||
        typeof row.media_type !== 'string' || !['utf-8', 'utf8'].includes(String(row.encoding)) || typeof row.content !== 'string' ||
        !Number.isSafeInteger(row.size_bytes) || Number(row.size_bytes) < 0 || typeof row.sha256 !== 'string' || !sha.test(row.sha256))
      throw new Error('项目交付文件清单无效');
    const bytes = new TextEncoder().encode(row.content);
    if (bytes.byteLength !== row.size_bytes) throw new Error('项目交付文件的大小或校验值不一致');
    const actual = await digest(bytes);
    cancelled(signal);
    if (actual !== row.sha256) throw new Error('项目交付文件的大小或校验值不一致');
    paths.add(row.path); files.push(row as DeliveryFile); totalBytes += bytes.byteLength;
  }
  const readme = files.find(file => file.path === 'README.md');
  if (!readme) throw new Error('项目交付包缺少说明文档');
  const { manifest_sha256: checksum, files: _files, ...metadata } = value;
  const manifest = { ...metadata, files: files.map(({ content: _content, ...file }) => file) };
  if (await digest(new TextEncoder().encode(JSON.stringify(manifest))) !== checksum) throw new Error('项目交付清单校验失败');
  const text = JSON.stringify(value, null, 2) + '\n';
  cancelled(signal);
  return { bundle: value as ResearchDelivery, text, readme, totalBytes,
    filename: `eeg-research-project-${project.id}-r${project.revision}.json` };
}
