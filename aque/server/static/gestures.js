// gestures.js — standalone, extensible touch-gesture recognizer.
//
// It RECOGNIZES gestures and looks them up in a map; it does not know what an
// action means (sending bytes, scrolling, etc.) — the caller decides. That
// keeps it reusable: floating buttons can drive the same action objects.
//
// Usage:
//   const g = new GestureInput(el, {
//     onAction: (action, gestureName) => { ... },   // discrete one-finger gestures
//     onScroll: (dyPx) => { ... },                   // two-finger vertical pan
//     map: {
//       tap: {...}, doubletap: {...}, longpress: {...},
//       "swipe-up": {...}, "swipe-down": {...}, "swipe-left": {...}, "swipe-right": {...},
//     },
//   });
//
// Disambiguation: a single-finger gesture fires ONLY if the whole touch
// sequence stayed at one finger (tracked via maxTouches), and never within a
// short cooldown after a multi-touch gesture — so the staggered land/lift of a
// two-finger pan can't leak a stray tap/swipe.
(function (global) {
  "use strict";

  const DEFAULTS = {
    longPressMs: 550,
    doubleTapMs: 300,
    swipeMinPx: 28,
    moveCancelPx: 12,
    multiCooldownMs: 250, // suppress single-finger gestures this long after a multi-touch
  };

  class GestureInput {
    constructor(el, opts = {}) {
      this.el = el;
      this.opts = Object.assign({}, DEFAULTS, opts);
      this.map = opts.map || {};
      this.onAction = opts.onAction || function () {};
      this.onScroll = opts.onScroll || null;
      this._bind();
    }

    setMap(map) { this.map = map || {}; }
    on(gesture, action) { this.map[gesture] = action; }
    gestures() { return Object.keys(this.map); }

    _fire(gesture) {
      const action = this.map[gesture];
      if (action) this.onAction(action, gesture);
    }

    _bind() {
      const o = this.opts;
      let sx = 0, sy = 0, lastTap = 0, longTimer = null, longFired = false;
      let lastTwoY = null, maxTouches = 0, suppressUntil = 0;

      const cancelLong = () => { if (longTimer) { clearTimeout(longTimer); longTimer = null; } };
      const midY = (touches) => (touches[0].clientY + touches[1].clientY) / 2;
      const isMulti = () => maxTouches >= 2;

      this.el.addEventListener("touchstart", (e) => {
        maxTouches = Math.max(maxTouches, e.touches.length);
        if (e.touches.length >= 2) {           // two-finger: scroll mode
          lastTwoY = midY(e.touches);
          cancelLong();
          return;
        }
        if (isMulti()) return;                 // a leftover finger from a multi sequence
        const t = e.touches[0];
        sx = t.clientX; sy = t.clientY; longFired = false;
        longTimer = setTimeout(() => { longTimer = null; longFired = true; this._fire("longpress"); }, o.longPressMs);
      }, { passive: true });

      this.el.addEventListener("touchmove", (e) => {
        if (isMulti()) {
          if (e.touches.length >= 2 && this.onScroll) {
            const y = midY(e.touches);
            const dy = y - lastTwoY;
            lastTwoY = y;
            if (dy !== 0) this.onScroll(dy);
          }
          return;
        }
        if (!longTimer) return;
        const t = e.touches[0];
        if (Math.hypot(t.clientX - sx, t.clientY - sy) > o.moveCancelPx) cancelLong();
      }, { passive: true });

      this.el.addEventListener("touchend", (e) => {
        if (e.touches.length > 0) return;      // wait until every finger is up

        const wasMulti = isMulti();
        const now = Date.now();
        cancelLong();
        maxTouches = 0;                         // sequence over

        if (wasMulti) { suppressUntil = now + o.multiCooldownMs; return; }
        if (now < suppressUntil) return;        // just after a multi-touch — ignore
        if (longFired) return;                  // long-press already handled it

        const t = e.changedTouches[0];
        const dx = t.clientX - sx, dy = t.clientY - sy;
        if (Math.hypot(dx, dy) >= o.swipeMinPx) {
          const dir = Math.abs(dx) > Math.abs(dy)
            ? (dx > 0 ? "swipe-right" : "swipe-left")
            : (dy > 0 ? "swipe-down" : "swipe-up");
          this._fire(dir);
          lastTap = 0;
          return;
        }

        if (now - lastTap < o.doubleTapMs) {
          lastTap = 0;
          this._fire("doubletap");
        } else {
          lastTap = now;
          const at = now;
          setTimeout(() => { if (lastTap === at) { lastTap = 0; this._fire("tap"); } }, o.doubleTapMs);
        }
      }, { passive: true });
    }
  }

  global.GestureInput = GestureInput;
})(window);
