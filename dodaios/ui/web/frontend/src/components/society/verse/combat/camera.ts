/**
 * Camera and aim hooks for the integrator: over-the-shoulder rig presets for
 * hip fire, sights, sprint and shield, the camera pose that follows from
 * them, and crosshair convergence (the blaster sits right of and below the
 * camera, so aim is solved from the muzzle to whatever is under the
 * crosshair; bolts then land where the crosshair is).
 */
import { raycastWorld } from "./arena";
import { DEG, dirFromAngles, forwardX, forwardZ, lerp, rightX, rightZ, type Vec3 } from "./math";
import { sweepCapsule, sweepOut } from "./raycast";
import { muzzleOf, type SimContext } from "./sim";
import type { PlayerView, ViewState } from "./view";

export interface CameraRig {
  /** Offset of the camera pivot from the feet: to the right, up; and its distance back along the view. */
  right: number;
  up: number;
  back: number;
  /**
   * Vertical field of view, degrees, at the default third-person setting (the
   * duel camera widens or narrows it with the person's field of view). Hip
   * 50 deg shows about 80 deg across a 16:9 frame, a usual shoulder shooter.
   */
  fovDeg: number;
}

export const CAMERA_RIGS: Readonly<Record<"hip" | "ads" | "sprint" | "shield", CameraRig>> = {
  hip: { right: 0.55, up: 1.68, back: 2.5, fovDeg: 50 },
  ads: { right: 0.42, up: 1.62, back: 1.3, fovDeg: 34 },
  sprint: { right: 0.5, up: 1.6, back: 2.9, fovDeg: 55 },
  shield: { right: 0.62, up: 1.72, back: 2.75, fovDeg: 48 },
};

function mix(a: CameraRig, b: CameraRig, t: number): CameraRig {
  return { right: lerp(a.right, b.right, t), up: lerp(a.up, b.up, t), back: lerp(a.back, b.back, t), fovDeg: lerp(a.fovDeg, b.fovDeg, t) };
}

/** The rig for a player's state (sights blend in with `ads`). Ease the result over ~0.15 s in the view. */
export function cameraRigFor(p: PlayerView): CameraRig {
  if (p.sprinting) return CAMERA_RIGS.sprint;
  if (p.shieldUp) return CAMERA_RIGS.shield;
  return mix(CAMERA_RIGS.hip, CAMERA_RIGS.ads, p.ads);
}

/** Camera position and view direction for a rig: behind the right shoulder, orbiting the pivot with the pitch. */
export function cameraPose(p: Pick<PlayerView, "x" | "z" | "yaw" | "pitch">, rig: CameraRig): { position: Vec3; dir: Vec3 } {
  const dir = dirFromAngles(p.yaw, p.pitch);
  const pivot = { x: p.x + rightX(p.yaw) * rig.right, y: rig.up, z: p.z + rightZ(p.yaw) * rig.right };
  return { position: { x: pivot.x - dir.x * rig.back, y: pivot.y - dir.y * rig.back, z: pivot.z - dir.z * rig.back }, dir };
}

export interface AimSolution {
  yaw: number;
  pitch: number;
  /** The world point under the crosshair. */
  point: Vec3;
  target: "player" | "world" | "none";
}

const sw = sweepOut();

/**
 * Aim for the local player so the bolt from its muzzle meets what the camera
 * ray (crosshair) hits. Feed `yaw` and `pitch` into the ControlState.
 */
export function resolveAim(ctx: SimContext, view: ViewState, camPos: Vec3, camDir: Vec3, maxDist = 90): AimSolution {
  const me = view.players[view.slot];
  const l = Math.hypot(camDir.x, camDir.y, camDir.z) || 1;
  const d = { x: camDir.x / l, y: camDir.y / l, z: camDir.z / l };
  // Start the ray level with the player, so nothing between camera and shoulder counts.
  const t0 = me ? Math.max(0, (me.x - camPos.x) * d.x + (1.4 - camPos.y) * d.y + (me.z - camPos.z) * d.z) : 0;
  const a = { x: camPos.x + d.x * t0, y: camPos.y + d.y * t0, z: camPos.z + d.z * t0 };
  const span = maxDist;
  let best = 1;
  let target: AimSolution["target"] = "none";
  const hit = raycastWorld(ctx.arena, a.x, a.y, a.z, a.x + d.x * span, a.y + d.y * span, a.z + d.z * span);
  if (hit && hit.surface !== "exit") { best = hit.t; target = "world"; }
  const b = ctx.tuning.body;
  for (const p of view.players) {
    if (p.local || !p.alive) continue;
    const t = sweepCapsule(a.x, a.y, a.z, d.x * span, d.y * span, d.z * span, p.x, p.z, b.hitBottom, b.hitTop, b.hitRadius, sw);
    if (t >= 0 && t < best) { best = t; target = "player"; }
  }
  const point = { x: a.x + d.x * span * best, y: a.y + d.y * span * best, z: a.z + d.z * span * best };
  if (!me) return { yaw: Math.atan2(d.x, d.z), pitch: Math.asin(d.y), point, target };
  const m = muzzleOf(ctx.tuning, { x: me.x, z: me.z, yaw: Math.atan2(d.x, d.z) });
  const dx = point.x - m.x;
  const dy = point.y - m.y;
  const dz = point.z - m.z;
  // Too close to converge sensibly (a wall in the face): keep the camera's direction.
  if (Math.hypot(dx, dz) < 1.5) return { yaw: Math.atan2(d.x, d.z), pitch: Math.asin(d.y), point, target };
  return { yaw: Math.atan2(dx, dz), pitch: Math.atan2(dy, Math.hypot(dx, dz)), point, target };
}

/** Crosshair radius in pixels for a cone half-angle (HUD spread circle). */
export function crosshairRadiusPx(spreadDeg: number, fovDeg: number, viewportHeightPx: number): number {
  return (Math.tan(spreadDeg * DEG) / Math.tan((fovDeg * DEG) / 2)) * (viewportHeightPx / 2);
}

/** Forward on the floor for a yaw (for WASD in the camera frame). */
export function floorForward(yaw: number): { x: number; z: number } {
  return { x: forwardX(yaw), z: forwardZ(yaw) };
}
