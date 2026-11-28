'use client';
import { useEffect, useMemo, useState } from 'react';
import { useLanguage } from '@/components/language-provider';
import { Button } from '@/components/ui/button';
import { FilePicker } from '@/components/ui/file-picker';
import { apiJson } from '@/client/task-client';
import { ERNIE_MNI_MAPPING, type Point } from '@/lib/ernie-mni';
import { localizedRecordTitle } from '@/lib/i18n/records';
import type { ElectrodeDesign } from '@/lib/design-decision';
import type { LocalLibrary, SavedRecord, SavedSummary } from '@/lib/local-library';
import {
  ERNIE_CRANIAL_FRAME,
  SUBJECT_HEAD_PRESETS,
  calibrateFromPhotoLandmarks,
  classifyCephalicIndex,
  cephalicClassLabel,
  exportPersonalizedMontageCsv,
  exportPersonalizedMontageJson,
  morphLayoutToSubject,
  type FrontPhotoLandmarks,
  type PhotoLandmark2D,
  type SidePhotoLandmarks,
  type SubjectHeadProfile,
} from '@/lib/head-personalization';
import { cn } from '@/lib/utils';

const DEFAULT_FRONT: FrontPhotoLandmarks = {
  leftTragus: [0.22, 0.58],
  rightTragus: [0.78, 0.58],
  vertexTop: [0.5, 0.14],
};

const DEFAULT_SIDE: SidePhotoLandmarks = {
  nasion: [0.18, 0.52],
  inion: [0.84, 0.58],
  tragus: [0.52, 0.62],
  vertexTop: [0.5, 0.14],
};

const FRONT_KEYS: readonly [keyof FrontPhotoLandmarks, string][] = [
  ['leftTragus', '左耳屏 LPA'],
  ['rightTragus', '右耳屏 RPA'],
  ['vertexTop', '颅顶最高点 Cz'],
];

const SIDE_KEYS: readonly [keyof SidePhotoLandmarks, string][] = [
  ['nasion', '鼻根 Nz'],
  ['inion', '枕外隆凸 Iz'],
  ['tragus', '耳屏中心'],
  ['vertexTop', '颅顶最高点 Cz'],
];

function downloadTextDataUrl(filename: string, content: string, mime: string) {
  const anchor = document.createElement('a');
  anchor.href = `data:${mime};charset=utf-8,${encodeURIComponent(content)}`;
  anchor.download = filename;
  anchor.click();
}

function readImageDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(typeof reader.result === 'string' ? reader.result : '');
    reader.onerror = () => reject(new Error('照片文件读取失败'));
    reader.readAsDataURL(file);
  });
}

export function HeadPhotoPersonalizer({
  importedDesign,
}: {
  importedDesign: ElectrodeDesign | null;
}) {
  const { tx, locale } = useLanguage();
  const [mode, setMode] = useState<'anthropometric' | 'photo'>('anthropometric');
  const [circumferenceMm, setCircumferenceMm] = useState(585);
  const [cephalicIndex, setCephalicIndex] = useState(81.5);
  const [vertexHeightMm, setVertexHeightMm] = useState(134);
  const [profileLabel, setProfileLabel] = useState('自定义个体头型');

  const [frontImg, setFrontImg] = useState<string>('');
  const [sideImg, setSideImg] = useState<string>('');
  const [frontMarks, setFrontMarks] = useState<FrontPhotoLandmarks>(DEFAULT_FRONT);
  const [sideMarks, setSideMarks] = useState<SidePhotoLandmarks>(DEFAULT_SIDE);
  const [activeFrontKey, setActiveFrontKey] = useState<keyof FrontPhotoLandmarks>('leftTragus');
  const [activeSideKey, setActiveSideKey] = useState<keyof SidePhotoLandmarks>('nasion');
  const [photoError, setPhotoError] = useState('');
  // Landmarks the user has clicked on the current photos; the defaults are only a guide.
  const [placedFront, setPlacedFront] = useState<ReadonlySet<string>>(() => new Set());
  const [placedSide, setPlacedSide] = useState<ReadonlySet<string>>(() => new Set());
  // True only while the shown profile is the solve of the current photos and landmarks.
  const [photoSolved, setPhotoSolved] = useState(false);

  const [library, setLibrary] = useState<SavedSummary[]>([]);
  const [libraryState, setLibraryState] = useState<'loading' | 'ready' | 'error'>('loading');
  const [selectedRecordId, setSelectedRecordId] = useState<string>('');
  const [loadedRecord, setLoadedRecord] = useState<SavedRecord | null>(null);
  const [failedId, setFailedId] = useState<string | null>(null);
  // Until the user picks one, the imported design (when there is one) or the newest saved layout is shown.
  const activeId = selectedRecordId || (importedDesign ? '__imported__' : library[0]?.id ?? '');
  const recordId = activeId && activeId !== '__imported__' ? activeId : null;

  useEffect(() => {
    const ctrl = new AbortController();
    apiJson<LocalLibrary>('/api/local-compute/library', { signal: ctrl.signal })
      .then((res) => {
        setLibrary(res.records.filter((r) => r.status === 'completed'));
        setLibraryState('ready');
      })
      .catch(() => {
        if (!ctrl.signal.aborted) setLibraryState('error');
      });
    return () => ctrl.abort();
  }, []);

  useEffect(() => {
    if (!recordId) return;
    const ctrl = new AbortController();
    apiJson<{ record: SavedRecord }>('/api/local-compute/library/' + recordId, {
      signal: ctrl.signal,
    })
      .then((res) => setLoadedRecord(res.record))
      .catch(() => {
        if (!ctrl.signal.aborted) setFailedId(recordId);
      });
    return () => ctrl.abort();
  }, [recordId]);

  const importedSource = useMemo(
    () =>
      importedDesign
        ? {
            name: importedDesign.name || '已导入布局',
            xyzMm: importedDesign.xyz_mm as Point[],
            regionIndices: importedDesign.region_indices,
            electrodeNames: importedDesign.electrode_names,
          }
        : null,
    [importedDesign],
  );

  // Null while the catalog or the chosen record is loading, or when the record has no coordinates.
  const activeSource = useMemo(() => {
    if (!recordId) {
      if (importedSource) return importedSource;
      if (libraryState === 'loading') return null;
      // No saved layout and no import: the labelled 16-ch frontal + bilateral ear example from the Ernie cap.
      const compactNames = [
        'Fp1', 'Fpz', 'Fp2', 'AF7', 'AF3', 'AF4', 'AF8', 'Fz',
        'FT7', 'T7', 'TP7', 'P7', 'FT8', 'T8', 'TP8', 'P8',
      ];
      const mapByName = new Map(
        ERNIE_MNI_MAPPING.labels.positions_mm.map((r) => [
          String(r[0]),
          [Number(r[1]), Number(r[2]), Number(r[3])] as Point,
        ]),
      );
      const pts = compactNames.map((n) => mapByName.get(n)!).filter(Boolean);
      return {
        name: '16导前额+双耳周穿戴示例',
        xyzMm: pts,
        regionIndices: pts.map((_, i) => (i < 8 ? 0 : i < 12 ? 1 : 2)),
        electrodeNames: compactNames,
      };
    }
    if (loadedRecord?.id !== recordId || !loadedRecord.layout?.xyzMm?.length) return null;
    return {
      name: localizedRecordTitle(loadedRecord, locale),
      xyzMm: loadedRecord.layout.xyzMm as Point[],
      regionIndices:
        loadedRecord.layout.regionIndices ?? loadedRecord.layout.xyzMm.map(() => 0),
      electrodeNames: undefined,
    };
  }, [recordId, importedSource, libraryState, loadedRecord, locale]);
  const sourceUnavailable =
    !activeSource &&
    (recordId ? failedId === recordId || loadedRecord?.id === recordId : libraryState === 'error');

  const profile: SubjectHeadProfile = useMemo(
    () => ({
      id: 'custom_subject',
      label: profileLabel,
      circumferenceMm,
      cephalicIndex,
      vertexHeightMm,
    }),
    [profileLabel, circumferenceMm, cephalicIndex, vertexHeightMm],
  );

  const personalized = useMemo(
    () =>
      activeSource &&
      morphLayoutToSubject(
        activeSource.xyzMm,
        activeSource.regionIndices,
        profile,
        activeSource.electrodeNames,
      ),
    [activeSource, profile],
  );

  function applyPhotoCalibration() {
    setPhotoError('');
    try {
      const calibrated = calibrateFromPhotoLandmarks(
        frontMarks,
        sideMarks,
        circumferenceMm,
        '照片标定受试者',
      );
      setCephalicIndex(calibrated.cephalicIndex);
      setVertexHeightMm(calibrated.vertexHeightMm);
      setProfileLabel(calibrated.label);
      setPhotoSolved(true);
    } catch (e) {
      setPhotoSolved(false);
      setPhotoError(e instanceof Error ? e.message : '照片标志点标定失败');
    }
  }
  const photoMissing = [
    ...(frontImg ? [] : ['选择正视图']),
    ...FRONT_KEYS.filter(([k]) => !placedFront.has(k)).map(([, label]) => label),
    ...(sideImg ? [] : ['选择侧视图']),
    ...SIDE_KEYS.filter(([k]) => !placedSide.has(k)).map(([, label]) => label),
  ];
  const photoPending = mode === 'photo' && !photoSolved;

  const regionColors = ['#2563eb', '#0d9488', '#d97706', '#9333ea', '#e11d48', '#0284c7'];

  return (
    <section
      className="lab-panel mt-5 space-y-4"
      aria-labelledby="head-personalizer-heading"
      data-head-photo-personalizer
    >
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border pb-4">
        <div className="max-w-3xl">
          <p className="lab-eyebrow">{tx('个体头型适配 · 照片标志点与三维解剖配准')}</p>
          <h2 id="head-personalizer-heading" className="mt-1 text-lg font-semibold">
            {tx('针对具体使用者的个体化电极布局建议')}
          </h2>
          <p className="mt-1 text-sm leading-6 text-muted-foreground">
            {tx(
              '不同头围、长圆头型（头长宽指数 CI）与颅顶曲率会让最佳电极落点产生数毫米至十余毫米偏移。上传受试者正侧面头型照片点选标志点，或直接输入头围与头型参数，即可将该实验场景的最佳布局映射为该受试者的专属三维电极坐标。',
            )}
          </p>
        </div>
        <div
          className="inline-flex rounded-lg border border-border bg-secondary/65 p-0.5 text-xs"
          role="tablist"
          aria-label={tx('个体头型标定方式')}
        >
          {(
            [
              ['anthropometric', '头围与头型参数'],
              ['photo', '正侧面头型照片标定'],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={mode === id}
              onClick={() => setMode(id)}
              className={cn(
                'rounded-md px-3 py-1.5 font-medium transition-colors',
                mode === id
                  ? 'bg-card text-foreground shadow-2xs'
                  : 'text-muted-foreground hover:text-foreground',
              )}
            >
              {tx(label)}
            </button>
          ))}
        </div>
      </div>

      <div className="grid items-start gap-5 lg:grid-cols-[1.08fr_0.92fr]">
        <div className="space-y-4">
          <label className="lab-label">
            {tx('选择要适配的源布局方案（支持8–64导任意已算方案或上方导入布局）')}
            <select
              className="lab-select mt-1.5"
              value={activeId}
              onChange={(e) => setSelectedRecordId(e.target.value)}
            >
              {importedDesign && (
                <option value="__imported__">
                  {tx('上方当前导入的设计')} · {importedDesign.name} (
                  {importedDesign.xyz_mm.length} {tx('电极')})
                </option>
              )}
              {library.slice(0, 30).map((rec) => (
                <option key={rec.id} value={rec.id}>
                  {localizedRecordTitle(rec, locale)}
                </option>
              ))}
              {!importedDesign && library.length === 0 && (
                <option value="">
                  {tx(libraryState === 'loading' ? '读取方案目录…' : '16导前额+双耳周穿戴示例')}
                </option>
              )}
            </select>
          </label>

          {mode === 'anthropometric' ? (
            <div className="space-y-3.5 rounded-xl border border-border/80 bg-muted/25 p-4">
              <div className="space-y-1.5">
                <span className="text-xs font-medium text-foreground">
                  {tx('一键切换典型头型样本')}
                </span>
                <div className="grid gap-1.5 sm:grid-cols-2">
                  {SUBJECT_HEAD_PRESETS.map((preset) => {
                    const active =
                      Math.abs(circumferenceMm - preset.circumferenceMm) < 0.5 &&
                      Math.abs(cephalicIndex - preset.cephalicIndex) < 0.2;
                    return (
                      <button
                        key={preset.id}
                        type="button"
                        onClick={() => {
                          setCircumferenceMm(preset.circumferenceMm);
                          setCephalicIndex(preset.cephalicIndex);
                          setVertexHeightMm(preset.vertexHeightMm);
                          setProfileLabel(preset.label);
                        }}
                        className={cn(
                          'rounded-lg border px-3 py-2 text-left text-xs font-medium transition-colors',
                          active
                            ? 'border-primary bg-primary/10 text-primary'
                            : 'border-border bg-card text-ink-soft hover:border-foreground/30',
                        )}
                      >
                        {tx(preset.label)}
                      </button>
                    );
                  })}
                </div>
              </div>

              <label className="lab-label text-xs">
                <span className="flex justify-between">
                  <span>{tx('受试者水平头围')}</span>
                  <span className="font-mono font-semibold text-foreground tabular-nums">
                    {(circumferenceMm / 10).toFixed(1)} cm ({circumferenceMm} mm)
                  </span>
                </span>
                <input
                  type="range"
                  aria-label={tx('受试者水平头围')}
                  min={500}
                  max={635}
                  step={1}
                  value={circumferenceMm}
                  onChange={(e) => {
                    setCircumferenceMm(Number(e.target.value));
                    setProfileLabel('自定义个体头型');
                  }}
                  className="mt-1.5 block w-full accent-primary"
                />
              </label>

              <label className="lab-label text-xs">
                <span className="flex justify-between">
                  <span>{tx('头长宽指数 CI（100 × 头宽 ÷ 头长）')}</span>
                  <span className="font-mono font-semibold text-foreground tabular-nums">
                    {cephalicIndex.toFixed(1)} · {tx(cephalicClassLabel(classifyCephalicIndex(cephalicIndex)))}
                  </span>
                </span>
                <input
                  type="range"
                  aria-label={tx('头长宽指数 CI（100 × 头宽 ÷ 头长）')}
                  min={70}
                  max={89}
                  step={0.2}
                  value={cephalicIndex}
                  onChange={(e) => {
                    setCephalicIndex(Number(e.target.value));
                    setProfileLabel('自定义个体头型');
                  }}
                  className="mt-1.5 block w-full accent-primary"
                />
              </label>

              <label className="lab-label text-xs">
                <span className="flex justify-between">
                  <span>{tx('双耳连线至颅顶高度')}</span>
                  <span className="font-mono font-semibold text-foreground tabular-nums">
                    {vertexHeightMm.toFixed(1)} mm
                  </span>
                </span>
                <input
                  type="range"
                  aria-label={tx('双耳连线至颅顶高度')}
                  min={114}
                  max={150}
                  step={0.5}
                  value={vertexHeightMm}
                  onChange={(e) => {
                    setVertexHeightMm(Number(e.target.value));
                    setProfileLabel('自定义个体头型');
                  }}
                  className="mt-1.5 block w-full accent-primary"
                />
              </label>
            </div>
          ) : (
            <div className="space-y-3.5 rounded-xl border border-border/80 bg-muted/25 p-4">
              <p className="text-xs leading-5 text-muted-foreground">
                {tx(
                  '照片仅在本地浏览器内存中读取，不上传任何服务器。分别上传正视图与侧视图，选择要标定的解剖点后在图上点击位置，结合实测头围即可消去拍摄距离差异并解算三维头型比例。',
                )}
              </p>
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-2 rounded-lg border border-border bg-card p-2.5">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs font-semibold">{tx('1 · 正面头型照')}</span>
                    <FilePicker
                      accept="image/*"
                      buttonLabel="选择正视图"
                      onChange={async (e) => {
                        const f = e.target.files?.[0];
                        if (!f) return;
                        setFrontImg(await readImageDataUrl(f));
                        setPlacedFront(new Set());
                        setPhotoSolved(false);
                      }}
                    />
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {FRONT_KEYS.map(([k, label]) => (
                      <button
                        key={k}
                        type="button"
                        onClick={() => setActiveFrontKey(k)}
                        className={cn(
                          'rounded border px-2 py-0.5 text-[11px]',
                          activeFrontKey === k
                            ? 'border-primary bg-primary/10 font-medium text-primary'
                            : 'border-border text-muted-foreground',
                        )}
                      >
                        {tx(label)}
                      </button>
                    ))}
                  </div>
                  <button
                    type="button"
                    aria-label={tx('1 · 正面头型照')}
                    className="block w-full cursor-crosshair rounded-md border border-border/70 bg-secondary/40 p-0"
                    onClick={(e) => {
                      const rect = e.currentTarget.getBoundingClientRect();
                      const pt: PhotoLandmark2D = [
                        Math.max(0.02, Math.min(0.98, (e.clientX - rect.left) / rect.width)),
                        Math.max(0.02, Math.min(0.98, (e.clientY - rect.top) / rect.height)),
                      ];
                      setFrontMarks((prev) => ({ ...prev, [activeFrontKey]: pt }));
                      setPlacedFront((prev) => new Set(prev).add(activeFrontKey));
                      setPhotoSolved(false);
                    }}
                  >
                    <svg viewBox="0 0 200 200" className="block w-full">
                      {frontImg ? (
                        <image href={frontImg} x="0" y="0" width="200" height="200" preserveAspectRatio="xMidYMid meet" />
                      ) : (
                        <ellipse cx="100" cy="108" rx="56" ry="74" fill="none" stroke="currentColor" strokeOpacity="0.28" strokeDasharray="4 3" />
                      )}
                      <line
                        x1={frontMarks.leftTragus[0] * 200}
                        y1={frontMarks.leftTragus[1] * 200}
                        x2={frontMarks.rightTragus[0] * 200}
                        y2={frontMarks.rightTragus[1] * 200}
                        stroke="#2563eb"
                        strokeWidth="1.5"
                        strokeDasharray="3 2"
                      />
                      {FRONT_KEYS.map(([k, label]) => {
                        const [nx, ny] = frontMarks[k];
                        return (
                          <g key={k} opacity={placedFront.has(k) ? 1 : 0.4}>
                            <circle cx={nx * 200} cy={ny * 200} r="4.5" fill="#2563eb" stroke="#ffffff" strokeWidth="1.5" />
                            <text x={nx * 200} y={ny * 200 - 8} textAnchor="middle" fontSize="9.5" fill="currentColor">
                              {tx(label)}
                            </text>
                          </g>
                        );
                      })}
                    </svg>
                  </button>
                </div>

                <div className="space-y-2 rounded-lg border border-border bg-card p-2.5">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs font-semibold">{tx('2 · 侧面头型照')}</span>
                    <FilePicker
                      accept="image/*"
                      buttonLabel="选择侧视图"
                      onChange={async (e) => {
                        const f = e.target.files?.[0];
                        if (!f) return;
                        setSideImg(await readImageDataUrl(f));
                        setPlacedSide(new Set());
                        setPhotoSolved(false);
                      }}
                    />
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {SIDE_KEYS.map(([k, label]) => (
                      <button
                        key={k}
                        type="button"
                        onClick={() => setActiveSideKey(k)}
                        className={cn(
                          'rounded border px-1.5 py-0.5 text-[11px]',
                          activeSideKey === k
                            ? 'border-primary bg-primary/10 font-medium text-primary'
                            : 'border-border text-muted-foreground',
                        )}
                      >
                        {tx(label)}
                      </button>
                    ))}
                  </div>
                  <button
                    type="button"
                    aria-label={tx('2 · 侧面头型照')}
                    className="block w-full cursor-crosshair rounded-md border border-border/70 bg-secondary/40 p-0"
                    onClick={(e) => {
                      const rect = e.currentTarget.getBoundingClientRect();
                      const pt: PhotoLandmark2D = [
                        Math.max(0.02, Math.min(0.98, (e.clientX - rect.left) / rect.width)),
                        Math.max(0.02, Math.min(0.98, (e.clientY - rect.top) / rect.height)),
                      ];
                      setSideMarks((prev) => ({ ...prev, [activeSideKey]: pt }));
                      setPlacedSide((prev) => new Set(prev).add(activeSideKey));
                      setPhotoSolved(false);
                    }}
                  >
                    <svg viewBox="0 0 200 200" className="block w-full">
                      {sideImg ? (
                        <image href={sideImg} x="0" y="0" width="200" height="200" preserveAspectRatio="xMidYMid meet" />
                      ) : (
                        <ellipse cx="102" cy="104" rx="68" ry="72" fill="none" stroke="currentColor" strokeOpacity="0.28" strokeDasharray="4 3" />
                      )}
                      <line
                        x1={sideMarks.nasion[0] * 200}
                        y1={sideMarks.nasion[1] * 200}
                        x2={sideMarks.inion[0] * 200}
                        y2={sideMarks.inion[1] * 200}
                        stroke="#0d9488"
                        strokeWidth="1.5"
                        strokeDasharray="3 2"
                      />
                      {SIDE_KEYS.map(([k, label]) => {
                        const [nx, ny] = sideMarks[k];
                        return (
                          <g key={k} opacity={placedSide.has(k) ? 1 : 0.4}>
                            <circle cx={nx * 200} cy={ny * 200} r="4.5" fill="#0d9488" stroke="#ffffff" strokeWidth="1.5" />
                            <text x={nx * 200} y={ny * 200 - 8} textAnchor="middle" fontSize="9.5" fill="currentColor">
                              {tx(label)}
                            </text>
                          </g>
                        );
                      })}
                    </svg>
                  </button>
                </div>
              </div>

              <div className="flex flex-wrap items-end justify-between gap-3">
                <label className="lab-label text-xs">
                  {tx('卷尺实测水平头围基准（mm）')}
                  <input
                    type="number"
                    min={480}
                    max={650}
                    value={circumferenceMm}
                    onChange={(e) => {
                      const n = Number(e.target.value);
                      if (!Number.isFinite(n) || n < 480 || n > 650) return;
                      setCircumferenceMm(n);
                      setPhotoSolved(false);
                    }}
                    className="lab-input mt-1 h-9 w-36 font-mono text-xs tabular-nums"
                  />
                </label>
                <Button
                  type="button"
                  size="sm"
                  onClick={applyPhotoCalibration}
                  disabled={photoMissing.length > 0}
                >
                  {tx('根据正侧面标志点解算个体头型')}
                </Button>
              </div>
              {photoMissing.length > 0 && (
                <p className="text-xs text-muted-foreground">
                  {tx('待完成：')}
                  {locale === 'en' ? ' ' : ''}
                  {photoMissing.map((item) => tx(item)).join(locale === 'en' ? ', ' : '、')}
                </p>
              )}
              {photoError && (
                <p role="alert" className="text-xs text-destructive">
                  {tx(photoError)}
                </p>
              )}
            </div>
          )}

          {personalized ? (
            <>
          {photoPending && (
            <output className="block rounded-lg border border-warning/30 bg-warning-surface px-3 py-2 text-xs text-warning">
              {tx('照片标定尚未成功：下方结果仍是上一次的头型参数，解算成功后才能导出。')}
            </output>
          )}
          <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
            <div className="rounded-xl border border-border/80 bg-card p-3">
              <span className="block text-[11px] text-muted-foreground">{tx('头宽 × 头长')}</span>
              <span className="mt-1 block font-mono text-sm font-semibold tabular-nums">
                {personalized.dimensionsMm.breadthMm.toFixed(1)} ×{' '}
                {personalized.dimensionsMm.lengthMm.toFixed(1)} mm
              </span>
            </div>
            <div className="rounded-xl border border-border/80 bg-card p-3">
              <span className="block text-[11px] text-muted-foreground">{tx('平均点位偏移')}</span>
              <span className="mt-1 block font-mono text-sm font-semibold tabular-nums">
                {personalized.meanShiftMm.toFixed(2)} mm
              </span>
            </div>
            <div className="rounded-xl border border-border/80 bg-card p-3">
              <span className="block text-[11px] text-muted-foreground">{tx('最大点位偏移')}</span>
              <span className="mt-1 block font-mono text-sm font-semibold text-primary tabular-nums">
                {personalized.maxShiftMm.toFixed(2)} mm
              </span>
            </div>
            <div className="rounded-xl border border-border/80 bg-card p-3">
              <span className="block text-[11px] text-muted-foreground">{tx('个体最小电极间距')}</span>
              <span
                className={cn(
                  'mt-1 block font-mono text-sm font-semibold tabular-nums',
                  personalized.spacingSafe ? 'text-success' : 'text-warning',
                )}
              >
                {personalized.subjectMinSpacingMm.toFixed(2)} mm
              </span>
            </div>
          </div>

          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              size="sm"
              disabled={photoPending}
              onClick={() =>
                downloadTextDataUrl(
                  'eeg-personalized-subject-montage.csv',
                  exportPersonalizedMontageCsv(personalized),
                  'text/csv',
                )
              }
            >
              {tx('导出个体专属电极坐标 CSV')}
            </Button>
            <Button
              type="button"
              size="sm"
              disabled={photoPending}
              variant="outline"
              onClick={() =>
                downloadTextDataUrl(
                  'eeg-personalized-subject-montage.json',
                  exportPersonalizedMontageJson(personalized, activeSource!.name),
                  'application/json',
                )
              }
            >
              {tx('导出个体专属方案 JSON')}
            </Button>
          </div>
            </>
          ) : (
            <output className="block rounded-xl border border-border/80 bg-card p-3 text-sm text-muted-foreground">
              {tx(sourceUnavailable ? '指定记录无法读取，请刷新记录或重新选择。' : '读取方案目录…')}
            </output>
          )}
        </div>

        {personalized && (
        <div className="rounded-xl border border-border/80 bg-card p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-sm font-semibold">
              {tx('俯视双轮廓对照：模板头 vs 个体头型电极偏移')}
            </h3>
            <span className="font-mono text-xs text-muted-foreground tabular-nums">
              {personalized.rows.length} {tx('电极')} · CI {cephalicIndex.toFixed(1)}
            </span>
          </div>
          <svg
            viewBox="-125 -135 250 265"
            className="mx-auto mt-3 block max-h-[340px] w-full"
            aria-label={tx('个体头型与模板头电极位置俯视对照图')}
          >
            <title>{tx('个体头型与模板头电极位置俯视对照图')}</title>
            {/* Nose indicator */}
            <path
              d={`M -12 ${-(personalized.dimensionsMm.lengthMm / 2) * 0.96} L 0 ${-(personalized.dimensionsMm.lengthMm / 2) * 1.09} L 12 ${-(personalized.dimensionsMm.lengthMm / 2) * 0.96}`}
              fill="none"
              stroke="currentColor"
              strokeOpacity="0.65"
              strokeWidth="1.6"
            />
            {/* Template Ernie head contour (dashed) */}
            <ellipse
              cx="0"
              cy="0"
              rx={ERNIE_CRANIAL_FRAME.breadthMm / 2}
              ry={ERNIE_CRANIAL_FRAME.lengthMm / 2}
              fill="none"
              stroke="currentColor"
              strokeOpacity="0.3"
              strokeWidth="1.2"
              strokeDasharray="4 3"
            />
            {/* Subject individual head contour (solid accent) */}
            <ellipse
              cx="0"
              cy="0"
              rx={personalized.dimensionsMm.breadthMm / 2}
              ry={personalized.dimensionsMm.lengthMm / 2}
              fill="currentColor"
              fillOpacity="0.03"
              stroke="#2563eb"
              strokeWidth="1.75"
            />
            {/* Electrode shift vectors & dots */}
            {personalized.rows.map((row) => {
              const tx0 = row.templateMm[0] - ERNIE_CRANIAL_FRAME.origin[0];
              const ty0 = -(row.templateMm[1] - ERNIE_CRANIAL_FRAME.origin[1]);
              const sx0 = row.subjectMm[0] - ERNIE_CRANIAL_FRAME.origin[0];
              const sy0 = -(row.subjectMm[1] - ERNIE_CRANIAL_FRAME.origin[1]);
              const color = regionColors[row.region % regionColors.length];
              return (
                <g key={row.index}>
                  <line
                    x1={tx0}
                    y1={ty0}
                    x2={sx0}
                    y2={sy0}
                    stroke={color}
                    strokeOpacity="0.55"
                    strokeWidth="1.2"
                  />
                  <circle cx={tx0} cy={ty0} r="2.1" fill="none" stroke="currentColor" strokeOpacity="0.38" strokeWidth="1" />
                  <circle cx={sx0} cy={sy0} r="3.4" fill={color} stroke="#ffffff" strokeWidth="0.9">
                    <title>
                      {`${row.name}: (${row.subjectMm[0].toFixed(1)}, ${row.subjectMm[1].toFixed(1)}, ${row.subjectMm[2].toFixed(1)}) mm · Δ=${row.shiftMm.toFixed(2)} mm`}
                    </title>
                  </circle>
                </g>
              );
            })}
          </svg>
          <div className="mt-2 flex flex-wrap items-center justify-center gap-4 text-[11px] text-muted-foreground">
            <span className="inline-flex items-center gap-1.5">
              <span className="inline-block w-4 border-t border-dashed border-foreground/50" />
              {tx('Ernie 标准模板轮廓')}
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="inline-block w-4 border-t-2 border-primary" />
              {tx('当前个体头型轮廓与专属落点')}
            </span>
          </div>
        </div>
        )}
      </div>
    </section>
  );
}
