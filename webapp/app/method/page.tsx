'use client';
import { useLanguage } from '@/components/language-provider';
/* oxlint-disable next/no-html-link-for-pages -- vinext production link prefetch is not runtime-safe */
import type { ReactNode } from 'react';
import {
  Braces,
  CircleAlert,
  FileCheck2,
  Layers3,
  Route,
  Sigma,
} from 'lucide-react';

import { SiteHeader } from '@/components/site-header';
import { DocumentationLink } from '@/components/documentation-navigation';
import { METHOD_CONTENTS } from '@/lib/documentation';
import { MethodBackLink, TechnicalDetails } from '@/components/method-context';
import { RetentionExplainer } from '@/components/retention-explainer';
import { SimulationExplainer } from '@/components/simulation-explainer';
import simulationCopy from '@/lib/i18n/simulation-catalog.json';
import { CopyrightNotice } from '@/components/copyright-notice';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';

const Formula = ({ children }: { children: ReactNode }) => (
  <div className="my-4 overflow-x-auto rounded-xl border border-[#d9e4e0] bg-[#f4f8f6] px-4 py-3 font-mono text-sm leading-7 text-[#173640]">
    {children}
  </div>
);

export default function MethodPage() {
  const { tx } = useLanguage();
  return (
    <main className="min-h-screen bg-[#f4f7f4] text-[#102a34]">
      <SiteHeader current="method" />

      <section className="border-b border-[#d7e2df] bg-[linear-gradient(120deg,#edf7f3_0%,#faf7ee_60%,#f4f7f4_100%)]">
        <div className="mx-auto max-w-5xl px-4 py-10 sm:px-6 lg:px-8">
          <MethodBackLink />
          <div className="flex flex-wrap gap-2">
            <Badge className="bg-[#102f3a] text-white">{tx("协议 V2")}</Badge>
            <Badge
              variant="outline"
              className="border-[#dfbd70] bg-[#fff8e8] text-[#765815]"
            >
              {tx("当前：单头模仿真 · 独立头模验证另列阶段")}</Badge>
          </div>
          <h1 className="mt-4 text-balance text-3xl font-semibold tracking-[-0.035em] sm:text-4xl">
            {tx("建模与原理")}</h1>
          <p className="mt-4 max-w-4xl text-base leading-7 text-[#536c72]">
            {tx("从脑源与组织传播开始，理解信号接收、重建和评价。首次操作步骤请查看“使用指南”。")}</p>
          
          <nav aria-label={tx("建模与原理目录")} className="mt-6 grid gap-3 text-base sm:grid-cols-2 lg:grid-cols-3">
            {METHOD_CONTENTS.map(([id, title]) => <a key={id} href={'#' + id} className="text-primary underline underline-offset-4">{tx(title)}</a>)}
          </nav>
          <div className="mt-4 flex flex-wrap gap-x-6 gap-y-3 text-base text-primary underline underline-offset-4">
            <a href="#simulation-model">{tx(simulationCopy.title.source)}</a>
            <a className="font-semibold" href="#retention-guide">{tx("保留率到底是什么？查看公式、示例与AR判断 ↓")}</a>
            <a href="#about-copyright">{tx('关于与版权')}</a>
          </div>
        </div>
      </section>

      <div className="mx-auto max-w-5xl space-y-12 px-4 py-10 sm:px-6 lg:px-8">
        <SimulationExplainer />
        <RetentionExplainer />
        <section id="model-terms" className="lab-panel space-y-3 scroll-mt-40" aria-label={tx("术语对照")}>
          <h2 className="text-lg font-semibold">{tx("对象与指标名称")}</h2>
          <p className="text-base leading-7">{tx("“允许布置范围”直接平铺选择：首页列出已有面积对比与19个预设组合；布局设计中，每个区域都可从9个部位选择，不限于预设。顺序对应各区电极数，可重复选择同一部位，但仍需满足完整布局与区域分离要求。选择部位本身不自动启动计算，除非另行开启自动计算。")}</p>
          <p className="text-base leading-7">{tx(simulationCopy.termDefinition.source)}</p>
          <p className="text-base leading-7">{tx("当前候选表面经过三组固定方向的外部曝光筛选（128、256、旋转后的128方向）：每组至少有一条无遮挡射线才准入。筛选覆盖区域中心、电极、表面路径和面积面片，排除被外层表面完全遮挡的内部点。它定义几何视线可达范围，尚不包含人工解剖标注或电极贴附验证。")}</p>
          <p className="text-base leading-7">{tx("三维彩色面片使用计算中保存的原生顶点集合，每个顶点占相邻三角形面积的三分之一；这与报告的面积积分一致。每区按钮显示电极数与实际面积，并将视角转到该区域。原坐标范围的面积结果保留在“历史面积实验”，新搜索不沿用旧坐标的分数。")}</p>
          <p className="text-base leading-7">{tx("三项指标为“信号重建保留率”“幅度保留率（最差10%）”和“相对定位评分”。G取三者最低值，用于与接受阈值AR比较。")}</p>
          <p className="text-base leading-7">{tx("少毛发候选区按模型坐标近似划定，毛发分布尚待解剖审核。耳后邻近区为近耳后外侧范围，耳周扩展区覆盖更大范围，眶周上外侧为眼眶上外侧近似范围。")}</p>
        </section>
        <section id="electrode-editor" className="lab-panel space-y-4 scroll-mt-24">
          <h2 className="text-xl font-semibold">{tx('电极编辑：数量与位置的独立评价')}</h2>
          <p className="text-base leading-7">{tx('载入有保存区域边界的真实64点布局。保留稳定编号，移除点位不补点、不重新分配；移动吸附到原区域内已有FEM结果的候选点。原区域面积不随删点改变。')}</p>
          <p className="text-base leading-7">{tx('编辑后只使用启用点的前向矩阵，并重新计算参考无关对比、重建器及指标。N个启用点提供N−1个参考无关维度，重建目标始终是标准64的63维干净场。噪声仍由标准64标定，不能随删点重新归一化。')}</p>
          <p className="text-base leading-7">{tx('标准64、原始布局和编辑布局在同一协议下重新评价。定位沿用4096字典源、256离字典生成源和每源16次噪声重复；删点前后按稳定槽位配对噪声。仅有2点时未知振幅定位不可辨识，定位显示不可用。')}</p>
          <p className="text-base leading-7">{tx('编辑草稿与已评价结果分开保存。修改点位后旧评分失效；评价结果使用独立缓存，不加入固定64点实验曲线。当前编辑记录不接入只支持完整64点的信号仿真入口。')}</p>
          <a className="text-primary underline" href="/electrodes">{tx('电极编辑')}</a>
        </section>
        <section id="design-decision" className="lab-panel space-y-4 scroll-mt-24">
          <h2 className="text-xl font-semibold">{tx("方案对比、坐标导入与位置偏移")}</h2>
          <p className="text-base leading-7">{tx("在结果库的“方案对比”中选择A、B，核对协议、实际面积与允许位置范围，再设置各项性能要求。可导出Markdown报告、完整JSON及64点CSV坐标。外部坐标文件在布局设计的“坐标导入”中评价；位置偏移测试保留在方案对比。")}</p>
          <p className="text-base leading-7">{tx("坐标导入限定为已经配准到本项目Ernie头模的原生毫米坐标；X向右、Y向前、Z向上。模板明确记录坐标系、单位、64个点和从0开始的区域标签。其他头模、MNI或数字化仪坐标需先配准。三维预览只显示输入，不产生性能评分。")}</p>
          <p className="text-base leading-7">{tx("点击“评价当前坐标”后，候选库内的点复用相应FEM场。新点投影到原头表面，最大调整距离限制为2 mm；最小直线点距为4 mm。新位置通过FEM直接求解，同时重新计算标准64参照，核对其与原前向库的一致性。结果保存实际评价坐标，三维图可切换原始输入和实际评价位置。")}</p>
          <p className="text-base leading-7">{tx("网格偏移测试只使用已有FEM候选点。对每个区域生成一个目标平移方向，在3、6或10 mm位移上限内匹配64个互异的候选点；4次确定种子的试验不依据性能重抽样。匹配后的实际位移、目标误差、未移动比例及点距分别报告；点距失败的试验保留坐标和原因，不给出分数。原区域标签保留，贴片边界与连通性不重新认证。")}</p>
          <Formula>y₀ = H₀j + ε；yδ = Hδj + ε；z = H₆₄j<br />{tx("重新标定：使用Hδ对应的LMMSE估计器。")}<br />{tx("沿用原标定：将H₀对应的固定估计器作用于yδ。")}<br />{tx("两者均以标准64干净场为目标，物理噪声尺度保持不变。")}</Formula>
          <p className="text-base leading-7">{tx("这些重建分数由给定源协方差的期望误差计算，不是有限训练样本下的实测结果。固定估计器的解释率可为负值，表示其误差超过输出零信号的基准。定位使用4096点字典、256个离字典生成源及每源16次噪声，新评价采用配对噪声，与原记录评分分开显示。")}</p>
          <p className="text-base leading-7">{tx("本地布局搜索、源信号仿真和坐标评价共用一个计算工作槽。原布局搜索与原多源模式最多2线程；新单源、新坐标接收和坐标评价单线程。新坐标相关任务上限10分钟，支持停止和相同输入缓存复用。独立头模迁移、实测噪声校准和实体采集对照列为下一验证阶段。")}</p>
        </section>
        <section id="source-field-interaction" className="lab-panel space-y-4 scroll-mt-24">
          <h2 className="text-xl font-semibold">{tx("源—场交互与可复现实验")}</h2>
          <p className="text-base leading-7">{tx("“计算记录”提供初始化、已接受的位置交换曲线及最终布局。搜索目标沿用原实验定义；曲线不包含未保存的被拒绝提案。完整实验包包含原始记录、配置、轨迹和SHA256身份，重新运行需要对应代码版本、头模与前向矩阵。")}</p>
          <p className="text-base leading-7">{tx(simulationCopy.interactionIntro.source)}</p>
          <a className="text-primary underline underline-offset-4" href="#simulation-sources">{tx(simulationCopy.modelLink.source)}</a>
          <p className="text-base leading-7">{tx("接收仿真固定使用所选记录的原坐标，不执行新布局优化或表面准入审核。列表中的“历史布局”沿用原坐标协议，其结果不归入当前表面筛选下的布局比较；原记录及原多源分析继续可读。")}</p>
          <Formula>ẑX(t) = AX yX(t)；eX(t) = ẑX(t) − z(t)</Formula>
          <p className="text-base leading-7">{tx("接收电位采用各布局64通道平均参考。两侧的电极颜色表示这一参考定义下实际坐标处的电位，单位μV；蓝为负、红为正，两侧及全部预览时间共用同一色标。接收图使用各自坐标；重建图和残差图均使用标准64平均参考目标场。点间不插值。黄色标记显示真实源位置，原始法向箭头只在记录包含方向时显示。")}</p>
          <p className="text-base leading-7">{tx("拖动时间或播放更新同一时刻的电位；点击电极选择通道，点击源选择源波形。动画读取抗混叠降采样后的50Hz、8秒预览，正式评分始终来自200Hz、20秒完整模拟。它展示准静态电位，不表示信号沿头皮传播。")}</p>
          <p className="text-base leading-7">{tx("“方案对比”中的坐标评价完成后，可进入源—接收仿真。新坐标使用已保存的实际评价坐标，首次运行直接求解FEM并归档64×4352前向矩阵。后续源场景复用该矩阵，源或干扰改变时只重算信号。原多源缓存、新源场景缓存与新坐标前向缓存分别保存。")}</p>
          <p className="text-sm leading-6 text-muted-foreground">{tx("流程组织参考 ")}<a className="text-primary underline" href="https://github.com/TBBL-UTHealth/SEPIO">SEPIO</a>{tx("，源—场交互参考 ")}<a className="text-primary underline" href="https://github.com/mne-tools/dipole-simulator">MNE Dipole Simulator</a>{tx("。本项目保持固定64电极的空间集中研究及原指标定义，未移植这两个项目的优化目标或程序代码。")}</p>
        </section>
        <TechnicalDetails>
        <nav aria-label={tx("技术内容分类")} className="flex flex-wrap gap-4 text-base text-primary underline">
          <a href="#local-compute">{tx("当前：布局计算")}</a><a href="#single-head-optimization">{tx("历史：半径实验")}</a><a href="#planned-validation">{tx("后续：验证计划")}</a><a href="#anatomical-display">{tx("3D显示与来源")}</a>
        </nav>
        <section id="local-compute" className="method-panel scroll-mt-24">
          <h3>{tx("本机按需计算：调整参数后发生什么")}</h3>
          <p>
            {tx("本地设计页通过同源接口调用这台电脑上的Python程序。固定64点、最小电极直线间距4 mm，标准64导名义SNR＝20 dB， 原始前向库包含5,387个候选位置；当前外部曝光筛选保留其中4,847个。修改半径或区域后，在筛选后的范围内重新搜索，复用对应原坐标的FEM前向场。")}</p>
          <p>
            {tx("新版搜索在候选中心组合规模不超过256组时检查全部组合；更大规模保留最多16组的有界筛选。 每组先检查候选点数量，再进行2次布局初始化，最终进行1轮64点坐标交换，每点最多12个提案。 搜索覆盖上述候选中心与区内提案，连续空间的全局最优性和不可行性仍待验证。 优化目标预先固定为信号重建与幅度保留率（最差10%）中的较低值；冻结点位后再计算源定位。 字典为4,096个源，定位使用原有256个离字典源、每源16次噪声；512个新源的复评属于另一批次。")}</p>
          <p>
            {tx("区域采用ROI约束的表面边图路径，要求在原头表面邻接图上形成恰好R个不接触的连通分量。 滑块设置的是共同半径上限；遇区域连接时缩小实际半径，同时报告实际半径和面积。 耳后邻近区、少毛发候选区等范围采用坐标掩膜，解剖审查另列阶段。")}</p>
          <p>
            {tx("一次只运行一个任务、使用2线程，180秒超时停止。相同参数、科学代码及前向数据身份的结果可从本机缓存读取； 修改AR只更新三项阈值判断。G达到AR表示本记录三项相对指标均达到用户阈值。 本地服务未启动时显示未连接；公开托管页面不会连接或使用访问者电脑。")}</p>
          <p>
            {tx("数据读取优先于计算。关闭自动计算后仍查找缓存，命中时直接恢复坐标和分数；无匹配记录才按需启动Python。 完成或有限搜索未构造出布局的结果保存在本机项目文件中，重启App后继续使用，不因修改AR失效。 取消、失败和超时仅保存任务日志，不作为性能缓存。输入文件变动时重新校验模型与数据版本。 搜索算法更新后，旧记录仍可查看，也可只恢复其原始参数；设计页读取当前版本的匹配结果。")}</p>
          <p>
            {tx("“计算记录”页只读展示已有严格面积和半径方案；342个早期半径布局通过历史筛选查看。 总面积上限数据采用原4096点字典与256个生成源；早期半径布局允许区域相交。 历史记录保留其原始协议；当前半径计算按自身版本查找匹配数据。不同协议分别绘制曲线。")}</p>
        </section>

        <section id="single-head-optimization" className="scroll-mt-24">
          <div className="section-kicker">
            <FileCheck2 className="size-4" />
            {tx("历史结果页 · 原半径实验（允许区域相交）")}</div>
          <h2 className="method-title">{tx("同样64个点，只改变空间布局")}</h2>
          <p className="method-lead">
            {tx("1、2、3、4、6区分别分配64；32+32；22+21+21；16×4；11+11+11+11+10+10个测量点。每种区域数均有全头自由中心和低毛发近似约束，另加7种指定耳后／前额／眶周组合，共17个实验族。6种半径上限（20、30、40、50、65、80 mm）乘2种最小电极直线间距（4、6 mm），共204个条件。")}</p>
          <div className="mt-5 space-y-4">
            <div className="method-panel">
              <h3>{tx("① 候选位置上直接求解的FEM前向场")}</h3>
              <p>
                {tx("在Ernie实际头表面生成5,387个候选点，对每一点直接计算体积FEM lead field。采用同一4,096个面积加权皮层法向源和全头基准，候选位置独立于BioSemi64原始点。半径为网格边图最短路径上限；点距是欧氏弦距；面积是连通顶点掩膜的分摊近似。这些几何量采用离散表面近似。")}</p>
            </div>
            <div className="method-panel">
              <h3>{tx("② 有记录的中心与电极坐标搜索")}</h3>
              <p>
                {tx("每条件最多24组中心、每组4次几何起点。按20 dB信号重建及min(信号重建,敏感度)分别保留2个起点，每起点进行2轮逐电极交换，每次最多16个候选。再尝试1轮中心交换、每区最多4个中心提案。中心移动必须保留当前点的区域成员资格，之后额外扫描该区域。记录全部接受移动、直接重评分及几何约束；较大半径使用重新核验的小半径结果作为起点。")}</p>
              <p>
                {tx("结果为当前候选网格和预算内找到的较优布局。未构造成功的条件保留尝试次数和已放置点数，其几何可行性仍待判定。")}</p>
            </div>
            <div className="method-panel">
              <h3>{tx("③ 对所有最终布局统一评价")}</h3>
              <p>
                {tx("两个分支的最终布局都报告0/10/20 dB的信号重建、敏感度和定位。相同物理通道噪声由全头基准标定，各布局保持同一物理噪声尺度。定位使用256个离字典生成源、每源16次噪声、4,096点固定法向ML字典。每布局每档位进行4,096次模拟试验。定位不参与逐坐标优化，只在最终候选中用于结果比较。")}</p>
              <p>
                {tx("各布局共享噪声分布，但采用独立的固定种子噪声实现，定位比值保留蒙特卡洛波动。生成与反演仍共用解剖和导电率；4096点字典的离散、方向及空间歧义导致模型内非零误差底限。")}</p>
            </div>
            <div className="method-panel">
              <h3>{tx("④ 模型内阈值判断与独立验证分开")}</h3>
              <Formula>
                U = LCVaR₁₀%[mean_noise(max(0,1 − error_mm/50))]；Rloc =
                U(X)/U(B₆₄)
              </Formula>
              <Formula>
                {tx("G(X;SNR) = min(Rfield, Rsensitivity, Rloc)；Pass = [G ≥ AR]")}</Formula>
              <p>
                {tx("单次定位评分u先对每源16次噪声取均值，再按生成源面积取最低10%的加权均值，得到下尾评分U；相对定位评分Rloc为候选布局U除以标准64导U。基准U为零或非有限数时，Rloc和G保持未定义。三项相对指标分别报告，G用于联合达标判定；每个SNR档位独立判断。")}</p>
              <p>
                {tx("阶段一评价单头模中的布局表现。阶段二计划冻结入围布局，开展独立头模、源先验与模型失配验证。群体置信界评价尚待实施。")}</p>
            </div>
          </div>
          <a
            href="/results"
            className="mt-5 inline-flex text-sm font-semibold text-[#117d72]"
          >
            {tx("查看本历史批次的布局、评分与记录 →")}</a>
        </section>
        <section id="first-batch" className="scroll-mt-24">
          <div className="section-kicker">
            <FileCheck2 className="size-4" />
            {tx("历史原型 · 首批双区域比较")}</div>
          <h2 className="method-title">{tx("优化前的首批原型记录")}</h2>
          <p className="method-lead">
            {tx("首批采用SimNIBS Ernie体积FEM头模，固定两个区域、每区32点。32次几何构造中完成28组配置，包含26种不同的点位集合。没有运行区域中心或区内坐标的性能优化。")}</p>
          <div className="mt-5 space-y-4">
            <div className="method-panel">
              <h3>{tx("① 新电极位置的前向计算")}</h3>
              <p>
                {tx("基准为BioSemi64名称匹配的Ernie-SPM12全头模板坐标。571个唯一候选点与64个基准点在同一FEM上直接求解，再分别进行Helmert对比，得到63个参考无关观测维度。候选场在各位置直接求解。")}</p>
            </div>
            <div className="method-panel">
              <h3>{tx("② 固定源先验与物理噪声")}</h3>
              <p>
                {tx("使用4,096个皮层法向字典源、皮层面积加权的对角源协方差，偶极矩尺度10 nA·m。0/10/20 dB名义SNR均由全头基准标定；同一档位各布局共享相同通道噪声标准差。")}</p>
            </div>
            <div className="method-panel">
              <h3>{tx("③ 信号重建报告绝对解释率与相对比值")}</h3>
              <p>
                {tx("预测目标z是干净的全头64点参考无关电位场。根据源先验、前向模型和噪声协方差构造LMMSE估计器，解析计算期望重建误差。相对值为候选重建解释率除以同噪声基准重建解释率，保留超过100%的结果。")}</p>
              <Formula>
                A* = Σ<sub>zy</sub> Σ<sub>yy</sub>
                <sup>−1</sup>；F(X) = 1 − tr(Σ<sub>z|y</sub>) / tr(Σ
                <sub>zz</sub>)
              </Formula>
              <Formula>
                R<sub>field</sub>(X) = F(X) / F(B₆₄)
              </Formula>
              <p>
                {tx("因此基准的相对值恒为100%，而20 dB下基准的绝对解释率为99.31%。结果页同时显示这两个尺度。")}</p>
            </div>
            <div className="method-panel">
              <h3>{tx("④ 敏感度与定位分别解释")}</h3>
              <p>
                {tx("敏感度逐源计算候选与全头基准的最大双极幅度比，按相对保留率排序，取最低10%皮层面积的加权均值，权重按皮层面积分配。定位仅计算30 mm半径上限、6 mm点距的四个预冻结原型及基准，以256个离字典生成源、每源16次噪声，扫描4,096个固定法向候选源；共61,440次模拟试验。")}</p>
              <p>
                {tx("无噪声基准仍有10.73 mm中位误差和20.57 mm的P90误差，说明离散固定法向字典存在匹配限制。生成与反演共用头模和导电率，离网格设置仍保留同模型偏差；定位结果用于当前反演器的诊断。")}</p>
            </div>
            <div className="method-panel">
              <h3>{tx("⑤ 计算复现与模型近似")}</h3>
              <p>
                {tx("12项计算检查通过，两个独立进程重复运行的前向和指标NPZ逐字节一致，均基于同一头模。108 / 4,352个源采用最近灰质恢复，其中4个曲面点与血液分割不一致，作为明确的灰质近似模型保留。区域是坐标掩膜裁剪的图路径贴片，点距采用欧氏弦距，连续测地几何与毛发范围审核列入后续计划。")}</p>
              <p>
                {tx("首批原型范围为双区域几何布局。1/3/4/6区域、坐标优化和新源复评按后续批次记录；群体阈值与连续最小面积评价列入后续计划。")}</p>
            </div>
          </div>
          <a
            href="/pilot-results"
            className="mt-5 inline-flex items-center gap-2 font-semibold text-[#117d72]"
          >
            {tx("查看交互曲线、点位与原始数据 →")}</a>
        </section>

        <div id="planned-validation" className="scroll-mt-28 space-y-10 rounded-2xl border border-amber-200 bg-amber-50/30 p-5">
        <div className="space-y-2"><h2 className="text-xl font-semibold">{tx("后续验证计划 · 尚未全部实施")}</h2><p className="text-base leading-7">{tx("以下为理想化几何与群体评价的计划。当前实现见上方“布局计算”和指标说明。")}</p></div>
        <section>
          <div className="section-kicker">
            <Sigma className="size-4" />{tx("1 · 优化变量")}</div>
          <h2 className="method-title">{tx("总数固定，优化区域和全部坐标")}</h2>
          <p className="method-lead">
            {tx("总测量电极数固定为64，区域数为1、2、3、4或6。三个区域和六个区域采用平衡整数分配。")}</p>
          <Formula>
            N = 64；m(R) = (64), (32,32), (22,21,21), (16,16,16,16),
            (11,11,11,11,10,10)
          </Formula>
          <p className="method-copy">
            {tx("计划把每区定义为包含该区全部电极的最小测地圆盘。主尺寸是各区实际半径的最大值；滑块给出共同上限，不强迫所有区域等大。所有点之间必须满足最小测地距离。")}</p>
          <Formula>
            Ωᵣ(cᵣ,aᵣ) = {tx('{')}x ∈ M : d<sub>M</sub>(x,cᵣ) ≤ aᵣ{tx('}')}；d
            <sub>M</sub>(xᵢ,xⱼ) ≥ δ
          </Formula>
          <Formula>
            a<sub>max</sub>(X) = maxᵣ aᵣ(X)；aᵣ(X) ≤ a
          </Formula>
        </section>

        <section>
          <div className="section-kicker">
            <Layers3 className="size-4" />{tx("2 · 三类比较")}</div>
          <h2 className="method-title">{tx("把聚集代价与低毛发约束代价分开")}</h2>
          <div className="mt-5 grid gap-4 md:grid-cols-3">
            {tx([
              [
                '全合格表面自由中心',
                '约束最少的比较族，用于评价限定部位带来的性能变化；搜索结果为当前预算内找到的较优值。',
              ],
              [
                '低毛发联合域',
                '电极只能位于耳后、耳周、前额和眶周掩膜。理想等噪声模型中各部位保持相同噪声尺度。',
              ],
              [
                '指定解剖组合',
                '直接比较严格双耳后、耳后加前额及双侧完整耳周等可解释原型。',
              ],
            ].map(([title, text]) => (
              <Card key={title} className="border-[#d9e3e0] bg-white">
                <CardContent>
                  <h3 className="font-semibold text-[#173640]">{tx(title)}</h3>
                  <p className="mt-2 text-sm leading-6 text-[#61757b]">
                    {tx(text)}
                  </p>
                </CardContent>
              </Card>
            )))}
          </div>
        </section>

        <section>
          <div className="section-kicker">
            <Braces className="size-4" />{tx("3 · 指标与AR")}</div>
          <h2 className="method-title">{tx("三项评价指标分别报告")}</h2>
          <div className="mt-5 space-y-4">
            <div className="method-panel">
              <h3>{tx("主指标：64导信号重建保留率")}</h3>
              <p>
                {tx("无噪声BioSemi64电位场是重建目标；候选与BioSemi观测均含同一物理尺度的独立噪声。分别计算LMMSE解释率，再取候选/BioSemi比值。绝对值和相对值同时报告。")}</p>
            </div>
            <div className="method-panel">
              <h3>{tx("全皮层法向源敏感度")}</h3>
              <p>
                {tx("逐源比较最大双极幅度；每头模先取表面积加权的源下10% CVaR，再跨头模取下10% CVaR。结果为两层面积加权下尾指标。")}</p>
            </div>
            <div className="method-panel">
              <h3>{tx("离网格单源定位")}</h3>
              <p>
                {tx("使用冻结的固定法向单偶极最大似然扫描。相对分数来自0–50 mm定位成功曲线面积；同时报告中位数、p90和p95绝对毫米误差。")}</p>
            </div>
          </div>
          <Formula>
            {tx("Pass(X;AR) = 1[LCB₉₅(R")}<sub>field</sub>{tx(") ≥ AR ∧ LCB₉₅(R")}<sub>sens</sub>{tx(") ≥ AR ∧ LCB₉₅(R")}<sub>loc</sub>{tx(") ≥ AR]")}</Formula>
          <p className="method-copy">
            {tx("置信区间的bootstrap单位是头模型。本项目早期计划以至少100个独立锁定测试头模进行群体置信界评估；样本量与具体执行方案尚待确定。三个约束中的最低LCB称为“三项相对指标的最低置信下限”。")}</p>
        </section>

        <section>
          <div className="section-kicker">
            <Route className="size-4" />{tx("4 · 半径—性能曲线")}</div>
          <h2 className="method-title">{tx("区域半径与性能的权衡曲线")}</h2>
          <Formula>
            γ̂<sub>R,D</sub>(a) = best found<sub>aₘₐₓ(X)≤a</sub> min {tx('{')}R
            <sub>field</sub>, R<sub>sens</sub>, R<sub>loc</sub>
            {tx('}')}
          </Formula>
          <Formula>
            â<sub>pass</sub>{tx("(AR) = 最小已验证通过的半径上限")}</Formula>
          <p className="method-copy">
            {tx("几何不可行性通过严格装填界或完备证明判定；性能不可行性通过严格性能上界判定。有限搜索低于AR时，记录为“预设搜索预算内未找到达标布局”。")}</p>
        </section>

        <section>
          <div className="section-kicker">
            <FileCheck2 className="size-4" />{tx("5 · 执行顺序")}</div>
          <h2 className="method-title">{tx("后续验证的执行顺序")}</h2>
          <ol className="mt-5 space-y-3">
            {tx([
              '选择包含完整耳后、耳周、前额和眶周的解剖头表面，并核对来源与许可。',
              '在同一坐标系注册BioSemi64、连续候选表面、源空间和低毛发掩膜。',
              '通过初步装填实验确定最小测地点距，并证明每个目标区域能够容纳规定点数。',
              '冻结clean target、源协方差、噪声尺度和定位器，再验证参考不变性与网格加密稳定性。',
              '运行双耳后32+32、耳后32+前额32和完整耳周32+32原型。',
              '原型通过后运行R={1,2,3,4,6}全量搜索；群体阈值验证的早期计划采用至少100个独立锁定测试头模，尚未实施。',
            ].map((item, index) => (
              <li
                key={item}
                className="flex gap-3 rounded-xl border border-[#dbe4e1] bg-white px-4 py-3 text-sm leading-6 text-[#526970]"
              >
                <span className="grid size-7 shrink-0 place-items-center rounded-full bg-[#e4f3ef] font-mono text-xs font-semibold text-[#117d72]">
                  {tx(index + 1)}
                </span>
                <span>{tx(item)}</span>
              </li>
            )))}
          </ol>
        </section>

        </div>
        <section id="anatomical-display" className="method-panel scroll-mt-24">
          <h3>{tx("三维头部、设计示意与结果坐标的区别")}</h3>
          <p>
            {tx("头皮、面部、双耳与内部灰质表面来自同一 SimNIBS Ernie 示例头模。显示保留原始几何，进行了表面分量提取、米制单位转换与浏览器格式压缩；肤色与电极外观为显示样式。")}</p>
          <p>
            {tx("“布局设计”页在当前配置尚无结果时，用径向投影显示几何示意。 本地任务完成后，替换为该配置实际优化出的64点MRI坐标与对应全头64导基准；修改参数后显示新配置的状态。")}</p>
          <p>
            {tx("设计页的已计算布局与结果页均使用保存的FEM电极MRI坐标，仅按100 mm对应一个显示单位换算，不重新径向投影。触点外观沿表面法向抬高1.2 mm以避免遮挡，属于显示效果，不改变计算坐标。图中标明点位来源为示意或计算记录。")}</p>
          <p>
            {tx("数据来源：")}<a
              className="text-[#117d72] underline"
              href="https://github.com/simnibs/example-dataset/releases/tag/v4.1"
            >
              SimNIBS example dataset v4.1
            </a>
            ，© SimNIBS developers 2024，
            <a
              className="text-[#117d72] underline"
              href="https://creativecommons.org/licenses/by-nc/4.0/"
            >
              CC BY-NC 4.0
            </a>
            {tx("。原头模下脸与颈部存在截断，灰质表面保留源网格的不连续边界；当前资产只用于可视化。")}</p>
        </section>

        <section className="rounded-[24px] border border-[#e2bd68] bg-[#fff8e8] p-6 sm:p-7">
          <div className="flex items-center gap-2 font-semibold text-[#6f5314]">
            <CircleAlert className="size-5" />
            {tx("结果适用范围")}</div>
          <ul className="mt-4 grid gap-2 text-sm leading-6 text-[#7b6532] sm:grid-cols-2">
            <li>{tx("• 双耳后邻近区32+32按具体记录判定AR；固定示例G约12.50%，在AR＝10%时通过模型内判据。")}</li>
            <li>{tx("• BioSemi64为归一化比较基准；绝对重建和定位误差另行报告。")}</li>
            <li>{tx("• 当前源先验评价空间采集表现；MI/P300任务分类及人体表现尚待验证。")}</li>
            <li>{tx("• 早期BioSemi64子集实验与当前固定64点空间布局实验采用不同研究定义，分别归档。")}</li>
            <li>{tx("• 电位场由解剖头模的FEM计算，示意图用于展示位置。")}</li>
            <li>{tx("• 源空间覆盖本模型的皮层法向源；深部源属于后续扩展范围。")}</li>
            <li>{tx("• 搜索结果为有限预算内的较优布局；整体可行性和全局最优性另行验证。")}</li>
          </ul>
        </section>

        <section id="method-references" className="scroll-mt-40">
          <div className="section-kicker">
            <FileCheck2 className="size-4" />{tx("6 · 方法参考")}</div>
          <h2 className="method-title">
            {tx("相关研究及其适用范围")}</h2>
          <div className="mt-5 space-y-3 text-sm leading-7 text-[#596f75]">
            <p>
              <a
                className="font-medium text-[#117d72] underline underline-offset-4"
                href="https://doi.org/10.1007/s10548-020-00793-2"
              >
                {tx("Meiser等，2020")}</a>
              {tx("研究耳周阵列对源位置和方向的敏感性。本项目进一步考察固定64点布局、区域尺寸和信号重建。")}</p>
            <p>
              <a
                className="font-medium text-[#117d72] underline underline-offset-4"
                href="https://doi.org/10.1016/j.jneumeth.2015.08.015"
              >
                {tx("Song等，2015")}</a>
              {tx("研究电极密度和头表面覆盖范围对定位的影响，为布局比较提供依据。")}</p>
            <p>
              <a
                className="font-medium text-[#117d72] underline underline-offset-4"
                href="https://doi.org/10.1088/1741-2552/ad1783"
              >
                {tx("Meiser、Knoll与Bleichner，2024")}</a>
              {tx("研究单耳周31点的二维高密度采样，展示多个触点带来的附加信息。其阵列覆盖耳周范围。")}</p>
          </div>
        </section>
        </TechnicalDetails>
        <DocumentationLink target="guide" className="inline-block text-base font-semibold text-primary underline underline-offset-4">{tx("返回使用指南，继续操作")}</DocumentationLink>
        <CopyrightNotice />
      </div>
    </main>
  );
}
