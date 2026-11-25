/**
 * Free-text search of the layout list. Visitors type in either language, with full- or half-width characters, any
 * spacing or punctuation, and their own words for sites and counts ("耳朵后面", "两个区", "2 regions", "120cm²").
 * Query and record text are normalized the same way. Words that name a region count, an electrode count or a site
 * become markers, and a record carries the markers of its own counts and sites, so these words match by meaning.
 * Every word of the query must match; the order of the words does not matter.
 */

export type SearchFacts = { regionCount?: number | null; electrodeCount?: number | null; locations?: readonly string[]; ids?: readonly string[] };
/** What one record is searched in. Record ids are kept apart: a short number such as "35" must not match an id. */
export type SearchTarget = { text: string; ids: string };
/** One word of a query: the text as typed, and the normalized token a record must contain. */
export type SearchWord = { word: string; token: string };

const NUMBER_WORDS: Record<string, number> = {
  一: 1, 单: 1, 二: 2, 两: 2, 俩: 2, 双: 2, 三: 3, 四: 4, 五: 5, 六: 6,
  one: 1, single: 1, two: 2, three: 3, four: 4, five: 5, six: 6,
};
const count = (value: string) => (/^\d+$/.test(value) ? Number(value) : NUMBER_WORDS[value]);
// Marker names are letters and digits only, so no separator splits them.
const marker = (name: string) => ` §${name}§ `;
// English words only match whole words, so "ear" is not found in "near".
const en = (pattern: string) => `(?<![a-z])(?:${pattern})(?![a-z])`;

/** Rules in order: counts first, then the specific site words before the general ones. */
const MEANINGS: [RegExp, (...groups: string[]) => string][] = [
  // Interference names keep their meaning: "眼电" is not the eye region.
  [new RegExp(`眼电|${en('eog')}`, 'g'), () => marker('eog')],
  [new RegExp(`心电|${en('ecg|ekg')}`, 'g'), () => marker('ecg')],
  [/(\d+|[一二两俩双三四五六单])\s*个?\s*(?:分区|区域|区)/g, (_, n) => marker('r' + count(n))],
  [new RegExp(en('(\\d+|one|two|three|four|five|six|single)[\\s_-]*regions?'), 'g'), (_, n) => marker('r' + count(n))],
  [/(\d+)\s*个?\s*(?:电极|导联|导|通道)/g, (_, n) => marker('e' + Number(n))],
  [new RegExp(`(?<![a-z0-9])(\\d+)[\\s_-]*(?:electrodes?|channels?|ch|leads?)(?![a-z])`, 'g'), (_, n) => marker('e' + Number(n))],
  [new RegExp(`耳朵?(?:后面|后方|后侧|背后|后)|乳突|${en('post[\\s_-]*auricular|behind[\\s_-]*(?:the[\\s_-]*)?ears?|mastoids?')}`, 'g'), () => marker('earback')],
  [new RegExp(`耳朵?(?:周围|周边|旁边|周|旁|边|侧|附近)|${en('peri[\\s_-]*auricular|around[\\s_-]*(?:the[\\s_-]*)?ears?')}`, 'g'), () => marker('eararound')],
  [new RegExp(`耳朵|耳廓|耳|${en('ears?|auricular')}`, 'g'), () => marker('ear')],
  [new RegExp(`前额|额头|额部|脑门|${en('foreheads?|brows?')}`, 'g'), () => marker('forehead')],
  [new RegExp(`眼睛|眼眶|眼周|眼|眶周|眶|眉毛|眉弓|眉|${en('peri[\\s_-]*orbital|orbital|peri[\\s_-]*ocular|eyes?')}`, 'g'), () => marker('eye')],
  [new RegExp(`少毛发|低毛发|无毛发|少发|无发|没有?头发|${en('hairless|low[\\s_-]*hair')}`, 'g'), () => marker('lowhair')],
  [new RegExp(`全头皮|全头|整个?头皮|整头|${en('whole[\\s_-]*(?:head|scalp)')}`, 'g'), () => marker('whole')],
  [new RegExp(`左侧|左边|左|${en('left')}`, 'g'), () => marker('left')],
  [new RegExp(`右侧|右边|右|${en('right')}`, 'g'), () => marker('right')],
  [new RegExp(`中部|中间|中央|正中|${en('middle|central|centre|center')}`, 'g'), () => marker('middle')],
];

const SITE_MARKERS: Record<string, string[]> = {
  PL: ['ear', 'earback', 'left'], PR: ['ear', 'earback', 'right'],
  AL: ['ear', 'eararound', 'left'], AR: ['ear', 'eararound', 'right'],
  FL: ['forehead', 'left'], FM: ['forehead', 'middle'], FR: ['forehead', 'right'],
  OL: ['eye', 'left'], OR: ['eye', 'right'],
  whole: ['whole'], low_hair: ['lowhair'],
};

// Words that describe every record or only join other words.
const FILLER = new Set(['布局', '方案', '记录', '设计', '查找', '搜索', '显示', '找',
  'layout', 'layouts', 'design', 'designs', 'record', 'records', 'plan', 'the', 'a', 'an', 'of', 'with', 'and', 'or', 'in', 'at', 'for', 'on']);
const SEPARATORS = /[\s·•‧・,，、;；:：/\\|+&()（）[\]【】{}<>《》"'“”‘’!！?？=~～≤≥＜＞_\-–—.。]+/g;
const CONNECTORS = /[和与及或的]/g;

function unify(text: string) {
  return text.normalize('NFKC').toLowerCase()
    .replace(/平方厘米|平方公分|cm\s*\^\s*2/g, 'cm2')
    .replace(/毫米/g, 'mm');
}

function tidy(text: string) {
  return text.replace(SEPARATORS, ' ')
    .replace(/(\d)\s+(cm2|mm|cm)(?![a-z0-9])/g, '$1$2')
    // A number written against a Chinese word is its own word: "半径35" holds "半径" and "35".
    .replace(/([㐀-鿿])(?=[a-z0-9])/g, '$1 ').replace(/([a-z0-9])(?=[㐀-鿿])/g, '$1 ')
    .replace(/\s+/g, ' ').trim();
}

/** The text with the words that name a count or a site replaced by markers, and what each marker replaced. */
function meanings(text: string) {
  const typed = new Map<string, string>();
  let rest = text;
  for (const [pattern, replace] of MEANINGS) rest = rest.replace(pattern, (match: string, ...groups: string[]) => {
    const value = replace(match, ...groups), key = value.trim();
    if (!typed.has(key)) typed.set(key, match.trim());
    return value;
  });
  return { rest, typed, markers: [...typed.keys()] };
}

/** The normalized text a record is searched in: its words, the markers they mean and the markers of its facts. */
export function searchTarget(words: readonly string[], facts: SearchFacts = {}): SearchTarget {
  const unified = unify(words.join(' '));
  const markers = new Set(meanings(unified).markers);
  if (facts.regionCount) markers.add(`§r${facts.regionCount}§`);
  if (facts.electrodeCount) markers.add(`§e${facts.electrodeCount}§`);
  for (const location of facts.locations ?? []) for (const name of SITE_MARKERS[location] ?? []) markers.add(`§${name}§`);
  return { text: [tidy(unified), ...markers].join(' '), ids: (facts.ids ?? []).join(' ').toLowerCase() };
}

/** The words of a query, each with the token a record must contain. */
export function parseSearch(query: string): SearchWord[] {
  const { rest, typed } = meanings(unify(query).replace(CONNECTORS, ' '));
  const tokens = [...new Set(tidy(rest).split(' ').filter(token => token && !FILLER.has(token)))];
  return tokens.map(token => ({ word: typed.get(token) ?? token, token }));
}

// An id is found from six of its hexadecimal characters on.
const ID_FRAGMENT = /^[0-9a-f]{6,}$/;

export function matchesSearch(target: SearchTarget, words: readonly SearchWord[]): boolean {
  return words.every(({ token }) => target.text.includes(token) || (ID_FRAGMENT.test(token) && target.ids.includes(token)));
}

/** The words of a query that no record matches, so the page can say which word to change. */
export function unmatchedWords(words: readonly SearchWord[], targets: readonly SearchTarget[]): string[] {
  return words.filter(word => !targets.some(target => matchesSearch(target, [word]))).map(word => word.word);
}
