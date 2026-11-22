/** Bounded coordinate-file declarations, independent of scientific identities. */
const common = ['schema', 'format', 'electrodes_file', 'coordsystem_file', 'coordinate_system', 'unit', 'coordinate_system_description', 'region_index_base', 'region_description'];
const conversionFields = ['method', 'mapping_id', 'input_coordinate_system', 'input_unit', 'max_surface_distance_mm'];
/** BIDS template coordinate systems accepted as MNI input. All are mapped with the SimNIBS MNI152NLin6Asym warp. */
export const MNI_COORDINATE_SYSTEMS = Object.freeze(['MNI152NLin6Asym', 'MNI152NLin6Sym', 'MNI152Lin', 'MNI152NLin2009aAsym', 'MNI152NLin2009aSym',
  'MNI152NLin2009bAsym', 'MNI152NLin2009bSym', 'MNI152NLin2009cAsym', 'MNI152NLin2009cSym', 'MNI305', 'MNIColin27', 'IXI549Space', 'ICBM452AirSpace', 'ICBM452Warp5Space']);
export const LABEL_CAP = 'EEG10-20_extended_SPM12';
export const MNI_IMPORT_LIMIT_MM = 10;
const text = (value, max, multiline = false) => typeof value === 'string' && value.length <= max && value.trim() && !Array.from({ length: value.length }, (_, index) => value.charCodeAt(index)).some(code => (code < 32 && !(multiline && [9, 10, 13].includes(code))) || code === 127);
const fileName = name => text(name, 200) && !/[\\/]/.test(name) && !['.', '..'].includes(name);
const plain = value => Boolean(value) && typeof value === 'object' && !Array.isArray(value);
const byCode = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
const keys = (value, expected) => Object.keys(value).sort(byCode).join(',') === [...expected].sort(byCode).join(',');

function conversionValid(value, format) {
  if (!plain(value) || !keys(value, conversionFields) || typeof value.mapping_id !== 'string' || !/^[0-9a-f]{64}$/.test(value.mapping_id)) return false;
  if (format === 'bids-electrodes/1')
    return value.method === 'ernie-mni-scalp/1' && MNI_COORDINATE_SYSTEMS.includes(value.input_coordinate_system) && value.input_unit === 'mm' &&
      Number.isFinite(value.max_surface_distance_mm) && value.max_surface_distance_mm >= 0 && value.max_surface_distance_mm <= MNI_IMPORT_LIMIT_MM;
  return value.method === 'cap-labels/1' && value.input_coordinate_system === LABEL_CAP && value.input_unit === null && value.max_surface_distance_mm === null;
}

/**
 * `/1` records an Ernie-native coordinate file. `/2` records a converted input:
 * an MNI coordinate file or a list of 10-05 electrode names, with the mapping that produced the Ernie coordinates.
 */
export function validateCoordinateSource(value) {
  const v2 = plain(value) && value.schema === 'electrode-coordinate-source/2';
  if (!plain(value) || !(v2 || value.schema === 'electrode-coordinate-source/1') || !keys(value, v2 ? [...common, 'conversion'] : common) ||
      !(value.format === 'bids-electrodes/1' || (v2 && value.format === 'electrode-labels/1')) ||
      value.coordinate_system !== 'ernie_native_mm' || value.unit !== 'mm' || value.region_index_base !== 0 ||
      !text(value.coordinate_system_description, 2048, true) || !text(value.region_description, 1024, true) || !fileName(value.electrodes_file) ||
      !(value.format === 'electrode-labels/1' ? value.coordsystem_file === null : fileName(value.coordsystem_file)) ||
      (v2 && !conversionValid(value.conversion, value.format)))
    throw new Error('坐标来源说明格式无效');
  return v2 ? { ...value, conversion: { ...value.conversion } } : { ...value };
}

/** The input files a coordinate source names, for display. */
export function coordinateSourceFiles(source) {
  const files = [source.electrodes_file, source.coordsystem_file].filter(Boolean).join(' + ');
  return source.conversion ? `${files} · ${source.conversion.input_coordinate_system} → Ernie` : files;
}
