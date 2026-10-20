/**
 * The pan/zoom view over a plate, in plate metres. Pure.
 *
 * A view is the plate point at the viewport centre (cu, cv) and a scale in CSS
 * pixels per plate metre. The orthographic camera is derived from it, so the
 * screen, the plate and the 3D world share one mapping.
 *
 * Two hard limits (BRIEF §2): the plate always covers the whole viewport
 * (nothing outside the hull is ever shown), and zoom-in stops at 1.25× the
 * plate's native density in device pixels. When the two disagree (a viewport
 * larger than the plate at that density) coverage wins.
 */
import type { PlateCamera, PlatePoint } from "./plateMath";

export interface View { cu: number; cv: number; scale: number }

export interface Viewport {
  /** CSS pixels. */
  width: number;
  height: number;
  /** Device pixels per CSS pixel. */
  dpr: number;
}

/** Zoom-in limit relative to the plate's native density. */
export const MAX_DENSITY = 1.25;

export interface ScaleLimits { min: number; max: number }

export function scaleLimits(cam: PlateCamera, vp: Viewport): ScaleLimits {
  const cover = Math.max(vp.width / cam.frameW, vp.height / cam.frameH);
  const native = (MAX_DENSITY * cam.pxPerMetre) / Math.max(vp.dpr, 0.01);
  return { min: cover, max: Math.max(cover, native) };
}

/** The view moved inside the plate and its scale inside the limits. */
export function clampView(cam: PlateCamera, vp: Viewport, view: View): View {
  const { min, max } = scaleLimits(cam, vp);
  const scale = Math.min(max, Math.max(min, view.scale));
  const halfW = vp.width / (2 * scale);
  const halfH = vp.height / (2 * scale);
  return {
    scale,
    cu: clampSpan(view.cu, -cam.frameW / 2 + halfW, cam.frameW / 2 - halfW),
    cv: clampSpan(view.cv, -cam.frameH / 2 + halfH, cam.frameH / 2 - halfH),
  };
}

function clampSpan(value: number, lo: number, hi: number): number {
  // A rounding sliver can leave lo a hair above hi at the coverage limit: centre then.
  if (lo > hi) return (lo + hi) / 2;
  return Math.min(hi, Math.max(lo, value));
}

export function screenToPlate(view: View, vp: Viewport, sx: number, sy: number): PlatePoint {
  return { u: view.cu + (sx - vp.width / 2) / view.scale, v: view.cv - (sy - vp.height / 2) / view.scale };
}

export function plateToScreen(view: View, vp: Viewport, u: number, v: number): { x: number; y: number } {
  return { x: (u - view.cu) * view.scale + vp.width / 2, y: (view.cv - v) * view.scale + vp.height / 2 };
}

/** Zoom by `factor`, keeping the plate point under (sx, sy) where it is. Not clamped. */
export function zoomAt(view: View, vp: Viewport, sx: number, sy: number, factor: number): View {
  const anchor = screenToPlate(view, vp, sx, sy);
  const scale = view.scale * factor;
  return { scale, cu: anchor.u - (sx - vp.width / 2) / scale, cv: anchor.v + (sy - vp.height / 2) / scale };
}

/** Pan by a screen-space drag delta. */
export function panBy(view: View, dx: number, dy: number): View {
  return { ...view, cu: view.cu - dx / view.scale, cv: view.cv + dy / view.scale };
}

/** The visible plate rectangle. */
export function viewRect(view: View, vp: Viewport): { u0: number; u1: number; v0: number; v1: number } {
  const halfW = vp.width / (2 * view.scale);
  const halfH = vp.height / (2 * view.scale);
  return { u0: view.cu - halfW, u1: view.cu + halfW, v0: view.cv - halfH, v1: view.cv + halfH };
}

/** Orthographic frustum in camera space (metres), centred on the view. */
export function frustum(view: View, vp: Viewport): { left: number; right: number; top: number; bottom: number } {
  const halfW = vp.width / (2 * view.scale);
  const halfH = vp.height / (2 * view.scale);
  return { left: -halfW, right: halfW, top: halfH, bottom: -halfH };
}

/** Device pixels per plate L0 pixel: 1 = native, the limit is MAX_DENSITY. */
export function density(cam: PlateCamera, vp: Viewport, view: View): number {
  return (view.scale * vp.dpr) / cam.pxPerMetre;
}

/**
 * One step of critically damped approach toward the target, frame-rate
 * independent. `halfLifeS` is how long it takes to close half the gap.
 */
export function damp(current: View, target: View, dtS: number, halfLifeS: number): View {
  if (halfLifeS <= 0) return target;
  const k = 1 - Math.pow(0.5, dtS / halfLifeS);
  // Zoom eases in log space so zooming in and out feel the same.
  const scale = Math.exp(Math.log(current.scale) + (Math.log(target.scale) - Math.log(current.scale)) * k);
  return { cu: current.cu + (target.cu - current.cu) * k, cv: current.cv + (target.cv - current.cv) * k, scale };
}

/** True when two views are close enough that the camera can stop moving. */
export function settled(a: View, b: View): boolean {
  return Math.abs(a.cu - b.cu) * a.scale < 0.05 && Math.abs(a.cv - b.cv) * a.scale < 0.05
    && Math.abs(a.scale - b.scale) / b.scale < 1e-4;
}
