// Page swiper: native CSS scroll-snap on touch, mouse-drag bridged to
// scrollLeft for desktop. Tracks the currently visible page and emits
// "pagechange" events for the indicator dots.

const DRAG_THRESHOLD_PX = 4;

export class PageSwiper extends EventTarget {
  constructor(container) {
    super();
    this.el = container;
    this.activeIndex = 0;
    this._dragging = false;
    this._dragStartX = 0;
    this._dragStartScroll = 0;
    this._didDrag = false;

    this.el.addEventListener("scroll", () => this._onScroll(), { passive: true });
    this.el.addEventListener("pointerdown", (e) => this._onDown(e));
    this.el.addEventListener("pointermove", (e) => this._onMove(e));
    this.el.addEventListener("pointerup", (e) => this._onUp(e));
    this.el.addEventListener("pointercancel", () => this._cancelDrag());
    window.addEventListener("resize", () => this._onScroll());
  }

  get pageCount() {
    return this.el.children.length;
  }

  pageWidth() {
    return this.el.clientWidth;
  }

  goTo(index, smooth = true) {
    const i = Math.max(0, Math.min(this.pageCount - 1, index));
    this.el.scrollTo({
      left: i * this.pageWidth(),
      behavior: smooth ? "smooth" : "auto",
    });
  }

  // Touch is handled natively by scroll-snap; we only intercept mouse to
  // translate horizontal drag into scrollLeft.
  _onDown(e) {
    if (e.pointerType !== "mouse") return;
    // Don't hijack pointers that started on interactive elements — buttons,
    // inputs and the scrubber thumb need their own click semantics.
    if (e.target.closest("button, input, select, textarea, a, [role='button']")) {
      return;
    }
    this._dragging = true;
    this._didDrag = false;
    this._dragStartX = e.clientX;
    this._dragStartScroll = this.el.scrollLeft;
    this._pointerId = e.pointerId;
  }

  _onMove(e) {
    if (!this._dragging) return;
    const dx = e.clientX - this._dragStartX;
    if (!this._didDrag && Math.abs(dx) > DRAG_THRESHOLD_PX) {
      // Only capture once we know it's a real drag. This way a click that
      // doesn't move stays a click, and the underlying element receives it.
      this._didDrag = true;
      this.el.classList.add("is-dragging");
      try {
        this.el.setPointerCapture(this._pointerId);
      } catch (_) { /* capture can fail if pointer already released */ }
    }
    if (this._didDrag) {
      this.el.scrollLeft = this._dragStartScroll - dx;
      e.preventDefault();
    }
  }

  _onUp(e) {
    if (!this._dragging) return;
    const wasDrag = this._didDrag;
    this._cancelDrag();
    if (wasDrag) {
      const idx = Math.round(this.el.scrollLeft / this.pageWidth());
      this.goTo(idx);
    }
  }

  _cancelDrag() {
    this._dragging = false;
    this._didDrag = false;
    this.el.classList.remove("is-dragging");
  }

  _onScroll() {
    const idx = Math.round(this.el.scrollLeft / this.pageWidth());
    if (idx !== this.activeIndex) {
      this.activeIndex = idx;
      this.dispatchEvent(new CustomEvent("pagechange", { detail: idx }));
    }
  }
}

// Edge-swipe helper: fires `onSwipe` when the user drags upward from the
// bottom edge of the viewport. Mouse + touch via pointer events.
//
// Designed not to interfere with the page swiper (horizontal pans) or
// with widgets that sit further from the bottom edge: the gesture only
// arms when pointerdown lands in the bottom `edgeZonePx` strip, and
// cancels on the first sideways drift past `maxOffAxis`.
export function attachSwipeFromBottom(
  el,
  onSwipe,
  { edgeZonePx = 32, minDistance = 60, maxOffAxis = 40 } = {},
) {
  let active = null;

  el.addEventListener("pointerdown", (e) => {
    if (window.innerHeight - e.clientY > edgeZonePx) return;
    // Don't hijack interactive elements that happen to live near the edge.
    if (e.target.closest("button, input, select, textarea, a, [role='button']")) {
      return;
    }
    active = { x: e.clientX, y: e.clientY, id: e.pointerId, fired: false };
    // Touch has implicit pointer capture; mouse doesn't. Capture explicitly
    // so pointermove keeps firing on `el` once the cursor leaves the strip.
    try { el.setPointerCapture(e.pointerId); } catch (_) { /* not supported on some pointer types */ }
  });

  el.addEventListener("pointermove", (e) => {
    if (!active || e.pointerId !== active.id || active.fired) return;
    const dx = e.clientX - active.x;
    const dy = e.clientY - active.y;
    if (Math.abs(dx) > maxOffAxis) {
      active = null;
      return;
    }
    if (dy < -minDistance) {
      active.fired = true;
      onSwipe?.();
    }
  });

  const end = () => { active = null; };
  el.addEventListener("pointerup", end);
  el.addEventListener("pointercancel", end);
}

// Lightweight long-press helper (touch + mouse). Distinguishes click from
// long-press based on a duration threshold.
export function attachLongPress(el, { onClick, onLongPress, ms = 500 } = {}) {
  let timer = null;
  let fired = false;
  let startX = 0;
  let startY = 0;

  const cancel = () => {
    if (timer) {
      clearTimeout(timer);
      timer = null;
    }
  };

  el.addEventListener("pointerdown", (e) => {
    fired = false;
    startX = e.clientX;
    startY = e.clientY;
    timer = setTimeout(() => {
      fired = true;
      timer = null;
      onLongPress?.(e);
    }, ms);
  });

  el.addEventListener("pointermove", (e) => {
    if (!timer) return;
    const dx = e.clientX - startX;
    const dy = e.clientY - startY;
    if (Math.hypot(dx, dy) > 8) cancel();
  });

  el.addEventListener("pointerup", (e) => {
    cancel();
    if (!fired) onClick?.(e);
  });

  el.addEventListener("pointercancel", cancel);
  el.addEventListener("pointerleave", cancel);
}
