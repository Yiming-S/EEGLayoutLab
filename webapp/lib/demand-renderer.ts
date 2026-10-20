type FrameQueue = {
  request: (callback: FrameRequestCallback) => number;
  cancel: (frame: number) => void;
};

/** Coalesce display changes and continue only while the camera is moving. */
export function createDemandRenderer(
  draw: () => boolean,
  frames: FrameQueue = {
    request: (callback) => requestAnimationFrame(callback),
    cancel: (frame) => cancelAnimationFrame(frame),
  },
) {
  let frame: number | null = null;
  let enabled = true;
  let disposed = false;
  let dirty = false;

  const schedule = () => {
    if (enabled && !disposed && frame === null) frame = frames.request(render);
  };
  const render = () => {
    frame = null;
    if (!enabled || disposed) return;
    dirty = false;
    // OrbitControls can request another frame from its change event here.
    const moving = draw();
    if (moving) dirty = true;
    if (dirty) schedule();
  };
  const invalidate = () => {
    dirty = true;
    schedule();
  };
  const cancelPending = () => {
    if (frame !== null) frames.cancel(frame);
    frame = null;
  };

  return {
    invalidate,
    renderNow() {
      dirty = true;
      if (!enabled || disposed) return;
      cancelPending();
      render();
    },
    setEnabled(value: boolean) {
      if (enabled === value || disposed) return;
      enabled = value;
      if (value) invalidate();
      else cancelPending();
    },
    dispose() {
      disposed = true;
      cancelPending();
    },
  };
}
