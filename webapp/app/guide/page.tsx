'use client';
/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
import { useEffect, useState } from 'react';
import { SiteHeader } from '@/components/site-header';
import { MethodBackLink } from '@/components/method-context';
import { DocumentationLink } from '@/components/documentation-navigation';
import { useLanguage } from '@/components/language-provider';
import { parseAR } from '@/lib/lab-workflow';
import { USAGE_EXPLANATIONS } from '@/lib/usage-guide';

const STEPS = [
  { id: 'usage-purpose', title: '1. 这个 App 能做什么？', paragraphs: [], action: '开始查看已有结果', path: '/', section: 'simulation-overview', note: '比较电极集中到少数区域后，相对标准全头64导的采集表现。先查看已有结果，再设计布局；已有数据可直接读取，新布局按需计算。' },
  { id: 'usage-compare', title: '2. 查看已有方案', paragraphs: [0], action: '查看已有结果', path: '/', section: 'retention-reading', note: '选中方案后查看三维点位、实际面积和各项指标。比较前先核对实验协议、面积或半径约束，以及电极总数。' },
  { id: 'usage-design', title: '3. 设置并计算布局', paragraphs: [2, 4], action: '打开布局设计', path: '/design', section: 'local-compute', note: '依次选择允许布置范围、区域数量和每区半径上限，再点击计算。修改布局参数后，先读取匹配缓存；没有匹配记录时再运行新计算。尚未生成完整布局时，扩大半径或调整区域后重试。' },
  { id: 'usage-electrodes', title: '4. 调整具体电极', paragraphs: [1], action: '打开电极编辑', path: '/electrodes', section: 'electrode-editor', note: '先选择符合编辑条件的已保存布局，再启用编辑模式。移动或删除电极后重新评价，原布局与编辑结果分别保存。' },
  { id: 'usage-reception', title: '5. 对照模拟接收信号', paragraphs: [5], action: '打开信号仿真', path: '/reception', section: 'source-field-interaction', note: '先选完整64点布局，再选择单源或多源、波形与干扰强度。比较同一场景下的标准64导、当前布局接收信号和重建结果。没有选择布局时，先完成布局选择；编辑后的减导记录不进入此实验。' },
  { id: 'usage-reading', title: '6. 读懂并比较结果', paragraphs: [3], action: '打开方案对比', path: '/decision', section: 'retention-guide', note: '先看场重建保留率：全头信号能还原到什么程度；再看最差10%源的幅度保留率：哪些源接收薄弱；最后看定位效用及毫米误差：能否分辨信号来源。' },
  { id: 'usage-records', title: '7. 保存、缓存与导出', paragraphs: [6], action: '打开计算记录', path: '/library', section: 'design-decision', note: '计算记录用于找回布局、参数与结果。方案对比支持报告、JSON和坐标CSV导出；实验包保留复现信息。修改最低保留要求只更新判断，不重新生成布局或信号。' },
] as const;

export default function GuidePage() {
  const { tx } = useLanguage();
  const [ar, setAR] = useState(90);
  useEffect(() => {
    const restore = () => setAR(parseAR(new URLSearchParams(window.location.search).get('ar')));
    restore(); window.addEventListener('popstate', restore);
    return () => window.removeEventListener('popstate', restore);
  }, []);
  return <main className="min-h-screen bg-background text-foreground">
    <SiteHeader current="guide" />
    <section className="border-b border-border bg-[linear-gradient(120deg,#edf7f3_0%,#faf7ee_60%,#f4f7f4_100%)]">
      <div className="mx-auto max-w-5xl px-4 py-10 sm:px-6 lg:px-8">
        <MethodBackLink />
        <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">{tx('使用指南')}</h1>
        <p className="mt-4 text-base leading-7 text-muted-foreground">{tx('从结果库查看已有实验；在布局设计中设置区域、编辑电极或导入坐标；在信号仿真中比较接收波形。使用指南与建模原理分别阅读。')}</p>
        
      </div>
    </section>
    <div className="mx-auto max-w-5xl space-y-7 px-4 py-8 sm:px-6 lg:px-8">
      <nav aria-label={tx('使用指南目录')} className="grid gap-3 rounded-xl border bg-white p-5 text-base sm:grid-cols-2">
        {STEPS.map((step) => <a key={step.id} href={'#' + step.id} className="text-primary underline underline-offset-4">{tx(step.title)}</a>)}
      </nav>
      {STEPS.map((step) => <section key={step.id} id={step.id} aria-labelledby={step.id + '-title'} className="lab-panel scroll-mt-40 space-y-4">
        <h2 id={step.id + '-title'} className="text-xl font-semibold">{tx(step.title)}</h2>
        <p className="text-base leading-8">{tx(step.note)}</p>
        {step.id === 'usage-design' && <p className="text-base leading-8">{tx('已有电极坐标时，可直接进入坐标导入，上传CSV或JSON并评价；不必先运行区域布局搜索。')} <a href={'/coordinates?ar=' + ar} className="text-primary underline">{tx('坐标导入')}</a></p>}
        {step.paragraphs.map((index) => <p key={index} className="text-base leading-8 text-muted-foreground">{tx(USAGE_EXPLANATIONS[index][1])}</p>)}
        <div className="flex flex-wrap items-center gap-x-6 gap-y-3 border-t pt-4 text-base">
          <a href={step.path + '?ar=' + ar} className="font-semibold text-primary underline underline-offset-4">{tx(step.action)}</a>
          <DocumentationLink target="method" section={step.section} className="text-primary underline underline-offset-4">{tx('查看对应计算原理')}</DocumentationLink>
        </div>
      </section>)}
    </div>
  </main>;
}
