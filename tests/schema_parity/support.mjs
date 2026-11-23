// Helpers shared by the format modules in formats/: deterministic randomness, exact double bits and request
// texts with chosen number spellings.

/** A seeded generator (mulberry32), so every format module produces the same variants on every run. */
export function createRandom(seed) {
  let state = seed >>> 0;
  const rand32 = () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return (t ^ (t >>> 14)) >>> 0;
  };
  const random = () => rand32() / 2 ** 32;
  return { rand32, random, pick: list => list[Math.floor(random() * list.length)] };
}

const view = new DataView(new ArrayBuffer(8));
/** The 16 hex digits of a double's IEEE 754 bits. */
export const bits = x => { view.setFloat64(0, x); return view.getBigUint64(0).toString(16).padStart(16, '0'); };
const fromBits = b => { view.setBigUint64(0, b); return view.getFloat64(0); };
/** The double `steps` units in the last place above (or below, if negative) a positive double. */
export const nextUp = (x, steps = 1) => { view.setFloat64(0, x); return fromBits(view.getBigUint64(0) + BigInt(steps)); };
/** A random double from 64 random bits; may be NaN or infinite. */
export const doubleFromBits = (high, low) => { view.setUint32(0, high); view.setUint32(4, low); return view.getFloat64(0); };

/** Text inserted verbatim into a request text, for number spellings JSON.stringify would not write. */
export class Raw { constructor(text) { this.text = text; } }
export const raw = text => new Raw(text);
/** An object entry that is left out of the request text. */
export const ABSENT = Symbol('absent');
export const toText = value => {
  if (value instanceof Raw) return value.text;
  if (Array.isArray(value)) return '[' + value.map(toText).join(',') + ']';
  if (value && typeof value === 'object')
    return '{' + Object.entries(value).filter(([, v]) => v !== ABSENT).map(([k, v]) => JSON.stringify(k) + ':' + toText(v)).join(',') + '}';
  return JSON.stringify(value);
};
/** A label for a value in a variant name. */
export const label = value => (value === ABSENT ? 'absent' : value instanceof Raw ? value.text : JSON.stringify(value));

/**
 * Collects variants for one format. `add` takes a value (written with toText) or a Raw text; `addBytes` takes
 * raw body bytes. `expect` marks a shared fixture: generate.mjs fails if Node's outcome differs from it.
 */
export function collector() {
  const variants = [];
  return {
    variants,
    add: (name, value, expect) => variants.push({ name, text: value instanceof Raw ? value.text : toText(value), ...(expect ? { expect } : {}) }),
    addBytes: (name, bytes) => variants.push({ name, bytes: Buffer.from(bytes).toString('base64') }),
  };
}
