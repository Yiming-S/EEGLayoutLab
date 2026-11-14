import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile, readdir } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import ts from 'typescript';
import { builtinModules } from 'node:module';

async function files(root, extensions) {
  const entries = await readdir(root, { withFileTypes: true });
  return (await Promise.all(entries.map(entry => entry.isDirectory()
    ? files(join(root, entry.name), extensions)
    : extensions.some(ext => entry.name.endsWith(ext)) ? [join(root, entry.name)] : []))).flat();
}

async function imports(path) {
  const source = await readFile(path, 'utf8');
  const tree = ts.createSourceFile(path, source, ts.ScriptTarget.Latest, true);
  const names = [];
  function visit(node) {
    const specifier = node.moduleSpecifier;
    if (specifier && ts.isStringLiteral(specifier)) names.push(specifier.text);
    if (ts.isCallExpression(node) && node.expression.kind === ts.SyntaxKind.ImportKeyword &&
        node.arguments.length && ts.isStringLiteral(node.arguments[0])) names.push(node.arguments[0].text);
    ts.forEachChild(node, visit);
  }
  visit(tree);
  return names;
}

void test('browser modules cannot import server or Node implementations', async () => {
  for (const root of ['features', 'client', 'viewer', 'components', 'app', 'lib']) {
    for (const path of await files(root, ['.ts', '.tsx', '.mjs'])) {
      for (const name of await imports(path)) {
        const target = name.startsWith('@/') ? resolve(name.slice(2)) : resolve(dirname(path), name);
        assert.ok(!name.startsWith('node:') && !builtinModules.includes(name) && !target.startsWith(resolve('server') + '/'), `${path} imports ${name}`);
        if (root === 'features') assert.ok(!target.startsWith(resolve('app') + '/'), `${path} imports route ${name}`);
        if (root === 'viewer') for (const forbidden of ['app', 'features', 'client', 'components']) {
          assert.ok(!target.startsWith(resolve(forbidden) + '/'), `${path} imports ${name}`);
        }
      }
    }
  }
});

void test('framework hosting stays outside the scientific service modules', async () => {
  for (const path of await files(resolve('server'), ['.mjs'])) {
    if (path.startsWith(resolve('server/host') + '/')) continue;
    for (const name of await imports(path)) assert.ok(!/^(vinext|vite)(\/|$)/.test(name), `${path} imports framework ${name}`);
  }
});

void test('shared contracts have no rendering, service, or framework dependencies', async () => {
  const root = resolve('../contracts');
  for (const path of await files(root, ['.ts', '.mjs'])) {
    for (const name of await imports(path)) {
      assert.ok(name.startsWith('.') && resolve(dirname(path), name).startsWith(root + '/'), `${path} imports ${name}`);
    }
  }
});

void test('server modules have no circular runtime imports', async () => {
  const modules = await files(resolve('server'), ['.mjs']);
  const known = new Set(modules), graph = new Map();
  for (const path of modules) graph.set(path, (await imports(path))
    .filter(name => name.startsWith('.')).map(name => resolve(dirname(path), name)).filter(name => known.has(name)));
  const done = new Set();
  function visit(path, stack = []) {
    assert.ok(!stack.includes(path), `Circular import: ${[...stack, path].join(' -> ')}`);
    if (done.has(path)) return;
    for (const child of graph.get(path)) visit(child, [...stack, path]);
    done.add(path);
  }
  for (const path of modules) visit(path);
});
