import type { ProjectEntry } from '../../client/projects';
import type { SavedRecord } from '../../lib/local-library';
import type { EditorResult } from '../../lib/electrode-editor';
import type { SourceResult } from '../../lib/source-reception';

const object = (value: unknown): value is Record<string, unknown> => Boolean(value && typeof value === 'object' && !Array.isArray(value));
export type ProjectSnapshotView = { kind: 'layout'; record: SavedRecord } | { kind: 'editor'; result: EditorResult } | { kind: 'source'; result: SourceResult };

/** The server validates scientific data and its checksum. Keep its arrays intact. */
export function projectSnapshotView(entry: ProjectEntry, snapshot: unknown): ProjectSnapshotView {
  if (!object(snapshot) || snapshot.schema !== 'research-project-snapshot/1' || snapshot.kind !== entry.kind || snapshot.record_id !== entry.record_id || !object(snapshot.payload))
    throw new Error('项目科学副本与记录不匹配');
  const payload = snapshot.payload;
  if (entry.kind === 'source' && ['source-reception/1', 'source-reception/2'].includes(String(payload.schema_version)) && object(payload.waveforms) && Array.isArray(payload.waveforms.time_s) && Array.isArray(payload.conditions))
    return { kind: 'source', result: payload as unknown as SourceResult };
  if (entry.kind === 'layout' && object(payload.record) && payload.record.id === entry.record_id && object(payload.record.layout) && Array.isArray(payload.record.layout.xyzMm))
    return { kind: 'layout', record: payload.record as SavedRecord };
  if (entry.kind === 'editor' && object(payload.cache) && object(payload.cache.result) && payload.cache.result.schema === 'electrode-editor/1' && Array.isArray(payload.cache.result.evaluated_xyz_mm))
    return { kind: 'editor', result: payload.cache.result as EditorResult };
  throw new Error('项目科学副本格式无效');
}
