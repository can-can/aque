// gestures.js — standalone, extensible touch-gesture recognizer.
//
// One-finger gestures: tap, doubletap, longpress, and a DRAG.
//   The drag emits one direction step per `stepPx` of finger movement (like a
//   scroll wheel): it moves ONLY while your finger moves, so it stops the instant
//   you stop or lift — no timer, no overshoot, and it can never run away (there
//   is nothing running when the finger is still). A quick flick sends one step
//   in its direction.
// Two-finger: vertical pan reported via onScroll(dyPx).
//
// onAction(action, gestureName, isRepeat): isRepeat is true for the extra steps
// emitted while dragging (so the page can skip the on-screen flash for those).
(function (global) {
  "use strict";

  const DEFAULTS = {
    longPressMs: 550,
    doubleTapMs: 300,
    swipeMinPx: 28,      // movement before a drag engages (also the flick threshold)
    moveCancelPx: 12,
    stepPx: 24,          // finger pixels per direction step while dragging
    multiCooldownMs: 250,
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

    _fire(gesture, repeat) {
      const action = this.map[gesture];
      if (action) this.onAction(action, gesture, !!repeat);
    }

    _bind() {
      const o = this.opts;
      let sx = 0, sy = 0, lastTap = 0, longTimer = null, longFired = false;
      let maxTouches = 0, suppressUntil = 0, lastTwoY = null;
      let dragging = false, lastX = 0, lastY = 0, accV = 0, accH = 0;

      const cancelLong = () => { if (longTimer) { clearTimeout(longTimer); longTimer = null; } };
      const midY = (t) => (t[0].clientY + t[1].clientY) / 2;
      const isMulti = () => maxTouches >= 2;
      const dominant = (dx, dy) => Math.abs(dx) > Math.abs(dy)
        ? (dx > 0 ? "swipe-right" : "swipe-left")
        : (dy > 0 ? "swipe-down" : "swipe-up");

      this.el.addEventListener("touchstart", (e) => {
        maxTouches = Math.max(maxTouches, e.touches.length);
        if (e.touches.length >= 2) {
          lastTwoY = midY(e.touches);
          cancelLong();
          dragging = false;
          return;
        }
        if (isMulti()) return;
        const t = e.touches[0];
        sx = lastX = t.clientX; sy = lastY = t.clientY;
        longFired = false; dragging = false; accV = 0; accH = 0;
        longTimer = setTimeout(() => { longTimer = null; longFired = true; this._fire("longpress"); }, o.longPressMs);
      }, { passive: true });

      this.el.addEventListener("touchmove", (e) => {
        if (isMulti()) {
          if (e.touches.length >= 2 && this.onScroll) {
            const y = midY(e.touches); const dy = y - lastTwoY; lastTwoY = y;
            if (dy !== 0) this.onScroll(dy);
          }
          return;
        }
        const t = e.touches[0];
        if (!t) return;

        if (!dragging) {
          const dx = t.clientX - sx, dy = t.clientY - sy;
          if (Math.hypot(dx, dy) >= o.swipeMinPx) {
            cancelLong();
            dragging = true;
            lastX = t.clientX; lastY = t.clientY;
            accV = 0; accH = 0;
            this._fire(dominant(dx, dy));           // first step (with flash)
          } else if (longTimer && Math.hypot(dx, dy) > o.moveCancelPx) {
            cancelLong();
          }
          return;
        }

        // Dragging: emit one step per stepPx of movement, in the move's direction.
        accV += t.clientY - lastY;
        accH += t.clientX - lastX;
        lastX = t.clientX; lastY = t.clientY;
        while (accV >= o.stepPx) { this._fire("swipe-down", true); accV -= o.stepPx; }
        while (accV <= -o.stepPx) { this._fire("swipe-up", true); accV += o.stepPx; }
        while (accH >= o.stepPx) { this._fire("swipe-right", true); accH -= o.stepPx; }
        while (accH <= -o.stepPx) { this._fire("swipe-left", true); accH += o.stepPx; }
      }, { passive: true });

      this.el.addEventListener("touchend", (e) => {
        if (e.touches.length > 0) return;
        const wasMulti = isMulti();
        const t0 = Date.now();
        cancelLong();
        maxTouches = 0;
        const wasDrag = dragging;
        dragging = false;

        if (wasMulti) { suppressUntil = t0 + o.multiCooldownMs; return; }
        if (t0 < suppressUntil) return;
        if (wasDrag) return;          // was a drag-scroll, not a tap/flick
        if (longFired) return;

        const t = e.changedTouches[0];
        const dx = t.clientX - sx, dy = t.clientY - sy;
        if (Math.hypot(dx, dy) >= o.swipeMinPx) { this._fire(dominant(dx, dy)); lastTap = 0; return; }
        if (t0 - lastTap < o.doubleTapMs) { lastTap = 0; this._fire("doubletap"); }
        else { lastTap = t0; const at = t0; setTimeout(() => { if (lastTap === at) { lastTap = 0; this._fire("tap"); } }, o.doubleTapMs); }
      }, { passive: true });

      this.el.addEventListener("touchcancel", () => {
        cancelLong();
        maxTouches = 0;
        dragging = false;
      }, { passive: true });
    }
  }

  global.GestureInput = GestureInput;
})(window);
