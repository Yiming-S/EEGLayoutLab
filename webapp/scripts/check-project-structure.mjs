import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { tmpdir } from 'node:os';
import { codeIdentity } from '../server/local-compute-server.mjs';
import { repositoryRootForWebapp, nativePythonPath, DESIGN_WORKFLOW, RECEPTION_WORKFLOW, RECEPTION_V2_WORKFLOW, EDITOR_WORKFLOW } from '../server/project-paths.mjs';

void test('legacy service exports retain class and function identity', async () => {
  for (const name of ['local-compute-server', 'local-data-library', 'local-input-integrity', 'source-reception-server', 'reception-v2-support', 'design-evaluation-server', 'electrode-editor-server', 'experiment-bundle']) {
    const original = await import('../scripts/' + name + '.mjs');
    const current = await import('../server/' + name + '.mjs');
    assert.deepEqual(Object.keys(original), Object.keys(current));
    for (const key of Object.keys(current)) assert.equal(original[key], current[key]);
  }
});

void test('stable routes delegate to feature workspaces and have no service imports', async () => {
  for (const name of ['reception', 'electrodes', 'decision']) {
    const route = await readFile(`app/${name}/page.tsx`, 'utf8');
    assert.match(route, new RegExp(`@/features/${name}/${name}-workspace`));
    assert.ok(route.split('\n').length < 10);
    for (const file of await readdir(`features/${name}`)) {
      const source = await readFile(`features/${name}/${file}`, 'utf8');
      assert.doesNotMatch(source, /from ['"][^'"]*(?:\/server\/|node:)/);
    }
  }
});

void test('checkout roots and independently scoped implementation identities are explicit', async t => {
  const root = repositoryRootForWebapp(resolve('.'));
  assert.equal(root, resolve('..'));
  assert.equal(nativePythonPath(root), resolve('../.runtime/simnibs-4.6.0/bin/python'));
  const fixture = await mkdtemp(join(tmpdir(), 'eeg-source-identity-'));
  t.after(() => rm(fixture, { recursive: true, force: true }));
  for (const path of ['scripts/run_local_radius_compute.py', 'configs/single_head_optimization.json',
    'results/v2/current_multiregion_bank.json', 'results/v2/current_surface_admissibility.json',
    'src/compact_eeg/local_radius_compute.py', 'src/compact_eeg/workflows/other.py']) {
    await mkdir(dirname(join(fixture, path)), { recursive: true });
    await writeFile(join(fixture, path), '{}');
  }
  const identity = codeIdentity(fixture);
  assert.ok(Object.keys(identity).some(p => p === 'src/compact_eeg/local_radius_compute.py'));
  assert.ok(!Object.keys(identity).some(p => p.includes('/workflows/')));
  for (const path of new Set([...DESIGN_WORKFLOW, ...RECEPTION_WORKFLOW, ...RECEPTION_V2_WORKFLOW, ...EDITOR_WORKFLOW])) {
    const body = await readFile(resolve(root, path), 'utf8');
    assert.ok(body.length > 0);
    assert.ok(path.startsWith('src/compact_eeg/workflows/'));
  }
  assert.ok(EDITOR_WORKFLOW.some(p => p.endsWith('/electrode_editor.py')));
  assert.ok(RECEPTION_WORKFLOW.some(p => p.endsWith('/source_reception.py')));
});
