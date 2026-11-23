// The committed TypeScript request types (contracts/generated/openapi.d.ts) are generated from the committed
// OpenAPI document. tests/test_schema_service.py checks that the document matches the Python schemas.
// Regenerate both with: python -m eeglayoutlab.server.openapi contracts/generated/openapi.json
// and, in webapp/: npm run generate:api-types
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';

const webapp = fileURLToPath(new URL('..', import.meta.url));
const script = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8')).scripts['generate:api-types'];

void test('the generated API types match the committed OpenAPI document', () => {
  assert.match(script, /^openapi-typescript \S+ --default-non-nullable false -o \S+$/);
  const [, ...args] = script.split(' ');
  const cli = fileURLToPath(new URL('../node_modules/openapi-typescript/bin/cli.js', import.meta.url));
  const result = spawnSync(process.execPath, [cli, ...args, '--check'], { cwd: webapp, encoding: 'utf8' });
  assert.equal(result.status, 0, `${result.stdout}${result.stderr}\nRun npm run generate:api-types in webapp/.`);
});
