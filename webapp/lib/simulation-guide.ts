/** Documentation anchors only; no simulation parameters or cache keys are changed here. */
export const SIMULATION_SECTIONS = [
  ['simulation-overview', 'overviewTitle'],
  ['simulation-forward', 'forwardTitle'],
  ['simulation-sources', 'sourcesTitle'],
  ['simulation-comparison', 'comparisonTitle'],
  ['simulation-artifacts', 'artifactsTitle'],
  ['simulation-parameters', 'parametersTitle'],
] as const;
export const SIMULATION_DETAIL_IDS = ['simulation-fem-details', 'simulation-prior-details', 'simulation-waveform-details'] as const;
export const isSimulationGuideHash = (hash: string) => hash === '#simulation-model'
  || SIMULATION_SECTIONS.some(([id]) => hash === '#' + id)
  || SIMULATION_DETAIL_IDS.some((id) => hash === '#' + id);
