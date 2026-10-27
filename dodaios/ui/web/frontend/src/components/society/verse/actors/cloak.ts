/**
 * A cloak that trails: secondary motion for a body whose skeleton carries the
 * cloak bones (the Sovereign skin: `Cloak_{R,C,L}{1,2}`, children of Chest,
 * never animated by the shared clips).
 *
 * Each of the three columns (right, centre, left) is a damped spring on two
 * angles in the character's own frame: pitch (the hem lifts backwards as the
 * body walks forward) and roll (it swings sideways against a strafe or a
 * turn). The lower segment follows the upper one with more lag, so the hem
 * whips a little after a stop. A light flutter rides on top while moving.
 */
import { Quaternion, Vector3, type Bone, type Object3D } from "three";

export const CLOAK_COLUMNS = ["R", "C", "L"] as const;

/** Spring stiffness (1/s²) and damping (1/s) of the upper and the lower segment. */
export const CLOAK_SPRING = { k1: 55, c1: 10, k2: 30, c2: 6.5 };

interface Column {
  side: number;
  phase: number;
  upper: Bone;
  lower: Bone;
  restUpper: Quaternion;
  restLower: Quaternion;
  // spring state: angles (rad) and rates (rad/s)
  p1: number; r1: number; vp1: number; vr1: number;
  p2: number; r2: number; vp2: number; vr2: number;
}

function wrap(a: number): number {
  return Math.atan2(Math.sin(a), Math.cos(a));
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, v));
}

/** Where the cloak wants to hang for a body moving at `forward`/`lateral` m/s, turning at `yawRate` rad/s. Pure. */
export function cloakTarget(forward: number, lateral: number, yawRate: number, side: number): { pitch: number; roll: number } {
  const speed = Math.hypot(forward, lateral);
  const pitch = clamp(0.3 * forward, -0.08, 0.62) * (side === 0 ? 1 : 0.88) + 0.04 * Math.abs(lateral);
  const roll = clamp(-0.09 * lateral - 0.05 * yawRate, -0.3, 0.3) + side * 0.05 * Math.min(speed, 2.5);
  return { pitch, roll };
}

const qa = new Quaternion();
const qb = new Quaternion();
const qParent = new Quaternion();
const qRoot = new Quaternion();
const qInv = new Quaternion();
const qc = new Quaternion();
const axisX = new Vector3();
const axisZ = new Vector3();

export class CloakRig {
  private readonly columns: Column[];
  private readonly chest: Object3D;
  private px = 0;
  private pz = 0;
  private pyaw = 0;
  private primed = false;
  private vf = 0;
  private vl = 0;
  private turn = 0;
  private t = 0;

  private constructor(private readonly root: Object3D, chest: Object3D, columns: Column[]) {
    this.chest = chest;
    this.columns = columns;
  }

  /** The cloak of a body, or null when its skeleton has no cloak bones. */
  static find(root: Object3D): CloakRig | null {
    const chest = root.getObjectByName("Chest");
    if (!chest) return null;
    const columns: Column[] = [];
    CLOAK_COLUMNS.forEach((name, i) => {
      const upper = root.getObjectByName(`Cloak_${name}1`) as Bone | undefined;
      const lower = root.getObjectByName(`Cloak_${name}2`) as Bone | undefined;
      if (!upper || !lower || lower.parent !== upper) return;
      columns.push({
        side: i - 1, phase: i * 2.1, upper, lower,
        restUpper: upper.quaternion.clone(), restLower: lower.quaternion.clone(),
        p1: 0, r1: 0, vp1: 0, vr1: 0, p2: 0, r2: 0, vp2: 0, vr2: 0,
      });
    });
    return columns.length ? new CloakRig(root, chest, columns) : null;
  }

  /** Forget the motion (the body was placed somewhere new). */
  reset(): void {
    this.primed = false;
    for (const c of this.columns) {
      c.p1 = c.r1 = c.vp1 = c.vr1 = c.p2 = c.r2 = c.vp2 = c.vr2 = 0;
      c.upper.quaternion.copy(c.restUpper);
      c.lower.quaternion.copy(c.restLower);
    }
  }

  /**
   * Step the springs for a body standing at (x, z) facing `yaw` and pose the cloak bones. Call after the
   * animation mixer and after the root has been placed for this frame.
   */
  update(dtS: number, x: number, z: number, yaw: number, still = false): void {
    const dt = Math.min(0.1, Math.max(1e-4, dtS));
    if (!this.primed) {
      this.px = x; this.pz = z; this.pyaw = yaw; this.primed = true;
    }
    const vx = (x - this.px) / dt;
    const vz = (z - this.pz) / dt;
    const s = Math.sin(yaw);
    const c = Math.cos(yaw);
    // A teleport (a lift ride, a respawn) is not a sprint.
    const jump = Math.hypot(vx, vz) > 12;
    const k = Math.min(1, dt * 10);
    this.vf += ((jump ? 0 : vx * s + vz * c) - this.vf) * k;
    this.vl += ((jump ? 0 : vx * c - vz * s) - this.vl) * k;
    this.turn += ((jump ? 0 : wrap(yaw - this.pyaw) / dt) - this.turn) * k;
    this.px = x; this.pz = z; this.pyaw = yaw;
    this.t += dt;
    const speed = Math.hypot(this.vf, this.vl);
    const flutter = still ? 0 : 0.035 * Math.min(speed, 2);

    // Integrate in small steps: a long frame must not blow the springs up.
    const steps = Math.max(1, Math.ceil(dt / (1 / 120)));
    const h = dt / steps;
    const { k1, c1, k2, c2 } = CLOAK_SPRING;
    for (const col of this.columns) {
      const want = cloakTarget(this.vf, this.vl, this.turn, col.side);
      const tp = want.pitch + flutter * Math.sin(this.t * 6.3 + col.phase);
      const tr = want.roll + flutter * 0.6 * Math.sin(this.t * 4.7 + col.phase * 1.7);
      for (let i = 0; i < steps; i++) {
        col.vp1 += (k1 * (tp - col.p1) - c1 * col.vp1) * h;
        col.vr1 += (k1 * (tr - col.r1) - c1 * col.vr1) * h;
        col.p1 += col.vp1 * h;
        col.r1 += col.vr1 * h;
        // The lower half bends a little further the same way, later.
        col.vp2 += (k2 * (0.45 * col.p1 - col.p2) - c2 * col.vp2) * h;
        col.vr2 += (k2 * (0.45 * col.r1 - col.r2) - c2 * col.vr2) * h;
        col.p2 += col.vp2 * h;
        col.r2 += col.vr2 * h;
      }
      col.p1 = clamp(col.p1, -0.2, 0.9);
      col.p2 = clamp(col.p2, -0.3, 0.6);
    }
    this.pose();
  }

  private pose(): void {
    // The character's own axes in the world: +X its left, +Z its front.
    this.root.updateMatrixWorld(true);
    this.root.getWorldQuaternion(qRoot);
    axisX.set(1, 0, 0).applyQuaternion(qRoot);
    axisZ.set(0, 0, 1).applyQuaternion(qRoot);
    this.chest.getWorldQuaternion(qParent);
    for (const col of this.columns) {
      // upper: local = parent⁻¹ · R(world) · parent · rest
      const p = qb.copy(qParent);
      setLocal(col.upper, p, col.restUpper, col.p1, col.r1);
      // lower: its parent is the upper bone as just posed
      p.multiply(col.upper.quaternion);
      setLocal(col.lower, p, col.restLower, col.p2, col.r2);
    }
  }
}

function setLocal(bone: Bone, parentWorld: Quaternion, rest: Quaternion, pitch: number, roll: number): void {
  qa.setFromAxisAngle(axisX, pitch);
  qa.multiply(qc.setFromAxisAngle(axisZ, roll));
  qInv.copy(parentWorld).invert();
  bone.quaternion.copy(qInv).multiply(qa).multiply(parentWorld).multiply(rest);
}
