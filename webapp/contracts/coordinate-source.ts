export type CoordinateConversion =
  | { method: 'ernie-mni-scalp/1'; mapping_id: string; input_coordinate_system: string; input_unit: 'mm'; max_surface_distance_mm: number }
  | { method: 'cap-labels/1'; mapping_id: string; input_coordinate_system: 'EEG10-20_extended_SPM12'; input_unit: null; max_surface_distance_mm: null }
  | { method: 'head-landmarks-surface/1'; mapping_id: string; input_coordinate_system: string; input_unit: 'mm' | 'cm' | 'm';
      landmark_source: 'coordsystem' | 'file'; scale: number; rotation_deg: number; max_landmark_residual_mm: number;
      max_surface_distance_mm: number; iterations: number };

export type RegionAssignment = { method: 'file' } | { method: 'balanced-spatial/1'; region_count: 1 | 2 | 3 | 4 | 6 };

export type CoordinateSourceMetadata = {
  schema: 'electrode-coordinate-source/1' | 'electrode-coordinate-source/2' | 'electrode-coordinate-source/3';
  format: 'bids-electrodes/1' | 'electrode-labels/1' | 'mne-elc/1' | 'eeglab-sfp/1';
  electrodes_file: string;
  /** null only for a label list, which has no coordinate-system file. */
  coordsystem_file: string | null;
  coordinate_system: 'ernie_native_mm';
  unit: 'mm';
  coordinate_system_description: string;
  region_index_base: 0;
  region_description: string;
  /** Present for `/2` and `/3`: the conversion that produced the Ernie coordinates (null in `/3` for an Ernie-native input). */
  conversion?: CoordinateConversion | null;
  /** Present exactly for `/3`: whether the regions came from the file or were assigned on import. */
  region_assignment?: RegionAssignment;
};
