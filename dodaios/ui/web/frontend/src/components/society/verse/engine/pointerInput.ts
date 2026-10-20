/**
 * Mouse, touch and pen input on the stage surface: drag to pan, wheel and
 * pinch to zoom toward the pointer, double-click to focus, a click without a
 * drag is a tap (pick a crew member, use a station, walk). Hover is reported
 * for name plates and station labels. Keyboard panning lives in the stage,
 * which knows when focus belongs to it.
 */
import type { ViewController } from "./viewController";

/** A press that moved less than this (CSS px) is a click, not a drag. */
const TAP_SLOP_PX = 5;
/** Wheel zoom per pixel of wheel delta; a pinch on a trackpad arrives as a ctrl-wheel. */
const WHEEL_ZOOM = 0.0016;
const PINCH_WHEEL_ZOOM = 0.01;

export interface PointerCallbacks {
  tap: (sx: number, sy: number) => void;
  hover: (sx: number, sy: number) => void;
  leave: () => void;
  /** A drag or zoom began: hover labels hide while the camera moves. */
  moved: () => void;
  /** A drag began (the person looks around, as opposed to zooming). */
  dragged?: () => void;
  /** Where the wheel zooms around instead of the cursor (third person: the commander), or null for the cursor. */
  zoomAnchor?: () => { x: number; y: number } | null;
}

interface Press { id: number; x: number; y: number; startX: number; startY: number; t: number }

export function attachPointerInput(el: HTMLElement, view: ViewController, cb: PointerCallbacks): () => void {
  const presses = new Map<number, Press>();
  let dragging = false;
  let pinchDistance = 0;
  let velocity = { x: 0, y: 0 };

  const local = (e: { clientX: number; clientY: number }) => {
    const r = el.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  };

  const onDown = (e: PointerEvent) => {
    if (e.button !== 0 && e.pointerType === "mouse") return;
    const p = local(e);
    presses.set(e.pointerId, { id: e.pointerId, x: p.x, y: p.y, startX: p.x, startY: p.y, t: performance.now() });
    el.setPointerCapture(e.pointerId);
    velocity = { x: 0, y: 0 };
    if (presses.size === 2) {
      const [a, b] = [...presses.values()];
      pinchDistance = Math.hypot(a.x - b.x, a.y - b.y);
      dragging = true;
    }
  };

  const onMove = (e: PointerEvent) => {
    const p = local(e);
    const press = presses.get(e.pointerId);
    if (!press) {
      if (presses.size === 0) cb.hover(p.x, p.y);
      return;
    }
    if (presses.size === 2) {
      press.x = p.x;
      press.y = p.y;
      const [a, b] = [...presses.values()];
      const d = Math.hypot(a.x - b.x, a.y - b.y);
      if (pinchDistance > 0 && d > 0) view.zoomAt((a.x + b.x) / 2, (a.y + b.y) / 2, d / pinchDistance);
      pinchDistance = d;
      return;
    }
    const dx = p.x - press.x;
    const dy = p.y - press.y;
    if (!dragging && Math.hypot(p.x - press.startX, p.y - press.startY) > TAP_SLOP_PX) {
      dragging = true;
      cb.moved();
      cb.dragged?.();
    }
    if (dragging) {
      view.drag(dx, dy);
      const now = performance.now();
      const dt = Math.max(1, now - press.t) / 1000;
      // A short running average, so the last jittery event does not decide the fling.
      velocity = { x: velocity.x * 0.6 + (dx / dt) * 0.4, y: velocity.y * 0.6 + (dy / dt) * 0.4 };
      press.t = now;
    }
    press.x = p.x;
    press.y = p.y;
  };

  const onUp = (e: PointerEvent) => {
    const press = presses.get(e.pointerId);
    if (!press) return;
    presses.delete(e.pointerId);
    if (el.hasPointerCapture(e.pointerId)) el.releasePointerCapture(e.pointerId);
    if (presses.size > 0) return;
    if (!dragging && e.type === "pointerup") cb.tap(press.x, press.y);
    else if (dragging && performance.now() - press.t < 80) view.fling(velocity.x, velocity.y);
    dragging = false;
    pinchDistance = 0;
  };

  const onWheel = (e: WheelEvent) => {
    e.preventDefault();
    const p = cb.zoomAnchor?.() ?? local(e);
    const unit = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? 400 : 1;
    const k = e.ctrlKey ? PINCH_WHEEL_ZOOM : WHEEL_ZOOM;
    view.zoomAt(p.x, p.y, Math.exp(-e.deltaY * unit * k));
    cb.moved();
  };

  const onDouble = (e: MouseEvent) => {
    const p = local(e);
    view.focusAt(p.x, p.y);
  };

  const onLeave = () => { if (presses.size === 0) cb.leave(); };

  el.addEventListener("pointerdown", onDown);
  el.addEventListener("pointermove", onMove);
  el.addEventListener("pointerup", onUp);
  el.addEventListener("pointercancel", onUp);
  el.addEventListener("pointerleave", onLeave);
  el.addEventListener("wheel", onWheel, { passive: false });
  el.addEventListener("dblclick", onDouble);
  return () => {
    el.removeEventListener("pointerdown", onDown);
    el.removeEventListener("pointermove", onMove);
    el.removeEventListener("pointerup", onUp);
    el.removeEventListener("pointercancel", onUp);
    el.removeEventListener("pointerleave", onLeave);
    el.removeEventListener("wheel", onWheel);
    el.removeEventListener("dblclick", onDouble);
  };
}
