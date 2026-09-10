import { readdirSync, readFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';

// Browser and live-computation checks are separate, opt-in commands.
const files = readdirSync('scripts').filter((file) =>
  file.startsWith('check-') && file.endsWith('.mjs') &&
  /from ['"]node:test['"]/.test(readFileSync(`scripts/${file}`, 'utf8')),
).sort().map((file) => `scripts/${file}`);
if (!files.length) throw new Error('No unit tests found.');
const result = spawnSync(process.execPath, ['--test', ...files], { stdio: 'inherit' });
if (result.error) throw result.error;
process.exitCode = result.status ?? 1;
