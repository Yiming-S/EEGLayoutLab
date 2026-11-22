import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { bidsNeedsMniSurface, exportBIDSElectrodes, exportMniBIDSElectrodes, parseBIDSElectrodes, parseElectrodeLabels, POSITION_PROVENANCE } from '../lib/bids-electrodes.ts';
import { ERNIE_MNI_MAPPING, MAPPING_ID, ernieToMni, mniToErnie, surfaceFromBuffers, verifiedSurface } from '../lib/ernie-mni.ts';
import { scientificDesign } from '../lib/design-decision.ts';
import { normalizeDesignRequest } from '../server/design-evaluation-server.mjs';
import { validateCoordinateSource } from '../contracts/coordinate-source.mjs';

const buffer = path => { const bytes = readFileSync(new URL('../public' + path, import.meta.url)); return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength); };
const scalp = buffer(ERNIE_MNI_MAPPING.scalp_buffer.file), mniBuffer = buffer(ERNIE_MNI_MAPPING.mni_buffer.file);
const surface = await verifiedSurface(scalp, mniBuffer);
const golden = ERNIE_MNI_MAPPING.golden;
const distance = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
const labelFile = (names, regions = names.map((_, index) => index % 2), separator = '\t') =>
  ({ name: 'layout-labels.tsv', text: ['name' + separator + 'region', ...names.map((name, index) => name + separator + regions[index])].join('\n') + '\n' });
const standard = () => parseElectrodeLabels(labelFile(golden.standard64.names));
const coordinateSystem = files => JSON.parse(files.find(file => file.name.endsWith('coordsystem.json')).text);

/** Neuromag head frame from NAS/LPA/RPA: x toward RPA, y toward the nasion, z up. */
function headFrame({ NAS, LPA, RPA }) {
  const sub = (a, b) => a.map((value, axis) => value - b[axis]), dot = (a, b) => a.reduce((sum, value, axis) => sum + value * b[axis], 0);
  const unit = v => v.map(value => value / Math.hypot(...v)), ex = unit(sub(RPA, LPA));
  const origin = LPA.map((value, axis) => value + dot(sub(NAS, LPA), ex) * ex[axis]), ey = unit(sub(NAS, origin));
  const ez = [ex[1] * ey[2] - ex[2] * ey[1], ex[2] * ey[0] - ex[0] * ey[2], ex[0] * ey[1] - ex[1] * ey[0]];
  return point => [ex, ey, ez].map(axis => dot(sub(point, origin), axis));
}

void test('exported coordinate systems state template provenance and landmarks oriented as a head frame', () => {
  const design = standard();
  for (const [files, points] of [[exportBIDSElectrodes(design), design.xyz_mm], [exportMniBIDSElectrodes(design, surface), null]]) {
    const system = coordinateSystem(files), toHead = headFrame(system.AnatomicalLandmarkCoordinates);
    assert.equal(system.EEGLayoutLabPositionProvenance, POSITION_PROVENANCE);
    assert.match(system.AnatomicalLandmarkCoordinateSystemDescription, /Not digitized/);
    assert.equal(system.AnatomicalLandmarkCoordinateUnits, 'mm');
    const rows = files.find(file => file.name.endsWith('electrodes.tsv')).text.trim().split('\n').slice(1).map(line => line.split('\t'));
    const at = name => toHead((points ?? rows.map(row => row.slice(1, 4).map(Number)))[rows.findIndex(row => row[0] === name)]);
    assert.ok(at('Cz')[2] > 80, 'Cz lies above the preauricular plane');
    assert.ok(at('C3')[0] < -30 && at('C4')[0] > 30, 'left and right are not swapped');
    assert.ok(at('Fpz')[1] > 60 && at('Oz')[1] < -60, 'front and back are not swapped');
  }
});

void test('10-05 labels reproduce the standard64 reference and resolve the old 10-20 names', () => {
  const design = standard();
  assert.ok(Math.max(...design.xyz_mm.map((point, index) => distance(point, golden.standard64.xyz_mm[index]))) < 1e-9);
  assert.deepEqual(design.electrode_names, golden.standard64.names);
  assert.equal(design.source_metadata.schema, 'electrode-coordinate-source/2');
  assert.equal(design.source_metadata.coordsystem_file, null);
  assert.deepEqual(design.source_metadata.conversion, { method: 'cap-labels/1', mapping_id: MAPPING_ID, input_coordinate_system: 'EEG10-20_extended_SPM12', input_unit: null, max_surface_distance_mm: null });
  const old = golden.standard64.names.map(name => ({ T7: 't3', T8: 'T4', P7: 'T5', P8: 'T6' })[name] ?? name.toLowerCase());
  const csv = parseElectrodeLabels({ ...labelFile(old, undefined, ','), name: 'labels.csv' });
  assert.deepEqual(csv.xyz_mm, design.xyz_mm);
  assert.deepEqual(csv.electrode_names, design.electrode_names);
  // Names are presentation metadata: the scientific request equals a plain coordinate import.
  assert.deepEqual(normalizeDesignRequest({ action: 'evaluate', design: scientificDesign(design), radius_mm: 6, seed: 42 }).design.xyz_mm, design.xyz_mm);
});

void test('label lists reject unknown, repeated or malformed entries', () => {
  const names = [...golden.standard64.names];
  for (const file of [
    labelFile(names.map((name, index) => index === 3 ? 'C99' : name)),
    labelFile(names.map(name => name === 'P7' ? 'T5' : name).map((name, index) => index === 0 ? 'P7' : name)),
    labelFile(names.slice(0, 63)),
    { ...labelFile(names), text: labelFile(names).text.replace('name\tregion', 'label\tregion') },
    labelFile(names, names.map(() => 0).map((value, index) => index < 40 ? 0 : 1)),
    { ...labelFile(names), name: 'labels.json' },
  ]) assert.throws(() => parseElectrodeLabels(file));
});

void test('surface mapping reproduces the Python builder on the same triangles', () => {
  const rows = new Map(ERNIE_MNI_MAPPING.labels.positions_mm.map(([name, ...xyz]) => [name, xyz]));
  const forward = ernieToMni(golden.surface_mapping.labels.map(name => rows.get(name)), surface);
  forward.points.forEach((point, index) => assert.ok(distance(point, golden.surface_mapping.ernie_to_mni_mm[index]) < 1e-4, golden.surface_mapping.labels[index]));
  const inverse = mniToErnie(golden.surface_mapping.mni_cap_mm, surface);
  inverse.points.forEach((point, index) => assert.ok(distance(point, golden.surface_mapping.mni_cap_to_ernie_mm[index]) < 1e-4, golden.surface_mapping.labels[index]));
  assert.ok(Math.max(...forward.distances_mm) < 1e-4, 'cap positions lie on the usable scalp');
});

void test('Ernie -> MNI files -> Ernie keeps names, order, regions and coordinates within 1 µm', () => {
  const design = { ...standard(), region_indices: Array.from({ length: 64 }, (_, index) => index % 4) };
  const files = exportMniBIDSElectrodes(design, surface);
  assert.deepEqual(files.map(file => file.name), ['space-MNI152NLin6Asym_electrodes.tsv', 'space-MNI152NLin6Asym_coordsystem.json', 'space-MNI152NLin6Asym_electrodes.json']);
  assert.equal(coordinateSystem(files).EEGCoordinateSystem, 'MNI152NLin6Asym');
  assert.ok(bidsNeedsMniSurface(files) && !bidsNeedsMniSurface(exportBIDSElectrodes(design)));
  assert.throws(() => parseBIDSElectrodes(files), /映射数据/);
  const back = parseBIDSElectrodes(files, surface);
  assert.deepEqual(back.electrode_names, design.electrode_names);
  assert.deepEqual(back.region_indices, design.region_indices);
  assert.ok(Math.max(...back.xyz_mm.map((point, index) => distance(point, design.xyz_mm[index]))) < 1e-3);
  assert.equal(back.source_metadata.conversion.input_coordinate_system, 'MNI152NLin6Asym');
  assert.ok(back.source_metadata.conversion.max_surface_distance_mm < 1e-4);
  assert.deepEqual(validateCoordinateSource(back.source_metadata), back.source_metadata);
  // The converted source survives an Ernie-native export; that export declares the native frame.
  const native = exportBIDSElectrodes(back);
  assert.equal(coordinateSystem(native).EEGCoordinateSystemDescription, 'Ernie native coordinate frame used by EEGLayoutLab, in millimetres.');
  assert.deepEqual(parseBIDSElectrodes(native), back);
  assert.deepEqual(exportBIDSElectrodes(parseBIDSElectrodes(native)), native);
});

void test('MNI files with other units, coordinates off the scalp or a mixed frame are rejected', () => {
  const files = exportMniBIDSElectrodes(standard(), surface);
  const mutate = (index, change) => files.map((file, at) => at === index ? { ...file, text: change(file.text) } : file);
  const system = change => mutate(1, text => { const value = JSON.parse(text); change(value); return JSON.stringify(value); });
  for (const bad of [
    system(value => { value.EEGCoordinateUnits = 'm'; }),
    system(value => { value.EEGLayoutLabCoordinateSystem = 'ernie_native_mm'; }),
    system(value => { value.EEGCoordinateSystem = 'CapTrak'; }),
    mutate(0, text => text.split('\n').map((line, row) => row === 0 || !line ? line : line.split('\t').map((cell, column) => column >= 1 && column <= 3 ? String(Number(cell) / 1000) : cell).join('\t')).join('\n')),
  ]) assert.throws(() => parseBIDSElectrodes(bad, surface));
  const accepted = parseBIDSElectrodes(system(value => { value.EEGCoordinateSystem = 'MNI152NLin2009cAsym'; }), surface);
  assert.match(accepted.source_metadata.coordinate_system_description, /differences between MNI templates are not modelled/);
});

void test('MNI export refuses electrodes outside the usable warp and the mapping refuses altered buffers', async () => {
  const design = standard(), outside = Array.from({ length: surface.native.length / 3 }, (_, index) => index)
    .find(index => !surface.onUsable[index] && [0, 1, 2].every(axis => surface.mni[3 * index + axis] === 0));
  const point = [0, 1, 2].map(axis => surface.native[3 * outside + axis]);
  assert.ok(point[2] < -100, 'the undefined part of the warp is on the neck');
  assert.throws(() => exportMniBIDSElectrodes({ ...design, xyz_mm: design.xyz_mm.map((value, index) => index === 5 ? point : value) }, surface), /MNI换算范围/);
  const altered = mniBuffer.slice(0); new Uint8Array(altered)[100] ^= 1;
  await assert.rejects(() => verifiedSurface(scalp, altered), /校验失败/);
  assert.throws(() => surfaceFromBuffers(scalp, mniBuffer.slice(0, -1)), /长度不符/);
});

void test('coordinate source /2 accepts only consistent conversions', () => {
  const source = standard().source_metadata, mni = parseBIDSElectrodes(exportMniBIDSElectrodes(standard(), surface), surface).source_metadata;
  for (const bad of [
    { ...source, coordsystem_file: 'coordsystem.json' },
    { ...source, conversion: { ...source.conversion, method: 'ernie-mni-scalp/1' } },
    { ...source, conversion: { ...source.conversion, mapping_id: 'x' } },
    { ...source, schema: 'electrode-coordinate-source/1' },
    { ...mni, coordsystem_file: null },
    { ...mni, conversion: { ...mni.conversion, max_surface_distance_mm: 11 } },
    { ...mni, conversion: { ...mni.conversion, input_coordinate_system: 'Other' } },
    { ...mni, conversion: undefined },
  ]) assert.throws(() => validateCoordinateSource(bad));
});
