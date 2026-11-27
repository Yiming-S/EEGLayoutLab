'use client';

import { useCallback, useEffect, useState } from 'react';
import { Check, Copy, Database, Info, RefreshCw } from 'lucide-react';
import { apiJson } from '@/client/task-client';
import { useLanguage } from '@/components/language-provider';
import { Button } from '@/components/ui/button';
import { SHOWCASE } from '@/lib/showcase';
import { cn } from '@/lib/utils';

export type DataStatus = {
  schema: 'eeglayoutlab-data-status/1';
  installed_form: boolean;
  cache_only: boolean;
  base_ready: boolean;
  base_present: number;
  base_total: number;
  scalp_node_table_ready: boolean;
  direct_fem_available: boolean;
  coordinate_evaluation_ready: boolean;
  heads: string[];
  scenarios: string[];
};

export type DataReadinessScope =
  | 'home'
  | 'design'
  | 'coordinates'
  | 'compare'
  | 'electrodes'
  | 'reception'
  | 'robustness';

export const DATA_STATUS_REFRESH_EVENT = 'eeg:data-status-refresh';

let cachedStatus: DataStatus | null = null;
let inflightRead: Promise<DataStatus | null> | null = null;

async function fetchDataStatus(force = false): Promise<DataStatus | null> {
  if (SHOWCASE) return null;
  if (!force && cachedStatus) return cachedStatus;
  if (!force && inflightRead) return inflightRead;
  const pending = apiJson<DataStatus>('/api/data-status', { timeoutMs: 8000 })
    .then((data) => {
      if (data && data.schema === 'eeglayoutlab-data-status/1') {
        cachedStatus = data;
        return data;
      }
      return null;
    })
    .catch(() => null)
    .finally(() => {
      if (inflightRead === pending) inflightRead = null;
    });
  inflightRead = pending;
  return pending;
}

export function refreshDataStatus() {
  cachedStatus = null;
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new Event(DATA_STATUS_REFRESH_EVENT));
  }
}

export function useDataStatus() {
  const [status, setStatus] = useState<DataStatus | null>(cachedStatus);
  const [refreshing, setRefreshing] = useState(false);

  const reload = useCallback(async (force = true) => {
    if (SHOWCASE) return;
    setRefreshing(true);
    try {
      const next = await fetchDataStatus(force);
      setStatus(next);
    } finally {
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    if (SHOWCASE) return;
    let cancelled = false;
    void fetchDataStatus(false).then((next) => {
      if (!cancelled && next) setStatus(next);
    });
    const onRefresh = () => {
      void fetchDataStatus(true).then((next) => {
        if (!cancelled) setStatus(next);
      });
    };
    window.addEventListener(DATA_STATUS_REFRESH_EVENT, onRefresh);
    return () => {
      cancelled = true;
      window.removeEventListener(DATA_STATUS_REFRESH_EVENT, onRefresh);
    };
  }, []);

  return { status, refreshing, reload: () => reload(true) };
}

export type DataInstallErrorHint = {
  command: string;
  suffix: string;
};

/** Maps missing-data or missing-SimNIBS worker diagnostics to an actionable CLI install command. */
export function dataInstallCommandForError(message: string): DataInstallErrorHint | null {
  if (!message) return null;
  const headMatch = /头模\s+([a-z0-9_-]+)\s+的头皮节点表尚未预计算/i.exec(message);
  if (headMatch) {
    return {
      command: `eeglayoutlab data install head-${headMatch[1]}`,
      suffix: '安装跨头模示例数据包（或指定 head-<编号>）后重试。',
    };
  }
  if (message.includes('该头模或其头皮节点表尚未预计算')) {
    return {
      command: 'eeglayoutlab data install --examples',
      suffix: '安装跨头模示例数据包（或指定 head-<编号>）后重试。',
    };
  }
  if (
    message.includes('名义头皮节点表') ||
    message.includes('需要预计算头皮节点表，本安装没有') ||
    /No module named ['"]simnibs['"]/i.test(message) ||
    (/\bernie\.msh\b|\bm2m_Ernie\b/i.test(message) && /not found|不存在|No such file|ENOENT/i.test(message))
  ) {
    return {
      command: 'eeglayoutlab data install scalp-node-table',
      suffix: '安装头皮节点表后重试。',
    };
  }
  if (message.includes('current_multiregion_bank') || message.includes('基础模型数据')) {
    return {
      command: 'eeglayoutlab data install',
      suffix: '安装基础模型数据后重试。',
    };
  }
  if (message.includes('头皮节点表尚未预计算')) {
    return {
      command: 'eeglayoutlab data install',
      suffix: '安装所需数据包后重试。',
    };
  }
  return null;
}

type NoticeSpec = {
  tone: 'warning' | 'info';
  title: string;
  body: string;
  command: string;
  secondaryLead?: string;
  secondaryCommand?: string;
};

export function resolveDataNotice(
  status: DataStatus | null,
  scope: DataReadinessScope,
): NoticeSpec | null {
  if (!status || status.cache_only) return null;

  if (!status.base_ready) {
    const bothMissing = !status.scalp_node_table_ready;
    return {
      tone: 'warning',
      title: '尚未安装基础模型数据（base）',
      body: bothMissing
        ? '当前可正常浏览已发表结论与已有记录；运行新的区域搜索、坐标评价、电极编辑或信号仿真前，请在终端安装默认模型数据包（base + scalp-node-table，约 1.80 GB）：'
        : '当前缺少基础模型数据包（base，约 0.41 GB）；请在终端运行以下命令补齐并校验数据后再提交新计算：',
      command: 'eeglayoutlab data install',
      secondaryLead: status.installed_form
        ? '也可运行一键启动命令自动下载校验数据并打开网页：'
        : '源码环境也可运行一键初始化脚本：',
      secondaryCommand: status.installed_form
        ? 'eeglayoutlab quickstart'
        : 'python3 scripts/setup_local.py',
    };
  }

  if (!status.scalp_node_table_ready && !status.direct_fem_available) {
    if (scope === 'coordinates' || scope === 'robustness') {
      return {
        tone: 'warning',
        title: '尚未安装头皮节点表（scalp-node-table）',
        body: '当前环境已安装基础数据（base），但未安装 SimNIBS 有限元求解器；评价导入的外部电极坐标、拟合数据先验或运行稳健性研究需要先安装预计算头皮节点表（约 1.40 GB）：',
        command: 'eeglayoutlab data install scalp-node-table',
      };
    }
    if (scope === 'home') {
      return {
        tone: 'info',
        title: '尚未安装头皮节点表（scalp-node-table）',
        body: '基础模型数据（base）已就绪，可直接运行按区域搜索、电极编辑与默认信号仿真。若需导入并评价自定义电极坐标或运行稳健性研究，请在终端安装头皮节点表（约 1.40 GB）：',
        command: 'eeglayoutlab data install scalp-node-table',
      };
    }
    return null;
  }

  if (!status.scalp_node_table_ready && status.direct_fem_available && scope === 'coordinates') {
    return {
      tone: 'info',
      title: '可选数据包：头皮节点表（scalp-node-table）尚未安装',
      body: '当前可通过本机 SimNIBS 直接求解新坐标的有限元场（单次最多约10分钟）；安装预计算头皮节点表（约 1.40 GB）可将坐标评价加速至数秒，并解锁重戴稳健性与电导率情景检查：',
      command: 'eeglayoutlab data install scalp-node-table',
    };
  }

  return null;
}

export function shouldShowReceptionDirectFemNotice(
  status: DataStatus | null,
  mode: 'multi_source' | 'cross_region' | 'single_source',
  hasCachedResult: boolean,
): boolean {
  return Boolean(
    status &&
      !status.cache_only &&
      status.base_ready &&
      !status.direct_fem_available &&
      mode !== 'multi_source' &&
      !hasCachedResult,
  );
}

export function ReceptionDirectFemNoticeBanner({
  status,
  mode,
  hasCachedResult,
  onSwitchToMultiSource,
  className,
}: {
  status: DataStatus | null;
  mode: 'multi_source' | 'cross_region' | 'single_source';
  hasCachedResult: boolean;
  onSwitchToMultiSource?: () => void;
  className?: string;
}) {
  const { tx } = useLanguage();
  if (!shouldShowReceptionDirectFemNotice(status, mode, hasCachedResult)) return null;
  return (
    <output
      aria-live="polite"
      className={cn(
        'block rounded-xl border border-primary/25 bg-primary/[0.045] px-3.5 py-3 text-xs leading-5 text-foreground',
        className,
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-2.5">
        <div className="min-w-0 flex-1 space-y-1">
          <p className="flex items-center gap-1.5 font-semibold text-foreground">
            <Info aria-hidden className="size-3.5 shrink-0 text-primary" />
            <span>{tx('当前运行环境未配置 SimNIBS 皮层法向求解器')}</span>
          </p>
          <p className="text-ink-soft">
            {tx(
              '已保存的跨区域多源与单源结果可直接读取回放，“区域内6源”模式也可直接运行新仿真；计算未缓存的新皮层法向源场景（v2）需在已安装 SimNIBS 的 macOS Apple Silicon 源码环境中执行。',
            )}
          </p>
        </div>
        {onSwitchToMultiSource && (
          <Button type="button" size="sm" variant="outline" onClick={onSwitchToMultiSource} className="shrink-0">
            {tx('切换到区域内6源模式')}
          </Button>
        )}
      </div>
    </output>
  );
}

export function ReceptionDirectFemNotice({
  mode,
  hasCachedResult,
  onSwitchToMultiSource,
  className,
}: {
  mode: 'multi_source' | 'cross_region' | 'single_source';
  hasCachedResult: boolean;
  onSwitchToMultiSource?: () => void;
  className?: string;
}) {
  const { status } = useDataStatus();
  if (SHOWCASE) return null;
  return (
    <ReceptionDirectFemNoticeBanner
      status={status}
      mode={mode}
      hasCachedResult={hasCachedResult}
      onSwitchToMultiSource={onSwitchToMultiSource}
      className={className}
    />
  );
}

export function DataReadinessBanner({
  status,
  scope,
  refreshing = false,
  onRefresh,
  className,
}: {
  status: DataStatus | null;
  scope: DataReadinessScope;
  refreshing?: boolean;
  onRefresh?: () => void;
  className?: string;
}) {
  const { tx } = useLanguage();
  const [copied, setCopied] = useState(false);
  const spec = resolveDataNotice(status, scope);
  if (!spec) return null;

  const copyCommand = () => {
    if (typeof navigator === 'undefined' || !navigator.clipboard?.writeText) return;
    void navigator.clipboard.writeText(spec.command).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    });
  };

  const isWarning = spec.tone === 'warning';
  return (
    <output
      aria-live="polite"
      className={cn(
        'block rounded-xl border px-4 py-3.5 text-sm shadow-2xs sm:px-5 sm:py-4',
        isWarning
          ? 'border-warning/35 bg-warning-surface/80 text-foreground'
          : 'border-primary/25 bg-primary/[0.045] text-foreground',
        className,
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1 space-y-1.5">
          <p className="flex items-center gap-2 font-semibold">
            <Database
              aria-hidden
              className={cn('size-4 shrink-0', isWarning ? 'text-warning' : 'text-primary')}
            />
            <span>{tx(spec.title)}</span>
          </p>
          <p className="text-[0.8125rem] leading-6 text-ink-soft">{tx(spec.body)}</p>
        </div>
        {onRefresh && (
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={refreshing}
            onClick={onRefresh}
            className="shrink-0"
          >
            <RefreshCw aria-hidden className={cn('size-3.5', refreshing && 'animate-spin')} />
            {tx(refreshing ? '正在重新检查…' : '重新检查数据')}
          </Button>
        )}
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <code className="rounded-lg border border-border bg-card px-3 py-1.5 font-mono text-xs font-medium text-foreground select-all">
          {spec.command}
        </code>
        <Button type="button" size="sm" variant="outline" onClick={copyCommand}>
          {copied ? <Check aria-hidden className="size-3.5" /> : <Copy aria-hidden className="size-3.5" />}
          {tx(copied ? '已复制' : '复制命令')}
        </Button>
      </div>
      {spec.secondaryLead && spec.secondaryCommand && (
        <p className="mt-2 text-xs leading-5 text-muted-foreground">
          {tx(spec.secondaryLead)}{' '}
          <code className="rounded border border-border/80 bg-card/85 px-1.5 py-0.5 font-mono text-[11px] text-foreground">
            {spec.secondaryCommand}
          </code>
        </p>
      )}
      <p className="mt-1.5 text-xs leading-5 text-muted-foreground">
        {tx('安装完成后无需重启服务，点击“重新检查数据”即可立即使用。')}
      </p>
    </output>
  );
}

export function DataReadinessNotice({
  scope,
  className,
}: {
  scope: DataReadinessScope;
  className?: string;
}) {
  const { status, refreshing, reload } = useDataStatus();
  if (SHOWCASE) return null;
  return (
    <DataReadinessBanner
      status={status}
      scope={scope}
      refreshing={refreshing}
      onRefresh={() => {
        refreshDataStatus();
        void reload();
      }}
      className={className}
    />
  );
}
