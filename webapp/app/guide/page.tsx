'use client';
/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
import { useEffect, useState } from 'react';
import { SiteHeader } from '@/components/site-header';
import { MethodBackLink } from '@/components/method-context';
import { DocumentationLink } from '@/components/documentation-navigation';
import { useLanguage } from '@/components/language-provider';
import { parseAR } from '@/lib/lab-workflow';
import { SHOWCASE } from '@/lib/showcase';
import { USAGE_EXPLANATIONS } from '@/lib/usage-guide';

// One step per area of the interface; each opens its page and the matching method chapter.
const STEPS = [
  { id: 'usage-purpose', paragraph: 0, action: '打开工作区', path: '/', section: 'simulation-overview', note: '比较电极集中到少数区域后，相对标准全头64导的采集表现。界面分五个板块，顶栏从左到右依次排列。' },
  { id: 'usage-compare', paragraph: 1, action: '打开总面积研究', path: '/findings', section: 'retention-reading', note: '先看已发表的结果：相同面积上限下，区域越少，保留的信号越少吗？比较前先核对实验协议、面积或半径约束，以及电极总数。' },
  { id: 'usage-design', paragraph: 2, action: '打开区域设计', path: '/design', section: 'local-compute', note: '依次选择允许布置范围、区域数量和每区半径上限，再点击计算；已有电极坐标时，直接进入坐标导入。尚未生成完整布局时，扩大半径或调整区域后重试。' },
  { id: 'usage-electrodes', paragraph: 3, action: '打开布局列表', path: '/library', section: 'design-decision', note: '布局列表每个布局一行；“查看布局”打开详情页，从那里发起评价、对比、研究、信号仿真、编辑和导出。' },
  { id: 'usage-reading', paragraph: 4, action: '打开方案对比', path: '/decision', section: 'retention-guide', note: '方案对比先选布局，再选评价条件；结论栏先说明两个布局是否达到要求以及相差多少，详细指标在下方。' },
  { id: 'usage-reception', paragraph: 5, action: '打开信号仿真', path: '/reception', section: 'source-field-interaction', note: '比较同一场景下的标准64导、当前布局接收信号和重建结果。编辑后的减导记录不进入此实验。' },
  { id: 'usage-records', paragraph: 6, action: '打开研究项目', path: '/projects', section: 'retention-ar', note: '研究项目把多个布局、对比和交付包放在一起，便于导出和交给合作者。方案对比支持报告、JSON和坐标CSV导出。' },
] as const;

export default function GuidePage() {
  const { tx } = useLanguage();
  const [ar, setAR] = useState(90);
  useEffect(() => {
    const restore = () => setAR(parseAR(new URLSearchParams(window.location.search).get('ar')));
    restore(); window.addEventListener('popstate', restore);
    return () => window.removeEventListener('popstate', restore);
  }, []);
  // The showcase has no workspace, projects or computation: those steps open the findings instead.
  const href = (path: string) => (SHOWCASE && ['/', '/projects', '/design', '/reception'].includes(path) ? '/findings' : path) + '?ar=' + ar;
  return <main className="lab-page">
    <SiteHeader current="guide" />
    <div className="lab-container max-w-5xl space-y-7 py-6">
      <header>
        <MethodBackLink />
        <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">{tx('使用指南')}</h1>
        <p className="mt-4 text-base leading-7 text-muted-foreground">{tx('工作区汇总最近的工作；布局板块新建和查找布局；分析板块提出问题；研究结果是已发表的实验；文档包括本指南与建模原理。')}</p>
      </header>
      <nav aria-label={tx('使用指南目录')} className="grid gap-3 rounded-xl border bg-card p-5 text-base sm:grid-cols-2">
        {STEPS.map(step => <a key={step.id} href={'#' + step.id} className="text-primary underline underline-offset-4">{tx(USAGE_EXPLANATIONS[step.paragraph][0])}</a>)}
      </nav>
      {STEPS.map(step => <section key={step.id} id={step.id} aria-labelledby={step.id + '-title'} className="lab-panel scroll-mt-40 space-y-4">
        <h2 id={step.id + '-title'} className="text-xl font-semibold">{tx(USAGE_EXPLANATIONS[step.paragraph][0])}</h2>
        <p className="text-base leading-8">{tx(step.note)}</p>
        <p className="text-base leading-8 text-muted-foreground">{tx(USAGE_EXPLANATIONS[step.paragraph][1])}</p>
        <div className="flex flex-wrap items-center gap-x-6 gap-y-3 border-t pt-4 text-base">
          <a href={href(step.path)} className="font-semibold text-primary underline underline-offset-4">{tx(step.action)}</a>
          {step.id === 'usage-design' && <a href={'/coordinates?ar=' + ar} className="text-primary underline underline-offset-4">{tx('坐标导入')}</a>}
          <DocumentationLink target="method" section={step.section} className="text-primary underline underline-offset-4">{tx('查看对应计算原理')}</DocumentationLink>
        </div>
      </section>)}
    </div>
  </main>;
}
