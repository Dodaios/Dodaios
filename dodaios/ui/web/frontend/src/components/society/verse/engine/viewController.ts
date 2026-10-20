/**
 * The camera's pan and zoom state over one plate: a target view the input
 * moves, and a current view that follows it with damping each frame. Drags
 * move both (the plate stays under the pointer); wheel, keys, focus, fling
 * and the third-person follow move the target only. Every view is clamped
 * (view.ts), so the plate always covers the viewport. With reduced motion
 * the current view jumps.
 *
 * The third-person camera works like a game's: close on the commander (about
 * 200 CSS px per metre on a large window), leading them a little in the
 * direction they walk, easing back onto them when they stop.
 */
import type { PlateCamera } from "./plateMath";
import { OVERVIEW_MAGNIFY_LIMIT } from "./tiles";
import { clampView, damp, panBy, scaleLimits, screenToPlate, settled, zoomAt, type View, type Viewport } from "./view";

const HALF_LIFE_S = 0.09;
/** Keyboard pan speed, CSS pixels per second (Shift doubles it). */
const KEY_PAN_PX_S = 720;
/** A released drag keeps going for about this long. */
const FLING_S = 0.22;
/** The third-person camera shows about this many metres across the longer side of the viewport (≈ 205 px/m on 2560 px). */
export const FOLLOW_SPAN_M = 12.5;
/** …and at least this many across the shorter side, so a wide, low panel still shows the floor around them. */
export const FOLLOW_MIN_SHORT_SPAN_M = 5;
/** A small panel follows from no further than this, CSS px per metre. */
export const FOLLOW_MIN_PX_M = 48;
/** The camera leads a walking commander by their velocity times this, seconds. */
const LEAD_S = 0.45;
/** The lead stays within this share of the half viewport, per axis. */
const LEAD_MAX = 0.22;
/** The lead eases toward the walking direction (and back to zero) with this half-life: no jitter at path corners. */
const LEAD_HALF_LIFE_S = 0.35;
/** Faster than this between two frames is a jump (sitting down, a stair snap), not a walk: the lead holds, m/s. */
const LEAD_MAX_SPEED = 8;
/** Further than this between two frames is a teleport (a lift, a respawn): the lead resets, metres. */
const TELEPORT_M = 1.5;

export type PanKey = "left" | "right" | "up" | "down";

function clampAbs(value: number, limit: number): number {
  return Math.max(-limit, Math.min(limit, value));
}

/** The third-person zoom for a plate and a viewport (ViewController.followScale). Pure. */
export function followScaleFor(cam: PlateCamera, vp: Viewport): number {
  const { min, max } = scaleLimits(cam, vp);
  const longer = Math.max(vp.width, vp.height);
  const shorter = Math.min(vp.width, vp.height);
  const wanted = Math.max(FOLLOW_MIN_PX_M, Math.min(longer / FOLLOW_SPAN_M, shorter / FOLLOW_MIN_SHORT_SPAN_M));
  const sharp = (OVERVIEW_MAGNIFY_LIMIT * cam.pxPerMetre) / Math.max(vp.dpr, 0.01);
  return Math.min(max, Math.max(min, Math.min(sharp, wanted)));
}

export class ViewController {
  cam: PlateCamera | null = null;
  vp: Viewport = { width: 1, height: 1, dpr: 1 };
  current: View = { cu: 0, cv: 0, scale: 1 };
  target: View = { cu: 0, cv: 0, scale: 1 };
  reduced = false;
  private keys = new Set<PanKey>();
  private focusPoint: { u: number; v: number } | null = null;
  /** The viewport has a real size (read-only outside this class). */
  measured = false;
  /** The current plate was framed against a real viewport. */
  private framed = false;
  private fast = false;
  /** Bumped whenever the current view changes, so consumers can skip work on still frames. */
  revision = 0;
  /** The third-person look-ahead, plate metres, and the followed point last frame. */
  private leadU = 0;
  private leadV = 0;
  private lastU = Number.NaN;
  private lastV = Number.NaN;

  /**
   * A new plate: frame it on `focus` (plate metres) at a comfortable zoom.
   * Before the viewport has been measured the framing waits for the first
   * real size, so a first open does not start fully zoomed out.
   */
  setPlate(cam: PlateCamera, focus: { u: number; v: number } | null): void {
    this.cam = cam;
    this.focusPoint = focus;
    this.framed = this.measured;
    this.resetLead();
    this.frame();
  }

  resize(vp: Viewport): void {
    this.vp = vp;
    this.measured = vp.width > 1 && vp.height > 1;
    if (!this.cam) return;
    if (!this.framed && this.measured) {
      this.framed = true;
      this.frame();
      return;
    }
    this.current = clampView(this.cam, vp, this.current);
    this.target = clampView(this.cam, vp, this.target);
    this.revision++;
  }

  private frame(): void {
    if (!this.cam) return;
    const { min, max } = scaleLimits(this.cam, this.vp);
    const scale = Math.sqrt(min * max);
    const view = clampView(this.cam, this.vp, { cu: this.focusPoint?.u ?? 0, cv: this.focusPoint?.v ?? 0, scale });
    this.current = view;
    this.target = view;
    this.revision++;
  }

  drag(dx: number, dy: number): void {
    if (!this.cam) return;
    // Looking around: the follow lets go until the commander walks again.
    this.resetLead();
    this.current = clampView(this.cam, this.vp, panBy(this.current, dx, dy));
    this.target = this.current;
    this.revision++;
  }

  /** Continue a released drag by its velocity (CSS px/s). */
  fling(vx: number, vy: number): void {
    if (!this.cam || this.reduced) return;
    this.target = clampView(this.cam, this.vp, panBy(this.target, vx * FLING_S, vy * FLING_S));
  }

  zoomAt(sx: number, sy: number, factor: number): void {
    if (!this.cam) return;
    this.target = clampView(this.cam, this.vp, zoomAt(this.target, this.vp, sx, sy, factor));
  }

  /** Bring a plate point to the centre, optionally at a new scale. */
  focus(u: number, v: number, scale = this.target.scale): void {
    if (!this.cam) return;
    this.target = clampView(this.cam, this.vp, { cu: u, cv: v, scale });
  }

  /**
   * The third-person zoom, CSS px per metre: close, like a game camera, so
   * the commander reads as a character (FOLLOW_SPAN_M across the longer side
   * of the viewport: about 205 px/m and a ~225 px tall figure on a 2560 px
   * window), at least FOLLOW_MIN_SHORT_SPAN_M across the shorter side, never
   * further than FOLLOW_MIN_PX_M in a small panel. Never closer than the
   * plate is sharp (its finest tiles magnified at most OVERVIEW_MAGNIFY_LIMIT
   * in device pixels; an older 96 px/m deck stops there), and inside the
   * plate's limits.
   */
  followScale(): number {
    if (!this.cam) return this.target.scale;
    return followScaleFor(this.cam, this.vp);
  }

  /**
   * Third person, every frame: keep the commander (a moving plate point) in
   * the middle of the screen at the current zoom, led a little in the
   * direction they walk. `dtS` is the frame's step (0 = no look-ahead update).
   */
  follow(u: number, v: number, dtS = 0): void {
    if (!this.cam) return;
    if (dtS > 0 && !this.reduced && Number.isFinite(this.lastU)) {
      const du = u - this.lastU;
      const dv = v - this.lastV;
      const jump = Math.hypot(du, dv);
      if (jump > TELEPORT_M) {
        this.leadU = 0;
        this.leadV = 0;
      } else if (jump / dtS <= LEAD_MAX_SPEED) {
        const halfW = this.vp.width / (2 * this.target.scale);
        const halfH = this.vp.height / (2 * this.target.scale);
        const wantU = clampAbs((du / dtS) * LEAD_S, LEAD_MAX * halfW);
        const wantV = clampAbs((dv / dtS) * LEAD_S, LEAD_MAX * halfH);
        const k = 1 - Math.pow(0.5, dtS / LEAD_HALF_LIFE_S);
        this.leadU += (wantU - this.leadU) * k;
        this.leadV += (wantV - this.leadV) * k;
      }
    }
    this.lastU = u;
    this.lastV = v;
    const next = clampView(this.cam, this.vp, { cu: u + this.leadU, cv: v + this.leadV, scale: this.target.scale });
    // A commander standing still keeps the same target, so a settled view stays still (no work on idle frames).
    if (Math.abs(next.cu - this.target.cu) > 1e-6 || Math.abs(next.cv - this.target.cv) > 1e-6 || next.scale !== this.target.scale) {
      this.target = next;
    }
  }

  /** Third person starts on this plate point: centred at the follow zoom, no lead. */
  reframeOn(u: number, v: number): void {
    this.resetLead();
    this.lastU = u;
    this.lastV = v;
    this.focus(u, v, this.followScale());
  }

  /** True while the camera still leads the commander (it eases back onto them after they stop). */
  get leading(): boolean {
    return Math.abs(this.leadU) + Math.abs(this.leadV) > 0.01;
  }

  /** Forget the look-ahead (a drag, the bird's-eye view, a new deck). */
  resetLead(): void {
    this.leadU = 0;
    this.leadV = 0;
    this.lastU = Number.NaN;
    this.lastV = Number.NaN;
  }

  /** Bird's-eye: pull back as far as the plate allows, around what is in the middle now. */
  overview(): void {
    if (!this.cam) return;
    this.resetLead();
    const { min } = scaleLimits(this.cam, this.vp);
    this.target = clampView(this.cam, this.vp, { ...this.target, scale: min });
  }

  /** Double-click: centre the point and zoom in, or back out when already close. */
  focusAt(sx: number, sy: number): void {
    if (!this.cam) return;
    const { min, max } = scaleLimits(this.cam, this.vp);
    const near = this.target.scale > max * 0.8;
    const scale = near ? Math.sqrt(min * max) : Math.min(max, this.target.scale * 2);
    const anchor = screenToPlate(this.target, this.vp, sx, sy);
    this.target = clampView(this.cam, this.vp, { cu: anchor.u, cv: anchor.v, scale });
  }

  setKey(key: PanKey, down: boolean, fast = false): void {
    if (down) this.keys.add(key);
    else this.keys.delete(key);
    this.fast = fast;
  }

  clearKeys(): void {
    this.keys.clear();
  }

  /** Advance one frame. Returns true while the view is still moving. */
  step(dtS: number): boolean {
    if (!this.cam) return false;
    if (this.keys.size > 0) {
      const d = KEY_PAN_PX_S * (this.fast ? 2 : 1) * dtS;
      const dx = (this.keys.has("left") ? d : 0) - (this.keys.has("right") ? d : 0);
      const dy = (this.keys.has("up") ? d : 0) - (this.keys.has("down") ? d : 0);
      this.target = clampView(this.cam, this.vp, panBy(this.target, dx, dy));
    }
    if (settled(this.current, this.target)) {
      if (this.current !== this.target) {
        this.current = this.target;
        this.revision++;
      }
      return false;
    }
    this.current = damp(this.current, this.target, dtS, this.reduced ? 0 : HALF_LIFE_S);
    this.revision++;
    return true;
  }
}
