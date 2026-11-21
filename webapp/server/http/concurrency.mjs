/** Bounded concurrency for expensive reads; excess callers wait briefly, then get a 503. */
export class Gate {
  constructor({ limit = 2, waiting = 8 } = {}) { this.limit = limit; this.maxWaiting = waiting; this.active = 0; this.queue = []; }
  async run(fn) {
    if (this.active >= this.limit) {
      if (this.queue.length >= this.maxWaiting)
        throw Object.assign(new Error('服务器正忙，请稍后重试'), { status: 503, retryAfter: 5 });
      await new Promise(resolve => this.queue.push(resolve));
    } else this.active++;
    try { return await fn(); }
    finally { const next = this.queue.shift(); if (next) next(); else this.active--; }
  }
}
