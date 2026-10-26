/**
 * The eye-level camera: over the commander's shoulder (third person) or
 * through their eyes (first person), turned by shooter mouse look.
 *
 * Third-person framing (docs/verse/realtime.md, "Camera"): the camera looks
 * past the commander's head from behind, offset sideways so they stand in
 * the lower right third of the frame; a little above their head, looking
 * slightly down. The wheel moves it between 1.2 and 5 m (eased); pushing in
 * past the closest distance hands over to first person (`viewMode.zoomStep`)
 * and scrolling out of first person comes back.
 *
 * First person: the camera sits at eye height (1.65 m) just in front of the
 * face, with no follow lag sideways (it is the head) and the vertical lag of
 * the third-person pivot (stairs stay smooth); a segment test keeps it out
 * of walls. The two cameras blend over about a fifth of a second when the
 * person changes, field of view included.
 *
 * The mouse turns the view (yaw, clamped pitch); the commander walks
 * relative to it (W away from the camera) and faces it while walking, so
 * the camera never turns on its own. The third-person camera never clips
 * through walls: a segment test pulls it in at once and it eases back out.
 *
 * Pure state and maths: the renderer calls `update` once per frame with the
 * commander's pose and a collision test; the input calls `look` and `zoom`.
 */
import { LOOK_SENSITIVITY, MOUSE_LOOK_RATE, lookDelta } from "./mouseLook";
import { zoomStep, type Person } from "./viewMode";

export { LOOK_SENSITIVITY };

export interface Vec3 { x: number; y: number; z: number }

/** First hit along the segment from → to as a fraction of its length (0..1), or null when it is clear. */
export type SegmentTest = (from: Vec3, to: Vec3) => number | null;

const DEG = Math.PI / 180;

export const SHOULDER = {
  /** Horizontal field of view in third person, degrees (the person's setting overrides it). */
  hfovDeg: 70,
  /** ... and in first person. */
  firstHfovDeg: 85,
  /** The range the person may set either field of view in, degrees. */
  minHfovDeg: 55,
  maxHfovDeg: 110,
  /** Narrow (portrait) frames keep at least this vertical field of view, degrees. */
  minVfovDeg: 40,
  /** Camera distance behind the pivot, metres, and the wheel's range. */
  distance: 2.4,
  minDistance: 1.2,
  maxDistance: 5,
  /** Time constant of the eased zoom, seconds. */
  zoomS: 0.09,
  /** Log zoom pushed past the closest distance (or out of first person) that changes the person: about one wheel notch. */
  handover: 0.1,
  /** Pivot height above the commander's feet, metres (about the top of the head). */
  pivotHeight: 1.74,
  /** First person: eye height above the feet and how far in front of the body's axis the eyes are, metres. */
  eyeHeight: 1.65,
  eyeForward: 0.1,
  /**
   * Sideways offset of the pivot, metres, along the camera's right: negative
   * puts the camera to the commander's left, so they stand right of centre.
   */
  side: -0.47,
  /** Default pitch, radians (positive looks down). */
  pitch: 7 * DEG,
  /** Pitch limits in third person and in first person, radians. */
  minPitch: -35 * DEG,
  maxPitch: 60 * DEG,
  firstMinPitch: -80 * DEG,
  firstMaxPitch: 80 * DEG,
  /** Radians per CSS pixel of drag (touch, or a mouse without pointer lock), and per pixel of pointer-lock movement. */
  dragRate: 0.0042,
  lockRate: MOUSE_LOOK_RATE,
  /** Lag of the pivot behind the commander, seconds (horizontal, vertical). */
  followS: 0.07,
  followYS: 0.16,
  /** Time constant of the third ↔ first person blend, seconds. */
  personS: 0.07,
  /** Gap kept between the camera and geometry, metres. */
  clearance: 0.24,
  /** First person: gap kept between the eyes and a wall in front, metres. */
  eyeClearance: 0.12,
  /** Distance regained per second after a pull-in, metres. */
  regainMps: 3.2,
} as const;

function wrap(a: number): number {
  return Math.atan2(Math.sin(a), Math.cos(a));
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v));
}

/** Vertical field of view (degrees) for a frame of `aspect` (width / height) at a horizontal one. Pure. */
export function verticalFov(aspect: number, hfovDeg: number = SHOULDER.hfovDeg, minVfovDeg: number = SHOULDER.minVfovDeg): number {
  const h = (hfovDeg * Math.PI) / 180;
  const v = 2 * Math.atan(Math.tan(h / 2) / Math.max(1e-3, aspect));
  return Math.max(minVfovDeg, (v * 180) / Math.PI);
}

/** A horizontal field of view as the person may set it, degrees. Pure. */
export function clampHfov(deg: number, fallback: number): number {
  return Number.isFinite(deg) ? clamp(deg, SHOULDER.minHfovDeg, SHOULDER.maxHfovDeg) : fallback;
}

export class ShoulderRig {
  /** View heading: the floor direction the camera looks along is (sin yaw, cos yaw); π looks toward −Z. */
  yaw = Math.PI;
  pitch: number = SHOULDER.pitch;
  /** The wanted distance (the wheel sets it); collisions shorten the actual one. */
  distance: number = SHOULDER.distance;
  /** Over the shoulder or through the eyes. */
  person: Person = "third";
  /** Multiplies the turn rate of drags and mouse look (the person's setting, 0.25–3). */
  sensitivity = 1;
  /** Moving the mouse up looks down (the person's setting). */
  invertY = false;
  /** Horizontal fields of view, degrees (the person's settings). */
  fovThird: number = SHOULDER.hfovDeg;
  fovFirst: number = SHOULDER.firstHfovDeg;
  /** Camera position and the point it looks at, world metres (valid after `update`). */
  readonly position: Vec3 = { x: 0, y: 0, z: 0 };
  readonly target: Vec3 = { x: 0, y: 0, z: 0 };
  /** The third-person distance in use after easing and collisions. */
  actual: number = SHOULDER.distance;
  /** How far the camera has blended into first person (0 third .. 1 first, eased), after `update`. */
  firstShare = 0;
  private zoomed: number = SHOULDER.distance;
  private push = 0;
  private blend = 0;
  private readonly pivot: Vec3 = { x: 0, y: 0, z: 0 };
  // Scratch points reused every frame, so `update` allocates nothing.
  private readonly shoulderPoint: Vec3 = { x: 0, y: 0, z: 0 };
  private readonly farPoint: Vec3 = { x: 0, y: 0, z: 0 };
  private readonly head: Vec3 = { x: 0, y: 0, z: 0 };
  private readonly eye: Vec3 = { x: 0, y: 0, z: 0 };
  private readonly dir: Vec3 = { x: 0, y: 0, z: 0 };
  private primed = false;

  /** The pitch limits of the current person, radians. */
  pitchLimits(): { min: number; max: number } {
    return this.person === "first"
      ? { min: SHOULDER.firstMinPitch, max: SHOULDER.firstMaxPitch }
      : { min: SHOULDER.minPitch, max: SHOULDER.maxPitch };
  }

  /** Turn the view by a pointer movement (CSS px); `locked` for pointer-lock deltas (shooter look), else a drag. */
  look(dx: number, dy: number, locked = false): void {
    const d = lookDelta(dx, dy, this, locked ? SHOULDER.lockRate : SHOULDER.dragRate);
    const { min, max } = this.pitchLimits();
    this.yaw = wrap(this.yaw - d.yaw);
    this.pitch = clamp(this.pitch + d.pitch, min, max);
  }

  /**
   * Zoom by `factor` (> 1 moves out): the third-person distance, and the
   * hand-over to and from first person. Returns the new person when it
   * changed, else null.
   */
  zoom(factor: number): Person | null {
    const next = zoomStep({ person: this.person, distance: this.distance, push: this.push }, factor, {
      min: SHOULDER.minDistance, max: SHOULDER.maxDistance, handover: SHOULDER.handover,
    });
    const changed = next.person !== this.person ? next.person : null;
    this.person = next.person;
    this.distance = next.distance;
    this.push = next.push;
    return changed;
  }

  /** Switch the person (the view switch); the camera blends over. */
  setPerson(person: Person): void {
    if (person === this.person) return;
    this.person = person;
    this.push = 0;
  }

  /** The horizontal field of view to render now (blended between the persons), degrees. */
  hfov(): number {
    const third = clampHfov(this.fovThird, SHOULDER.hfovDeg);
    const first = clampHfov(this.fovFirst, SHOULDER.firstHfovDeg);
    return third + (first - third) * this.firstShare;
  }

  /** Put the camera straight behind a body facing `heading` (radians, the actor's yaw), at the default pitch. */
  snapBehind(heading: number): void {
    this.yaw = wrap(heading);
    this.pitch = this.person === "first" ? 0 : SHOULDER.pitch;
    this.primed = false;
  }

  /** Turn the view toward a floor point seen from (fromX, fromZ), keeping the pitch (the crew card's "show"). */
  faceToward(fromX: number, fromZ: number, x: number, z: number): void {
    if (Math.hypot(x - fromX, z - fromZ) < 1e-6) return;
    this.yaw = Math.atan2(x - fromX, z - fromZ);
  }

  /** The floor direction the camera looks along (unit). */
  forward(): { x: number; z: number } {
    return { x: Math.sin(this.yaw), z: Math.cos(this.yaw) };
  }

  /** The floor direction of the screen's right (unit). */
  right(): { x: number; z: number } {
    return { x: -Math.cos(this.yaw), z: Math.sin(this.yaw) };
  }

  /**
   * World walking direction for held screen keys: `ix` right (+1) / left
   * (−1), `iz` toward the camera (+1, S) / away (−1, W). Unit length or null;
   * written into `out` when given (the frame loop allocates nothing).
   */
  walkDirection(ix: number, iz: number, out?: { x: number; z: number }): { x: number; z: number } | null {
    if (ix === 0 && iz === 0) return null;
    const fx = Math.sin(this.yaw);
    const fz = Math.cos(this.yaw);
    // The screen's right on the floor is (−cos yaw, sin yaw) = (−fz, fx).
    const x = -fz * ix - fx * iz;
    const z = fx * ix - fz * iz;
    const n = Math.hypot(x, z);
    if (n <= 1e-9) return null;
    const o = out ?? { x: 0, z: 0 };
    o.x = x / n;
    o.z = z / n;
    return o;
  }

  /**
   * Follow the body at (x, y, z) facing `heading`; `moving` while it walks.
   * `test` checks segments against the deck's geometry (the points it gets
   * are only valid during the call).
   */
  update(dtS: number, body: Readonly<Vec3> & { readonly heading: number; readonly moving: boolean }, test?: SegmentTest | null): void {
    const dt = clamp(dtS, 0, 0.1);
    const pivot = this.pivot;
    const gx = body.x;
    const gy = body.y + SHOULDER.pivotHeight;
    const gz = body.z;
    const wantFirst = this.person === "first" ? 1 : 0;
    /** How far the eased zoom moved out this frame: the camera follows it on top of the wall regain. */
    let zoomOut = 0;
    if (!this.primed) {
      pivot.x = gx;
      pivot.y = gy;
      pivot.z = gz;
      this.zoomed = this.distance;
      this.actual = this.distance;
      this.blend = wantFirst;
      this.primed = true;
    } else {
      const kx = 1 - Math.exp(-dt / SHOULDER.followS);
      const ky = 1 - Math.exp(-dt / SHOULDER.followYS);
      pivot.x += (gx - pivot.x) * kx;
      pivot.y += (gy - pivot.y) * ky;
      pivot.z += (gz - pivot.z) * kx;
      const before = this.zoomed;
      this.zoomed += (this.distance - this.zoomed) * (1 - Math.exp(-dt / SHOULDER.zoomS));
      zoomOut = Math.max(0, this.zoomed - before);
      this.blend += (wantFirst - this.blend) * (1 - Math.exp(-dt / SHOULDER.personS));
      if (Math.abs(wantFirst - this.blend) < 1e-3) this.blend = wantFirst;
    }
    // Back in third person a pitch beyond its limits comes inside them.
    const { min, max } = this.pitchLimits();
    this.pitch = clamp(this.pitch, min, max);
    const s = this.blend * this.blend * (3 - 2 * this.blend);
    this.firstShare = s;

    const fx = Math.sin(this.yaw);
    const fz = Math.cos(this.yaw);
    const cp = Math.cos(this.pitch);
    const dir = this.dir;
    dir.x = fx * cp;
    dir.y = -Math.sin(this.pitch);
    dir.z = fz * cp;

    // Third person. The shoulder point: sideways from the head along the screen's right (−fz, fx), pulled in when a
    // wall is that close.
    const shoulder = this.shoulderPoint;
    shoulder.x = pivot.x - fz * SHOULDER.side;
    shoulder.y = pivot.y;
    shoulder.z = pivot.z + fx * SHOULDER.side;
    if (test && s < 1) {
      const hit = test(pivot, shoulder);
      if (hit !== null) {
        const keep = Math.max(0, hit - SHOULDER.clearance / Math.abs(SHOULDER.side));
        shoulder.x = pivot.x + (shoulder.x - pivot.x) * keep;
        shoulder.z = pivot.z + (shoulder.z - pivot.z) * keep;
      }
    }
    let reach = this.zoomed;
    if (test && s < 1) {
      const far = this.farPoint;
      far.x = shoulder.x - dir.x * this.zoomed;
      far.y = shoulder.y - dir.y * this.zoomed;
      far.z = shoulder.z - dir.z * this.zoomed;
      const hit = test(shoulder, far);
      if (hit !== null) reach = Math.max(0.15, hit * this.zoomed - SHOULDER.clearance);
    }
    // In at once (never through a wall), back out smoothly; a wheel zoom out is followed as fast as it eases.
    this.actual = reach < this.actual ? reach : Math.min(reach, this.actual + SHOULDER.regainMps * dt + zoomOut);
    const tx = shoulder.x - dir.x * this.actual;
    const ty = shoulder.y - dir.y * this.actual;
    const tz = shoulder.z - dir.z * this.actual;

    // First person: the eyes, on the body's axis horizontally (no lag: it is the head), the pivot's eased height.
    const head = this.head;
    head.x = gx;
    head.y = pivot.y - (SHOULDER.pivotHeight - SHOULDER.eyeHeight);
    head.z = gz;
    const eye = this.eye;
    eye.x = gx + fx * SHOULDER.eyeForward;
    eye.y = head.y;
    eye.z = gz + fz * SHOULDER.eyeForward;
    if (test && s > 0) {
      // Never past a wall the face is against: the eyes stay a little short of it.
      const probeX = gx + fx * (SHOULDER.eyeForward + SHOULDER.eyeClearance);
      const probeZ = gz + fz * (SHOULDER.eyeForward + SHOULDER.eyeClearance);
      const far = this.farPoint;
      far.x = probeX;
      far.y = head.y;
      far.z = probeZ;
      const hit = test(head, far);
      if (hit !== null) {
        const reachEye = Math.max(0, hit * (SHOULDER.eyeForward + SHOULDER.eyeClearance) - SHOULDER.eyeClearance);
        eye.x = gx + fx * reachEye;
        eye.z = gz + fz * reachEye;
      }
    }

    this.position.x = tx + (eye.x - tx) * s;
    this.position.y = ty + (eye.y - ty) * s;
    this.position.z = tz + (eye.z - tz) * s;
    // Both cameras look along the same direction; the point ahead follows the blended position.
    this.target.x = this.position.x + dir.x * 10;
    this.target.y = this.position.y + dir.y * 10;
    this.target.z = this.position.z + dir.z * 10;
  }
}
