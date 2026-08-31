// One requestAnimationFrame loop for the whole dashboard.
//
// Several widgets animate between samples (value tweens, scrolling
// sparklines). Each running its own rAF loop would mean a dozen callbacks
// competing for the same frame on a kiosk that is also drawing its own CPU
// graph. They all subscribe here instead, and the loop only exists while
// somebody is subscribed — and never while the page is hidden.
//
// **Visibility matters more than it looks.** The dashboard keeps every page
// in the DOM and slides between them, so at any moment roughly three quarters
// of the widgets are off-screen — and animating them is work nobody can see.
// A subscriber therefore names the element it draws into, and stops being
// called while that element is outside the viewport.

const subscribers = new Map(); // fn -> element | null
const visibility = new WeakMap(); // element -> boolean
let frameId = null;

const observer =
  typeof IntersectionObserver === "undefined"
    ? null
    : new IntersectionObserver(
        (entries) => {
          for (const entry of entries) {
            visibility.set(entry.target, entry.isIntersecting);
          }
          // A page that just slid into view has to start animating again, and
          // the loop may have stopped while nothing was visible.
          schedule();
        },
        { threshold: 0 },
      );

function isVisible(el) {
  if (!el || !observer) return true;
  // Unknown until the observer has reported once — animate rather than
  // freeze, so a widget is never stuck on its first frame.
  const known = visibility.get(el);
  return known === undefined ? true : known;
}

function frame(now) {
  frameId = null;
  // Copy first: a callback may unsubscribe itself when its animation ends.
  for (const [fn, el] of [...subscribers]) {
    if (!isVisible(el)) continue;
    try {
      fn(now);
    } catch (err) {
      console.error("[ticker] subscriber failed:", err);
      subscribers.delete(fn);
    }
  }
  schedule();
}

function schedule() {
  if (frameId !== null || document.hidden) return;
  // Nothing visible to draw: let the loop stop entirely. The intersection
  // observer or the next subscribe() starts it again.
  let anyVisible = false;
  for (const el of subscribers.values()) {
    if (isVisible(el)) {
      anyVisible = true;
      break;
    }
  }
  if (!anyVisible) return;
  frameId = requestAnimationFrame(frame);
}

/**
 * Call `fn(timestampMs)` before every frame until unsubscribed.
 *
 * Pass the element the callback draws into — while it is off-screen, `fn` is
 * not called at all.
 */
export function subscribe(fn, el = null) {
  subscribers.set(fn, el);
  if (el && observer && !visibility.has(el)) observer.observe(el);
  schedule();
}

export function unsubscribe(fn) {
  const el = subscribers.get(fn);
  subscribers.delete(fn);
  if (el && observer) {
    // Only stop observing once no subscriber is left on that element.
    let stillUsed = false;
    for (const other of subscribers.values()) {
      if (other === el) {
        stillUsed = true;
        break;
      }
    }
    if (!stillUsed) observer.unobserve(el);
  }
  if (subscribers.size === 0 && frameId !== null) {
    cancelAnimationFrame(frameId);
    frameId = null;
  }
}

// A kiosk has no devtools to open. This is the one hook that answers "is the
// display animating things nobody can see?", which is the question that costs
// GPU time when the answer is wrong.
window.__edgeTicker = {
  stats() {
    let visible = 0;
    for (const el of subscribers.values()) if (isVisible(el)) visible += 1;
    return { subscribers: subscribers.size, visible, running: frameId !== null };
  },
};

document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    if (frameId !== null) {
      cancelAnimationFrame(frameId);
      frameId = null;
    }
  } else {
    schedule();
  }
});
