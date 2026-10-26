/**
 * Shooter mouse look, shared by the eye-level views (third and first person)
 * and the duel: one turn rate per pointer-lock pixel, the person's
 * sensitivity and inverted vertical axis applied the same way everywhere,
 * and one way to take the mouse (pointer lock, raw movement where the
 * browser offers it).
 *
 * Sign conventions differ between the callers, so `lookDelta` returns the
 * plain turn: `yaw` positive for a move to the right (the deck's yaw turns
 * the other way, so the callers subtract it) and `pitch` positive for "look
 * down" (the mouse moved toward the person); a caller whose pitch is
 * positive up subtracts it.
 */

/** The range of the turn-rate multiplier (the person's mouse sensitivity, `viewSettings`). */
export const LOOK_SENSITIVITY = { min: 0.25, max: 3 } as const;

/** Radians per pointer-lock pixel at sensitivity 1 (about 0.13° per count: a middle-of-the-road shooter default). */
export const MOUSE_LOOK_RATE = 0.0022;

export interface LookPrefs {
  sensitivity: number;
  invertY: boolean;
}

/** The sensitivity as used: finite and inside LOOK_SENSITIVITY. Pure. */
export function clampSensitivity(s: number): number {
  return Math.max(LOOK_SENSITIVITY.min, Math.min(LOOK_SENSITIVITY.max, Number.isFinite(s) ? s : 1));
}

/**
 * The turn for a mouse movement of (dx, dy) px at `rate` rad/px: `yaw` grows
 * with a move to the right, `pitch` grows with a move down (toward the
 * person), flipped by `invertY`. Pure.
 */
export function lookDelta(dx: number, dy: number, prefs: LookPrefs, rate: number = MOUSE_LOOK_RATE): { yaw: number; pitch: number } {
  const r = rate * clampSensitivity(prefs.sensitivity);
  return { yaw: dx * r, pitch: (prefs.invertY ? -dy : dy) * r };
}

/** The element holds the pointer lock (mouse look is on). */
export function hasMouseLook(el: Element | null | undefined): boolean {
  return !!el && document.pointerLockElement === el;
}

/**
 * Take the mouse for shooter look: pointer lock on `el`, asking for raw
 * (unaccelerated) movement first and falling back to a plain lock where the
 * browser refuses that. Needs a user gesture (a click, a key press). Never
 * throws; a refused request simply leaves the mouse free.
 */
export function requestMouseLook(el: HTMLElement): void {
  if (document.pointerLockElement === el || typeof el.requestPointerLock !== "function") return;
  const plain = () => {
    try {
      const p = el.requestPointerLock() as unknown;
      if (p && typeof (p as Promise<void>).catch === "function") (p as Promise<void>).catch(() => undefined);
    } catch {
      /* refused: the mouse stays free */
    }
  };
  try {
    const p = (el.requestPointerLock as (o?: { unadjustedMovement?: boolean }) => unknown)({ unadjustedMovement: true });
    if (p && typeof (p as Promise<void>).catch === "function") (p as Promise<void>).catch(plain);
  } catch {
    plain();
  }
}

/** Give the mouse back (Esc does the same in the browser). */
export function releaseMouseLook(el: Element | null | undefined): void {
  if (hasMouseLook(el)) document.exitPointerLock?.();
}
