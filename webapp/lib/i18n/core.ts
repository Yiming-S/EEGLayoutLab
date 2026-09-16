import catalog from './catalog.json' with { type: 'json' };
import editorCatalog from './editor-catalog.json' with { type: 'json' };
import simulationCatalog from './simulation-catalog.json' with { type: 'json' };
import documentationCatalog from './documentation-catalog.json' with { type: 'json' };
import resultsCatalog from './results-catalog.json' with { type: 'json' };
import workspaceCatalog from './workspace-catalog.json' with { type: 'json' };
import homeRefreshCatalog from './home-refresh-catalog.json' with { type: 'json' };
import metricRefreshCatalog from './metric-refresh-catalog.json' with { type: 'json' };
import viewerRefreshCatalog from './viewer-refresh-catalog.json' with { type: 'json' };
import exportRefreshCatalog from './export-refresh-catalog.json' with { type: 'json' };
import sourceRegionsCatalog from './source-regions-catalog.json' with { type: 'json' };

export type Locale = 'en' | 'zh-CN';
export const LANGUAGE_COOKIE = 'eeg-layout-language';
export const LANGUAGE_STORAGE_KEY = 'eeg-layout-language';
export const normalizeText = (text: string) => text.replace(/\s+/g, ' ').trim();

export function resolveLocale(saved?: string | null, acceptLanguage = ''): Locale {
  if (saved === 'en' || saved === 'zh-CN') return saved;
  const preferred = acceptLanguage.split(',').map((entry, index) => {
    const [tag, ...parameters] = entry.trim().split(';');
    const quality = parameters.find((p) => p.trim().startsWith('q='));
    return { tag: tag.toLowerCase(), q: quality ? Number(quality.trim().slice(2)) : 1, index };
  }).filter((v) => v.q > 0).sort((a, b) => b.q - a.q || a.index - b.index)[0];
  return preferred?.tag.startsWith('zh') ? 'zh-CN' : 'en';
}

/** Display terminology only. AR remains an immutable URL/protocol field. */
export function retentionTerminology(text: string): string {
  if (/^(?:PL|PR|AL|AR|FL|FM|FR|OL|OR)$/.test(text)) return text;
  if (/^(?:PL|PR|AL|AR|FL|FM|FR|OL|OR)(?:\s*[,+]\s*(?:PL|PR|AL|AR|FL|FM|FR|OL|OR))+$/.test(text)) return text;
  if (/Pass|â|G\s*[≥=]|≥\s*AR/.test(text)) return text.replace(/\bAR\b/g, 'τ');
  return text
    .replace(/(?:接受阈值|接受率|接受条件)\s*AR/g, '最低保留要求')
    .replace(/AR\s*(?:接受阈值|阈值|接受率)/g, '最低保留要求')
    .replace(/接受阈值|接受率/g, '最低保留要求')
    .replace(/\bAR\b/g, '最低保留要求')
    .replace(/信号重建保留率/g, '场重建保留率')
    .replace(/相对定位评分/g, '定位效用保留率');
}

type Entry = { source: string; en: string; zh?: string };
const entries = [...Object.values(catalog), ...Object.values(editorCatalog), ...Object.values(simulationCatalog), ...Object.values(documentationCatalog), ...Object.values(resultsCatalog), ...Object.values(workspaceCatalog), ...Object.values(homeRefreshCatalog), ...Object.values(metricRefreshCatalog), ...Object.values(viewerRefreshCatalog), ...Object.values(exportRefreshCatalog), ...Object.values(sourceRegionsCatalog)] as Entry[];
const exact = new Map(entries.map((entry) => [normalizeText(entry.source), entry]));
const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const templateToken = /\{\{(\d+)\}\}/g;
const templates = entries.filter((e) => /\{\{\d+\}\}/.test(e.source)).map((entry) => {
  const tokens: number[] = [];
  const pieces = entry.source.split(/(\{\{\d+\}\})/g).map((piece) => {
    const token = /^\{\{(\d+)\}\}$/.exec(piece);
    if (token) { tokens.push(Number(token[1])); return '([\\s\\S]*?)'; }
    return escape(piece);
  });
  return { entry, tokens, regex: new RegExp('^' + pieces.join('') + '$'), weight: entry.source.replace(templateToken, '').length };
}).filter((template) => template.weight >= 4).sort((a, b) => b.weight - a.weight);
// Legacy records assemble labels from stored metadata. Translate only known
// source phrases, longest first; never mutate records or inspect/change the DOM.
const phrases = [...exact.keys()].filter((s) => /[\u3400-\u9fff]/.test(s) && !/\{\{\d+\}\}/.test(s))
  .sort((a, b) => b.length - a.length);
const phrasePattern = phrases.length ? new RegExp(phrases.map(escape).join('|'), 'g') : null;

function translated(text: string, locale: Locale, depth = 0): string {
  const clean = normalizeText(text);
  const direct = exact.get(clean);
  if (direct) return locale === 'en' ? direct.en : direct.zh ?? retentionTerminology(direct.source);
  if (locale === 'zh-CN') return retentionTerminology(text);
  if (depth < 3) for (const { entry, tokens, regex } of templates) {
    const match = regex.exec(clean);
    if (!match) continue;
    const values = new Map(tokens.map((token, i) => [token, translated(match[i + 1], locale, depth + 1)]));
    return entry.en.replace(templateToken, (_, token) => values.get(Number(token)) ?? '');
  }
  return phrasePattern ? text.replace(phrasePattern, (part) => exact.get(part)!.en) : text;
}

export function translateText(text: string, locale: Locale): string {
  if (!text.trim()) return text;
  const leading = text.match(/^\s*/)?.[0] ?? '';
  const trailing = text.match(/\s*$/)?.[0] ?? '';
  const result = translated(text.trim(), locale);
  return leading + (locale === 'en' ? result.replace(/\b1 (regions|electrodes|sources|records|layouts|steps|points|trials)\b/g, (_, noun: string) => '1 ' + noun.slice(0, -1)) : result) + trailing;
}

/** Render-boundary adapter. Elements, callbacks, numbers and data objects keep identity. */
export function localize<T>(value: T, locale: Locale): T {
  if (typeof value === 'string') return translateText(value, locale) as T;
  if (Array.isArray(value)) return value.map((item) => localize(item, locale)) as T;
  return value;
}

export function formatDate(value: string | number | Date, locale: Locale, withTime = false) {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return locale === 'en' ? 'Date unavailable' : '日期不可用';
  return new Intl.DateTimeFormat(locale, withTime
    ? { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' }
    : { year: 'numeric', month: 'short', day: 'numeric' }).format(date);
}
