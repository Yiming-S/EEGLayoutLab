'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { FilePicker } from '@/components/ui/file-picker';
import { useLanguage } from '@/components/language-provider';
import type { SavedRecord } from '@/lib/local-library';
import {
  exportDesign,
  parseDesign,
  tryExportDesign,
  type ElectrodeDesign,
} from '@/lib/design-decision';
import {
  bidsNeedsMniSurface,
  parseBIDSElectrodes,
  parseElectrodeLabels,
} from '@/lib/bids-electrodes';
import { loadErnieMniSurface } from '@/lib/ernie-mni';
import { parseBrowserMontageFile, type RegionCount } from '@/lib/head-frame-import';
import type { MontageUnit } from '@/lib/montage-files';
import { downloadTextFile } from './decision-download';

export function CoordinateImportFields({
  draftNotice,
  importError,
  templateSourceRecord,
  onImported,
  onImportError,
}: {
  draftNotice: string;
  importError: string;
  templateSourceRecord?: SavedRecord;
  onImported: (design: ElectrodeDesign) => void;
  onImportError: (message: string) => void;
}) {
  const { tx } = useLanguage();
  // Used only for files without a region column, and for the unit of .sfp files, which declare none.
  const [regionCount, setRegionCount] = useState<RegionCount | 0>(0);
  const [montageUnit, setMontageUnit] = useState<MontageUnit>('mm');
  const importOptions = { regionCount: regionCount || undefined };

  return (
    <>
      {draftNotice && (
        <output className="block rounded-xl border border-primary/25 bg-primary/[0.04] px-3.5 py-2.5 text-xs text-ink-soft">
          {tx(draftNotice)}
        </output>
      )}
      <div className="lab-subpanel space-y-3">
        <label className="lab-label">
          {tx('导入CSV或JSON')}
          <FilePicker
            accept=".csv,.json"
            onChange={async (e) => {
              const file = e.target.files?.[0];
              if (!file) return;
              try {
                if (file.size > 65536) throw new Error('坐标文件上限64 KB');
                onImported(parseDesign(await file.text(), file.name));
              } catch (err) {
                onImportError(err instanceof Error ? err.message : '导入失败');
              }
            }}
          />
        </label>
        <label className="lab-label">
          {tx('没有region列时的区域数')}
          <select
            className="lab-select mt-2"
            value={regionCount}
            onChange={(event) => setRegionCount(Number(event.target.value) as RegionCount | 0)}
          >
            <option value={0}>{tx('不自动分区（文件须含region列）')}</option>
            {[1, 2, 3, 4, 6].map((count) => (
              <option key={count} value={count}>
                {tx(`按空间位置均衡分为${count}区`)}
              </option>
            ))}
          </select>
        </label>
        <p className="text-xs leading-5 text-muted-foreground">
          {tx(
            '数字化坐标和电极名称列表通常没有本软件的region列。选择区域数后，软件把64个电极按位置分成大小均衡的区域，并在坐标来源中记录分区方法。',
          )}
        </p>
      </div>
      <div className="lab-subpanel space-y-2.5">
        <label className="lab-label">
          {tx('导入BIDS坐标文件')}
          <FilePicker
            multiple
            accept=".tsv,.json"
            onChange={async (event) => {
              const files = Array.from(event.target.files ?? []);
              if (!files.length) return;
              try {
                if (files.length > 3 || files.some((file) => file.size > 65536))
                  throw new Error(
                    '请成对选择electrodes.tsv和coordsystem.json，每个文件不超过64 KB。',
                  );
                const coordinateFiles = await Promise.all(
                  files.map(async (file) => ({ name: file.name, text: await file.text() })),
                );
                const parsed = parseBIDSElectrodes(
                  coordinateFiles,
                  bidsNeedsMniSurface(coordinateFiles) ? await loadErnieMniSurface() : undefined,
                  importOptions,
                );
                onImported(parsed);
              } catch (caught) {
                onImportError(caught instanceof Error ? caught.message : '导入失败');
              }
            }}
          />
        </label>
        <p className="text-xs leading-5 text-muted-foreground">
          {tx(
            '同时选择electrodes.tsv和coordsystem.json；region列为本软件的零基区域扩展，可附electrodes.json说明。坐标须为Ernie原生空间或MNI模板空间，单位mm；MNI坐标经SimNIBS非线性变换映射到Ernie头皮。',
          )}
        </p>
        <p className="text-xs leading-5 text-muted-foreground">
          {tx(
            '数字化的头坐标（如CapTrak）须在coordsystem.json中给出NAS、LPA、RPA基准点，单位可为mm、cm或m。软件先按基准点对齐，再拟合到Ernie头皮并投影；这是模板头上的放置，不是个体解剖配准。',
          )}
        </p>
      </div>
      <div className="lab-subpanel space-y-2.5">
        <label className="lab-label">
          {tx('导入MNE或EEGLAB电极文件（.elc、.sfp）')}
          <FilePicker
            accept=".elc,.sfp"
            onChange={async (event) => {
              const file = event.target.files?.[0];
              if (!file) return;
              try {
                if (file.size > 65536) throw new Error('电极坐标文件不超过64 KB。');
                onImported(
                  parseBrowserMontageFile(
                    { name: file.name, text: await file.text() },
                    await loadErnieMniSurface(),
                    { ...importOptions, sfpUnit: montageUnit },
                  ),
                );
              } catch (caught) {
                onImportError(caught instanceof Error ? caught.message : '导入失败');
              }
            }}
          />
        </label>
        <label className="lab-label">
          {tx('.sfp坐标单位')}
          <select
            className="lab-select mt-2"
            value={montageUnit}
            onChange={(event) => setMontageUnit(event.target.value as MontageUnit)}
          >
            {(['mm', 'cm', 'm'] as const).map((unit) => (
              <option key={unit} value={unit}>
                {unit}
              </option>
            ))}
          </select>
        </label>
        <p className="text-xs leading-5 text-muted-foreground">
          {tx(
            '文件须含64个电极和Nz/LPA/RPA（或FidNz/FidT9/FidT10）基准点；.elc自带单位，.sfp没有单位字段，请先选择单位。本软件导出的文件按原坐标读回。',
          )}
        </p>
      </div>
      <div className="lab-subpanel space-y-2.5">
        <label className="lab-label">
          {tx('按10-05电极名称导入')}
          <FilePicker
            accept=".tsv,.csv,.txt"
            onChange={async (event) => {
              const file = event.target.files?.[0];
              if (!file) return;
              try {
                if (file.size > 65536)
                  throw new Error('请选择不超过64 KB的.tsv、.csv或.txt电极名称文件。');
                onImported(
                  parseElectrodeLabels(
                    { name: file.name, text: await file.text() },
                    importOptions,
                  ),
                );
              } catch (caught) {
                onImportError(caught instanceof Error ? caught.message : '导入失败');
              }
            }}
          />
        </label>
        <p className="text-xs leading-5 text-muted-foreground">
          {tx(
            '表头为name和region两列，共64行。位置取SimNIBS 10-05电极帽在Ernie头皮上的模板坐标，与标准64导参考同一来源；T3、T4、T5、T6按T7、T8、P7、P8读取。',
          )}
        </p>
      </div>
      {tx(
        importError && (
          <p
            role="alert"
            className="rounded-lg border border-danger/30 bg-danger-surface/65 px-3 py-2 text-sm text-danger"
          >
            {tx(importError)}
          </p>
        ),
      )}
      {tx(
        tryExportDesign(templateSourceRecord) && (
          <Button
            size="sm"
            variant="outline"
            onClick={() =>
              downloadTextFile(
                'eeg-design-template.json',
                JSON.stringify(exportDesign(templateSourceRecord!), null, 2),
                'application/json',
              )
            }
          >
            {tx('下载带实际坐标的JSON模板')}
          </Button>
        ),
      )}
    </>
  );
}
