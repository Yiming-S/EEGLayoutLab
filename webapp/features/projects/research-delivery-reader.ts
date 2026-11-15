import type { ProjectEntry, ResearchProject } from '../../client/projects';
import {
  openResearchDelivery as readDelivery,
  DELIVERY_INPUT_LIMIT,
} from './research-delivery-format.mjs';
export { DELIVERY_INPUT_LIMIT };
export type OpenDeliveryEntry = {
  entry: ProjectEntry;
  snapshot: Record<string, unknown>;
  snapshot_json: string;
};
export type OpenResearchDelivery = {
  project: ResearchProject;
  entries: OpenDeliveryEntry[];
  readme: string;
  original_text: string;
  manifest_sha256: string;
  exported_at: string;
  total_bytes: number;
};
/** The wire validator checks every entry before exposing typed, read-only data. */
export async function openResearchDelivery(
  raw: string,
  signal?: AbortSignal,
): Promise<OpenResearchDelivery> {
  return (await readDelivery(raw, signal)) as OpenResearchDelivery;
}
