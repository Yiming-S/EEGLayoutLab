#!/usr/bin/env node
/**
 * Operator tool for the shared library: list published records, approve them, or remove them.
 *
 *   node scripts/library-moderation.mjs [--queue-directory DIR | --repository-root DIR] list [--pending]
 *   node scripts/library-moderation.mjs ... approve <id>
 *   node scripts/library-moderation.mjs ... remove <id> [--reason TEXT]
 *   node scripts/library-moderation.mjs ... restore <id>
 *
 * The running server rereads the moderation file on its next list request; no restart is needed.
 */
import { existsSync, mkdirSync, readFileSync, readdirSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { atomicJson } from '../server/storage/records.mjs';
import { runtimeConfig } from '../server/runtime/config.mjs';
import { moderationPath, readModeration, recordsDirectory, validEntry } from '../server/library/record-visibility.mjs';

const ID = /^[a-f0-9]{64}$/;

export function parse(argv, env = process.env) {
  const args = [...argv], options = {};
  while (args[0]?.startsWith('--') && ['--queue-directory', '--repository-root'].includes(args[0])) {
    const [flag, value] = args.splice(0, 2);
    if (!value) throw new Error(`${flag} needs a directory.`);
    options[flag.slice(2)] = value;
  }
  const [command, ...rest] = args;
  if (!['list', 'approve', 'remove', 'restore'].includes(command)) throw new Error('Commands: list [--pending], approve <id>, remove <id> [--reason TEXT], restore <id>.');
  let queueDirectory = options['queue-directory'] ?? env.EEG_QUEUE_DIRECTORY;
  if (!queueDirectory) queueDirectory = runtimeConfig({ repositoryRoot: options['repository-root'] ?? env.EEG_REPOSITORY_ROOT ?? resolve('..'), env: {} }).queueDirectory;
  const parsed = { command, queueDirectory: resolve(queueDirectory) };
  if (command === 'list') {
    if (rest.length > 1 || (rest.length && rest[0] !== '--pending')) throw new Error('Usage: list [--pending]');
    parsed.pending = rest[0] === '--pending';
  } else {
    const [id, ...more] = rest;
    if (!ID.test(id || '')) throw new Error('Give the 64-hex record identifier.');
    parsed.id = id;
    if (command === 'remove' && more.length) {
      if (more.length !== 2 || more[0] !== '--reason' || !more[1].trim() || more[1].length > 500) throw new Error('Usage: remove <id> [--reason TEXT (at most 500 characters)]');
      parsed.reason = more[1].trim();
    } else if (more.length) throw new Error(`Unexpected arguments: ${more.join(' ')}`);
  }
  return parsed;
}

function entries(queueDirectory) {
  const directory = recordsDirectory(queueDirectory);
  if (!existsSync(directory)) return [];
  return readdirSync(directory).filter(name => ID.test(name.slice(0, -5)) && name.endsWith('.json')).map(name => {
    const id = name.slice(0, -5), value = JSON.parse(readFileSync(join(directory, name), 'utf8'));
    if (!validEntry(value, id)) throw new Error(`Invalid library visibility record ${id}.`);
    return value;
  });
}

export async function run(parsed, now = Date.now) {
  const file = moderationPath(parsed.queueDirectory), moderation = readModeration(file);
  if (parsed.command === 'list') {
    const rows = entries(parsed.queueDirectory).filter(entry => entry.published.length || moderation.records[entry.id])
      .map(entry => ({ id: entry.id, kind: entry.kind, label: entry.label ?? '', owners: entry.owners.length,
        published: entry.published.length ? entry.published.map(item => item.at).sort()[0] : null,
        moderation: moderation.records[entry.id]?.state ?? null, reason: moderation.records[entry.id]?.reason ?? null }))
      .filter(row => !parsed.pending || (row.published && !row.moderation))
      .sort((a, b) => String(a.published).localeCompare(String(b.published)));
    return { records: rows };
  }
  const known = entries(parsed.queueDirectory).some(entry => entry.id === parsed.id);
  if (!known && parsed.command !== 'restore') throw new Error('No visitor record with this identifier.');
  const records = { ...moderation.records };
  if (parsed.command === 'restore') delete records[parsed.id];
  else records[parsed.id] = { state: parsed.command === 'approve' ? 'approved' : 'removed', at: new Date(now()).toISOString(),
    ...(parsed.reason ? { reason: parsed.reason } : {}) };
  mkdirSync(dirname(file), { recursive: true, mode: 0o700 });
  await atomicJson(file, { version: 1, records });
  return { id: parsed.id, moderation: records[parsed.id]?.state ?? null };
}

if (import.meta.url === `file://${process.argv[1]}`) {
  try { console.log(JSON.stringify(await run(parse(process.argv.slice(2))), null, 2)); }
  catch (e) { console.error(e.message); process.exitCode = 1; }
}
