/**
 * Client network grouping for abuse limits. A browser cookie is free to reset, so
 * per-network caps sit beside per-browser caps. IPv4 groups by address and IPv6 by
 * /64, the block one subscriber usually controls. Only a keyed hash is stored.
 */
import { createHmac } from 'node:crypto';
import { isIP } from 'node:net';

const error = (message, status) => Object.assign(new Error(message), { status });

function ipv6Groups(address) {
  let value = address.split('%')[0].toLowerCase();
  if (value.includes('.')) {
    const at = value.lastIndexOf(':'), parts = value.slice(at + 1).split('.').map(Number);
    value = value.slice(0, at + 1) + ((parts[0] << 8) | parts[1]).toString(16) + ':' + ((parts[2] << 8) | parts[3]).toString(16);
  }
  const [head, tail] = value.split('::');
  const first = head ? head.split(':') : [], last = tail === undefined ? [] : tail ? tail.split(':') : [];
  const groups = tail === undefined ? first : [...first, ...Array(8 - first.length - last.length).fill('0'), ...last];
  return groups.map(group => parseInt(group || '0', 16));
}

/** Stable network label: `v4:a.b.c.d`, `v6:xxxx:xxxx:xxxx:xxxx` (/64), or `other:<text>`. */
export function networkPrefix(address) {
  const text = String(address ?? '');
  const kind = isIP(text);
  if (kind === 4) return `v4:${text}`;
  if (kind !== 6) return `other:${text.slice(0, 64)}`;
  const groups = ipv6Groups(text);
  if (groups.slice(0, 5).every(group => group === 0) && groups[5] === 0xffff)
    return `v4:${groups[6] >> 8}.${groups[6] & 255}.${groups[7] >> 8}.${groups[7] & 255}`;
  return `v6:${groups.slice(0, 4).map(group => group.toString(16)).join(':')}`;
}

export function networkId(secret, address) {
  return createHmac('sha256', secret).update(`network:${networkPrefix(address)}`).digest('hex');
}

/** Sliding one-window counter per network; in memory, so a restart only forgives recent use. */
export class NetworkWindow {
  constructor({ limit, windowMs, message, now = Date.now }) {
    this.limit = limit; this.windowMs = windowMs; this.message = message; this.now = now; this.events = new Map();
  }
  take(network) {
    if (!network) return;
    const now = this.now(), recent = (this.events.get(network) ?? []).filter(at => now - at < this.windowMs);
    if (recent.length >= this.limit) { this.events.set(network, recent); throw error(this.message, 429); }
    recent.push(now); this.events.set(network, recent);
    if (this.events.size > 10000) for (const [key, times] of this.events) if (!times.some(at => now - at < this.windowMs)) this.events.delete(key);
  }
}
