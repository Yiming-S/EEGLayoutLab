import type { SavedRecord } from './local-library.ts';

export const SHOWCASE_DISPLAY_COPY_SCHEMA = 'eeg-showcase-display-copy/1';
export const DISPLAY_COPY_SERIALIZATION = 'ECMAScript JSON.stringify, member order preserved, UTF-8';
export const DISPLAY_COPY_REFERENCE_SCOPE = 'requires_undisclosed_original_files';
export const DISPLAY_COPY_REDACTION_POLICY = 'home_directory_prefix_to_tilde/1';
const SHA256 = /^[a-f0-9]{64}$/;
export const LOCAL_PRIVATE_PATH = /\/Users\/|\/home\/|\/private\/var\/|\/var\/folders\//;

export type ShowcaseDisplayCopy = {
  schema: typeof SHOWCASE_DISPLAY_COPY_SCHEMA;
  record_id: string;
  record: SavedRecord;
  source_reference: {
    verification: typeof DISPLAY_COPY_REFERENCE_SCOPE;
    original_bundle_schema: 'eeg-reproducibility-bundle/1';
    source_file: { path: string; sha256: string };
    scientific_key: string | null;
    result_sha256: string | null;
  };
  redaction: { policy: typeof DISPLAY_COPY_REDACTION_POLICY; original_included: false };
  display_record: Record<string, unknown>;
  display_context: Record<string, unknown>;
  search: unknown;
  snapshots: unknown;
  coordinate_note: string | null;
  integrity: {
    algorithm: 'SHA-256';
    serialization: typeof DISPLAY_COPY_SERIALIZATION;
    display_record_sha256: string;
    result_sha256: string | null;
    payload_sha256: string;
  };
};

export const isShowcaseDisplayCopy = (value: unknown): value is ShowcaseDisplayCopy =>
  Boolean(value && typeof value === 'object' && (value as { schema?: unknown }).schema === SHOWCASE_DISPLAY_COPY_SCHEMA);

/** Hash the JSON data, not the indentation or newline of its downloadable file. */
export async function displayCopyDigest(value: unknown) {
  const text = JSON.stringify(value);
  if (text === undefined) throw new Error('展示副本校验失败，未导出文件。');
  const bytes = new TextEncoder().encode(text);
  return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)))
    .map(byte => byte.toString(16).padStart(2, '0')).join('');
}

/** Only these digests verify the redacted copy. Its original identifiers are opaque references. */
export async function verifyShowcaseDisplayCopy(value: unknown, expected?: Pick<SavedRecord, 'id' | 'dataset_id'>) {
  const fail = () => { throw new Error('展示副本校验失败，未导出文件。'); };
  if (!isShowcaseDisplayCopy(value)) return fail();
  const copy = value;
  if (!SHA256.test(copy.record_id) || copy.record?.id !== copy.record_id || typeof copy.record.dataset_id !== 'string' ||
      (expected && (copy.record_id !== expected.id || copy.record.dataset_id !== expected.dataset_id)) ||
      copy.redaction?.policy !== DISPLAY_COPY_REDACTION_POLICY || copy.redaction.original_included !== false ||
      copy.source_reference?.verification !== DISPLAY_COPY_REFERENCE_SCOPE ||
      copy.source_reference.original_bundle_schema !== 'eeg-reproducibility-bundle/1' ||
      typeof copy.source_reference.source_file?.path !== 'string' || !SHA256.test(copy.source_reference.source_file.sha256) ||
      ![copy.source_reference.scientific_key, copy.source_reference.result_sha256].every(v => v === null || (typeof v === 'string' && SHA256.test(v))) ||
      !copy.display_record || typeof copy.display_record !== 'object' || Array.isArray(copy.display_record) ||
      !copy.display_context || typeof copy.display_context !== 'object' || Array.isArray(copy.display_context) ||
      !copy.search || typeof copy.search !== 'object' || Array.isArray(copy.search) || !Array.isArray(copy.snapshots) ||
      ['original_record', 'reproduction', 'source'].some(key => key in copy) ||
      ['key', 'result_sha256', 'identity'].some(key => key in copy.display_record) ||
      'identity' in copy.display_context || LOCAL_PRIVATE_PATH.test(JSON.stringify(copy)) ||
      copy.integrity?.algorithm !== 'SHA-256' || copy.integrity.serialization !== DISPLAY_COPY_SERIALIZATION ||
      !SHA256.test(copy.integrity.display_record_sha256) || !SHA256.test(copy.integrity.payload_sha256)) return fail();
  const { integrity, ...payload } = copy;
  const [recordDigest, resultDigest, payloadDigest] = await Promise.all([
    displayCopyDigest(copy.display_record),
    copy.display_record.result === undefined ? null : displayCopyDigest(copy.display_record.result),
    displayCopyDigest(payload),
  ]);
  if (recordDigest !== integrity.display_record_sha256 || resultDigest !== integrity.result_sha256 || payloadDigest !== integrity.payload_sha256) return fail();
  return copy;
}
