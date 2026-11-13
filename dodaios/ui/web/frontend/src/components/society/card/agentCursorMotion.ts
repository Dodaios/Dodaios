/**
 * Travel time for the agent cursor, measured in PAGE pixels (the browser's
 * own 1280-wide picture), not in pixels of whatever view shows it: the
 * browser worker waits the same time before it presses
 * (`society/browser/pointer.py`, `glide_seconds`), so the arrow arrives just
 * as the page reacts, in the small tile and on the big stage alike.
 *
 * A short hop stays on screen long enough to follow; a move across the
 * whole page takes about two thirds of a second. The path is a slight arc
 * that starts gently and settles onto the target, the way a hand moves a
 * mouse, instead of a straight line that stops dead.
 */
export const GLIDE_MIN_MS = 280;
export const GLIDE_MAX_MS = 650;
/** How far the arc bows out, as a share of the distance, and at most (page px). */
const ARC_SHARE = 0.12;
const ARC_MAX_PX = 48;

export interface CursorClick {
  id: number;
  x: number;
  y: number;
}

export interface CursorMotion {
  x: number;
  y: number;
  fromX: number;
  fromY: number;
  toX: number;
  toY: number;
  /** Control point of the arc from `from` to `to` (a quadratic curve). */
  ctrlX: number;
  ctrlY: number;
  start: number;
  duration: number;
  clickId: number;
  pendingClick: CursorClick | null;
}

export interface CursorTarget {
  x: number;
  y: number;
  clickId: number;
  clickX: number;
  clickY: number;
}

export interface AimResult {
  motion: CursorMotion;
  changed: boolean;
  releaseClick: CursorClick | null;
}

/** Keep in step with `glide_seconds` in `society/browser/pointer.py`. */
export function glideDurationMs(distancePx: number): number {
  if (!Number.isFinite(distancePx) || distancePx < 1) return 0;
  return Math.min(GLIDE_MAX_MS, Math.max(GLIDE_MIN_MS, 240 + distancePx * 0.3));
}

/** Starts gently, travels, and settles: the arrow never jerks off or stops dead. */
export function easeInOutCubic(t: number): number {
  const clamped = Math.min(1, Math.max(0, t));
  return clamped < 0.5
    ? 4 * clamped * clamped * clamped
    : 1 - Math.pow(-2 * clamped + 2, 3) / 2;
}

/**
 * The bend of a move: off the straight line by a share of its length. A
 * sideways move bows upward whichever way it goes, like a wrist turning.
 */
export function arcControl(fromX: number, fromY: number, toX: number, toY: number): { x: number; y: number } {
  const dx = toX - fromX;
  const dy = toY - fromY;
  const length = Math.hypot(dx, dy);
  const midX = (fromX + toX) / 2;
  const midY = (fromY + toY) / 2;
  if (length < 1) return { x: midX, y: midY };
  const bow = Math.min(ARC_MAX_PX, length * ARC_SHARE) * (dx >= 0 ? 1 : -1);
  // The unit normal (dy, -dx) points up for a move to the right.
  return { x: midX + (dy / length) * bow, y: midY - (dx / length) * bow };
}

function along(from: number, ctrl: number, to: number, t: number): number {
  const rest = 1 - t;
  return rest * rest * from + 2 * rest * t * ctrl + t * t * to;
}

export function projectFramePoint(
  frameX: number,
  frameY: number,
  frameW: number,
  frameH: number,
  hostW: number,
  hostH: number,
): { x: number; y: number; scale: number } {
  if (frameW <= 0 || frameH <= 0 || hostW <= 0 || hostH <= 0) {
    return { x: frameX, y: frameY, scale: 1 };
  }
  const scale = Math.min(hostW / frameW, hostH / frameH);
  return {
    x: (hostW - frameW * scale) / 2 + frameX * scale,
    y: (hostH - frameH * scale) / 2 + frameY * scale,
    scale,
  };
}

export function beginCursor(x: number, y: number, now: number): CursorMotion {
  return {
    x,
    y,
    fromX: x,
    fromY: y,
    toX: x,
    toY: y,
    ctrlX: x,
    ctrlY: y,
    start: now,
    duration: 0,
    clickId: 0,
    pendingClick: null,
  };
}

function close(a: number, b: number): boolean {
  return Math.abs(a - b) < 0.5;
}

export function aimCursor(
  motion: CursorMotion,
  target: CursorTarget,
  distancePx: number,
  now: number,
  reducedMotion: boolean,
): AimResult {
  const samePoint = close(motion.toX, target.x) && close(motion.toY, target.y);
  const sameClick = motion.clickId === target.clickId;
  if (samePoint && sameClick) return { motion, changed: false, releaseClick: null };

  let releaseClick: CursorClick | null = null;
  let pending = motion.pendingClick;
  if (!samePoint && pending) {
    const headingToClick = close(target.x, pending.x) && close(target.y, pending.y);
    if (!headingToClick) {
      releaseClick = pending;
      pending = null;
    }
  }

  let next: CursorMotion = { ...motion, clickId: target.clickId, pendingClick: pending };
  if (!samePoint) {
    const duration = reducedMotion ? 0 : glideDurationMs(distancePx);
    const snap = reducedMotion || duration === 0;
    const ctrl = arcControl(motion.x, motion.y, target.x, target.y);
    next = {
      ...next,
      fromX: motion.x,
      fromY: motion.y,
      toX: target.x,
      toY: target.y,
      ctrlX: ctrl.x,
      ctrlY: ctrl.y,
      start: now,
      duration,
      x: snap ? target.x : motion.x,
      y: snap ? target.y : motion.y,
    };
  }
  if (!sameClick && target.clickId > motion.clickId && target.clickId > 0) {
    next = {
      ...next,
      pendingClick: { id: target.clickId, x: target.clickX, y: target.clickY },
    };
  }
  return { motion: next, changed: true, releaseClick };
}

export function hasArrived(x: number, y: number, targetX: number, targetY: number): boolean {
  const dx = x - targetX;
  const dy = y - targetY;
  return dx * dx + dy * dy <= 2.5 * 2.5;
}

export function stepCursor(motion: CursorMotion, now: number): {
  motion: CursorMotion;
  arrivedClick: CursorClick | null;
  moving: boolean;
} {
  const t = motion.duration <= 0
    ? 1
    : Math.min(1, Math.max(0, (now - motion.start) / motion.duration));
  const eased = easeInOutCubic(t);
  const x = along(motion.fromX, motion.ctrlX, motion.toX, eased);
  const y = along(motion.fromY, motion.ctrlY, motion.toY, eased);
  let pending = motion.pendingClick;
  let arrivedClick: CursorClick | null = null;
  if (pending && hasArrived(x, y, pending.x, pending.y)) {
    arrivedClick = pending;
    pending = null;
  }
  return {
    motion: { ...motion, x, y, pendingClick: pending },
    arrivedClick,
    moving: t < 1,
  };
}
