/**
 * Mouse, touch and pen input in the eye-level views (third and first person).
 *
 * Mouse: shooter look. With the pointer locked to the stage (`requestMouseLook`;
 * entering the view or clicking the stage takes it) plain mouse movement
 * turns the view, the left button works whatever the centre crosshair is on
 * (`aim`), and Esc (the browser) gives the mouse back, so the HUD's buttons
 * work again. With the mouse free, a click on the stage takes it again
 * (`capture`); a drag still turns the view, for browsers that refuse the
 * lock.
 *
 * Touch and pen: a drag turns the camera, a pinch zooms, a tap picks what
 * is under the finger (`tap`).
 *
 * The wheel and the pinch zoom through `zoom`, so the stage can hand over
 * between third and first person.
 */
import type { ShoulderRig } from "./shoulderRig";

/** A press that moved less than this (CSS px) is a click, not a drag. */
const TAP_SLOP_PX = 5;
/** Log zoom per wheel pixel: one 100 px notch is a factor of about 1.13. */
export const WHEEL_ZOOM = 0.0012;
/** With the pointer locked, what is under the crosshair is looked up at most this often, ms. */
const LOCKED_HOVER_MS = 90;

export interface OrbitCallbacks {
  /** A tap or click on a screen point (touch, pen, or a mouse where the stage does not take the pointer). */
  tap: (sx: number, sy: number) => void;
  hover: (sx: number, sy: number) => void;
  leave: () => void;
  /** The camera began to turn: hover labels hide. */
  moved: () => void;
  /** Left button with the pointer locked: work what the centre crosshair is on (screen centre, CSS px). */
  aim?: (sx: number, sy: number) => void;
  /** A mouse click on the stage while the mouse is free: take it for mouse look. Absent: the click taps. */
  capture?: () => void;
  /** Zoom by a factor (> 1 moves out). Absent: the rig zooms itself. */
  zoom?: (factor: number) => void;
}

interface Press { x: number; y: number; startX: number; startY: number; mouse: boolean }

/** The zoom factor of a wheel event. Pure. */
export function wheelFactor(deltaY: number, deltaMode: number): number {
  const unit = deltaMode === 1 ? 16 : deltaMode === 2 ? 400 : 1;
  return Math.exp(deltaY * unit * WHEEL_ZOOM);
}

export function attachOrbitInput(el: HTMLElement, rig: ShoulderRig, cb: OrbitCallbacks): () => void {
  const presses = new Map<number, Press>();
  let dragging = false;
  let pinch = 0;

  const local = (e: { clientX: number; clientY: number }) => {
    const r = el.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  };
  const locked = () => document.pointerLockElement === el;
  const centre = () => ({ x: el.clientWidth / 2, y: el.clientHeight / 2 });
  const zoom = (factor: number) => { if (cb.zoom) cb.zoom(factor); else rig.zoom(factor); };
  let lockedHoverAt = -Infinity;

  // Mouse buttons held (a pointer event's `buttons` mask). A button pressed while another is held sends no
  // pointerdown, only a pointermove with a new mask, so the left button is watched there too.
  let buttons = 0;
  const aimAtCentre = () => {
    const c = centre();
    (cb.aim ?? cb.tap)(c.x, c.y);
  };

  const onDown = (e: PointerEvent) => {
    if (e.pointerType === "mouse") buttons = e.buttons;
    if (locked()) {
      if (e.button === 0) aimAtCentre();
      return;
    }
    const mouse = e.pointerType === "mouse";
    if (e.button !== 0 && mouse) return;
    const p = local(e);
    presses.set(e.pointerId, { x: p.x, y: p.y, startX: p.x, startY: p.y, mouse });
    el.setPointerCapture(e.pointerId);
    if (presses.size === 2) {
      const [a, b] = [...presses.values()];
      pinch = Math.hypot(a.x - b.x, a.y - b.y);
      dragging = true;
    }
  };

  const onMove = (e: PointerEvent) => {
    const chordLeft = e.pointerType === "mouse" && (e.buttons & 1) !== 0 && (buttons & 1) === 0 && buttons !== 0;
    if (e.pointerType === "mouse") buttons = e.buttons;
    if (locked()) {
      if (chordLeft) aimAtCentre();
      rig.look(e.movementX || 0, e.movementY || 0, true);
      const now = performance.now();
      if (now - lockedHoverAt >= LOCKED_HOVER_MS) {
        lockedHoverAt = now;
        const c = centre();
        cb.hover(c.x, c.y);
      }
      return;
    }
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
      if (pinch > 0 && d > 0) zoom(pinch / d);
      pinch = d;
      return;
    }
    if (!dragging && Math.hypot(p.x - press.startX, p.y - press.startY) > TAP_SLOP_PX) {
      dragging = true;
      cb.moved();
    }
    if (dragging) rig.look(p.x - press.x, p.y - press.y);
    press.x = p.x;
    press.y = p.y;
  };

  const onUp = (e: PointerEvent) => {
    if (e.pointerType === "mouse") buttons = e.buttons;
    const press = presses.get(e.pointerId);
    if (!press) return;
    presses.delete(e.pointerId);
    if (el.hasPointerCapture(e.pointerId)) el.releasePointerCapture(e.pointerId);
    if (presses.size > 0) return;
    if (!dragging && e.type === "pointerup") {
      // A mouse click takes the mouse for shooter look; a finger or a pen taps.
      if (press.mouse && cb.capture) cb.capture();
      else cb.tap(press.x, press.y);
    }
    dragging = false;
    pinch = 0;
  };

  const onWheel = (e: WheelEvent) => {
    e.preventDefault();
    zoom(wheelFactor(e.deltaY, e.deltaMode));
    cb.moved();
  };

  const onLeave = () => { if (presses.size === 0 && !locked()) cb.leave(); };

  el.addEventListener("pointerdown", onDown);
  el.addEventListener("pointermove", onMove);
  el.addEventListener("pointerup", onUp);
  el.addEventListener("pointercancel", onUp);
  el.addEventListener("pointerleave", onLeave);
  el.addEventListener("wheel", onWheel, { passive: false });
  // With the mouse taken, the right button never opens a menu over the view.
  const onMenu = (e: Event) => { if (locked()) e.preventDefault(); };
  el.addEventListener("contextmenu", onMenu);
  return () => {
    el.removeEventListener("contextmenu", onMenu);
    el.removeEventListener("pointerdown", onDown);
    el.removeEventListener("pointermove", onMove);
    el.removeEventListener("pointerup", onUp);
    el.removeEventListener("pointercancel", onUp);
    el.removeEventListener("pointerleave", onLeave);
    el.removeEventListener("wheel", onWheel);
  };
}
