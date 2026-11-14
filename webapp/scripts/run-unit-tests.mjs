import { readdirSync, readFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';

const args = process.argv.slice(2);
if (args.length > 1 || (args.length && args[0] !== '--fast')) throw new Error('Usage: run-unit-tests.mjs [--fast]');
const tier = args[0] === '--fast' ? 'fast' : 'all';

// Browser and live-computation checks are separate, opt-in commands.
const files = readdirSync('scripts').filter((file) =>
  file.startsWith('check-') && file.endsWith('.mjs') &&
  /from ['"]node:test['"]/.test(readFileSync(`scripts/${file}`, 'utf8')),
).sort().map((file) => `scripts/${file}`);
if (!files.length) throw new Error('No unit tests found.');
console.log(`EEGLayoutLab test tier: ${tier}; ${files.length} unit-test files. Live/browser scripts are excluded.`);
const result = spawnSync(process.execPath, ['--test', ...files], {
  stdio: 'inherit', env: { ...process.env, EEG_TEST_TIER: tier },
});
if (result.error) throw result.error;
process.exitCode = result.status ?? 1;
