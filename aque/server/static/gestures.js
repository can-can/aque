// gestures.js — standalone, extensible touch-gesture recognizer.
//
// One-finger gestures: tap, doubletap, longpress. A one-finger DRAG is NOT
//   handled here — the page lets iOS scroll a native layer and captures that,
//   because a JS touch stream for a one-finger drag is unreliable in a WKWebView
//   (iOS silently stops feeding touchmove events a few frames in).
// Two-finger gestures: a PAN that steps the arrow keys (4-directional) and a
//   PINCH that zooms. Each two-finger gesture commits to EITHER arrows or zoom —
//   whichever the fingers do first — so the two never fight.
//
// Listeners are PASSIVE: they never call preventDefault, so they can't block the
// element's native scrolling.
//
// onAction(action, gestureName, isRepeat): isRepeat is true for the extra arrow
// steps emitted while panning (so the page can skip the on-screen flash).
(function (global) {
  "use strict";

  const DEFAULTS = {
    longPressMs: 550,
    doubleTapMs: 300,
    swipeMinPx: 28,      // movement that disqualifies a touch from being a tap
    moveCancelPx: 12,    // movement that cancels a pending long-press
    stepPx: 24,          // two-finger pan pixels per arrow step
    multiCooldownMs: 250,
    pinchCommitPx: 16,   // two-finger distance change before pinch-zoom engages
    panCommitPx: 8,      // two-finger midpoint move before arrow-pan engages
    zoomStepPx: 36,      // pinch distance change per zoom step
  };

  class GestureInput {
    constructor(el, opts = {}) {
      this.el = el;
      this.opts = Object.assign({}, DEFAULTS, opts);
      this.map = opts.map || {};
      this.onAction = opts.onAction || function () {};
      this.onZoom = opts.onZoom || null;
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
      let sx = 0, sy = 0, lastTap = 0, longTimer = null, longFired = false, moved = false;
      let maxTouches = 0, suppressUntil = 0;
      // two-finger state: commit to "arrows" (pan) or "zoom" once, then stick.
      let twoMode = null, startDist = 0, startMidX = 0, startMidY = 0,
          lastTwoX = 0, lastTwoY = 0, lastDist = 0, accZoom = 0, accV = 0, accH = 0;

      const cancelLong = () => { if (longTimer) { clearTimeout(longTimer); longTimer = null; } };
      const midX = (t) => (t[0].clientX + t[1].clientX) / 2;
      const midY = (t) => (t[0].clientY + t[1].clientY) / 2;
      const dist2 = (t) => Math.hypot(t[0].clientX - t[1].clientX, t[0].clientY - t[1].clientY);
      const isMulti = () => maxTouches >= 2;

      this.el.addEventListener("touchstart", (e) => {
        maxTouches = Math.max(maxTouches, e.touches.length);
        if (e.touches.length >= 2) {
          lastTwoX = startMidX = midX(e.touches);
          lastTwoY = startMidY = midY(e.touches);
          startDist = lastDist = dist2(e.touches);
          twoMode = null; accZoom = 0; accV = 0; accH = 0;
          cancelLong();
          return;
        }
        if (isMulti()) return;
        const t = e.touches[0];
        sx = t.clientX; sy = t.clientY;
        longFired = false; moved = false;
        longTimer = setTimeout(() => { longTimer = null; longFired = true; this._fire("longpress"); }, o.longPressMs);
      }, { passive: true });

      this.el.addEventListener("touchmove", (e) => {
        if (isMulti()) {
          if (e.touches.length >= 2) {
            const x = midX(e.touches), y = midY(e.touches), d = dist2(e.touches);
            if (twoMode === null) {
              const ddist = d - startDist, pan = Math.hypot(x - startMidX, y - startMidY);
              if (Math.abs(ddist) >= o.pinchCommitPx && Math.abs(ddist) > pan) {
                twoMode = "zoom"; accZoom = ddist; lastDist = d;
              } else if (pan >= o.panCommitPx) {
                twoMode = "arrows"; lastTwoX = startMidX; lastTwoY = startMidY; accV = 0; accH = 0;
              }
            }
            if (twoMode === "arrows") {
              accV += y - lastTwoY; accH += x - lastTwoX;
              lastTwoX = x; lastTwoY = y;
              while (accV >= o.stepPx) { this._fire("swipe-down", true); accV -= o.stepPx; }
              while (accV <= -o.stepPx) { this._fire("swipe-up", true); accV += o.stepPx; }
              while (accH >= o.stepPx) { this._fire("swipe-right", true); accH -= o.stepPx; }
              while (accH <= -o.stepPx) { this._fire("swipe-left", true); accH += o.stepPx; }
            } else if (twoMode === "zoom" && this.onZoom) {
              accZoom += d - lastDist; lastDist = d;
              while (accZoom >= o.zoomStepPx) { this.onZoom(1); accZoom -= o.zoomStepPx; }
              while (accZoom <= -o.zoomStepPx) { this.onZoom(-1); accZoom += o.zoomStepPx; }
            }
          }
          return;
        }
        const t = e.touches[0];
        if (!t) return;
        // One finger: only watch for enough movement to cancel a pending
        // long-press. The drag itself is the native scroll — not ours.
        if (!moved && Math.hypot(t.clientX - sx, t.clientY - sy) > o.moveCancelPx) {
          moved = true; cancelLong();
        }
      }, { passive: true });

      this.el.addEventListener("touchend", (e) => {
        if (e.touches.length > 0) return;
        const wasMulti = isMulti();
        const t0 = Date.now();
        cancelLong();
        maxTouches = 0; twoMode = null;

        if (wasMulti) { suppressUntil = t0 + o.multiCooldownMs; return; }
        if (t0 < suppressUntil) return;
        if (longFired) return;

        const t = e.changedTouches[0];
        const dx = t.clientX - sx, dy = t.clientY - sy;
        if (Math.hypot(dx, dy) >= o.swipeMinPx) { lastTap = 0; return; }   // was a drag (native scroll), not a tap
        if (t0 - lastTap < o.doubleTapMs) { lastTap = 0; this._fire("doubletap"); }
        else { lastTap = t0; const at = t0; setTimeout(() => { if (lastTap === at) { lastTap = 0; this._fire("tap"); } }, o.doubleTapMs); }
      }, { passive: true });

      this.el.addEventListener("touchcancel", () => {
        cancelLong();
        maxTouches = 0; twoMode = null;
      }, { passive: true });
    }
  }

  global.GestureInput = GestureInput;
})(window);
