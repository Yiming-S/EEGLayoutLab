import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { exampleLayout, recentLayouts } from '../lib/layout-page.ts';
import { localizedRecordTitle } from '../lib/i18n/records.ts';
import { translateText } from '../lib/i18n/core.ts';
import { recordTitle } from '../lib/ui-language.ts';
import { TERMS } from '../lib/term-hints.ts';
import { movedSection } from '../lib/method-index.ts';

const hex = c => c.repeat(64);
const row = (id, key, day, extra = {}) => ({ id: hex(id), layout_key: key, dataset_id: 'design_evaluation', status: 'completed', region_count: 2,
  mode: 'imported_coordinates', label: 'cap', finished_at: `2026-11-${String(day).padStart(2, '0')}T10:00:00Z`, ...extra });

void test('recent layouts list each layout once, newest first, with its nominal evaluation first', () => {
  const records = [
    row('a', 'k1', 1),
    row('b', 'k1', 9, { evaluation_condition: { head: 'm2m_sub01' } }),
    row('c', 'k2', 5),
    row('d', 'k3', 3, { status: 'failed' }),
    row('e', undefined, 8),
  ];
  const groups = recentLayouts(records, 6);
  // A completed record without coordinates (no layout key) is its own entry.
  assert.deepEqual(groups.map(group => group[0].layout_key ?? group[0].id), ['k1', hex('e'), 'k2']);
  // The head-model run is the most recent, so its layout leads; the nominal record still names it.
  assert.deepEqual(groups[0].map(record => record.id), [hex('a'), hex('b')]);
  assert.equal(recentLayouts(records, 1).length, 1);
});

void test('the example layout is the one evaluated under the most conditions, then the most recent', () => {
  assert.equal(exampleLayout([]), null);
  assert.equal(exampleLayout([row('a', 'k1', 1), row('b', 'k1', 2), row('c', 'k2', 9)]), 'k1');
  assert.equal(exampleLayout([row('a', 'k1', 1), row('c', 'k2', 9)]), 'k2');
  assert.equal(exampleLayout([row('d', 'k3', 3, { status: 'failed' })]), null);
});

void test('a coordinate evaluation whose label already names its regions or evaluation states each once', () => {
  const named = row('a', 'k1', 1, { label: '2区 · AL + AR · 半径≤35 mm' });
  assert.equal(localizedRecordTitle(named, 'zh-CN'), '2区 · AL + AR · 半径≤35 mm · 已评价坐标');
  assert.equal(localizedRecordTitle(named, 'en'), '2区 · AL + AR · 半径≤35 mm · evaluated coordinates');
  assert.equal(recordTitle(named), '2区 · AL + AR · 半径≤35 mm · 已评价坐标');
  // A different count, or a label that only starts with the digit, keeps the prefix.
  for (const label of ['3区 · FL', '20区', 'cap']) assert.match(localizedRecordTitle({ ...named, label }, 'zh-CN'), /^2个区域 · /, label);
  assert.match(localizedRecordTitle({ ...named, label: 'cap' }, 'en'), /^2 regions · cap · evaluated coordinates$/);
  // A label copied from an earlier title carries both; neither repeats.
  const copied = { ...named, label: '2个区域 · standard64 via MNI · 已评价坐标' };
  for (const locale of ['zh-CN', 'en']) assert.equal(localizedRecordTitle(copied, locale), copied.label, locale);
  assert.equal(recordTitle(copied), copied.label);
});

void test('each term hint has both languages and opens an existing method chapter', () => {
  for (const [term, { question, text, hash }] of Object.entries(TERMS)) {
    assert.ok(movedSection(hash), term);
    for (const source of [question, text]) assert.doesNotMatch(translateText(source, 'en'), /[㐀-鿿]/, source);
  }
});

void test('the home page starts newcomers with the question, three goals and how to read a score', () => {
  const home = readFileSync('features/workspace/home-workspace.tsx', 'utf8');
  for (const href of ["'/findings?ar='", "'/coordinates?ar='", "'/design?ar='"]) assert.ok(home.includes(href), href);
  const texts = [...home.matchAll(/tx\('([^']+)'\)/g)].map(match => match[1]);
  for (const text of ['从这里开始', '打开示例布局', '怎么读分数', '我已了解，收起', '新手入门']) assert.ok(texts.includes(text), text);
  for (const text of texts) assert.doesNotMatch(translateText(text, 'en'), /[㐀-鿿]/, text);
  // The browser remembers a closed panel; reading storage never breaks the page.
  assert.match(home, /try \{ dismissed = localStorage\.getItem\(START_DISMISSED_KEY\)/);
});

void test('the header shows the current-layout bar only when a layout is selected or being drafted', () => {
  const header = readFileSync('components/site-header.tsx', 'utf8');
  assert.match(header, /\{\(selection\.id \|\| selection\.phase !== 'saved'\) && <div\s+aria-label=\{tx\('当前布局'\)\}/);
});
