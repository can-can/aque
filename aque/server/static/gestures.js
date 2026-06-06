// gestures.js — standalone, extensible touch-gesture recognizer.
//
// It RECOGNIZES gestures and looks them up in a map; it does not know what an
// action means (sending bytes, scrolling, etc.) — the caller decides. That
// keeps it reusable: floating buttons can drive the same action objects.
//
// One-finger gestures: tap, doubletap, longpress, swipe-up/down/left/right.
//   A swipe fires its direction once when you cross the threshold; if you then
//   HOLD, that direction AUTO-REPEATS (sticky), and you can steer it by moving
//   (drag down = ↓ repeats, drag up = ↑ repeats, etc.) until you lift.
// Two-finger: vertical pan reported via onScroll(dyPx).
//
// Disambiguation: a tap/doubletap fires only if the whole sequence stayed at
// one finger and outside the cooldown after a multi-touch gesture.
(function (global) {
  "use strict";

  const DEFAULTS = {
    longPressMs: 550,
    doubleTapMs: 300,
    swipeMinPx: 28,
    moveCancelPx: 12,
    multiCooldownMs: 250,
    repeatDelayMs: 400, // hold a swipe this long before it starts auto-repeating
    repeatMs: 120,      // interval between repeats while held
    repeatMaxMs: 5000,  // hard cap: a sticky repeat can never run longer than this
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
      let dirFired = false, curDir = null, repeatDelayTimer = null, repeatTimer = null, repeatMaxTimer = null;

      const cancelLong = () => { if (longTimer) { clearTimeout(longTimer); longTimer = null; } };
      const stopRepeat = () => {
        if (repeatDelayTimer) { clearTimeout(repeatDelayTimer); repeatDelayTimer = null; }
        if (repeatTimer) { clearInterval(repeatTimer); repeatTimer = null; }
        if (repeatMaxTimer) { clearTimeout(repeatMaxTimer); repeatMaxTimer = null; }
      };
      const midY = (t) => (t[0].clientY + t[1].clientY) / 2;
      const isMulti = () => maxTouches >= 2;
      const dominant = (dx, dy) => Math.abs(dx) > Math.abs(dy)
        ? (dx > 0 ? "swipe-right" : "swipe-left")
        : (dy > 0 ? "swipe-down" : "swipe-up");

      this.el.addEventListener("touchstart", (e) => {
        maxTouches = Math.max(maxTouches, e.touches.length);
        if (e.touches.length >= 2) {
          lastTwoY = midY(e.touches);
          cancelLong(); stopRepeat();
          dirFired = false; curDir = null;
          return;
        }
        if (isMulti()) return;
        const t = e.touches[0];
        sx = t.clientX; sy = t.clientY;
        longFired = false; dirFired = false; curDir = null;
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
        const dx = t.clientX - sx, dy = t.clientY - sy;
        const dist = Math.hypot(dx, dy);

        if (!dirFired) {
          if (dist >= o.swipeMinPx) {
            cancelLong();
            dirFired = true;
            curDir = dominant(dx, dy);
            this._fire(curDir);                                  // one arrow on the swipe
            repeatDelayTimer = setTimeout(() => {                // then sticky auto-repeat
              repeatTimer = setInterval(() => { if (curDir) this._fire(curDir, true); }, o.repeatMs);
              repeatMaxTimer = setTimeout(stopRepeat, o.repeatMaxMs); // (3) timeout fallback
            }, o.repeatDelayMs);
          } else if (longTimer && dist > o.moveCancelPx) {
            cancelLong();
          }
        } else if (dist >= o.swipeMinPx * 0.6) {
          curDir = dominant(dx, dy);                             // steer the held direction
        }
      }, { passive: true });

      this.el.addEventListener("touchend", (e) => {
        if (e.touches.length > 0) return;

        const wasMulti = isMulti();
        const now = Date.now();
        cancelLong(); stopRepeat();
        maxTouches = 0;
        const wasDir = dirFired;
        dirFired = false; curDir = null;

        if (wasMulti) { suppressUntil = now + o.multiCooldownMs; return; }
        if (now < suppressUntil) return;
        if (wasDir) return;        // swipe (and any repeats) already fired
        if (longFired) return;

        const t = e.changedTouches[0];
        const dx = t.clientX - sx, dy = t.clientY - sy;
        if (Math.hypot(dx, dy) >= o.swipeMinPx) {  // safety net if a move slipped through
          this._fire(dominant(dx, dy));
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

      this.el.addEventListener("touchcancel", () => {
        cancelLong();
        stopRepeat();
        maxTouches = 0;
        dirFired = false;
        curDir = null;
      }, { passive: true });

      // (1)(2) WebKit drops the end event on the originating element when a touch
      // is dragged off-screen (it cancels the touch for a system gesture). The
      // DOCUMENT still gets end events even off-element, so any release/cancel/
      // new-touch anywhere stops a running sticky repeat. The time cap above (3)
      // covers the case where the touch is dropped with no event at all.
      const stopOnEnd = () => { if (repeatTimer || repeatDelayTimer) stopRepeat(); };
      document.addEventListener("touchend", stopOnEnd, { passive: true, capture: true });
      document.addEventListener("touchcancel", stopOnEnd, { passive: true, capture: true });
      document.addEventListener("touchstart", stopOnEnd, { passive: true, capture: true });
    }
  }

  global.GestureInput = GestureInput;
})(window);
