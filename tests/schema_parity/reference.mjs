// JavaScript semantics that the Python service reproduces, recorded from this Node:
// - for eeglayoutlab.schemas.jsjson: JSON.stringify spelling, Math.hypot (near the 4 - 1e-7 mm spacing threshold),
//   toPrecision(4), Math.round, and object key order (`keyorder`: JSON.stringify(JSON.parse(text)));
// - for eeglayoutlab.jobs.nodepath: path.posix join, dirname, resolve, relative and normalize (`paths`).
import { posix } from 'node:path';
import { bits, createRandom, doubleFromBits, nextUp } from './support.mjs';

export function referenceCorpora() {
  const { rand32, random, pick } = createRandom(0x2026a11c);
  const T = 4 - 1e-7;
  const naive = d => Math.sqrt(d[0] * d[0] + d[1] * d[1] + d[2] * d[2]);

  const doubles = [0, -0, 1, -1, 0.1, 1e21, 1e-7, 1e-6, 1e20, 123e-20, 5e-324, -5e-324, 2.2250738585072014e-308, Number.MAX_VALUE, Number.MIN_VALUE,
    2 ** 53, 2 ** 53 + 2, 9.999999999999999e20, 1.0000000000000001e21, 0.000001, 0.0000012345, 100, 1e100, T, 0.30000000000000004];
  for (let i = 0; i < 20000; i++) {
    const x = doubleFromBits(rand32(), rand32());
    if (Number.isFinite(x)) doubles.push(x);
    doubles.push(Number((random() * 10 ** Math.floor(random() * 30 - 10)).toPrecision(1 + Math.floor(random() * 17))));
  }
  const numbers = doubles.map(x => [bits(x), JSON.stringify(x)]);

  const hypot = [];
  for (let i = 0; i < 20000; i++) {
    const scale = pick([1e-3, 1, 4, 10, 500, 1e5]);
    const d = i % 2 ? [random() - 0.5, random() - 0.5, random() - 0.5].map(v => v * scale) : (() => {
      const u = [random() - 0.5, random() - 0.5, random() - 0.5], s = nextUp(T, Math.floor(random() * 9) - 4) / naive(u);
      return u.map(v => v * s);
    })();
    hypot.push([...d.map(bits), bits(Math.hypot(...d))]);
  }

  const precisionValues = [1.0625, 0.0015, 2.5, 1.2345, 999.95, 0.001, 1000, 1e-3, 1.0005];
  for (let i = 0; i < 20000; i++) {
    const v = Number(`${1000 + Math.floor(random() * 9000)}e${Math.floor(random() * 7) - 6}`);
    precisionValues.push(v, nextUp(v, 1), nextUp(v, -1), v * (1 + random() * 1e-4));
  }
  const precision = precisionValues.map(v => [bits(v), Number(v.toPrecision(4)) === v]);

  const roundValues = [];
  for (let k = 0; k <= 100; k++) roundValues.push(k / 100, nextUp(k / 100, 1), nextUp(k / 100, -1), k / 100 + 0.005, k / 1000, k * 0.01);
  for (let i = 0; i < 5000; i++) roundValues.push(random(), Math.floor(random() * 96) / 100);
  const round2 = roundValues.filter(v => v >= 0).map(v => [bits(v), Math.round(v * 100) / 100 === v, bits(Math.round(v * 100))]);

  return { numbers, hypot, precision, round2, keyorder: keyOrderCorpus(), paths: pathCorpus() };
}

/**
 * [text, JSON.stringify(JSON.parse(text))] pairs. V8 writes array-index keys (canonical decimal strings of 0 to
 * 2**32 - 2) first in ascending order, then the other keys in insertion order; a repeated key keeps its first
 * position and takes its last value. Design results carry such keys (containing_tissue_counts "1", "2", "3", "-1").
 */
function keyOrderCorpus() {
  const { random, pick } = createRandom(0x6b65790);
  const texts = [
    '{"b":0,"2":1,"1":2,"01":3,"4294967295":4,"4294967294":5}',
    '{"b":1,"2":2,"-1":3,"01":4,"1":5,"4294967295":6,"4294967294":7}',
    '{"z":0,"-1":1,"1.5":2,"1e3":3," 1":4,"\u0663":5,"\u00b2":6,"":7,"0":8,"00":9,"7":10}',
    '{"native_qa":{"source_qa":{"containing_tissue_counts":{"-1":4,"1":66,"2":4244,"3":38}}},"result_sha256":"x"}',
    '{"a":1,"1":2,"a":3}',
    '{"1":1,"0":2,"1":3}',
    String.raw`{"\u0031":1,"a":2,"\u0030":3,"\u0032\u0033":4}`,
    '{"4294967296":0,"4294967295":1,"4294967294":2,"2147483648":3,"9007199254740993":4,"0":5}',
    '[{"2":0,"1":1},{"b":0,"a":1},[{"10":0,"9":1}]]',
    '{"__proto__":1,"1":2,"constructor":3,"0":4}',
    '{}', '[]', '{"":{"":{"0":[]}}}',
    // A digit key longer than Python's 4300-digit int() limit is an ordinary key; nesting deeper than Python's
    // recursion limit is written as parsed.
    `{"b":1,"1${'0'.repeat(4300)}":2,"1":3}`,
    '{"a":'.repeat(2000) + '[{"2":0,"1":1}]' + '}'.repeat(2000),
    '['.repeat(3000) + ']'.repeat(3000),
  ];
  for (const key of ['-1', '1.5', '1e3', ' 1', '1 ', '+1', '\u0663', '\u00b2', '\uff11', '', '0', '00', '01', '-0', '0x1', 'NaN', '4294967295'])
    texts.push(`{"${key}":0,"5":1,"a":2,"3":3}`);
  // Keys drawn from a pool that mixes array indices and ordinary keys, with duplicates and nesting.
  const pool = ['0', '1', '2', '3', '7', '9', '10', '17', '99', '100', '1000', '4294967294', '4294967295', '4294967296',
    '2147483647', '2147483648', '01', '00', '-1', '-0', '1.5', '1e3', '1.0', ' 1', '1 ', '+1', '\u0663', '\u00b2',
    '', 'a', 'b', 'z', 'id', 'length', '__proto__', 'constructor', 'x1', '1x', '0x1', 'NaN', 'Infinity', '09'];
  const scalar = () => pick(['0', '1', '-2.5', '1e-7', '"s"', '"1"', 'true', 'false', 'null', '[]', '{}']);
  const value = depth => {
    const r = random();
    if (depth > 3 || r < 0.5) return scalar();
    if (r < 0.65) return '[' + Array.from({ length: Math.floor(random() * 4) }, () => value(depth + 1)).join(',') + ']';
    return object(depth + 1);
  };
  const object = depth => '{' + Array.from({ length: Math.floor(random() * 9) }, () => `"${pick(pool)}":${value(depth)}`).join(',') + '}';
  for (let i = 0; i < 2000; i++) texts.push(object(0));
  return texts.map(text => [text, JSON.stringify(JSON.parse(text))]);
}

/**
 * [name, args, result] for path.posix functions, over dot segments, repeated and trailing slashes, absolute parts,
 * empty strings and a leading "//". `resolve` gets an absolute cwd as its first argument; `relative` resolves
 * relative arguments against `cwd`, which is recorded.
 */
function pathCorpus() {
  const { random, pick } = createRandom(0x9a7b5);
  const segments = ['a', 'b', 'c', 'results', 'v2', '.', '..', '...', '.a', 'a.', '..a', 'a..', '', 'x y', '\u00e9', '\ud83d\ude00', '.runtime'];
  const piece = () => {
    const count = Math.floor(random() * 5);
    let text = Array.from({ length: count }, () => pick(segments)).join(pick(['/', '/', '/', '//']));
    const r = random();
    if (r < 0.2) text = '/' + text; else if (r < 0.25) text = '//' + text; else if (r < 0.28) text = '///' + text;
    if (random() < 0.2) text += pick(['/', '//', '/.', '/..']);
    return JSON.parse(`"${text}"`);
  };
  const absolute = () => { const text = piece(); return text.startsWith('/') ? text : '/' + text; };
  const fixed = ['', '.', '..', '/', '//', '///', 'a', 'a/', 'a//', '/a', '//a', '///a', 'a/b/', 'a/b//', './', '../', '/..', '/../a',
    'a/../..', '../../a', 'a/./b', './a', 'a/b/../../..', '//a//b/../c/', 'results//v2/./x/../bank.npz', '\ud83d\ude00/..'].map(text => JSON.parse(`"${text}"`));
  const cases = [];
  const add = (name, args) => cases.push([name, args, posix[name](...args)]);
  for (const text of fixed) { add('normalize', [text]); add('dirname', [text]); add('join', [text]); add('join', ['a', text]); add('join', [text, 'b']); }
  add('join', []);
  for (const [a, b] of [['a', '/b'], ['/a', '/b'], ['', ''], ['', 'a'], ['a', ''], ['.', '.'], ['a', '..'], ['/', '..']]) add('join', [a, b]);
  const cwd = process.cwd();
  for (const [from, to] of [['/', '/'], ['/', '/a'], ['/a', '/'], ['/a/b', '/a/b/c'], ['/a/b/c', '/a/b'], ['/a/bc', '/a/b'], ['/a/b', '/a/bc'],
    ['', ''], ['', '.'], ['a', 'a/b'], ['/root', '/root/.runtime/simnibs-4.6.0/bin/python'], ['/r//', '/r/x/'], ['/a/\ud83d\ude00', '/a/\ud83d\ude01/b']])
    add('relative', [JSON.parse(`"${from}"`), JSON.parse(`"${to}"`)]);
  for (let i = 0; i < 3000; i++) {
    const r = random();
    if (r < 0.2) add('normalize', [piece()]);
    else if (r < 0.4) add('dirname', [piece()]);
    else if (r < 0.6) add('join', Array.from({ length: Math.floor(random() * 5) }, piece));
    else if (r < 0.8) add('resolve', [absolute(), ...Array.from({ length: Math.floor(random() * 4) }, piece)]);
    else add('relative', [random() < 0.8 ? absolute() : piece(), random() < 0.8 ? absolute() : piece()]);
  }
  return { cwd, cases };
}
