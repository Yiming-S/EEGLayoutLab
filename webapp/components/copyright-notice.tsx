'use client';
/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
import { useLanguage } from '@/components/language-provider';
import { COPYRIGHT_NOTICE } from '@/lib/copyright';

export function CopyrightNotice() {
  const { tx } = useLanguage();
  return (
    <section id="about-copyright" aria-labelledby="copyright-heading" className="lab-panel space-y-6 scroll-mt-40">
      <div>
        <h2 id="copyright-heading" className="text-xl font-semibold">EEG Layout Lab — {tx('关于与版权')}</h2>
        <p className="mt-2 text-sm text-[#53686e]">{COPYRIGHT_NOTICE}</p>
      </div>
      <p className="text-base leading-7">{tx('EEG Layout Lab 是用于脑电电极布局设计、数学仿真与性能比较的研究软件，研究电极数量、空间分布和区域范围与脑电采集能力之间的关系。')}</p>
      <div className="space-y-3">
        <h3 className="text-lg font-semibold">{tx('原创内容')}</h3>
        <p className="text-base leading-7">{tx('本版权声明适用于项目中由 Yiming Shen 创作的源代码、界面设计、说明文档及其他原创内容。第三方软件、头部模型、数据和其他引用材料不包含在上述原创内容范围内。')}</p>
      </div>
      <section id="third-party-licenses" aria-labelledby="third-party-heading" className="space-y-3 scroll-mt-40">
        <h3 id="third-party-heading" className="text-lg font-semibold">{tx('第三方许可')}</h3>
        <p className="text-base leading-7">{tx('本项目使用的第三方软件、模型及数据，其相关权利归各自权利人所有，并按各自的许可条件使用。具体来源、署名、许可链接及修改说明，见相关资产说明及所附许可文件。')}</p>
        <p className="text-base leading-7">{tx('其中，SimNIBS 头模及其派生显示资产保留相应的来源、署名和许可信息。对这些资产进行转换或用于本项目展示，不改变其原有权利归属。')}</p>
        <div className="rounded-xl border border-[#d9e4e0] bg-[#f4f8f6] p-4 text-sm leading-7">
          <p><a className="text-primary underline underline-offset-4" href="https://github.com/simnibs/example-dataset/releases/tag/v4.1">SimNIBS example dataset v4.1</a></p>
          <p>© SimNIBS developers 2024 · <a className="text-primary underline underline-offset-4" href="https://creativecommons.org/licenses/by-nc/4.0/">CC BY-NC 4.0</a></p>
          <p className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
            <a className="text-primary underline underline-offset-4" href="/models/ernie/README.md">{tx('模型资产来源与修改说明')}</a>
            <a className="text-primary underline underline-offset-4" href="/models/ernie/manifest.json">{tx('模型资产清单')}</a>
            <a className="text-primary underline underline-offset-4" href="#anatomical-display">{tx('三维显示与坐标说明')}</a>
          </p>
        </div>
      </section>
      <div className="space-y-3">
        <h3 className="text-lg font-semibold">{tx('许可与引用')}</h3>
        <p className="text-base leading-7">{tx('本声明用于标明版权归属，不代替具体的软件或数据许可。使用、修改或再分发项目内容时，应分别核对所涉及代码、文档、模型和数据的许可条件。')}</p>
        <p className="text-base leading-7">{tx('参考文献用于说明研究方法和理论来源，与第三方软件及数据许可分别列示。')}</p>
      </div>
    </section>
  );
}
