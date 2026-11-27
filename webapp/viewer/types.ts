import type * as THREE from 'three';
import type { DomainMode, RecordedLayout, XYZ } from '../../contracts/layout';
export type { DomainMode } from '../../contracts/layout';

export type ViewName = 'oblique' | 'front' | 'left' | 'right' | 'back' | 'top';
export type HoverTarget = {
  kind: 'electrode' | 'reference' | 'source';
  index: number;
  label: string;
  color: string;
  regionIndex?: number;
  sourceRegionId?: string | null;
  xyzMm?: XYZ;
  active?: boolean;
};
export type LayoutOptions = {
  editor?: {
    enabled: boolean;
    active: boolean[];
    selection: number[];
    candidates: { bank_indices: number[]; xyz_mm: XYZ[] }[];
    onSelect: (slot: number, multiple: boolean) => void;
    onMove: (slot: number, bankIndex: number) => void;
    onInvalid: () => void;
  };
  regionCount: number;
  allocation: number[];
  domainMode: DomainMode;
  maskCodes?: string[];
  radiusCm: number;
  electrodeNames?: string[];
  sourceXyzMm?: XYZ[];
  sourceNormals?: XYZ[];
  sourceRegions?: (string | null)[];
  selectedSource?: number;
  onSourceSelect?: (index: number) => void;
  electrodeValues?: number[];
  potentialLimit?: number;
  selectedElectrode?: number;
  onElectrodeSelect?: (index: number) => void;
  recordedLayout?: RecordedLayout;
};
export type SurfacePoint = {
  position: THREE.Vector3;
  normal: THREE.Vector3;
  direction: THREE.Vector3;
};
