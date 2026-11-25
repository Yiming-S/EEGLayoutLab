import test from 'node:test';
import assert from 'node:assert/strict';
import { matchesSearch, parseSearch, searchTarget, unmatchedWords } from '../lib/library-search.ts';

// Records as the layout list sees them: their titles in both languages, and the facts of the catalog entry.
const earBack = searchTarget(['2个区域 · 左耳后邻近区 + 右耳后邻近区 · 半径≤35 mm', '2 regions · Left postauricular vicinity + Right postauricular vicinity · radius ≤35 mm'],
  { regionCount: 2, electrodeCount: 64, locations: ['PL', 'PR'], ids: ['3a5f9c0d1e2b4a6c'] });
const earAround = searchTarget(['2区 · AL + AR · 半径≤35 mm · 已评价坐标', '2 regions · AL + AR · radius ≤35 mm · evaluated coordinates'], { regionCount: 2, electrodeCount: 64, locations: ['AL', 'AR'], ids: ['9e4c787ffe1603f1'] });
const forehead = searchTarget(['3个区域 · 全头候选区 · 总面积 ≤ 120 cm²', '3 regions · Whole-head candidate surface · total area ≤ 120 cm²'],
  { regionCount: 3, electrodeCount: 64, locations: ['FM'], ids: ['77aa00bb11cc22dd'] });
const signal = searchTarget(['信号实验 · 额区 · 短时爆发 · 眼电'], { regionCount: 2, electrodeCount: 64, locations: [], ids: ['5555aaaa5555aaaa'] });
const all = { earBack, earAround, forehead, signal };
const found = query => Object.entries(all).filter(([, target]) => matchesSearch(target, parseSearch(query))).map(([name]) => name);

void test('region counts match however they are written', () => {
  for (const query of ['2区', '2个区域', '两个区域', '二区', '双区', '2 个 区域', '２区', '2 regions', 'two-region', 'Two Regions'])
    assert.deepEqual(found(query), ['earBack', 'earAround', 'signal'], query);
  for (const query of ['3区', '三个区', '3 regions']) assert.deepEqual(found(query), ['forehead'], query);
});

void test('sites match by meaning in either language, from the specific word to the general one', () => {
  for (const query of ['耳后', '耳朵后面', '乳突', 'behind the ear', 'postauricular', 'post-auricular']) assert.deepEqual(found(query), ['earBack'], query);
  for (const query of ['耳周', '耳旁', '耳朵周围', 'around the ear', 'periauricular']) assert.deepEqual(found(query), ['earAround'], query);
  for (const query of ['耳', '耳朵', 'ear', 'Ears']) assert.deepEqual(found(query), ['earBack', 'earAround'], query);
  for (const query of ['前额', '额头', 'forehead', '中部前额']) assert.deepEqual(found(query), ['forehead'], query);
  assert.deepEqual(found('左耳后'), ['earBack']);
  assert.deepEqual(found('near'), [], 'an English word is matched whole: "near" is not "ear"');
  assert.deepEqual(found('眼电'), ['signal'], 'interference names keep their meaning');
  assert.deepEqual(found('眼周'), []);
});

void test('several words match in any order, with any spacing, width and punctuation', () => {
  for (const query of ['耳后 2区', '2区 耳后', '  耳后，２区  ', '耳后、2个区域', '耳后2区', '耳后的布局', 'behind ear; 2 regions', '耳后 + 两个区'])
    assert.deepEqual(found(query), ['earBack'], query);
  assert.deepEqual(found('耳后 3区'), []);
});

void test('areas and radii match with or without units and bounds', () => {
  for (const query of ['120', '120cm2', '120 cm²', '120平方厘米', '≤120', '<=120', '面积120', '总面积 120 cm2']) assert.deepEqual(found(query), ['forehead'], query);
  for (const query of ['半径35', '35mm', '35 毫米', 'radius 35', '半径≤35 mm']) assert.deepEqual(found(query), ['earBack', 'earAround'], query);
});

void test('an id is found from six hexadecimal characters, and a short number never matches an id', () => {
  assert.deepEqual(found('9e4c787f'), ['earAround']);
  assert.deepEqual(found('9E4C78'), ['earAround']);
  assert.deepEqual(found('5555'), [], 'four characters are a number, not an id fragment');
  assert.deepEqual(found('77'), [], 'the forehead record has 77 only in its id');
});

void test('an empty query matches every record, and the words no record contains are named as typed', () => {
  assert.deepEqual(parseSearch('  ，、 '), []);
  assert.deepEqual(found(''), Object.keys(all));
  const words = parseSearch('耳后 半径40 Occipital');
  assert.deepEqual(unmatchedWords(words, Object.values(all)), ['40', 'occipital']);
  assert.deepEqual(unmatchedWords(parseSearch('耳后 3区'), Object.values(all)), [], 'each word alone matches some record');
  assert.deepEqual(unmatchedWords(parseSearch('两个区 枕部'), Object.values(all)), ['枕部']);
  assert.deepEqual(unmatchedWords(parseSearch('耳朵后面 两个区 低毛发'), [earAround]), ['耳朵后面', '低毛发'], 'a site word is named as typed');
  for (const word of parseSearch('耳后 耳周 少毛发 全头 左 2区 64电极')) assert.match(word.token, /^(§[a-z0-9]+§)$/, word.word);
});
