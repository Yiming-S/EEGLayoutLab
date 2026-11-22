/**
 * Channel-subset selection from recorded EEG covariance (eeg-covariance-summary/1).
 *
 * A subset S is recorded against one of its own channels, so it measures the |S|−1 differences
 * x_c − x_s0; the choice of s0 does not change their span. The target is the average-referenced
 * signal of every universe channel. A linear reconstructor W = C Dᵀ(D C Dᵀ)⁻¹ is fitted on the
 * pooled training covariance C and the error is the unexplained variance fraction
 * tr((I − W D) C' (I − W D)ᵀ) / tr(C') on a covariance C' (the training covariance itself, or
 * a held-out one). Selection is greedy: the best pair, then the channel that explains the most
 * residual variance. Methods differ only in the covariance used for selection.
 */

export const SUBSET_SCHEMA = 'eeg-channel-subset/1';
export const SUMMARY_SCHEMA = 'eeg-covariance-summary/1';
export const PRIOR_SCHEMA = 'eeg-data-prior/1';
export const DEFAULT_COUNTS = [8, 16, 24, 32];
export const RANDOM_DRAWS = 200;
/** As in the prior fit: channels in at least this fraction of the training summaries form the universe. */
export const CHANNEL_PRESENCE = 0.9;
/** International 10-20 system, 19 channels, in current (T7/T8/P7/P8) names. */
export const TEN_TWENTY = ['Fp1', 'Fp2', 'F7', 'F3', 'Fz', 'F4', 'F8', 'T7', 'C3', 'Cz', 'C4', 'T8', 'P7', 'P3', 'Pz', 'P4', 'P8', 'O1', 'O2'];

export type Summary = {
  schema: string; label?: string | null; channels: string[]; covariance: number[][];
  processing: { band_hz: number[] }; source: { file: string; sha256: string; recording_sha256?: string };
};
export type PriorFile = {
  schema: string; id: string; channels: string[]; band_hz: number[];
  channel_model: { data_prior: number[][]; area_prior: number[][] };
};
export type Stats = { mean: number; median: number; p10: number; p90: number };
export type Matrix = { n: number; a: Float64Array };

const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);

function quantile(sorted: number[], q: number) {
  const position = (sorted.length - 1) * q, low = Math.floor(position), high = Math.ceil(position);
  return sorted[low] + (sorted[high] - sorted[low]) * (position - low);
}

export function stats(values: number[]): Stats {
  const sorted = [...values].sort((x, y) => x - y);
  return { mean: values.reduce((s, v) => s + v, 0) / values.length, median: quantile(sorted, .5), p10: quantile(sorted, .1), p90: quantile(sorted, .9) };
}

/** Average-referenced, trace-normalized matrix of all `channels` (used by tests and callers with plain arrays). */
export function covarianceMatrix(covariance: number[][], channels: string[]) {
  return restrict(covariance, channels, channels);
}

/** Square symmetric matrix of `names` taken from a covariance given at `channels`, average-referenced and trace-normalized. */
function restrict(covariance: number[][], channels: string[], names: string[]): Matrix {
  const index = names.map((name) => channels.indexOf(name)), n = names.length, a = new Float64Array(n * n);
  for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) a[i * n + j] = (covariance[index[i]][index[j]] + covariance[index[j]][index[i]]) / 2;
  const rows = new Float64Array(n);
  let total = 0;
  for (let i = 0; i < n; i++) { for (let j = 0; j < n; j++) rows[i] += a[i * n + j]; total += rows[i]; }
  for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) a[i * n + j] += total / (n * n) - rows[i] / n - rows[j] / n;
  const trace = traceOf({ n, a });
  if (!(trace > 0)) throw new Error('协方差的迹不为正');
  for (let k = 0; k < a.length; k++) a[k] /= trace;
  return { n, a };
}

function traceOf(m: Matrix) {
  let t = 0;
  for (let i = 0; i < m.n; i++) t += m.a[i * m.n + i];
  return t;
}

function mean(matrices: Matrix[]): Matrix {
  const n = matrices[0].n, a = new Float64Array(n * n);
  for (const m of matrices) for (let k = 0; k < a.length; k++) a[k] += m.a[k] / matrices.length;
  return { n, a };
}

/** Cholesky solve of A X = B for SPD A (k×k) and B (k×n), with a small ridge for numerical safety. */
function solve(A: Float64Array, k: number, B: Float64Array, n: number) {
  let trace = 0;
  for (let i = 0; i < k; i++) trace += A[i * k + i];
  const L = new Float64Array(k * k), ridge = 1e-12 * trace / Math.max(k, 1);
  for (let i = 0; i < k; i++) for (let j = 0; j <= i; j++) {
    let s = A[i * k + j] + (i === j ? ridge : 0);
    for (let p = 0; p < j; p++) s -= L[i * k + p] * L[j * k + p];
    if (i === j) {
      if (!(s > 0)) throw new Error('子集通道的协方差奇异');
      L[i * k + i] = Math.sqrt(s);
    } else L[i * k + j] = s / L[j * k + j];
  }
  const X = Float64Array.from(B);
  for (let c = 0; c < n; c++) {
    for (let i = 0; i < k; i++) { let s = X[i * n + c]; for (let p = 0; p < i; p++) s -= L[i * k + p] * X[p * n + c]; X[i * n + c] = s / L[i * k + i]; }
    for (let i = k - 1; i >= 0; i--) { let s = X[i * n + c]; for (let p = i + 1; p < k; p++) s -= L[p * k + i] * X[p * n + c]; X[i * n + c] = s / L[i * k + i]; }
  }
  return X;
}

/**
 * Reconstructor from `train` for `subset` (indices), as rows (subset[1..] − subset[0]) of a k−1 by n map V,
 * so that x̂ = Vᵀ (D x). Errors on any covariance follow from it.
 */
function reconstructor(train: Matrix, subset: number[]) {
  const { n, a } = train, s0 = subset[0], k = subset.length - 1;
  const B = new Float64Array(k * n);
  for (let m = 0; m < k; m++) for (let j = 0; j < n; j++) B[m * n + j] = a[subset[m + 1] * n + j] - a[s0 * n + j];
  const A = new Float64Array(k * k);
  for (let m = 0; m < k; m++) for (let p = 0; p < k; p++) A[m * k + p] = B[m * n + subset[p + 1]] - B[m * n + s0];
  return solve(A, k, B, n);
}

/** Unexplained variance fraction of `test` when `subset` is reconstructed with the training reconstructor. */
export function reconstructionError(train: Matrix, test: Matrix, subset: number[], V = subset.length > 1 ? reconstructor(train, subset) : null) {
  const { n } = test, c = test.a, total = traceOf(test);
  if (!V) return 1;
  const k = subset.length - 1, s0 = subset[0];
  // E = I − M with M = Vᵀ D; M[i][subset[m+1]] = V[m][i], M[i][s0] = −Σ_m V[m][i].
  const M = new Float64Array(n * n);
  for (let m = 0; m < k; m++) for (let i = 0; i < n; i++) { M[i * n + subset[m + 1]] += V[m * n + i]; M[i * n + s0] -= V[m * n + i]; }
  // tr(E C Eᵀ) = tr(C) − 2 tr(M C) + tr(M C Mᵀ), using only the nonzero columns of M.
  const columns = [s0, ...subset.slice(1)];
  let cross = 0, quadratic = 0;
  for (let i = 0; i < n; i++) for (const p of columns) cross += M[i * n + p] * c[p * n + i];
  for (let i = 0; i < n; i++) for (const p of columns) for (const q of columns) quadratic += M[i * n + p] * c[p * n + q] * M[i * n + q];
  return Math.max(0, (total - 2 * cross + quadratic) / total);
}

/** Greedy order of `count` channel indices that best explains `m` (pair first, then residual updates). */
export function greedyOrder(m: Matrix, count: number) {
  const { n } = m, R = Float64Array.from(m.a), total = traceOf(m), eps = 1e-12 * total;
  let best = -1, pair: [number, number] = [0, 1];
  const squared = new Float64Array(n * n);
  for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) { let s = 0; for (let p = 0; p < n; p++) s += R[i * n + p] * R[p * n + j]; squared[i * n + j] = s; }
  for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) {
    const den = R[i * n + i] + R[j * n + j] - 2 * R[i * n + j];
    if (den <= eps) continue;
    const gain = (squared[i * n + i] + squared[j * n + j] - 2 * squared[i * n + j]) / den;
    if (gain > best + 1e-15) { best = gain; pair = [i, j]; }
  }
  const order: number[] = [];
  const add = (c: number, s0: number) => {
    const u = new Float64Array(n);
    for (let i = 0; i < n; i++) u[i] = R[i * n + c] - R[i * n + s0];
    const den = u[c] - u[s0];
    if (den > eps) for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) R[i * n + j] -= u[i] * u[j] / den;
    order.push(c);
  };
  order.push(pair[0]);
  add(pair[1], pair[0]);
  while (order.length < Math.min(count, n)) {
    const s0 = order[0], chosen = new Set(order);
    let gainBest = -1, next = -1;
    for (let c = 0; c < n; c++) {
      if (chosen.has(c)) continue;
      const den = R[c * n + c] - 2 * R[c * n + s0] + R[s0 * n + s0];
      let gain = 0;
      if (den > eps) { for (let i = 0; i < n; i++) { const d = R[i * n + c] - R[i * n + s0]; gain += d * d; } gain /= den; }
      if (gain > gainBest + 1e-15) { gainBest = gain; next = c; }
    }
    add(next, s0); // next ≥ 0: gain ≥ 0 for every unchosen channel.
  }
  return order;
}

/** Seeded uniform generator (mulberry32), so random baselines are reproducible. */
export function generator(seed: number) {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function checkSummary(value: unknown, role: string): Summary {
  const s = value as Summary;
  const n = Array.isArray(s?.channels) ? s.channels.length : 0;
  if (!s || s.schema !== SUMMARY_SCHEMA || !n || !s.channels.every((c) => typeof c === 'string') || new Set(s.channels).size !== n ||
      !Array.isArray(s.covariance) || s.covariance.length !== n || !s.covariance.every((row) => Array.isArray(row) && row.length === n && row.every(finite)) ||
      !Array.isArray(s.processing?.band_hz) || s.processing.band_hz.length !== 2 || typeof s.source?.sha256 !== 'string' ||
      (s.source.recording_sha256 !== undefined && (typeof s.source.recording_sha256 !== 'string' || !/^[a-f0-9]{64}$/i.test(s.source.recording_sha256))))
    throw new Error(`${role}不是eeg-covariance-summary/1协方差摘要`);
  return s;
}

function checkPrior(value: unknown): PriorFile {
  const p = value as PriorFile, n = Array.isArray(p?.channels) ? p.channels.length : 0;
  const square = (m: unknown) => Array.isArray(m) && m.length === n && m.every((row) => Array.isArray(row) && row.length === n && row.every(finite));
  if (!p || p.schema !== PRIOR_SCHEMA || !n || typeof p.id !== 'string' || !Array.isArray(p.band_hz) || !square(p.channel_model?.data_prior) || !square(p.channel_model?.area_prior))
    throw new Error('不是eeg-data-prior/1数据先验文件');
  return p;
}

const sameBand = (a: number[], b: number[]) => a[0] === b[0] && a[1] === b[1];
const describe = (s: Summary) => ({ label: s.label ?? null, file: s.source.file, sha256: s.source.sha256,
  ...(s.source.recording_sha256 === undefined ? {} : { recording_sha256: s.source.recording_sha256 }) });

function checkRecordingSplit(training: Summary[], test: Summary[]) {
  const recordingHashes = new Set<string>();
  const entryHashes = new Set<string>();
  const legacyEntryHashes = new Set<string>();
  for (const { source } of training) {
    const entryHash = source.sha256.toLowerCase();
    entryHashes.add(entryHash);
    if (source.recording_sha256) recordingHashes.add(source.recording_sha256.toLowerCase());
    else legacyEntryHashes.add(entryHash);
  }
  for (const { source } of test) {
    const entryHash = source.sha256.toLowerCase();
    // Use the entry-file hash when only one side or neither side has the full recording hash.
    const repeated = source.recording_sha256
      ? recordingHashes.has(source.recording_sha256.toLowerCase()) || legacyEntryHashes.has(entryHash)
      : entryHashes.has(entryHash);
    if (repeated) throw new Error(`训练和检验摘要包含同一份录制：${source.file}`);
  }
}

export type SubsetOptions = { training: unknown[]; test?: unknown[]; prior?: unknown; counts?: number[]; draws?: number; seed?: number };

/** eeg-channel-subset/1: greedy subsets by data and by model, the 10-20 subset and random subsets, on training and held-out data. */
export function channelSubsets(options: SubsetOptions) {
  if (!options.training.length) throw new Error('至少需要一个训练摘要');
  const training = options.training.map((s, i) => checkSummary(s, `训练摘要${i + 1}`));
  const testInput = (options.test ?? []).map((s, i) => checkSummary(s, `检验摘要${i + 1}`));
  checkRecordingSplit(training, testInput);
  const prior = options.prior === undefined || options.prior === null ? null : checkPrior(options.prior);
  const band = training[0].processing.band_hz;
  if (![...training, ...testInput].every((s) => sameBand(s.processing.band_hz, band))) throw new Error('训练与检验摘要须使用同一频带');
  if (prior && !sameBand(prior.band_hz, band)) throw new Error('数据先验与摘要的频带不同');
  // Universe: channels in at least 90% of the training summaries (and in the prior), in order of first appearance;
  // training summaries missing one of them are left out, as in the prior fit.
  const order: string[] = [], presence = new Map<string, number>();
  for (const s of training) for (const name of s.channels) {
    if (!presence.has(name)) order.push(name);
    presence.set(name, (presence.get(name) ?? 0) + 1);
  }
  let universe = order.filter((name) => presence.get(name)! >= CHANNEL_PRESENCE * training.length);
  const outsidePrior = prior ? universe.filter((name) => !prior.channels.includes(name)) : [];
  if (prior) universe = universe.filter((name) => prior.channels.includes(name));
  if (universe.length < 4) throw new Error(`共同通道少于4个（${universe.length}个）`);
  const trainingSkipped = training.filter((s) => !universe.every((name) => s.channels.includes(name)))
    .map((s) => ({ ...describe(s), missing: universe.filter((name) => !s.channels.includes(name)) }));
  const used = training.filter((s) => universe.every((name) => s.channels.includes(name)));
  // Every channel can be in 90% of the summaries while each summary misses a different one.
  if (!used.length) throw new Error(`没有一份训练摘要包含全部${universe.length}个共同通道，请去掉缺通道较多的摘要后重试`);
  // Default sizes that do not fit the universe are dropped; requested sizes must fit.
  const counts = [...new Set(options.counts ?? DEFAULT_COUNTS.filter((k) => k < universe.length))].sort((a, b) => a - b);
  if (!counts.length || !counts.every((k) => Number.isInteger(k) && k >= 2 && k < universe.length))
    throw new Error(`通道数须为2到${universe.length - 1}之间的整数`);
  const draws = options.draws ?? RANDOM_DRAWS, seed = options.seed ?? 1;
  if (!Number.isInteger(draws) || draws < 10 || draws > 10000 || !Number.isInteger(seed) || seed < 0) throw new Error('随机子集次数或种子无效');
  const train = mean(used.map((s) => restrict(s.covariance, s.channels, universe)));
  const testSkipped = testInput.filter((s) => !universe.every((name) => s.channels.includes(name)))
    .map((s) => ({ ...describe(s), missing: universe.filter((name) => !s.channels.includes(name)) }));
  const test = testInput.filter((s) => universe.every((name) => s.channels.includes(name)));
  const tests = test.map((s) => restrict(s.covariance, s.channels, universe));
  // Errors are linear in a trace-normalized covariance, so the mean over held-out summaries is the error on their mean.
  const pooledTest = tests.length ? mean(tests) : null;
  const standard = TEN_TWENTY.filter((name) => universe.includes(name));
  // The data-greedy order also reaches the 10-20 size, so the two can be compared at equal channel counts.
  const maxCount = Math.max(counts.at(-1)!, standard.length < universe.length ? standard.length : 0);
  const evaluate = (subset: number[]) => {
    const V = reconstructor(train, subset);
    return { train_error: round(reconstructionError(train, train, subset, V)),
      test_error: tests.length ? roundStats(stats(tests.map((t) => reconstructionError(train, t, subset, V)))) : null };
  };
  const greedy = (selection: Matrix) => {
    const order = greedyOrder(selection, maxCount);
    return { order, value: { order: order.map((i) => universe[i]),
      counts: counts.map((k) => ({ count: k, channels: order.slice(0, k).map((i) => universe[i]), ...evaluate(order.slice(0, k)) })) } };
  };
  const data = greedy(train);
  const methods: Record<string, unknown> = { data: data.value };
  if (prior) {
    methods.data_prior = greedy(restrict(prior.channel_model.data_prior, prior.channels, universe)).value;
    methods.area_prior = greedy(restrict(prior.channel_model.area_prior, prior.channels, universe)).value;
  }
  const random = generator(seed);
  const randomRows = counts.map((k) => {
    const trainErrors: number[] = [], testErrors: number[] = [];
    const pool = universe.map((_, i) => i);
    for (let d = 0; d < draws; d++) {
      for (let i = 0; i < k; i++) { const j = i + Math.floor(random() * (pool.length - i)); [pool[i], pool[j]] = [pool[j], pool[i]]; }
      const subset = pool.slice(0, k), V = reconstructor(train, subset);
      trainErrors.push(reconstructionError(train, train, subset, V));
      if (pooledTest) testErrors.push(reconstructionError(train, pooledTest, subset, V));
    }
    return { count: k, train_error: roundStats(stats(trainErrors)), test_error_mean: testErrors.length ? roundStats(stats(testErrors)) : null };
  });
  return {
    schema: SUBSET_SCHEMA,
    band_hz: band,
    universe,
    channels_outside_prior: outsidePrior,
    counts,
    training: used.map(describe),
    training_skipped: trainingSkipped,
    test: test.map(describe),
    test_skipped: testSkipped,
    prior: prior ? { id: prior.id } : null,
    methods,
    standard_10_20: standard.length >= 2 ? { channels: standard, missing: TEN_TWENTY.filter((name) => !universe.includes(name)), count: standard.length,
      ...evaluate(standard.map((name) => universe.indexOf(name))),
      data_same_count: standard.length < universe.length ? { channels: data.order.slice(0, standard.length).map((i) => universe[i]), ...evaluate(data.order.slice(0, standard.length)) } : null } : null,
    random: { draws, seed, generator: 'mulberry32', counts: randomRows },
    definition: {
      error: 'unexplained variance fraction of the average-referenced universe channels; subset recorded against one of its own channels',
      reconstructor: 'linear minimum mean-square error, fitted on the pooled trace-normalized training covariance for every method',
      selection: 'greedy forward: best pair, then the channel explaining the most residual variance; methods differ only in the covariance used',
      test_error: 'per held-out summary: mean, median, P10, P90; random subsets report the distribution over draws of the mean held-out error',
    },
  };
}

const round = (v: number) => Number(v.toPrecision(6));
const roundStats = (s: Stats): Stats => ({ mean: round(s.mean), median: round(s.median), p10: round(s.p10), p90: round(s.p90) });
