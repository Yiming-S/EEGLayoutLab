/** One process permit per application; held through result verification and storage. */
export class ExecutionSlot {
  #owner = null;
  #paused = false;
  get busy() { return this.#owner !== null; }
  get paused() { return this.#paused; }
  pause() { this.#paused = true; }
  resume() { this.#paused = false; }
  acquire(owner) {
    if (owner == null) throw new TypeError('Execution permit requires an owner.');
    if (this.busy || this.paused) return null;
    const token = { owner };
    this.#owner = token;
    return () => { if (this.#owner === token) this.#owner = null; };
  }
}

export function executionSlotFor(queue) {
  return queue.executionSlot ??= new ExecutionSlot();
}
