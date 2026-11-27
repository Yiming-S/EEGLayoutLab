/** Compatibility entry point; rendering, layers and assets live in viewer/. */
export { createHeadScene, type HeadScene } from '../viewer/head-scene.ts';
export { loadHeadAssets, applySourceRoiGroups } from '../viewer/assets.ts';
export { REGION_COLORS } from '../viewer/contacts.ts';
export type {
  DomainMode,
  HoverTarget,
  ViewName,
  LayoutOptions,
} from '../viewer/types.ts';
