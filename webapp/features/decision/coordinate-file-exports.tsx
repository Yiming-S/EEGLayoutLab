'use client';
import { useState } from 'react';
import { useLanguage } from '@/components/language-provider';
import { Button } from '@/components/ui/button';
import { exportBIDSElectrodes, exportMniBIDSElectrodes, type CoordinateFile } from '@/lib/bids-electrodes';
import { loadErnieMniSurface } from '@/lib/ernie-mni';
import { exportEeglabSfp, exportMneElc } from '@/lib/montage-files';
import type { ElectrodeDesign } from '@/lib/design-decision';

function save(file: CoordinateFile) {
  const url = URL.createObjectURL(new Blob([file.text], { type: file.name.endsWith('.tsv') ? 'text/tab-separated-values;charset=utf-8' : file.name.endsWith('.json') ? 'application/json' : 'text/plain;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url; link.download = file.name; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function montageFiles(design: ElectrodeDesign) {
  try { return { files: [exportMneElc(design), exportEeglabSfp(design)] }; }
  catch (caught) { return { error: caught instanceof Error ? caught.message : 'MNE/EEGLAB坐标文件导出失败。' }; }
}

/** Ernie-native BIDS, MNE and EEGLAB files at once; the MNI files after an explicit conversion, which reads the mapping buffers. */
export function CoordinateFileExports({ design }: { design: ElectrodeDesign }) {
  const { tx } = useLanguage();
  const key = JSON.stringify([design.name, design.xyz_mm, design.region_indices, design.electrode_names]);
  const [mni, setMni] = useState<{ key: string; busy?: boolean; files?: CoordinateFile[]; error?: string } | null>(null);
  const current = mni?.key === key ? mni : null;
  const convert = async () => {
    setMni({ key, busy: true });
    try { setMni({ key, files: exportMniBIDSElectrodes(design, await loadErnieMniSurface()) }); }
    catch (caught) { setMni({ key, error: caught instanceof Error ? caught.message : 'MNI坐标换算失败。' }); }
  };
  const buttons = (files: CoordinateFile[]) => files.map(file =>
    <Button key={file.name} variant="outline" size="sm" onClick={() => save(file)}>{tx('下载')} {file.name}</Button>);
  const montage = montageFiles(design);
  return <details className="mt-3 rounded-lg border p-3"><summary className="cursor-pointer text-sm">{tx('坐标文件（BIDS、MNE、EEGLAB）')}</summary>
    <p className="mt-2 text-xs text-muted-foreground">{tx('以下文件保留原输入坐标，包含本软件区域扩展；这不是完整BIDS数据集导出。请同时保留三个文件。')}</p>
    <p className="mt-1 text-xs text-muted-foreground">{tx('坐标系文件写明这些是Ernie模板头上的设计位置，不是受试者实测位置，并附Ernie模板基准点（NAS、LPA、RPA）。')}</p>
    <div className="mt-3 flex flex-wrap gap-2">{buttons(exportBIDSElectrodes(design))}</div>
    <p className="mt-4 text-xs text-muted-foreground">{tx('MNI文件把同一布局换算到MNI152NLin6Asym（SimNIBS非线性变换，在Ernie头皮上取样）。下颌、耳部和颈部不在换算范围内。')}</p>
    {current?.files
      ? <div className="mt-2 flex flex-wrap gap-2">{buttons(current.files)}</div>
      : <Button className="mt-2" variant="outline" size="sm" disabled={current?.busy} onClick={() => void convert()}>{tx(current?.busy ? '正在换算MNI坐标…' : '换算为MNI坐标文件')}</Button>}
    {current?.error && <p role="alert" className="mt-2 text-sm text-red-800">{tx(current.error)}</p>}
    <p className="mt-4 text-xs text-muted-foreground">{tx('MNE-Python和EEGLAB文件使用同一Ernie坐标（毫米）和模板基准点。MNE读取时须设head_size=None，否则坐标会被缩放到标准球头；EEGLAB读取.sfp时会自动转为鼻尖朝+X的约定。')}</p>
    {montage.files
      ? <div className="mt-2 flex flex-wrap gap-2">{buttons(montage.files)}</div>
      : <p role="alert" className="mt-2 text-sm text-red-800">{tx(montage.error)}</p>}
    <pre className="mt-2 overflow-x-auto rounded bg-muted p-2 text-xs"><code>{"montage = mne.channels.read_custom_montage('electrodes.elc', head_size=None)\nraw.set_montage(montage)\n\nEEG = pop_chanedit(EEG, 'load', {'electrodes.sfp', 'filetype', 'sfp'});"}</code></pre>
  </details>;
}
