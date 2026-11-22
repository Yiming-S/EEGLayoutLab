'use client';
/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
import { useLanguage } from '@/components/language-provider';
import { COPYRIGHT_NOTICE } from '@/lib/copyright';

export function CopyrightNotice() {
  const { tx } = useLanguage();
  return (
    <section id="about-copyright" aria-labelledby="copyright-heading" className="lab-panel space-y-6 scroll-mt-40">
      <h2 id="copyright-heading" className="text-xl font-semibold">EEG Layout Lab — {tx('关于与版权')}</h2>
      <p className="text-base leading-7">{tx('EEG Layout Lab 用于设计脑电电极布局、模拟脑电信号和比较布局性能。')}</p>
      <div className="space-y-3">
        <h3 className="text-lg font-semibold">{tx('作者')}</h3>
        <p className="text-base leading-7">Yiming Shen, PhD</p>
      </div>
      <div className="space-y-3">
        <h3 className="text-lg font-semibold">{tx('致谢')}</h3>
        <p className="text-base leading-7">Yi Wang, PhD</p>
      </div>
      <p className="text-sm text-[#53686e]">{COPYRIGHT_NOTICE}</p>
      <p className="text-base leading-7">
        {tx('本项目的原创代码与文档采用 GNU 通用公共许可证第3版（仅此版本，GPL-3.0-only）。可按该许可修改和再分发，软件不提供担保。')}{' '}
        <a className="text-primary underline underline-offset-4" href="/LICENSE.txt">{tx('许可证全文')}</a>
      </p>
      <section id="third-party-licenses" aria-labelledby="third-party-heading" className="space-y-3 scroll-mt-40">
        <h3 id="third-party-heading" className="text-lg font-semibold">{tx('第三方许可')}</h3>
        <p className="text-base leading-7">{tx('本项目的 Ernie 头部模型和三维显示资产源自 SimNIBS 示例数据集 v4.1。')}</p>
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
    </section>
  );
}
