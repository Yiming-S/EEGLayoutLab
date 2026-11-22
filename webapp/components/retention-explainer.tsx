'use client';
import { useLanguage } from '@/components/language-provider';
/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
import type { ReactNode } from 'react';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { RETENTION_EXAMPLE as example, RETENTION_SECTIONS, guidePercent as pct } from '@/lib/retention-guide';
import simulationCopy from '@/lib/i18n/simulation-catalog.json';

function Formula({ children, label }: { children: ReactNode; label: string }) {
  const { tx } = useLanguage();
  return <figure aria-label={tx(label)} className="my-4 overflow-x-auto rounded-xl border bg-secondary/50 px-4 py-3 text-base leading-8 text-foreground">
    {children}
  </figure>;
}

function GuideSection({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  const { tx } = useLanguage();
  return <section id={id} aria-labelledby={id + '-title'} className="scroll-mt-24 border-t pt-8">
    <h3 id={id + '-title'} className="mb-5 text-xl font-semibold text-foreground">{tx(title)}</h3>
    <div className="space-y-4 text-base leading-8 text-muted-foreground [&_strong]:font-semibold [&_strong]:text-foreground [&_h4]:font-semibold [&_h4]:text-foreground [&_ul]:list-disc [&_ul]:space-y-1 [&_ul]:pl-6 [&_ol]:list-decimal [&_ol]:space-y-2 [&_ol]:pl-6">{children}</div>
  </section>;
}

function GuideTable({ headers, rows, label }: { headers: string[]; rows: ReactNode[][]; label: string }) {
  const { tx } = useLanguage();
  return <div className="rounded-xl border bg-card p-2 sm:p-3">
    <Table aria-label={tx(label)} className="text-sm sm:text-base">
      <TableHeader><TableRow>{tx(headers.map((h) => <TableHead scope="col" className="whitespace-normal py-3" key={h}>{tx(h)}</TableHead>))}</TableRow></TableHeader>
      <TableBody>{tx(rows.map((row, i) => <TableRow key={i}>{tx(row.map((cell, j) => j === 0
        ? <TableHead scope="row" className="h-auto whitespace-normal py-3 leading-7" key={j}>{tx(cell)}</TableHead>
        : <TableCell className="whitespace-normal py-3 leading-7" key={j}>{tx(cell)}</TableCell>))}</TableRow>))}</TableBody>
    </Table>
  </div>;
}

export function RetentionExplainer() {
  const { tx } = useLanguage();
  return <article id="retention-guide" aria-labelledby="retention-guide-title" className="scroll-mt-24 space-y-8 rounded-2xl border bg-card p-5 sm:p-8">
    <header className="space-y-4">
      <p className="text-sm font-semibold text-primary">{tx("指标说明 · 完整版")}</p>
      <h2 id="retention-guide-title" className="text-2xl font-semibold tracking-tight sm:text-3xl">{tx("如何理解相对标准64导的三项指标？")}</h2>
      <p className="text-base leading-8 text-muted-foreground">{tx("保持64个测量电极不变，将它们集中到少数头表面区域后，相比标准全头64导布局，还能保留多少信号重建、脑源敏感度和源定位能力？")}</p>
      <p className="text-base leading-8"><strong>{tx("三项相对指标分别衡量信号重建、幅度和定位表现，按各自定义解读。")}</strong></p>
    </header>
    <GuideTable label={tx("三项相对指标分别回答的问题")} headers={['指标', '回答的问题']} rows={[
      ['信号重建保留率', '能否利用当前布局的观测，恢复标准64导本应记录的脑电信号？'],
      ['幅度保留率（最差10%）', '对相对损失最严重的那部分脑源，还能记录到多大的电位差？'],
      ['相对定位评分', '源定位误差经规定规则评分后，相比标准64导表现如何？'],
    ]} />
    <p className="text-base leading-8 text-muted-foreground">{tx("标准64导是本实验的比较基准。其相对指标归一化为100%；")}<strong className="text-foreground">{tx("自身的噪声、重建误差和定位误差仍按绝对数值报告。")}</strong></p>
    <aside aria-label={tx("固定示例 · 独立于当前配置")} className="rounded-xl border border-warning/40 bg-warning-surface p-4 text-warning">
      <h3 className="font-semibold">{tx("固定示例 · 独立于当前配置")}</h3>
      <p className="mt-2 text-base leading-7">{tx("下文数值来自")}{tx(example.date)}{tx("保存的双侧耳后邻近区布局：每侧32点，每区半径上限25 mm，最小电极直线间距4 mm。示例数值固定，当前设计结果请在布局设计或计算记录中查看。")}</p>
      <p className="mt-2 text-sm leading-6">{tx("示例采用")}{tx(example.algorithm)}{tx("、单Ernie头模和标准64导标定的名义SNR＝20 dB条件。其他实验协议、信号仿真场景的结果应按各自记录解释。")}</p>
      <a className="mt-3 inline-block text-sm font-semibold underline underline-offset-4" href="/data/retention-example.json" download>{tx("下载固定示例的数值摘录 →")}</a>
    </aside>
    <nav aria-label={tx("保留率说明目录")} className="rounded-xl bg-secondary/50 p-4">
      <p className="mb-3 text-sm font-semibold">{tx("按问题阅读")}</p>
      <ol className="grid gap-x-6 gap-y-3 sm:grid-cols-2">{tx(RETENTION_SECTIONS.map(([id, name]) => <li key={id}><a className="text-sm font-medium text-primary underline decoration-primary/30 underline-offset-4 hover:decoration-primary" href={'#' + id}>{tx(name)}</a></li>))}</ol>
    </nav>

    <GuideSection id="retention-comparison" title={tx("一、两套布局如何进行比较？")}>
      <h4>{tx(simulationCopy.comparisonHeading.source)}</h4>
      <p>{tx(simulationCopy.comparisonCounts.source)}</p>
      <h4>{tx("使用同一个脑源模型")}</h4>
      <Formula label={tx("当前布局的含噪观测 yX 等于 HX 乘脑源 j 加噪声；目标 z64 等于 H64 乘同一脑源 j")}>
        y<sub>X</sub> = H<sub>X</sub>j + ε<sub>X</sub>；z<sub>64</sub> = H<sub>64</sub>j
      </Formula>
      <p>{tx(simulationCopy.comparisonSummary.source)}</p>
      <a className="text-primary underline underline-offset-4" href="#simulation-model">{tx(simulationCopy.modelLink.source)}</a>
      <p>{tx("上述信号均在参考无关空间中比较。同一个脑源在不同电极位置产生不同电位分布，因此")}<strong>{tx("空间信息取决于电极数量和位置分布。")}</strong></p>
      <h4>{tx("使用相同的物理噪声尺度")}</h4>
      <p>{tx("半径约束设计页采用按标准64导标定的名义SNR＝20 dB条件，把同一独立高斯噪声强度用于候选布局；定位的具体噪声实现随布局独立生成。")}</p>
      <p><strong>{tx("各布局使用相同物理噪声强度，实际信噪比随接收到的脑信号强度变化。")}</strong></p>
    </GuideSection>

    <GuideSection id="retention-field" title={tx("二、信号重建保留率：能恢复多少全头信号？")}>
      <p>{tx("这是与“采集效果是否接近标准全头64导”最直接对应的指标：")}<strong>{tx("只使用当前布局的观测，能够把标准64导位置上的脑电场恢复到什么程度？")}</strong></p>
      <h4>{tx("计算方法")}</h4>
      <ol>
        <li>{tx("同一个模拟脑源，在标准64导和当前布局上产生不同电位。")}</li>
        <li>{tx("两套观测加入相同物理强度的噪声。")}</li>
        <li>{tx("分别通过各自的最优线性估计器，重建同一个无噪声标准64导目标场。")}</li>
      </ol>
      <p>{tx("估计器在给定源协方差与噪声模型下，使线性重建的期望均方误差最小。")}</p>
      <Formula label={tx("重建解释率 EX 等于1减去重建均方误差除以无噪声目标场的总期望能量")}>
        E<sub>X</sub> = 1 − E[‖z<sub>64</sub> − ẑ<sub>64</sub>(y<sub>X</sub>)‖<sup>2</sup>] / E[‖z<sub>64</sub>‖<sup>2</sup>]
      </Formula>
      <p>{tx("分子是重建均方误差，分母是目标场的总期望能量。重建误差越小，重建解释率越高；式中的E[·]表示期望，E")}<sub>X</sub>{tx("表示该布局的重建解释率评分。")}</p>
      <p>{tx("半径约束设计页根据源先验、前向模型和噪声协方差，解析计算期望重建误差。")}</p>
      <h4>{tx("为什么还要除以标准64导的结果？")}</h4>
      <p>{tx("标准64导自身的含噪观测也存在重建误差。两套布局的解释率之比衡量相对重建表现。")}</p>
      <Formula label={tx("信号重建保留率 Rfield 等于当前布局重建解释率 EX 除以标准64导重建解释率 E64")}>R<sub>field</sub> = E<sub>X</sub> / E<sub>64</sub></Formula>
      <GuideTable label={tx("固定示例的绝对重建解释率")} headers={['用什么观测进行重建', '重建解释率']} rows={[
        ['标准全头64导自身的含噪观测', pct(example.referenceFieldAbsolute)],
        ['示例双耳后邻近布局的含噪观测', pct(example.fieldAbsolute)],
      ]} />
      <Formula label={tx("固定示例：56.76%除以99.31%约为57.15%")}>{tx("示例：")}{tx(pct(example.fieldAbsolute))} / {tx(pct(example.referenceFieldAbsolute))} ≈ <strong>{tx(pct(example.fieldRelative))}</strong></Formula>
      <p>{tx("在当前源先验、噪声和线性重建方法下，示例耳后邻近布局的重建解释率约为标准64导的")}{tx(pct(example.fieldRelative))}。</p>
      <p>{tx("这一比值衡量重建解释率。电位幅度、波形相关性、脑区分布和任务分类表现属于其他评价维度。")}</p>
    </GuideSection>

    <GuideSection id="retention-sensitivity" title={tx("三、幅度保留率（最差10%）：哪些脑源的信息损失最严重？")}>
      <p>{tx("一部分脑源表现较好，会使整体重建指标较高，同时另一部分脑源仍存在较大的损失。幅度保留率（最差10%）专门检查后者。")}</p>
      <h4>{tx("计算方法")}</h4>
      <p>{tx("对于同一个脑源q，计算布局能够产生的最大电极间电位差；它也等于所有双极组合中最大的电位差幅度。")}</p>
      <Formula label={tx("源q的最大双极幅度 AX 等于最大电位减最小电位；逐源比值 rq 等于 AX 除以标准64导幅度 A64")}>
        A<sub>X</sub>(q) = max<sub>i</sub> φ<sub>i</sub>(q) − min<sub>i</sub> φ<sub>i</sub>(q)<br />
        r<sub>q</sub> = A<sub>X</sub>(q) / A<sub>64</sub>(q)
      </Formula>
      <p>{tx("程序按r")}<sub>q</sub>{tx("从小到大排序，取")}<strong>{tx("相对表现最差、合计占10%皮层面积权重的脑源")}</strong>{tx("，计算面积加权平均值。")}</p>
      <Formula label={tx("幅度保留率（最差10%）是逐源幅度比按皮层面积加权的最低10%下尾平均")}>R<sub>sens</sub> = LCVaR<sub>10%,w</sub>(r<sub>q</sub>)</Formula>
      <p>{tx("LCVaR表示“下尾平均”。边界处按所需的部分权重计入，使所取皮层面积权重恰好为10%。")}</p>
      <h4>{tx("哪些源进入最差10%？")}</h4>
      <p>{tx("它指相比标准64导，当前布局对这些脑源的接收敏感度较弱。示例值")}<strong>{tx(pct(example.sensitivity))}</strong>{tx("表示：对相对表现最差的那部分模拟脑源，该布局的最大双极电位幅度，平均约为标准64导的12.50%。")}</p>
      <p>{tx("该指标是尾部源的幅度比均值。尾部内各源仍有差异，单个源的值可以低于均值；全体源表现需结合逐源结果查看。")}</p>
      <p>{tx("信号重建57.15%与敏感度12.50%并不矛盾：前者衡量整体期望重建误差，后者检查相对损失最大的尾部脑源。")}</p>
      <details className="rounded-lg border p-4 text-sm leading-7"><summary className="cursor-pointer font-semibold text-foreground">{tx("数值边界：标准64导对某个源的幅度接近零时")}</summary><p className="mt-3">{tx("实现以数值容差排除接近零的分母，并重新归一化有效源面积权重；排除面积超过0.1%时，指标无法计算。本固定示例未排除任何源。该容差属于本实验的数值处理规则。")}</p></details>
    </GuideSection>

    <GuideSection id="retention-localization" title={tx("四、相对定位评分：定位误差如何转换成相对指标？")}>
      <p><strong>{tx("半径约束设计页通过离散源定位仿真计算误差，再换算为相对评分。")}</strong></p>
      <h4>{tx("先计算模拟定位误差")}</h4>
      <p>{tx("本页示例使用256个离开反演字典网格的生成源，每个源16次噪声重复，采用4,096点固定法向反演字典。两套布局使用相同的定位算法与物理噪声标定规则。")}</p>
      <Formula label={tx("定位误差d为估计位置与真实生成位置之间的三维距离，单位毫米")}>{tx("d = ‖r̂ − r‖，单位mm")}</Formula>
      <p>{tx("重复次数表示同一头模中不同源与噪声的模拟次数。")}</p>
      <h4>{tx("把误差转换为效用评分")}</h4>
      <Formula label={tx("单次定位评分u等于0与1减去误差除以50毫米两者中的较大值")}>u(d) = max(0, 1 − d / (50 mm))</Formula>
      <GuideTable label={tx("50毫米定位误差评分的含义")} headers={['定位误差', '效用评分']} rows={[
        ['0 mm', '1.0'], ['10 mm', '0.8'], ['25 mm', '0.5'], ['≥50 mm', '0'],
      ]} />
      <p>{tx("50 mm是本实验规定的评分尺度。改变这个尺度会改变评分。")}</p>
      <h4>{tx("计算下尾评分并与标准64导比较")}</h4>
      <ol>
        <li>{tx("每个脑源先对16次噪声的效用评分求平均。")}</li>
        <li>{tx("对每套布局分别取表现最差10%源面积权重的平均评分。")}</li>
        <li>{tx("当前布局评分除以标准64导评分。")}</li>
      </ol>
      <Formula label={tx("相对定位评分等于当前布局下尾效用UX除以标准64导下尾效用U64")}>R<sub>loc</sub> = U<sub>X</sub> / U<sub>64</sub></Formula>
      <p><strong>{tx("两套布局的最差10%不一定包含同一组脑源。")}</strong></p>
      <Formula label={tx("固定示例：0.09663除以0.52111约为18.54%")}>{tx("示例：")}{tx(example.utility.toFixed(5))} / {tx(example.referenceUtility.toFixed(5))} ≈ <strong>{tx(pct(example.localizationRelative))}</strong></Formula>
      <p>{tx("它表示按当前误差评分函数和下尾聚合规则，示例布局的定位评分约为标准64导的18.54%，即相对定位评分为18.54%。更直观的毫米误差如下。")}</p>
      <GuideTable label={tx("固定示例与标准64导的绝对定位误差")} headers={['定位误差', '标准64导', '示例耳后邻近布局']} rows={[
        ['中位数', `${example.referenceMedianMm.toFixed(2)} mm`, `${example.medianMm.toFixed(2)} mm`],
        ['90分位数', `${example.referenceP90Mm.toFixed(2)} mm`, `${example.p90Mm.toFixed(2)} mm`],
      ]} />
      <p>{tx("90分位数表示约90%的模拟试验误差不超过该数值。此处误差分位数按模拟试验汇总，下尾评分另按皮层面积加权。")}</p>
      <p>{tx("相对评分比较经过换算后的定位表现；毫米误差直接描述空间偏差，两者同时报告。")}</p>
    </GuideSection>

    <GuideSection id="retention-ar" title={tx("五、最低值G和接受阈值AR如何使用？")}>
      <p>{tx("AR是用户设定的相对性能接受阈值。界面显示90%时，公式中对应0.90。当前设计页要求三项指标分别达到AR。")}</p>
      <Formula label={tx("通过当且仅当信号重建、幅度保留率（最差10%）、相对定位评分三项都不低于AR")}>
        {tx("Pass(X; AR) = 1[R")}<sub>field</sub> {tx(" ≥ AR ∧ R")}<sub>sens</sub> {tx(" ≥ AR ∧ R")}<sub>loc</sub> {tx(" ≥ AR]")}</Formula>
      <p>{tx("G只是这个规则的简写：")}</p>
      <Formula label={tx("G是三个相对指标的最低值，通过条件是G不低于AR")}>
        G(X) = min(R<sub>field</sub>, R<sub>sens</sub>, R<sub>loc</sub>{tx(")；Pass = 1[G ≥ AR]")}</Formula>
      <Formula label={tx("固定示例G为57.15%、12.50%、18.54%三者最低值12.50%")}>
        {tx("示例：G = min(")}{tx(pct(example.fieldRelative))}, {tx(pct(example.sensitivity))}, {tx(pct(example.localizationRelative))}) = <strong>{tx(pct(example.global))}</strong>
      </Formula>
      <GuideTable label={tx("固定示例在不同AR下的共同通过判断")} headers={['AR设置', '示例布局是否通过三项共同约束']} rows={[
        ['90%', '不通过'], ['50%', '不通过，虽然信号重建已超过50%'], ['10%', '通过当前模型的点估计判据'],
      ]} />
      <p>{tx("判断使用未四舍五入的数值。页面显示的小数只是便于阅读。")}</p>
      <p><strong>{tx("G＝12.50%表示三项指标中的最低值为12.50%。")}</strong>{tx("重建解释率、电位差幅度和定位评分分别评价不同能力；统一阈值用于三项联合达标判定。")}</p>
      <p>{tx("AR判定针对聚合后的三项指标，个别脑源可低于阈值。当前搜索优化信号重建与敏感度中的较低值，定位在冻结布局后评价。人体与跨头模表现属于后续验证。")}</p>
      <h4>{tx("修改AR为什么不需要重新计算？")}</h4>
      <p>{tx("AR只改变通过判断，不改变电极位置、区域大小、前向模型、噪声或已有指标，因此直接使用已有结果。修改区域、半径或布局后，必须查找该配置的匹配结果；没有匹配结果时需要重新计算。")}</p>
    </GuideSection>

    <GuideSection id="retention-geometry" title={tx("六、几何有解与性能达标是两件事")}>
      <p>{tx("App先构造满足约束的64点布局，再评价性能。几何可行表示：")}</p>
      <ul>
        <li>{tx("有64个不同的测量点，且每区分配符合要求；")}</li>
        <li>{tx("点距达到下限，电极位于允许区域及半径范围内；")}</li>
        <li>{tx("区域满足规定的分离要求。")}</li>
      </ul>
      <p>{tx("性能达标表示所要求的指标达到AR。")}<strong>{tx("几何构造和性能评价是两个独立步骤。")}</strong>{tx("搜索未找到布局时，记录本轮搜索状态；整体几何可行性仍待判定。")}</p>
      <p>{tx("当前半径是ROI约束下的头表面网格边图路径上限，是连续表面距离的离散近似；面积使用原生顶点面积积分。几何定义和搜索预算应与结果一同解释。")}</p>
    </GuideSection>

    <GuideSection id="retention-scope" title={tx("七、这些结果适用于什么范围？")}>
      <p>{tx("本说明中的示例限定于：")}</p>
      <ul>
        <li>{tx("单个Ernie头模型，以及规定的皮层法向源与源权重；")}</li>
        <li>{tx("规定的前向模型、噪声、重建与定位方法；")}</li>
        <li>{tx("有限候选位置与有限布局搜索；")}</li>
        <li>{tx("坐标定义的耳后邻近区或少毛发候选区（模型近似）。")}</li>
      </ul>
      <p>{tx("位置范围采用模型坐标近似，皮肤与毛发分布尚待解剖审核。生成与反演共用头模和前向方法，离字典源仍存在同模型偏差。布局采用有限网格搜索，全局最优性尚未验证。")}</p>
      <p><strong>{tx("布局设计页评价给定皮层源先验与测量噪声下的表现。ECG/EOG干扰另在信号仿真页设置；MI、P300任务分类和人体表现尚待验证。")}</strong></p>
      <GuideTable label={tx("布局设计与源接收对照的区别")} headers={['页面', '主要用途']} rows={[
        ['布局设计页', '在规定源先验下，搜索并评价电极布局。'],
        ['信号仿真页', '固定布局，观察指定源位置、波形和干扰条件下的接收及重建表现。'],
      ]} />
      <p>{tx("信号仿真中的心电和眼电采用假设性空间场，用于预设干扰条件下的对照。两个页面的源条件和评价范围不同，结果按各自实验协议阅读。")}</p>
      <p>{tx("首页总面积上限约束结果、历史半径实验和冻结布局新源复评也有各自协议。各记录分别注明生成源、定位字典和其他实验参数。")}</p>
    </GuideSection>

    <GuideSection id="retention-reading" title={tx("八、阅读结果时应该优先看什么？")}>
      <ol>
        <li>{tx("关心采集效果能否接近全头64导：先看")}<strong>{tx("信号重建保留率")}</strong>{tx("，同时查看候选与标准64导的绝对重建解释率。")}</li>
        <li>{tx("关心是否遗漏某些脑源：再看")}<strong>{tx("幅度保留率（最差10%）")}</strong>。</li>
        <li>{tx("关心源位置能否估计准确：查看")}<strong>{tx("毫米单位定位误差")}</strong>{tx("及相对定位评分。")}</li>
        <li>{tx("需要多项约束共同通过：用G与AR判断，并查看限制达标的指标。")}</li>
      </ol>
      <p className="rounded-xl border border-primary/20 bg-primary/5 p-4 text-foreground"><strong>{tx("结果由头模、源先验、噪声、估计器和评价规则共同确定。信号重建、幅度与定位表现分别报告。")}</strong></p>
      <a className="inline-block text-sm font-semibold text-primary underline underline-offset-4" href="#retention-guide">{tx("返回本节目录 ↑")}</a>
    </GuideSection>
  </article>;
}
