// Value tween that follows the *measured* update cadence.
//
// Metric modules deliver one sample per interval, so a widget that writes
// each sample straight into the DOM steps once per second and looks like it
// is stuttering. A Smoothed value walks from the previous sample to the new
// one over roughly the time the next sample will take to arrive: the display
// is continuous, and it lands on the true value just as the next one shows
// up. The lag this buys is one interval — worth it for a gauge, which is why
// this is not used for anything where the exact instant matters.
//
// The cadence is measured rather than configured: the interval is a per
// module setting the widget knows nothing about, and it changes at runtime
// when the settings are edited.

import { subscribe, unsubscribe } from "./ticker.js";

// Continuous animation between samples, measured on the 2560x720 kiosk
// (CPU of the whole kiosk process tree, 15 s averages):
//
//   nothing animated ............................  3 %
//   value interpolation only .................... 23 %
//   travelling sparklines only .................. 21 %
//
// A moving picture costs about twenty points of a CPU core permanently, and
// on this machine that showed up as roughly fifteen points of GPU — on a
// display whose whole job is to report how busy the machine is. Off by
// default for that reason; flip this to true to get the smooth version back.
export const SMOOTH_UPDATES = false;

const DEFAULT_GAP_MS = 1000;
const MIN_FRAME_MS = 40; // ~25 fps

export class Smoothed {
  /**
   * @param {(value:number)=>void} apply  writes the interpolated value out
   * @param {{minGap?:number,maxGap?:number}} opts  bounds for the measured gap
   */
  constructor(apply, { minGap = 80, maxGap = 3000, el = null } = {}) {
    this.apply = apply;
    this.minGap = minGap;
    this.maxGap = maxGap;
    // The element this value is displayed in — the ticker skips the callback
    // while it is off-screen.
    this.el = el;
    this._lastFrame = 0;
    this._gap = null;      // rolling estimate of the sample interval
    this._lastSet = null;  // when the previous sample arrived
    this._from = null;
    this._to = null;
    this._start = 0;
    this._running = false;
    this._tick = this._tick.bind(this);
  }

  /** Feed the newest sample. The first one is applied immediately. */
  set(target) {
    if (!Number.isFinite(target)) return;
    if (!SMOOTH_UPDATES) {
      this._to = target;
      this.apply(target);
      return;
    }
    const now = performance.now();
    if (this._to === null) {
      this._to = target;
      this._from = target;
      this._lastSet = now;
      this.apply(target);
      return;
    }
    const observed = Math.min(Math.max(now - this._lastSet, this.minGap), this.maxGap);
    this._gap = this._gap === null ? observed : this._gap * 0.7 + observed * 0.3;
    this._lastSet = now;
    // Start from wherever the animation currently stands, not from the last
    // sample — otherwise a value arriving early makes the display jump back.
    this._from = this._current();
    this._to = target;
    this._start = now;
    if (!this._running) {
      this._running = true;
      subscribe(this._tick, this.el);
    }
  }

  /** The value on screen right now. */
  _current() {
    if (this._from === null) return this._to ?? 0;
    const dur = this._gap ?? DEFAULT_GAP_MS;
    const p = dur > 0 ? Math.min(1, (performance.now() - this._start) / dur) : 1;
    return this._from + (this._to - this._from) * p;
  }

  _tick(now) {
    // A number counting up does not need 60 fps. Every write here is text,
    // which means layout and paint, so this cap is the difference between a
    // smooth display and one that keeps the GPU busy for nothing.
    if (now - this._lastFrame < MIN_FRAME_MS) return;
    this._lastFrame = now;
    const dur = this._gap ?? DEFAULT_GAP_MS;
    const p = dur > 0 ? Math.min(1, (now - this._start) / dur) : 1;
    this.apply(this._from + (this._to - this._from) * p);
    if (p >= 1) {
      this._running = false;
      unsubscribe(this._tick);
    }
  }

  destroy() {
    if (this._running) {
      this._running = false;
      unsubscribe(this._tick);
    }
  }
}
