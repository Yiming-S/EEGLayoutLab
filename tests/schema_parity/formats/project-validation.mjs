// Node's request validation of the project endpoints, for the project-* formats: the checks ProjectService and
// ProjectStore (webapp/server/projects/service.mjs:10-131, store.mjs:174-270) make before a project is read, run by
// Node's own code. The store's serialized operation never runs (serialize resolves at once), so no file is touched;
// ProjectService.resolveSnapshot runs its attachment check and stops at the first read of a record.
import { readFileSync } from 'node:fs';
import { ProjectService } from '../../../webapp/server/projects/service.mjs';
import { ProjectStore } from '../../../webapp/server/projects/store.mjs';
import { ABSENT, raw } from '../support.mjs';

export const ID = '00000000-0000-4000-8000-000000000001';
export const ENTRY = '00000000-0000-4000-8000-000000000002';
export const KEY = 'a'.repeat(64);
const PASSED = Symbol('passed');
class Reached extends Error {}
const reached = () => { throw new Reached('a scientific record was read'); };

export const store = new ProjectStore('/nonexistent/eeg-project-parity');
store.serialize = () => Promise.resolve(PASSED);
const queue = { get library() { return reached(); }, get editor() { return reached(); }, root: '/nonexistent', python: 'python3' };
const service = new ProjectService({ queue, scheduler: { own: reached }, guard: () => true, send: () => {}, tokenMatches: () => true,
  store, delivery: {} });

/** The entry kinds of Node's attachment check (service.mjs keeps the list unexported). */
const serviceSource = readFileSync(new URL('../../../webapp/server/projects/service.mjs', import.meta.url), 'utf8');
export const ENTRY_KINDS = JSON.parse(`[${serviceSource.match(/\[([^\]]*)\]\.includes\(input\.kind\)/)[1].replace(/'/g, '"')}]`);

/** ProjectService.body of a request whose text is JSON.stringify(value). */
export function body(value) {
  const text = JSON.stringify(value);
  return service.body({ headers: { 'content-type': 'application/json' }, async *[Symbol.asyncIterator]() { yield Buffer.from(text); } });
}

/** ProjectService.resolveSnapshot up to its first read: its attachment check. */
export async function attachment(input) {
  try { await service.resolveSnapshot(input, { id: 'visitor' }); } catch (error) { if (error instanceof Reached) return; throw error; }
  throw new Error('resolveSnapshot passed its attachment check without reading a record');
}

/** Awaits a store call that passed its checks and reached serialize. */
export async function accepted(pending) {
  if (await pending !== PASSED) throw new Error('the store call did not reach its serialized operation');
}

/** The electrode-name annotation Node reads for an evaluation: its id is a string. */
export const annotation = (id, record_id) => ({ schema: 'eeg-electrode-annotation/1', id: String(id), record_id,
  request_sha256: 'e'.repeat(64), electrode_names: Array.from({ length: 64 }, (_, i) => `E${i + 1}`) });

export const trimmed = value => value.trim();

/** Text values around the rules of text(value, name, max, required): types, bounds in UTF-16 units, control
 * characters and JavaScript white space. Each is [label, value]. */
export function texts(max) {
  const x = n => 'x'.repeat(n);
  return [
    ['plain', 'Study A'], ['padded', '  Study A \n'], ['empty', ''], ['space', ' '], ['nbsp', ' '], ['bom', '﻿'],
    ['ls', ' '], ['ideographic', '　'], ['nel', '\u0085'], ['tab', '\t'], ['innerTab', 'a\tb'], ['innerLf', 'a\nb'],
    ['innerCr', 'a\rb'], ['nul', 'a\u0000b'], ['us', 'a\u001fb'], ['vt', 'a\u000bb'], ['del', 'a\u007fb'], ['c1', 'a\u009fb'],
    ['loneHigh', raw('"a\\ud800"')], ['loneLow', raw('"\\udc00b"')], ['emoji', '😀'], ['cjk', '研究项目'],
    [`max${max}`, x(max)], [`over${max}`, x(max + 1)], ['maxEmoji', x(max - 2) + '😀'], ['overEmoji', x(max - 1) + '😀'],
    ['maxPadded', ' ' + x(max - 1)], ['overPadded', ' ' + x(max)], ['padInside', `  ${x(max - 4)}  `],
    ['null', null], ['number', 1], ['true', true], ['array', ['a']], ['object', { a: 1 }],
  ];
}

/** Revision spellings around Number.isSafeInteger(value) && value >= 1. Each is [label, value]. */
export const REVISIONS = [
  ['1', 1], ['2', 2], ['0', 0], ['-1', -1], ['1.5', 1.5], ['maxSafe', 2 ** 53 - 1], ['unsafe', 2 ** 53], ['string', '1'],
  ['true', true], ['null', null], ['array', [1]], ['object', {}], ['huge', raw('1e300')], ['negZero', raw('-0')],
  ['onePointZero', raw('1.0')], ['oneE0', raw('1e0')], ['maxSafeDecimal', raw('9007199254740991.0')],
  ['aboveSafe', raw('9007199254740993')], ['tiny', raw('1e-300')], ['absent', ABSENT],
];

/** Bodies that are not plain objects (ProjectService.body). */
export const NOT_OBJECTS = [['array', []], ['arrayObject', [{}]], ['string', 'x'], ['number', 1], ['null', null], ['true', true]];
