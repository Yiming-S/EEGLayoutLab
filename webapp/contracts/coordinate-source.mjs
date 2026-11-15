/** Bounded coordinate-file declarations, independent of scientific identities. */
const fields = ['schema', 'format', 'electrodes_file', 'coordsystem_file', 'coordinate_system', 'unit', 'coordinate_system_description', 'region_index_base', 'region_description'];
const text = (value, max, multiline = false) => typeof value === 'string' && value.length <= max && value.trim() && !Array.from({ length: value.length }, (_, index) => value.charCodeAt(index)).some(code => (code < 32 && !(multiline && [9, 10, 13].includes(code))) || code === 127);
export function validateCoordinateSource(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).sort().join(',') !== [...fields].sort().join(',') ||
      value.schema !== 'electrode-coordinate-source/1' || value.format !== 'bids-electrodes/1' || value.coordinate_system !== 'ernie_native_mm' || value.unit !== 'mm' || value.region_index_base !== 0 ||
      !text(value.coordinate_system_description, 2048, true) || !text(value.region_description, 1024, true) ||
      ![value.electrodes_file, value.coordsystem_file].every(name => text(name, 200) && !/[\\/]/.test(name) && !['.', '..'].includes(name)))
    throw new Error('坐标来源说明格式无效');
  return { ...value };
}
