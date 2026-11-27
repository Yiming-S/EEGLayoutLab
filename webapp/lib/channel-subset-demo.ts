import { SUMMARY_SCHEMA, TEN_TWENTY, generator, type Summary } from './channel-subset.ts';
import { ERNIE_MNI_MAPPING, type Point } from './ernie-mni.ts';

const PREFERRED_EXTRA = [
  'AF3', 'AF4', 'FC5', 'FC1', 'FC2', 'FC6', 'C1', 'C2', 'CP5', 'CP1', 'CP2', 'CP6', 'POz',
];

const DEMO_SOURCE_CENTERS: readonly Point[] = [
  [0, 62, 35],
  [-46, -8, 52],
  [46, -8, 52],
  [-54, -42, 18],
  [54, -42, 18],
  [0, -72, 20],
];

function demoChannels(): { names: string[]; xyz: Point[] } {
  const golden = ERNIE_MNI_MAPPING.golden.standard64;
  const wanted = new Set<string>([...TEN_TWENTY, ...PREFERRED_EXTRA]);
  for (const name of golden.names) {
    if (wanted.size >= 32) break;
    wanted.add(name);
  }
  const names: string[] = [];
  const xyz: Point[] = [];
  golden.names.forEach((name, index) => {
    if (wanted.has(name) && names.length < 32) {
      names.push(name);
      xyz.push(golden.xyz_mm[index] as Point);
    }
  });
  return { names, xyz };
}

function syntheticCovariance(xyz: readonly Point[], seed: number): number[][] {
  const rand = generator(seed);
  const n = xyz.length;
  const weights = DEMO_SOURCE_CENTERS.map(() => 0.45 + 1.15 * rand());
  const gain = xyz.map((pt) =>
    DEMO_SOURCE_CENTERS.map((src) => {
      const d = Math.hypot(pt[0] - src[0], pt[1] - src[1], pt[2] - src[2]);
      return 1 / (1 + (d / 44) ** 2);
    }),
  );
  return Array.from({ length: n }, (_, i) =>
    Array.from({ length: n }, (_, j) => {
      let sum = 0;
      for (let s = 0; s < DEMO_SOURCE_CENTERS.length; s++) {
        sum += weights[s] * gain[i][s] * gain[j][s];
      }
      const dist = Math.hypot(xyz[i][0] - xyz[j][0], xyz[i][1] - xyz[j][1], xyz[i][2] - xyz[j][2]);
      const background = 0.14 * Math.exp(-dist / 52);
      const sensor = i === j ? 0.05 + 0.03 * rand() : 0;
      return Number((sum + background + sensor).toPrecision(8));
    }),
  );
}

function makeSummary(
  label: string,
  file: string,
  prefix: string,
  index: number,
  names: string[],
  xyz: readonly Point[],
  seed: number,
): Summary {
  const tag = String(index).padStart(2, '0');
  return {
    schema: SUMMARY_SCHEMA,
    label,
    channels: [...names],
    covariance: syntheticCovariance(xyz, seed),
    processing: { band_hz: [1, 40] },
    source: {
      file,
      sha256: prefix.repeat(62) + tag,
      recording_sha256: (prefix === '1' ? 'a' : 'b').repeat(62) + tag,
    },
  };
}

/** Deterministic synthetic 32-channel 10-05 covariance summaries (4 training + 2 held-out) for cold-start browser exploration. */
export function buildDemoChannelSubsetInput(): { training: Summary[]; test: Summary[] } {
  const { names, xyz } = demoChannels();
  return {
    training: [1, 2, 3, 4].map((index) =>
      makeSummary(`demo-train-${index}`, `demo-train-0${index}.edf`, '1', index, names, xyz, 20260 + index),
    ),
    test: [1, 2].map((index) =>
      makeSummary(`demo-heldout-${index}`, `demo-heldout-0${index}.edf`, '2', index, names, xyz, 20280 + index),
    ),
  };
}
