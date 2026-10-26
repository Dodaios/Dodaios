/**
 * The duel's over-the-shoulder camera: the combat core's rigs (hip, sights,
 * sprint, shield; `combat/camera.ts`) eased into each other, turned by the
 * mouse, kept out of the deck's walls, with the blaster's recoil and a short
 * shake on top.
 *
 * Two directions matter. The *aim* (`yaw`, `pitch`) is what the person
 * points at with the mouse; the crosshair is solved from it (resolveAim) and
 * it goes to the simulation. The *view* adds the recoil the simulation put
 * on the blaster, so the screen kicks with every shot and the crosshair in
 * the middle stays where the bolts go, as in big shooters.
 *
 * Coordinates: the arena's (deck metres, floor at y 0); `floorY` lifts the
 * camera onto the deck's floor. Pitch is positive up (the combat core's
 * convention). Pure state and maths.
 */
import { cameraRigFor, type CameraRig } from "../combat/camera";
import { DEG } from "../combat/math";
import type { PlayerView } from "../combat/view";
import { MOUSE_LOOK_RATE, lookDelta } from "../engine/realtime/mouseLook";
import { SHOULDER, clampHfov, type SegmentTest, type Vec3 } from "../engine/realtime/shoulderRig";

export const DUEL_CAMERA = {
  /** Radians per pointer-lock pixel at sensitivity 1 (the eye-level views' mouse look); sights turn slower. */
  lookRate: MOUSE_LOOK_RATE,
  adsLookFactor: 0.62,
  /** Pitch limits, radians (positive up). */
  minPitch: -1.05,
  maxPitch: 1.05,
  /** Rig easing time constant, seconds (about 0.15 s to settle). */
  easeS: 0.05,
  /** Share of the blaster's recoil the view follows. */
  recoilView: 1,
  /** Gap kept between the camera and geometry, metres. */
  clearance: 0.2,
  /** Distance regained per second after a wall pulled the camera in, metres. */
  regainMps: 4,
  /** Head height the collision tests start from, metres. */
  headHeight: 1.6,
  /** Extra sideways offset of the view (metres, to the right) on top of the core's rig, so the body clears the crosshair. */
  extraRight: 0.2,
} as const;

export interface DuelCameraPose {
  position: Vec3;
  /** A point straight ahead (for lookAt). */
  target: Vec3;
  /** The view direction (unit), including recoil and shake. */
  dir: Vec3;
  /** The aim ray without recoil: what resolveAim gets. */
  aimDir: Vec3;
  /** Vertical field of view, degrees. */
  fovDeg: number;
}

/**
 * A rig's vertical field of view (set for the default third-person field of
 * view) at the person's own third-person setting: the same zoom ratio, so a
 * wider setting widens the duel just as much. Pure.
 */
export function duelFov(rigFovDeg: number, hfovSettingDeg: number = SHOULDER.hfovDeg): number {
  const ratio = Math.tan((clampHfov(hfovSettingDeg, SHOULDER.hfovDeg) * DEG) / 2) / Math.tan((SHOULDER.hfovDeg * DEG) / 2);
  return (2 * Math.atan(Math.tan((rigFovDeg * DEG) / 2) * ratio)) / DEG;
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v));
}

function wrap(a: number): number {
  return Math.atan2(Math.sin(a), Math.cos(a));
}

function dirOf(yaw: number, pitch: number, out: Vec3): Vec3 {
  const c = Math.cos(pitch);
  out.x = Math.sin(yaw) * c;
  out.y = Math.sin(pitch);
  out.z = Math.cos(yaw) * c;
  return out;
}

export class DuelCamera {
  /** The aim, radians (yaw 0 faces +Z, pitch positive up). */
  yaw = 0;
  pitch = 0;
  sensitivity = 1;
  invertY = false;
  /** The person's third-person horizontal field of view (view settings), degrees. */
  hfovSetting: number = SHOULDER.hfovDeg;
  readonly pose: DuelCameraPose = {
    position: { x: 0, y: 0, z: 0 }, target: { x: 0, y: 0, z: 0 }, dir: { x: 0, y: 0, z: 1 }, aimDir: { x: 0, y: 0, z: 1 }, fovDeg: duelFov(cameraRigFor({ sprinting: false, shieldUp: false, ads: 0 } as PlayerView).fovDeg),
  };
  private rig: CameraRig = { ...cameraRigFor({ sprinting: false, shieldUp: false, ads: 0 } as PlayerView) };
  private primed = false;
  private back = 2.5;
  private shake = 0;
  private shakeT = 0;
  private ads = 0;
  private readonly pivot: Vec3 = { x: 0, y: 0, z: 0 };
  private readonly head: Vec3 = { x: 0, y: 0, z: 0 };
  private readonly far: Vec3 = { x: 0, y: 0, z: 0 };

  /** Turn the aim by a mouse movement (CSS px): the same mouse look as the eye-level views (`mouseLook`). */
  look(dx: number, dy: number): void {
    const d = lookDelta(dx, dy, this, DUEL_CAMERA.lookRate * (1 - (1 - DUEL_CAMERA.adsLookFactor) * this.ads));
    this.yaw = wrap(this.yaw - d.yaw);
    // Pitch here is positive up; the look's is positive down.
    this.pitch = clamp(this.pitch - d.pitch, DUEL_CAMERA.minPitch, DUEL_CAMERA.maxPitch);
  }

  /** Face a direction at once (a round's spawn), level. */
  face(yaw: number, pitch = 0): void {
    this.yaw = wrap(yaw);
    this.pitch = clamp(pitch, DUEL_CAMERA.minPitch, DUEL_CAMERA.maxPitch);
    this.primed = false;
  }

  /** A short shake (a shot, a hit taken); strength in degrees. */
  kick(strengthDeg: number): void {
    this.shake = Math.min(3, this.shake + strengthDeg);
  }

  /**
   * Follow the local player: ease the rig for their state, place the camera
   * behind the right shoulder (pulled in front of walls), add recoil and
   * shake. `test` is the deck's collision in world coordinates.
   */
  update(dtS: number, me: PlayerView, floorY = 0, test?: SegmentTest | null): DuelCameraPose {
    const dt = clamp(dtS, 0, 0.1);
    const want = cameraRigFor(me);
    const k = this.primed ? 1 - Math.exp(-dt / DUEL_CAMERA.easeS) : 1;
    const r = this.rig;
    r.right += (want.right - r.right) * k;
    r.up += (want.up - r.up) * k;
    r.back += (want.back - r.back) * k;
    r.fovDeg += (want.fovDeg - r.fovDeg) * k;
    this.ads = me.ads;

    this.shakeT += dt;
    this.shake *= Math.exp(-dt / 0.09);
    const sy = this.shake * DEG * Math.sin(this.shakeT * 71.3) * 0.6;
    const sp = this.shake * DEG * Math.sin(this.shakeT * 53.9 + 1.3);
    const recoilYaw = me.aimYaw - me.yaw;
    const recoilPitch = me.aimPitch - me.pitch;
    const viewYaw = this.yaw + recoilYaw * DUEL_CAMERA.recoilView + sy;
    const viewPitch = clamp(this.pitch + recoilPitch * DUEL_CAMERA.recoilView + sp, -1.4, 1.4);

    const pose = this.pose;
    dirOf(this.yaw, this.pitch, pose.aimDir);
    const dir = dirOf(viewYaw, viewPitch, pose.dir);
    // Pivot: beside the head along the view's right; the camera orbits it with the pitch.
    const rx = -Math.cos(viewYaw);
    const rz = Math.sin(viewYaw);
    const head = this.head;
    head.x = me.x;
    head.y = floorY + DUEL_CAMERA.headHeight;
    head.z = me.z;
    const pivot = this.pivot;
    const side = r.right + DUEL_CAMERA.extraRight * (1 - 0.4 * this.ads);
    pivot.x = me.x + rx * side;
    pivot.y = floorY + r.up;
    pivot.z = me.z + rz * side;
    if (test) {
      const hit = test(head, pivot);
      if (hit !== null) {
        const keep = Math.max(0, hit - DUEL_CAMERA.clearance / Math.max(0.05, side));
        pivot.x = head.x + (pivot.x - head.x) * keep;
        pivot.z = head.z + (pivot.z - head.z) * keep;
      }
    }
    let reach = r.back;
    if (test) {
      const far = this.far;
      far.x = pivot.x - dir.x * r.back;
      far.y = pivot.y - dir.y * r.back;
      far.z = pivot.z - dir.z * r.back;
      const hit = test(pivot, far);
      if (hit !== null) reach = Math.max(0.2, hit * r.back - DUEL_CAMERA.clearance);
    }
    if (!this.primed) this.back = reach;
    // In at once (never through a wall), back out smoothly.
    this.back = reach < this.back ? reach : Math.min(reach, this.back + DUEL_CAMERA.regainMps * dt);
    this.primed = true;
    pose.position.x = pivot.x - dir.x * this.back;
    pose.position.y = pivot.y - dir.y * this.back;
    pose.position.z = pivot.z - dir.z * this.back;
    pose.target.x = pivot.x + dir.x * 20;
    pose.target.y = pivot.y + dir.y * 20;
    pose.target.z = pivot.z + dir.z * 20;
    pose.fovDeg = duelFov(r.fovDeg, this.hfovSetting);
    return pose;
  }
}
