'use client';
/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
import { useEffect, useState, type ReactNode } from 'react';
import { useLanguage } from '@/components/language-provider';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import copy from '@/lib/i18n/simulation-catalog.json';
import { SIMULATION_SECTIONS, type SIMULATION_DETAIL_IDS } from '@/lib/simulation-guide';

type CopyKey = keyof typeof copy;
const linkClass = 'rounded-sm text-primary underline underline-offset-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary';

function ModelFormula({ label, children }: { label: string; children: ReactNode }) {
  return <figure aria-label={label} className="overflow-x-auto rounded-xl border bg-secondary/50 px-4 py-3 text-base leading-8 text-foreground">{children}</figure>;
}

function ModelSection({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return <section id={id} aria-labelledby={id + '-title'} className="scroll-mt-40 space-y-4 border-t pt-8">
    <h3 id={id + '-title'} className="text-xl font-semibold text-foreground">{title}</h3>
    {children}
  </section>;
}

function ModelDetails({ id, title, children }: { id: typeof SIMULATION_DETAIL_IDS[number]; title: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const reveal = () => { if (window.location.hash === '#' + id) setOpen(true); };
    reveal();
    window.addEventListener('hashchange', reveal);
    return () => window.removeEventListener('hashchange', reveal);
  }, [id]);
  return <details id={id} open={open} onToggle={(event) => setOpen(event.currentTarget.open)} className="scroll-mt-40 rounded-xl border bg-secondary/20 p-4 sm:p-5">
    <summary className="cursor-pointer rounded-sm font-semibold text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary">{title}</summary>
    <div className="mt-5 space-y-4">{children}</div>
  </details>;
}

function ModelTable({ label, headers, rows }: { label: string; headers: [string, string]; rows: [string, string][] }) {
  return <div className="min-w-0 rounded-xl border p-2 sm:p-3"><Table aria-label={label} className="text-sm sm:text-base">
    <TableHeader><TableRow>{headers.map((title) => <TableHead scope="col" className="whitespace-normal py-3" key={title}>{title}</TableHead>)}</TableRow></TableHeader>
    <TableBody>{rows.map(([label, description]) => <TableRow key={label}>
      <TableHead scope="row" className="h-auto w-1/3 whitespace-normal py-3 align-top leading-7">{label}</TableHead>
      <TableCell className="whitespace-normal py-3 align-top leading-7">{description}</TableCell>
    </TableRow>)}</TableBody>
  </Table></div>;
}

export function SimulationExplainer() {
  const { tx } = useLanguage();
  const text = (key: CopyKey) => tx(copy[key].source);
  return <article id="simulation-model" aria-labelledby="simulation-model-title" className="min-w-0 scroll-mt-40 space-y-8 rounded-2xl border bg-card p-5 text-base leading-8 text-muted-foreground sm:p-8">
    <header className="space-y-4">
      <p className="text-sm font-semibold text-primary">{text('kicker')}</p>
      <h2 id="simulation-model-title" className="text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">{text('title')}</h2>
      <p>{text('intro')}</p>
    </header>
    <nav aria-label={text('contentsLabel')} className="grid gap-x-6 gap-y-3 rounded-xl bg-secondary/50 p-4 text-sm sm:grid-cols-2">
      {SIMULATION_SECTIONS.map(([id, title]) => <a key={id} className={linkClass} href={'#' + id}>{text(title)}</a>)}
    </nav>

    <ModelSection id="simulation-overview" title={text('overviewTitle')}>
      <ModelFormula label={text('observationFormula')}>
        y(t) = Hj(t) + ε(t)<br />
        y<sub>i</sub>(t) = ∑<sub>q=1</sub><sup>Q</sup> H<sub>iq</sub>j<sub>q</sub>(t) + ε<sub>i</sub>(t)
      </ModelFormula>
      <dl className="grid gap-5 sm:grid-cols-2">
        {(['source', 'forward', 'noise', 'signal'] as const).map((key) => <div key={key}>
          <dt className="font-semibold text-foreground">{text(`${key}Label`)}</dt>
          <dd className="mt-1">{text(`${key}Definition`)}</dd>
        </div>)}
      </dl>
      <p>{text('dimensions')}</p>
    </ModelSection>

    <ModelSection id="simulation-forward" title={text('forwardTitle')}>
      <ol className="list-decimal space-y-2 pl-6">
        {(['headStep', 'conductivityStep', 'geometryStep', 'femStep'] as const).map((key) => <li key={key}>{text(key)}</li>)}
      </ol>
      <p>{text('layoutRows')}</p>
      <p>{text('attenuation')}</p>
      <ModelDetails id="simulation-fem-details" title={text('femDetails')}>
        <ModelFormula label={text('pdeLabel')}>∇ · [σ(r)∇φ(r)] = ∇ · J<sub>p</sub>(r)</ModelFormula>
        <p>{text('pdeExplanation')}</p>
        <p>{text('reciprocitySteps')}</p>
        <ModelFormula label={text('reciprocityLabel')}>
          H<sub>iq</sub> = −n<sub>q</sub><sup>T</sup>E<sub>i</sub>(r<sub>q</sub>) / I<br />
          [H] = V/(A·m)；[j] = A·m；[Hj] = V
        </ModelFormula>
        <p>{text('referenceRecovery')}</p>
        <p className="text-sm">{text('implementationLabel')}<br /><code className="break-all">src/compact_eeg/cortical_fem.py · FixedMeshLeadfield.evaluate</code></p>
        <a className={linkClass} href="https://simnibs.github.io/simnibs/build/html/tutorial/advanced/eeg_leadfields.html">{text('officialReference')}</a>
      </ModelDetails>
    </ModelSection>

    <ModelSection id="simulation-sources" title={text('sourcesTitle')}>
      <ModelTable label={text('sourceUseTable')} headers={[text('calculationHeader'), text('sourceUseHeader')]} rows={[
        [tx('信号重建保留率'), text('fieldUse')],
        [tx('幅度保留率（最差10%）'), text('sensitivityUse')],
        [tx('相对定位评分'), text('localizationUse')],
        [tx('信号仿真'), text('waveformUse')],
      ]} />
      <p className="rounded-xl border border-primary/20 bg-primary/5 p-4 font-medium text-foreground">{text('distinction')}</p>
      <ModelDetails id="simulation-prior-details" title={text('priorDetails')}>
        <p>{text('sourceSampling')}</p>
        <ModelFormula label={text('covarianceLabel')}>
          E[j] = 0；C<sub>j</sub> = a² diag(w₁, …, w<sub>Q</sub>)；∑<sub>q</sub> w<sub>q</sub> = 1<br />
          C<sub>yy</sub> = HC<sub>j</sub>H<sup>T</sup> + C<sub>ε</sub>
        </ModelFormula>
        <p>{text('priorExplanation')}</p>
        <p>{text('priorScope')}</p>
        <p className="text-sm">{text('implementationLabel')}<br /><code className="break-all">scripts/prepare_ernie_cortical_inputs.py</code><br /><code className="break-all">src/compact_eeg/layout_search_metrics.py · LayoutSearchMetrics</code></p>
      </ModelDetails>
      <ModelDetails id="simulation-waveform-details" title={text('waveformDetails')}>
        <p>{text('selectionExplanation')}</p>
        <ModelFormula label={text('waveformLabel')}>
          s<sub>q</sub>(t) = 0.65 b₀(t) + 0.50 b<sub>q</sub>(t) + 0.30 sin(2πf<sub>q</sub>t + φ<sub>q</sub>)<br />
          j<sub>q</sub>(t) = a √w̃<sub>q</sub> · UnitRMS[g(t)s<sub>q</sub>(t)]
        </ModelFormula>
        <p>{text('waveformComponents')}</p>
        <p>{text('envelopeExplanation')}</p>
        <ModelFormula label={text('waveformLabel')}>
          g(t) = 0.12 + ∑<sub>c ∈ {'{2.5, 7, 12, 17}'} s</sub> exp[−0.5 ((t − c) / (0.65 s))²]<br />
          a = 10 nA·m；∑<sub>q</sub> w̃<sub>q</sub> = 1；√(∑<sub>q</sub> mean<sub>t</sub> j<sub>q</sub>(t)²) = a
        </ModelFormula>
        <p>{text('amplitudeExplanation')}</p>
        <p className="text-sm">{text('implementationLabel')}<br /><code className="break-all">src/compact_eeg/workflows/source_reception.py · generate_latents / fit_decoders</code><br /><code className="break-all">src/compact_eeg/workflows/source_reception_v2.py · _single_source_result</code></p>
      </ModelDetails>
    </ModelSection>

    <ModelSection id="simulation-comparison" title={text('comparisonTitle')}>
      <ModelFormula label={text('comparisonFormula')}>
        y<sub>B</sub>(t) = H<sub>B</sub>j(t) + ε<sub>B</sub>(t)；y<sub>X</sub>(t) = H<sub>X</sub>j(t) + ε<sub>X</sub>(t)<br />
        z<sub>B</sub>(t) = H<sub>B</sub>j(t)
      </ModelFormula>
      <p>{text('comparisonConditions')}</p>
      <p>{text('referenceExplanation')}</p>
      <p>{text('targetExplanation')}</p>
      <a className={linkClass} href="#retention-guide">{text('metricsLink')}</a>
    </ModelSection>

    <ModelSection id="simulation-artifacts" title={text('artifactsTitle')}>
      <ModelFormula label={text('artifactsFormula')}>y(t) = Hj(t) + a<sub>ECG</sub>(t) + a<sub>EOG</sub>(t) + ε(t)</ModelFormula>
      <p>{text('artifactExplanation')}</p>
      <p>{text('artifactCalibration')}</p>
      <a className={linkClass} href="#source-field-interaction">{text('interactionLink')}</a>
    </ModelSection>

    <ModelSection id="simulation-parameters" title={text('parametersTitle')}>
      <p>{text('parametersScope')}</p>
      <ModelTable label={text('parametersTitle')} headers={[text('parameterHeader'), text('settingHeader')]} rows={
        (['head', 'sources', 'bank', 'evaluation', 'sampling'] as const).map((key) => [text(`${key}Parameter`), text(`${key}Value`)])
      } />
      <a className={linkClass} href="#simulation-model">{text('backLink')}</a>
    </ModelSection>
  </article>;
}
