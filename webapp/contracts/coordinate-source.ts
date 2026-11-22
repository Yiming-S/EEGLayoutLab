export type CoordinateConversion =
  | { method: 'ernie-mni-scalp/1'; mapping_id: string; input_coordinate_system: string; input_unit: 'mm'; max_surface_distance_mm: number }
  | { method: 'cap-labels/1'; mapping_id: string; input_coordinate_system: 'EEG10-20_extended_SPM12'; input_unit: null; max_surface_distance_mm: null };

export type CoordinateSourceMetadata = {
  schema: 'electrode-coordinate-source/1' | 'electrode-coordinate-source/2';
  format: 'bids-electrodes/1' | 'electrode-labels/1';
  electrodes_file: string;
  /** null only for a label list, which has no coordinate-system file. */
  coordsystem_file: string | null;
  coordinate_system: 'ernie_native_mm';
  unit: 'mm';
  coordinate_system_description: string;
  region_index_base: 0;
  region_description: string;
  /** Present exactly for `/2`: the conversion that produced the Ernie coordinates. */
  conversion?: CoordinateConversion;
};
