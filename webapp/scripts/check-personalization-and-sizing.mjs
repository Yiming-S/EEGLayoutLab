import test from 'node:test';
import assert from 'node:assert/strict';
import zlib from 'node:zlib';
import fs from 'node:fs';
import path from 'node:path';
import Module, { createRequire } from 'node:module';
import ts from 'typescript';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

import { normalizeDataPrior } from '../contracts/scientific-options.mjs';
import { readDataPriorFile } from '../lib/data-prior.ts';
import {
  SCENARIO_PRIOR_PRESETS,
  buildSyntheticFmriNifti,
  decompressGzipIfNeeded,
  exportScenarioDataPriorJson,
  niftiVolumeToDataPrior,
  parseFmriPeakTable,
  parseNiftiHeader,
  projectMniPeaksToDataPrior,
} from '../lib/fmri-prior.ts';
import {
  ERNIE_CRANIAL_FRAME,
  SUBJECT_HEAD_PRESETS,
  calibrateFromPhotoLandmarks,
  dimensionsFromCircumferenceAndCi,
  ellipseCircumferenceMm,
  exportPersonalizedMontageCsv,
  exportPersonalizedMontageJson,
  morphLayoutToSubject,
} from '../lib/head-personalization.ts';
import {
  analyzeHardwareSizing,
  exportHardwareCadCsv,
  exportHardwareCadJson,
} from '../lib/hardware-sizing.ts';

const root = path.resolve(import.meta.dirname, '..');
const modules = new Map();
function loadUI(file) {
  let target = path.resolve(root, file);
  if (!fs.existsSync(target)) {
    target = ['.tsx', '.ts', '.json'].map((e) => target + e).find((p) => fs.existsSync(p));
  }
  if (!target) throw new Error('Fixture module not found: ' + file);
  if (target.endsWith('.json')) return JSON.parse(fs.readFileSync(target, 'utf8'));
  if (modules.has(target)) return modules.get(target).exports;
  const unit = new Module(target);
  modules.set(target, unit);
  unit.filename = target;
  unit.paths = Module._nodeModulePaths(path.dirname(target));
  const require = createRequire(target);
  unit.require = (specifier) => {
    if (specifier.startsWith('@/')) return loadUI(specifier.slice(2));
    if (specifier.startsWith('.')) {
      return loadUI(path.relative(root, path.resolve(path.dirname(target), specifier)));
    }
    return require(specifier);
  };
  unit._compile(
    ts.transpileModule(fs.readFileSync(target, 'utf8'), {
      compilerOptions: {
        jsx: ts.JsxEmit.ReactJSX,
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
        esModuleInterop: true,
      },
      fileName: target,
    }).outputText,
    target,
  );
  return unit.exports;
}

const { LanguageProvider } = loadUI('components/language-provider.tsx');
const render = (component, props, locale) =>
  renderToStaticMarkup(
    React.createElement(LanguageProvider, { initialLocale: locale }, React.createElement(component, props)),
  );
const visibleText = (html) =>
  html
    .replace(/<(script|style|pre|code|textarea)\b[^>]*>[\s\S]*?<\/\1>/g, '')
    .replace(/<[^>]+>/g, '')
    .replaceAll('简体中文', '');

await test('scenario functional presets and MNI/NIfTI fMRI projections produce canonical data priors', async () => {
  assert.equal(SCENARIO_PRIOR_PRESETS.length, 4);
  for (const preset of SCENARIO_PRIOR_PRESETS) {
    assert.deepEqual(normalizeDataPrior(preset.prior), preset.prior, preset.id);
    const exported = exportScenarioDataPriorJson(preset.prior, preset.id);
    const reparsed = readDataPriorFile(exported);
    assert.deepEqual(reparsed.value, preset.prior);
  }

  // Occipital MNI peaks must make occipital (index 3) the highest-gain ROI
  const occPeaks = parseFmriPeakTable('L_V1,-12,-88,2,6.5,18\nR_V1,14,-86,4,6.2,18');
  assert.equal(occPeaks.length, 2);
  const occMapped = projectMniPeaksToDataPrior(occPeaks);
  assert.deepEqual(normalizeDataPrior(occMapped.prior), occMapped.prior);
  const occGain = occMapped.prior.region_gain[3];
  for (let i = 0; i < occMapped.prior.region_gain.length; i++) {
    if (i !== 3) assert.ok(occGain > occMapped.prior.region_gain[i], `occipital > region ${i}`);
  }

  // Real binary NIfTI-1 (.nii and gzipped .nii.gz) parsing & cortical projection
  const niftiBuffer = buildSyntheticFmriNifti(occPeaks);
  const hdr = parseNiftiHeader(niftiBuffer);
  assert.deepEqual(hdr.dims.slice(0, 3), [46, 55, 46]);

  const gzBuf = zlib.gzipSync(Buffer.from(niftiBuffer));
  const gzArrayBuf = gzBuf.buffer.slice(gzBuf.byteOffset, gzBuf.byteOffset + gzBuf.byteLength);
  const unzippedBuf = await decompressGzipIfNeeded(gzArrayBuf);
  const fromNifti = niftiVolumeToDataPrior(unzippedBuf, { statThreshold: 1.5 });
  assert.deepEqual(normalizeDataPrior(fromNifti.prior), fromNifti.prior);
  assert.ok(fromNifti.summary.activeSources > 0);
  assert.ok(fromNifti.prior.region_gain[3] > fromNifti.prior.region_gain[0]);
});

await test('anthropometric & photo-landmark head personalization preserves reference geometry and scales camera-invariantly', () => {
  const { lengthMm, breadthMm } = dimensionsFromCircumferenceAndCi(570, 78);
  assert.ok(Math.abs(ellipseCircumferenceMm(lengthMm, breadthMm) - 570) < 1e-6);
  assert.ok(Math.abs((100 * breadthMm) / lengthMm - 78) < 1e-6);

  // Camera zoom invariance: scaling front or side photo normalized coordinates around center preserves calibrated CI & dimensions
  const frontA = { leftTragus: [0.24, 0.6], rightTragus: [0.76, 0.6], vertexTop: [0.5, 0.16] };
  const sideA = { nasion: [0.16, 0.54], inion: [0.84, 0.58], tragus: [0.5, 0.6], vertexTop: [0.5, 0.12] };
  const frontZoomed = {
    leftTragus: [0.5 + (0.24 - 0.5) * 0.7, 0.5 + (0.6 - 0.5) * 0.7],
    rightTragus: [0.5 + (0.76 - 0.5) * 0.7, 0.5 + (0.6 - 0.5) * 0.7],
    vertexTop: [0.5 + (0.5 - 0.5) * 0.7, 0.5 + (0.16 - 0.5) * 0.7],
  };
  const cal1 = calibrateFromPhotoLandmarks(frontA, sideA, 582);
  const cal2 = calibrateFromPhotoLandmarks(frontZoomed, sideA, 582);
  assert.equal(cal1.cephalicIndex, cal2.cephalicIndex);
  assert.equal(cal1.vertexHeightMm, cal2.vertexHeightMm);
  // The page's untouched default marks solve to CI ≈ 92.2; out-of-range solves are reported, not clamped.
  assert.throws(
    () => calibrateFromPhotoLandmarks(
      { leftTragus: [0.22, 0.58], rightTragus: [0.78, 0.58], vertexTop: [0.5, 0.14] },
      { nasion: [0.18, 0.52], inion: [0.84, 0.58], tragus: [0.52, 0.62], vertexTop: [0.5, 0.14] },
      585,
    ),
    /超出成人范围 67–92/,
  );
  assert.throws(
    // CI stays ≈ 82 but the side view implies a ~185 mm vertex height.
    () => calibrateFromPhotoLandmarks({ ...frontA, vertexTop: [0.5, 0.022] }, { ...sideA, tragus: [0.5, 0.739] }, 582),
    /颅顶高度 .* 超出成人范围/,
  );

  const sample8 = [
    [-74.5, 42.8, 6.8],
    [-77.2, 10.5, -1.9],
    [-78.2, -18.2, -7.5],
    [-71.1, -46.5, -9.9],
    [79.7, 43.6, -1.0],
    [80.4, 9.9, -9.2],
    [81.2, -19.6, -15.4],
    [68.4, -46.3, -15.8],
  ];
  const regions8 = [0, 0, 0, 0, 1, 1, 1, 1];

  // Reference preset stays within sub-millimeter rounding of Ernie native coordinates
  const refPreset = SUBJECT_HEAD_PRESETS.find((p) => p.id === 'ernie_reference');
  const refMorphed = morphLayoutToSubject(sample8, regions8, refPreset);
  assert.ok(refMorphed.maxShiftMm < 0.35, `expected near-zero shift on reference, got ${refMorphed.maxShiftMm}`);
  assert.ok(ERNIE_CRANIAL_FRAME.breadthMm > 140 && ERNIE_CRANIAL_FRAME.lengthMm > 185);

  // Large dolichocephalic subject shifts coordinates by several millimetres while preserving safe spacing
  const largePreset = SUBJECT_HEAD_PRESETS.find((p) => p.id === 'large_dolicho');
  const largeMorphed = morphLayoutToSubject(sample8, regions8, largePreset);
  assert.ok(largeMorphed.meanShiftMm > 3.0);
  assert.equal(largeMorphed.spacingSafe, true);

  const csv = exportPersonalizedMontageCsv(largeMorphed);
  const json = JSON.parse(exportPersonalizedMontageJson(largeMorphed, 'Ear-8'));
  assert.match(csv, /schema=eeg-personalized-montage\/1/);
  assert.equal(json.schema, 'eeg-personalized-montage/1');
  assert.equal(json.xyz_mm.length, 8);
});

await test('hardware S/M/L sizing reduces required radial spring stroke compared to universal one-size shell', () => {
  const wearable12 = [
    [-49.8, 96.9, 20.8],
    [-25.5, 111.1, 26.3],
    [3.3, 116.0, 31.3],
    [32.6, 112.6, 23.6],
    [56.6, 97.5, 14.8],
    [5.4, 71.6, 86.7],
    [-74.5, 42.8, 6.8],
    [-77.2, 10.5, -1.9],
    [-78.2, -18.2, -7.5],
    [79.7, 43.6, -1.0],
    [80.4, 9.9, -9.2],
    [81.2, -19.6, -15.4],
  ];
  const regions12 = [0, 0, 0, 0, 0, 0, 1, 1, 1, 2, 2, 2];

  const sml = analyzeHardwareSizing(wearable12, regions12, {
    designName: 'Wearable-12',
    sizingMode: 'three_size_sml',
  });
  const oneSize = analyzeHardwareSizing(wearable12, regions12, {
    designName: 'Wearable-12',
    sizingMode: 'one_size_universal',
  });

  assert.equal(sml.electrodeCount, 12);
  assert.ok(
    sml.summary.maxRadialStrokeMm < oneSize.summary.maxRadialStrokeMm,
    'S/M/L split must require smaller plunger travel than one-size',
  );
  for (const e of sml.electrodes) {
    const nLen = Math.hypot(e.normal[0], e.normal[1], e.normal[2]);
    assert.ok(Math.abs(nLen - 1) < 1e-2, `unit normal length ${nLen}`);
  }

  const cadCsv = exportHardwareCadCsv(sml);
  const cadJson = JSON.parse(exportHardwareCadJson(sml));
  assert.match(cadCsv, /normal_x,normal_y,normal_z,radial_stroke_mm/);
  assert.equal(cadJson.schema, 'eeg-hardware-sizing-reference/1');
  assert.equal(cadJson.electrodes.length, 12);
});

await test('upgraded DataPriorPicker, HeadPhotoPersonalizer, and HardwareSizingPanel render bilingually with zero Han leaks in English', () => {
  const { DataPriorPicker } = loadUI('features/data/data-prior-picker.tsx');
  const { HeadPhotoPersonalizer } = loadUI('features/personalize/head-photo-personalizer.tsx');
  const { HardwareSizingPanel } = loadUI('features/robustness/hardware-sizing-panel.tsx');

  const activePrior = SCENARIO_PRIOR_PRESETS[0].prior;
  for (const locale of ['zh-CN', 'en']) {
    const priorHtml = render(
      DataPriorPicker,
      { value: activePrior, source: 'ssvep_occipital', onChange() {} },
      locale,
    );
    const personalizerHtml = render(HeadPhotoPersonalizer, { importedDesign: null }, locale);
    const hardwareHtml = render(HardwareSizingPanel, { draftDesign: null }, locale);

    assert.match(priorHtml, /data-scenario-prior-picker/);
    assert.match(personalizerHtml, /data-head-photo-personalizer/);
    assert.match(hardwareHtml, /data-hardware-sizing-panel/);

    if (locale === 'en') {
      for (const [name, html] of [
        ['DataPriorPicker', priorHtml],
        ['HeadPhotoPersonalizer', personalizerHtml],
        ['HardwareSizingPanel', hardwareHtml],
      ]) {
        const leaked = visibleText(html).match(/.{0,30}[\u3400-\u9fff].{0,30}/g);
        assert.equal(leaked, null, `${name} leaked Chinese in English: ${JSON.stringify(leaked)}`);
      }
    }
  }
});
