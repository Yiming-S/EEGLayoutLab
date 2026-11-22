import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { ERNIE_MNI_MAPPING, ernieToMni, projectOntoScalp, verifiedSurface } from '../lib/ernie-mni.ts';
import { exportBIDSElectrodes, parseBIDSElectrodes, parseElectrodeLabels } from '../lib/bids-electrodes.ts';
import { exportEeglabSfp, exportMneElc, readMneElc } from '../lib/montage-files.ts';
import { parseBrowserMontageFile, parseMontageFile } from '../lib/head-frame-import.ts';
import { ERNIE_LANDMARKS, assignBalancedRegions, landmarkSimilarity, registerHeadPoints, regionSizes, similarityFit } from '../lib/head-registration.ts';
import { HEAD_REGISTRATION_LIMIT_MM, validateCoordinateSource } from '../contracts/coordinate-source.mjs';
import { designSubmission as parseSubmission } from '../server/annotations/electrode-names.mjs';
import { designSubmission } from '../lib/design-decision.ts';

const buffer = path => { const bytes = readFileSync(new URL('../public' + path, import.meta.url)); return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength); };
const surface = await verifiedSurface(buffer(ERNIE_MNI_MAPPING.scalp_buffer.file), buffer(ERNIE_MNI_MAPPING.mni_buffer.file));
const names = ERNIE_MNI_MAPPING.golden.standard64.names;
const standard = parseElectrodeLabels({ name: 'standard64.tsv', text: 'name\tregion\n' + names.map((name, index) => `${name}\t${index % 2}`).join('\n') + '\n' });
const distance = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
const errors = points => points.map((point, index) => distance(point, standard.xyz_mm[index])).sort((a, b) => a - b);

/** A participant's frame: Ernie scaled, rotated about two axes and shifted, plus seeded Gaussian noise. */
function subject({ scale = 1.07, degrees = 25, noise = 0, landmarkNoise = 0, seed = 7 } = {}) {
  let state = seed;
  const random = () => { state = (state * 16807) % 2147483647; return state / 2147483647; };
  const gauss = () => Math.sqrt(-2 * Math.log(random())) * Math.cos(2 * Math.PI * random());
  const a = degrees * Math.PI / 180, b = a / 3;
  const rz = [[Math.cos(a), -Math.sin(a), 0], [Math.sin(a), Math.cos(a), 0], [0, 0, 1]];
  const rx = [[1, 0, 0], [0, Math.cos(b), -Math.sin(b)], [0, Math.sin(b), Math.cos(b)]];
  const rotation = rz.map(row => [0, 1, 2].map(c => row.reduce((sum, value, k) => sum + value * rx[k][c], 0)));
  const move = (p, sd) => rotation.map((row, r) => scale * (row[0] * p[0] + row[1] * p[1] + row[2] * p[2]) + [12, -30, 45][r] + sd * gauss());
  return { points: standard.xyz_mm.map(p => move(p, noise)), landmarks: Object.fromEntries(['NAS', 'LPA', 'RPA'].map(name => [name, move(ERNIE_LANDMARKS[name], landmarkNoise)])) };
}

const elcText = ({ points, landmarks }, unit = 'mm', factor = 1) => ['# digitized', `UnitPosition\t${unit}`, 'NumberPositions=\t67', 'Positions',
  ...[...points, landmarks.NAS, landmarks.LPA, landmarks.RPA].map(p => p.map(v => v * factor).join(' ')), 'Labels', ...names, 'Nz', 'LPA', 'RPA', ''].join('\n');

void test('the closed-form similarity fit and the landmark frame recover an exact transform', () => {
  const { points, landmarks } = subject();
  const fit = similarityFit(standard.xyz_mm, points, points.map(() => 1));
  assert.ok(Math.abs(fit.scale - 1.07) < 1e-9);
  const initial = landmarkSimilarity(landmarks);
  const back = points.map(p => initial.rotation.map((row, r) => initial.scale * (row[0] * p[0] + row[1] * p[1] + row[2] * p[2]) + initial.translation[r]));
  assert.ok(Math.max(...errors(back)) < 1e-9);
});

void test('noise-free digitized coordinates register exactly; noisy ones within the expected error', () => {
  const exact = registerHeadPoints(subject().points, subject().landmarks, surface);
  assert.ok(errors(exact.points)[63] < 1e-4 && Math.abs(exact.scale - 1 / 1.07) < 1e-7);
  // 1.5 mm electrode and 3 mm landmark digitization noise: the surface fit improves on landmarks alone.
  const noisy = subject({ noise: 1.5, landmarkNoise: 3, seed: 11 }), registered = registerHeadPoints(noisy.points, noisy.landmarks, surface);
  const initial = landmarkSimilarity(noisy.landmarks);
  const landmarkOnly = projectOntoScalp(noisy.points.map(p => initial.rotation.map((row, r) => initial.scale * (row[0] * p[0] + row[1] * p[1] + row[2] * p[2]) + initial.translation[r])), surface);
  assert.ok(errors(registered.points)[32] < errors(landmarkOnly.points)[32], 'surface fit improves the median');
  assert.ok(errors(registered.points)[32] < 3.5 && errors(registered.points)[63] < 10, JSON.stringify(errors(registered.points).slice(30, 34)));
  assert.ok(registered.iterations < 500 && registered.distances_mm.every(d => d < 10));
});

void test('the grid scalp projection agrees with the full-surface search', () => {
  // On the upper head every triangle is usable by the MNI warp, so the MNI-surface projection searches the same triangles.
  const points = standard.xyz_mm.slice(0, 40).map(p => p.map(v => v * 1.02 + 1.5));
  const fast = projectOntoScalp(points, surface), reference = ernieToMni(points, surface);
  fast.distances_mm.forEach((value, index) => assert.ok(value <= reference.distances_mm[index] + 1e-9));
});

void test('EEGLayoutLab .elc and .sfp exports read back unchanged; other montages are registered', () => {
  for (const [file, options] of [[exportMneElc(standard), {}], [exportEeglabSfp(standard), { unit: 'mm' }]]) {
    const back = parseMontageFile(file, surface, { ...options, regionCount: 2 });
    assert.deepEqual(back.xyz_mm, standard.xyz_mm);
    assert.equal(back.source_metadata.conversion, null);
    assert.deepEqual(back.source_metadata.region_assignment, { method: 'balanced-spatial/1', region_count: 2 });
  }
  const digitized = subject({ noise: 1, landmarkNoise: 2 });
  const fromMetres = parseMontageFile({ name: 'cap.elc', text: elcText(digitized, 'm', 1e-3) }, surface, { regionCount: 4 });
  const fromMm = parseMontageFile({ name: 'cap.elc', text: elcText(digitized) }, surface, { regionCount: 4 });
  fromMetres.xyz_mm.forEach((p, i) => assert.ok(distance(p, fromMm.xyz_mm[i]) < 1e-6));
  const source = validateCoordinateSource(fromMetres.source_metadata);
  assert.equal(source.schema, 'electrode-coordinate-source/3');
  assert.equal(source.conversion.method, 'head-landmarks-surface/1');
  assert.equal(source.conversion.input_unit, 'm');
  assert.match(source.coordinate_system_description, /not an individual anatomical registration/);
  assert.ok(errors(fromMetres.xyz_mm)[32] < 3);
  // The server's submission adapter keeps the /3 source.
  const submission = parseSubmission(JSON.parse(JSON.stringify(designSubmission(fromMetres, 'evaluate', 6, 42))));
  assert.equal(submission.source_metadata.schema, 'electrode-coordinate-source/3');
});

void test('browser imports use the elc declared unit regardless of the sfp unit selector', () => {
  const digitized = subject();
  const baseline = parseMontageFile({ name: 'cap.elc', text: elcText(digitized) }, surface, { regionCount: 4 });
  for (const [unit, factor] of [['mm', 1], ['cm', 0.1], ['m', 0.001]]) {
    const file = { name: 'cap.ELC', text: elcText(digitized, unit, factor) };
    for (const sfpUnit of ['mm', 'cm', 'm']) {
      const back = parseBrowserMontageFile(file, surface, { regionCount: 4, sfpUnit });
      back.xyz_mm.forEach((point, i) => assert.ok(distance(point, baseline.xyz_mm[i]) < 1e-6));
      assert.equal(back.source_metadata.conversion.input_unit, unit);
      assert.deepEqual(back.electrode_names, baseline.electrode_names);
    }
  }
  // The CLI can still reject an explicitly contradictory unit assertion.
  assert.throws(() => parseMontageFile({ name: 'cap.elc', text: elcText(digitized, 'm', 0.001) }, surface,
    { regionCount: 4, unit: 'mm' }), /单位不一致/);
});

void test('browser sfp imports keep using the selected unit', () => {
  const digitized = subject();
  const baseline = parseMontageFile({ name: 'cap.elc', text: elcText(digitized) }, surface, { regionCount: 2 });
  const rows = [['FidNz', digitized.landmarks.NAS], ['FidT9', digitized.landmarks.LPA], ['FidT10', digitized.landmarks.RPA],
    ...names.map((name, i) => [name, digitized.points[i]])];
  for (const [sfpUnit, factor] of [['mm', 1], ['cm', 0.1], ['m', 0.001]]) {
    const text = rows.map(([name, point]) => [name, ...point.map(value => value * factor)].join('\t')).join('\n') + '\n';
    const back = parseBrowserMontageFile({ name: 'cap.SFP', text }, surface, { regionCount: 2, sfpUnit });
    back.xyz_mm.forEach((point, i) => assert.ok(distance(point, baseline.xyz_mm[i]) < 1e-6));
    assert.deepEqual(back.electrode_names, baseline.electrode_names);
    assert.equal(back.source_metadata.conversion.input_unit, sfpUnit);
  }
});

void test('montage readers refuse ambiguous files', () => {
  const digitized = subject();
  assert.throws(() => parseMontageFile({ name: 'cap.sfp', text: exportEeglabSfp(standard).text }, surface, { regionCount: 2 }), /单位/);
  assert.throws(() => parseMontageFile(exportMneElc(standard), surface), /region/);
  assert.throws(() => parseMontageFile({ name: 'cap.elc', text: elcText(digitized).replace('UnitPosition\tmm\n', '') }, surface, { regionCount: 2 }), /UnitPosition/);
  const noNasion = ['UnitPosition\tmm', 'NumberPositions=\t66', 'Positions', ...[...digitized.points, digitized.landmarks.LPA, digitized.landmarks.RPA].map(p => p.join(' ')),
    'Labels', ...names, 'LPA', 'RPA', ''].join('\n');
  assert.throws(() => parseMontageFile({ name: 'cap.elc', text: noNasion }, surface, { regionCount: 2 }), /基准点NAS/);
  const sixtyThree = readMneElc({ name: 'cap.elc', text: elcText(digitized) });
  assert.equal(sixtyThree.names.length, 64);
  // Coordinates in the wrong unit land far from the scalp or need an implausible scale.
  assert.throws(() => parseMontageFile({ name: 'cap.elc', text: elcText(digitized, 'cm') }, surface, { regionCount: 2 }), /缩放|头皮/);
});

void test('BIDS head-frame pairs (CapTrak) are registered; extra channels and n/a rows are skipped', () => {
  const digitized = subject({ noise: 1, landmarkNoise: 2 });
  const tsv = 'name\tx\ty\tz\ttype\timpedance\n' + digitized.points.map((p, i) => [names[i], ...p, 'EEG', 5].join('\t')).join('\n') +
    '\nGND\t1\t2\t3\tGND\tn/a\nREF\tn/a\tn/a\tn/a\tEEG\tn/a\n';
  const system = { EEGCoordinateSystem: 'CapTrak', EEGCoordinateUnits: 'mm', AnatomicalLandmarkCoordinates: digitized.landmarks,
    AnatomicalLandmarkCoordinateSystem: 'CapTrak', AnatomicalLandmarkCoordinateUnits: 'mm' };
  const files = [{ name: 'sub-01_electrodes.tsv', text: tsv }, { name: 'sub-01_coordsystem.json', text: JSON.stringify(system) }];
  assert.throws(() => parseBIDSElectrodes(files, surface), /region/);
  assert.throws(() => parseBIDSElectrodes(files, undefined, { regionCount: 3 }), /头皮/);
  const design = parseBIDSElectrodes(files, surface, { regionCount: 3 });
  assert.equal(design.source_metadata.conversion.input_coordinate_system, 'CapTrak');
  assert.equal(design.source_metadata.conversion.landmark_source, 'coordsystem');
  assert.ok(errors(design.xyz_mm)[32] < 3);
  const mismatched = { ...system, AnatomicalLandmarkCoordinateUnits: 'm' };
  assert.throws(() => parseBIDSElectrodes([files[0], { ...files[1], text: JSON.stringify(mismatched) }], surface, { regionCount: 3 }), /单位/);
  // Ernie-native exports without the region column take assigned regions and keep coordinates.
  const native = exportBIDSElectrodes(standard).slice(0, 2).map(file => file.name === 'electrodes.tsv'
    ? { ...file, text: file.text.split('\n').map(line => line.split('\t').slice(0, 4).join('\t')).join('\n') } : file);
  const reassigned = parseBIDSElectrodes(native, undefined, { regionCount: 6 });
  assert.deepEqual(reassigned.xyz_mm, standard.xyz_mm);
  assert.equal(reassigned.source_metadata.conversion, null);
});

void test('balanced spatial regions have the evaluator sizes and do not depend on electrode order', () => {
  for (const count of [1, 2, 3, 4, 6]) {
    const labels = assignBalancedRegions(standard.xyz_mm, count);
    assert.deepEqual(Array.from({ length: count }, (_, r) => labels.filter(l => l === r).length).sort((a, b) => b - a), regionSizes(count));
    // Region numbers run from anterior to posterior, whatever the region sizes.
    const front = Array.from({ length: count }, (_, r) => { const ys = standard.xyz_mm.filter((_, i) => labels[i] === r).map(p => p[1]); return ys.reduce((a, b) => a + b, 0) / ys.length; });
    assert.deepEqual(front, [...front].sort((a, b) => b - a), `${count} regions`);
    const order = standard.xyz_mm.map((_, i) => (i * 37) % 64), shuffled = assignBalancedRegions(order.map(i => standard.xyz_mm[i]), count);
    // Same partition after reordering: electrodes grouped together stay together.
    const together = (l, i, j) => l[i] === l[j];
    for (let i = 0; i < 64; i += 7) for (let j = 0; j < 64; j += 5)
      assert.equal(together(labels, order[i], order[j]), together(shuffled, i, j));
  }
  const named = parseElectrodeLabels({ name: 'names.txt', text: 'name\n' + names.join('\n') + '\n' }, { regionCount: 4 });
  assert.deepEqual(named.xyz_mm, standard.xyz_mm);
  assert.deepEqual(named.source_metadata.region_assignment, { method: 'balanced-spatial/1', region_count: 4 });
  assert.throws(() => parseElectrodeLabels({ name: 'names.txt', text: 'name\n' + names.join('\n') + '\n' }), /region/);
});

const mnePython = process.env.EEG_MNE_PYTHON || 'python3';
const hasMne = spawnSync(mnePython, ['-I', '-c', 'import mne'], { stdio: 'ignore' }).status === 0;
/** MNE's built-in template montages (shipped with the package): positions and fiducials in millimetres. */
function mneMontage(kind) {
  const script = ['import json, sys, mne', 'p = mne.channels.make_standard_montage(sys.argv[1]).get_positions()',
    'mm = lambda v: [float(x) * 1000 for x in v]',
    'print(json.dumps({"names": list(p["ch_pos"]), "points": [mm(v) for v in p["ch_pos"].values()], "landmarks": {"NAS": mm(p["nasion"]), "LPA": mm(p["lpa"]), "RPA": mm(p["rpa"])}}))'].join('\n');
  const run = spawnSync(mnePython, ['-I', '-c', script, kind], { encoding: 'utf8' });
  assert.equal(run.status, 0, run.stderr);
  return JSON.parse(run.stdout);
}

void test('another template head (MNE standard_1005 on fsaverage) lands near Ernie\'s own 10-05 positions', { skip: hasMne ? false : `${mnePython} has no mne` }, () => {
  const fsaverage = mneMontage('standard_1005'), index = new Map(fsaverage.names.map((name, i) => [name.toLowerCase(), i]));
  const points = names.map(name => fsaverage.points[index.get(name.toLowerCase())]);
  const design = parseMontageFile({ name: 'fsaverage.elc', text: elcText({ points, landmarks: fsaverage.landmarks }) }, surface, { regionCount: 4 });
  // The two heads differ in shape: occipital sites sit about 2 cm higher on fsaverage relative to NAS/LPA/RPA.
  const offsets = errors(design.xyz_mm);
  assert.ok(offsets[32] > 8 && offsets[32] < 11 && offsets[63] < 25, JSON.stringify([offsets[32], offsets[63]]));
  assert.ok(design.source_metadata.conversion.max_surface_distance_mm < HEAD_REGISTRATION_LIMIT_MM);
  // MNE's biosemi64 is a spherical template, not a head: refused with a pointer to the name list.
  const sphere = mneMontage('biosemi64');
  assert.throws(() => parseMontageFile({ name: 'biosemi64.elc', text: elcText(sphere) }, surface, { regionCount: 4 }), /球面模板/);
});
