import { readFileSync, writeFileSync } from 'node:fs';
import { comparisonGroup, dominates, paretoAnalysis, paretoRanks, summaryObjectives } from '../../../webapp/lib/pareto.ts';
import { channelSubsets, generator } from '../../../webapp/lib/channel-subset.ts';
import { channelSubsetFigureSvg } from '../../../webapp/lib/channel-subset-figure.ts';

const [specPath, outPath] = process.argv.slice(2);
const spec = JSON.parse(readFileSync(specPath, 'utf8'));

const prngDraws = {};
for (const seed of spec.prngSeeds) {
  const rng = generator(seed);
  prngDraws[String(seed)] = Array.from({ length: spec.prngCount }, () => rng());
}

const paretoResults = spec.paretoCases.map(tc => {
  try {
    const analysis = paretoAnalysis(tc.items, tc.objectives);
    return { ok: true, json: JSON.stringify(analysis, null, 2) };
  } catch (error) {
    return { ok: false, error: error.message };
  }
});

const groupResults = spec.groupCases.map(record => comparisonGroup(record));
const summaryObjResults = spec.summaryObjCases.map(record => JSON.stringify(summaryObjectives(record)));
const dominatesResults = spec.dominatesCases.map(([a, b, dirs]) => dominates(a, b, dirs));
const rankResults = spec.rankCases.map(([pts, dirs]) => paretoRanks(pts, dirs));

const subsetResults = spec.subsetCases.map(tc => {
  try {
    const report = channelSubsets(tc.options);
    const heldOut = report.test.length > 0;
    const standard = report.standard_10_20;
    const svg = channelSubsetFigureSvg(report, {
      title: 'Reconstruction error of channel subsets',
      subtitle: [heldOut ? 'Mean held-out error' : 'Training error', `${report.universe.length} shared channels`, `${report.band_hz[0]}–${report.band_hz[1]} Hz`].join(' · '),
      xLabel: 'Channels in the subset',
      yLabel: 'Unexplained variance (lower is better)',
      names: {
        data: 'Greedy on the data',
        data_prior: 'Greedy on the data-prior model',
        area_prior: 'Greedy on the area-prior model',
        random: 'Random subsets, median and P10–P90',
        standard: standard ? `10-20 system (${standard.count})` : '',
      },
      channels: count => `${count} channels`,
      caption: [
        'Error is the unexplained variance fraction of the average-referenced shared channels. Each subset is recorded against one of its own channels; the reconstructor is fitted on the training summaries.',
        heldOut
          ? "Curves are the mean held-out error; the band is the P10–P90 of the random subsets' mean held-out error over draws. The data-greedy curve includes the size of the 10-20 subset."
          : "Without held-out summaries the curves are training errors, optimistic for greedy selection on the data; the band is the P10–P90 of the random subsets' training error.",
      ],
    });
    return { ok: true, json: JSON.stringify(report, null, 2), svg };
  } catch (error) {
    return { ok: false, error: error.message };
  }
});

writeFileSync(outPath, JSON.stringify({
  prngDraws,
  paretoResults,
  groupResults,
  summaryObjResults,
  dominatesResults,
  rankResults,
  subsetResults,
}));
