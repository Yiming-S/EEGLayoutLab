import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { translateText } from '../lib/i18n/core.ts';

const read = (file) => readFile(new URL('../' + file, import.meta.url), 'utf8');

await test('home leads with the selected layout and separates saved area exploration from new radius designs', async () => {
  const home = (await Promise.all(['features/overview/overview-workspace.tsx', 'features/overview/use-overview-controller.ts'].map(read))).join('\n');
  assert.ok(home.indexOf('id="selected-layout"') < home.indexOf('<table'));
  assert.ok(home.indexOf('<table') < home.indexOf('<PlacementDesignPresets'));
  assert.ok(home.includes('<SavedLayoutDetails') && home.includes(' compact />'));
  const controls = await read('components/placement-options.tsx');
  assert.ok(controls.includes('总面积约束 · 已计算数据'));
  assert.ok(controls.includes('每区半径约束 · 新建设计'));
  assert.ok(controls.includes('不沿用上方总面积约束、不自动计算'));
  assert.ok(controls.includes('REGION_COUNTS.map'));
  const homeControls = controls.slice(controls.indexOf('export function HomePlacementOptions'), controls.indexOf('export function PlacementDesignPresets'));
  assert.ok(!homeControls.includes('<details'));
  assert.ok(!home.includes('method: \'POST\''));
});

await test('selected record owns actions and export; header retains navigation without repeating record actions', async () => {
  const saved = await read('components/saved-layout-details.tsx');
  const header = await read('components/site-header.tsx');
  assert.equal((saved.match(/<LayoutExportMenu /g) ?? []).length, 1);
  assert.ok(saved.includes('compact={compact}'));
  for (const action of ['actions.edit', 'actions.compare', 'actions.reception', 'actions.design']) assert.ok(saved.includes(action));
  assert.ok(header.includes('workspaceLinks('));
  assert.ok(header.includes("tx('更换布局')"));
  assert.ok(!header.includes('layoutCapabilities('));
});

await test('refresh catalogs have complete translations and matching interpolation tokens', async () => {
  const seen = new Set();
  for (const file of ['catalog.json', 'workspace-catalog.json', 'documentation-catalog.json', 'exports-catalog.json', 'editor-catalog.json', 'simulation-catalog.json', 'projects-catalog.json', 'research-workflow-catalog.json']) {
    const catalog = JSON.parse(await read(`lib/i18n/${file}`));
    for (const entry of Object.values(catalog)) {
      const normalized = entry.source.replace(/\s+/g, ' ').trim();
      assert.ok(entry.source && entry.en);
      assert.ok(!seen.has(normalized), entry.source); seen.add(normalized);
      assert.doesNotMatch(entry.en, /[\u3400-\u9fff]/);
      const tokens = (text) => [...text.matchAll(/\{\{\d+\}\}/g)].map(match => match[0]).sort((a, b) => a.localeCompare(b));
      assert.deepEqual(tokens(entry.source), tokens(entry.en), entry.source);
      assert.equal(translateText(entry.source, 'en'), entry.en);
    }
  }
  for (const text of ['已达标 1/3 项', '还差 7.53 个百分点', '用此组合创建设计：左耳后邻近区 + 右耳后邻近区', '前方等待任务：2项；按提交顺序执行。']) {
    assert.doesNotMatch(translateText(text, 'en'), /[\u3400-\u9fff]|\{\{/);
  }
});
