// gestures.js — standalone, extensible touch-gesture recognizer.
//
// It only RECOGNIZES gestures and looks them up in a map; it does not know what
// an action means (sending bytes, showing a hint, etc.) — the caller decides.
// That keeps it reusable: floating buttons can drive the same action objects.
//
// Usage:
//   const g = new GestureInput(el, {
//     onAction: (action, gestureName) => { ... },   // do something with the action
//     map: {
//       tap:           { seq: "\r",     label: "⏎" },
//       doubletap:     { seq: "\x1b",   label: "Esc" },
//       longpress:     { seq: "\x03",   label: "Ctrl-C" },
//       "swipe-up":    { seq: "\x1b[A", label: "↑" },
//       "swipe-down":  { seq: "\x1b[B", label: "↓" },
//       "swipe-left":  { seq: "\x1b[D", label: "←" },
//       "swipe-right": { seq: "\x1b[C", label: "→" },
//     },
//   });
//
// Recognized gesture names: tap, doubletap, longpress,
//   swipe-up, swipe-down, swipe-left, swipe-right.
// Extend by adding entries to the map, or remap live with g.on(name, action).
// New gesture *types* (e.g. two-finger) can be added inside _bind without
// touching callers.
(function (global) {
  "use strict";

  const DEFAULTS = {
    longPressMs: 550,   // hold this long → longpress
    doubleTapMs: 300,   // two taps within this → doubletap
    swipeMinPx: 28,     // travel this far → swipe (else it's a tap)
    moveCancelPx: 12,   // moving this far cancels a pending longpress
  };

  class GestureInput {
    constructor(el, opts = {}) {
      this.el = el;
      this.opts = Object.assign({}, DEFAULTS, opts);
      this.map = opts.map || {};
      this.onAction = opts.onAction || function () {};
      this._bind();
    }

    /** Replace the whole gesture→action map. */
    setMap(map) { this.map = map || {}; }

    /** Add or override a single gesture's action. */
    on(gesture, action) { this.map[gesture] = action; }

    /** List the gestures that currently have an action. */
    gestures() { return Object.keys(this.map); }

    _fire(gesture) {
      const action = this.map[gesture];
      if (action) this.onAction(action, gesture);
    }

    _bind() {
      const o = this.opts;
      let sx = 0, sy = 0, lastTap = 0, longTimer = null, longFired = false;

      this.el.addEventListener("touchstart", (e) => {
        if (e.touches.length !== 1) { if (longTimer) { clearTimeout(longTimer); longTimer = null; } return; }
        const t = e.touches[0];
        sx = t.clientX; sy = t.clientY; longFired = false;
        longTimer = setTimeout(() => { longTimer = null; longFired = true; this._fire("longpress"); }, o.longPressMs);
      }, { passive: true });

      this.el.addEventListener("touchmove", (e) => {
        if (!longTimer) return;
        const t = e.touches[0];
        if (Math.hypot(t.clientX - sx, t.clientY - sy) > o.moveCancelPx) { clearTimeout(longTimer); longTimer = null; }
      }, { passive: true });

      this.el.addEventListener("touchend", (e) => {
        if (longTimer) { clearTimeout(longTimer); longTimer = null; }
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

        // tap vs double-tap (defer the single tap to see if a second arrives)
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
