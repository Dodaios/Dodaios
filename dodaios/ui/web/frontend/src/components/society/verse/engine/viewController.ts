/**
 * The camera's pan and zoom state over one plate: a target view the input
 * moves, and a current view that follows it with damping each frame. Drags
 * move both (the plate stays under the pointer); wheel, keys, focus, fling
 * and the third-person follow move the target only. Every view is clamped
 * (view.ts), so the plate always covers the viewport. With reduced motion
 * the current view jumps.
 */
import type { PlateCamera } from "./plateMath";
import { clampView, damp, panBy, scaleLimits, screenToPlate, settled, zoomAt, type View, type Viewport } from "./view";

const HALF_LIFE_S = 0.09;
/** Keyboard pan speed, CSS pixels per second (Shift doubles it). */
const KEY_PAN_PX_S = 720;
/** A released drag keeps going for about this long. */
const FLING_S = 0.22;
/** The third-person camera shows about this many metres across the longer side of the viewport. */
const FOLLOW_SPAN_M = 24;

export type PanKey = "left" | "right" | "up" | "down";

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

  /**
   * A new plate: frame it on `focus` (plate metres) at a comfortable zoom.
   * Before the viewport has been measured the framing waits for the first
   * real size, so a first open does not start fully zoomed out.
   */
  setPlate(cam: PlateCamera, focus: { u: number; v: number } | null): void {
    this.cam = cam;
    this.focusPoint = focus;
    this.framed = this.measured;
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
   * The third-person zoom: close enough that a person on the deck reads as a
   * figure (about 24 m across the longer side of the viewport), never below
   * 40 px per metre in a small panel; clamped to the plate's limits.
   */
  followScale(): number {
    if (!this.cam) return this.target.scale;
    const { min, max } = scaleLimits(this.cam, this.vp);
    const wanted = Math.max(40, Math.max(this.vp.width, this.vp.height) / FOLLOW_SPAN_M);
    return Math.min(max, Math.max(min, wanted));
  }

  /** Keep a moving plate point (the commander) in the middle of the screen, at the current zoom. */
  follow(u: number, v: number): void {
    if (!this.cam) return;
    this.target = clampView(this.cam, this.vp, { cu: u, cv: v, scale: this.target.scale });
  }

  /** Bird's-eye: pull back as far as the plate allows, around what is in the middle now. */
  overview(): void {
    if (!this.cam) return;
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
