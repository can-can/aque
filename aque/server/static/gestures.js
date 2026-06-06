// gestures.js — standalone, extensible touch-gesture recognizer.
//
// It RECOGNIZES gestures and looks them up in a map; it does not know what an
// action means (sending bytes, scrolling, etc.) — the caller decides. That
// keeps it reusable: floating buttons can drive the same action objects.
//
// Usage:
//   const g = new GestureInput(el, {
//     onAction: (action, gestureName) => { ... },   // discrete gestures
//     onScroll: (dyPx) => { ... },                   // two-finger vertical pan
//     map: {
//       tap:           { seq: "\r",     label: "⏎" },
//       doubletap:     { seq: "\x1b",   label: "Esc" },
//       longpress:     { panel: true },
//       "swipe-up":    { seq: "\x1b[A", label: "↑" },
//       "swipe-down":  { seq: "\x1b[B", label: "↓" },
//       "swipe-left":  { seq: "\x1b[D", label: "←" },
//       "swipe-right": { seq: "\x1b[C", label: "→" },
//     },
//   });
//
// Recognized: tap, doubletap, longpress, swipe-up/down/left/right (one finger);
// plus a continuous two-finger vertical pan reported via onScroll(dyPx) where
// dyPx is the incremental change in the two-finger midpoint (px, +down/-up).
// Extend by adding map entries (gestures), or new gesture *types* in _bind().
(function (global) {
  "use strict";

  const DEFAULTS = {
    longPressMs: 550,
    doubleTapMs: 300,
    swipeMinPx: 28,
    moveCancelPx: 12,
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
      let twoFinger = false, lastTwoY = null;

      const cancelLong = () => { if (longTimer) { clearTimeout(longTimer); longTimer = null; } };
      const midY = (touches) => (touches[0].clientY + touches[1].clientY) / 2;

      this.el.addEventListener("touchstart", (e) => {
        if (e.touches.length >= 2) {
          twoFinger = true;          // two-finger scroll mode for this sequence
          lastTwoY = midY(e.touches);
          cancelLong();
          return;
        }
        twoFinger = false;
        const t = e.touches[0];
        sx = t.clientX; sy = t.clientY; longFired = false;
        longTimer = setTimeout(() => { longTimer = null; longFired = true; this._fire("longpress"); }, o.longPressMs);
      }, { passive: true });

      this.el.addEventListener("touchmove", (e) => {
        if (twoFinger) {
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
        // Ignore the finger-lifts that end a two-finger gesture (no taps fired).
        if (twoFinger) { if (e.touches.length === 0) twoFinger = false; return; }

        cancelLong();
        if (longFired) return;
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

        const now = Date.now();
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
