import type { OpenDeliveryEntry, OpenResearchDelivery } from './research-delivery-reader';

export type LocalDeliveryDownload = { filename: string; mediaType: string; content: Blob | string };
export const originalDeliveryDownload = (delivery: OpenResearchDelivery, file: File): LocalDeliveryDownload => ({
  filename: `eeg-research-project-${delivery.project.id}-r${delivery.project.revision}.json`, mediaType: 'application/json', content: file,
});
export const deliverySnapshotDownload = (row: OpenDeliveryEntry): LocalDeliveryDownload => ({
  filename: `eeg-project-entry-${row.entry.id}.json`, mediaType: 'application/json', content: row.snapshot_json,
});
export const deliveryReadmeDownload = (delivery: OpenResearchDelivery): LocalDeliveryDownload => ({
  filename: `eeg-project-${delivery.project.id}-README.md`, mediaType: 'text/markdown;charset=utf-8', content: delivery.readme,
});

export function saveLocalDeliveryFile(file: LocalDeliveryDownload) {
  const blob = typeof file.content === 'string' ? new Blob([file.content], { type: file.mediaType }) : file.content;
  const href = URL.createObjectURL(blob), anchor = document.createElement('a');
  anchor.href = href; anchor.download = file.filename; document.body.appendChild(anchor);
  try { anchor.click(); } finally { anchor.remove(); setTimeout(() => URL.revokeObjectURL(href), 1000); }
}
