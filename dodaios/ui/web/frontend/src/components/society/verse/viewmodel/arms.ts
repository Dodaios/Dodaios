/**
 * The commander's own arms for the first-person viewmodel, built
 * procedurally: an upper arm and a tapered forearm in the uniform's cloth, a
 * gauntlet with a strap in the uniform's trim, and a gloved hand (palm,
 * knuckle plate, four two-segment fingers and a two-segment thumb). The
 * index finger and the thumb pose apart from the other three fingers, so a
 * hand can hold a grip with the index on the trigger. The left forearm
 * carries the shield emitter.
 *
 * The arm is a chain of bones (Object3Ds); its parts are not meshes of their
 * own but go into the viewmodel's one skinned mesh (`RigBuilder`), each bound
 * to the bone it moves with, so the whole rig is one draw call.
 *
 * Hand frame (the `hand` bone, origin at the wrist): +Z runs to the
 * knuckles, +Y is the back of the hand, +X the thumb's side for the right
 * hand; the left hand is the same hand mirrored (thumb on −X: its parts are
 * baked mirrored and its finger bones placed mirrored). Fingers curl toward
 * −Y (the palm).
 *
 * `pose` places the arm for a frame: shoulder, wrist and the hand's frame
 * given, the elbow is solved by two-bone IK toward a pole (it hangs down and
 * out, as an arm does), and the forearm turns about its axis so its back (and
 * the emitter) faces the way the back of the hand does.
 */
import {
  Bone, CylinderGeometry, Euler, Group, LatheGeometry, Matrix4, Object3D, Quaternion, SphereGeometry, TorusGeometry, Vector2, Vector3,
  type BufferGeometry,
} from "three";
import { solveElbow } from "../duel/figure";
import { chamferBox, type RigBuilder, type Slot } from "./rigMesh";

/** The arm's surfaces in the rig's palette. */
export interface ArmSlots {
  /** The uniform's cloth (sleeves). */
  sleeve: Slot;
  /** The uniform's trim (the gauntlet's strap, the panel on the back of the hand). */
  trim: Slot;
  /** Glove leather. */
  glove: Slot;
  /** Armour and the shield emitter's housing. */
  housing: Slot;
  /** The shield emitter's glowing strip and lens (left forearm only). */
  emitter: Slot;
}

export const ARM = {
  /** Upper arm and forearm lengths, metres (the upper arm is never in view; it is long enough that the hands reach the blaster). */
  upper: 0.36,
  fore: 0.3,
  /** Sleeve radii: shoulder, elbow, wrist. */
  rShoulder: 0.05,
  rElbow: 0.043,
  rWrist: 0.035,
  /** Finger segment lengths. */
  seg1: 0.042,
  seg2: 0.036,
  /** The forearm's sleeve stops this far short of the wrist, inside the glove's gauntlet. */
  sleeveShort: 0.06,
};

/**
 * A hand's pose: the three outer fingers' two joints, the index finger's two joints (radians toward the palm), and
 * the thumb's bend (0 open .. 1 closed) and its swing across the palm (radians).
 */
export interface HandPose {
  fingers: [number, number];
  index: [number, number];
  thumb: [number, number];
}

export function handPose(c1: number, c2: number, thumb: number, index: [number, number] = [c1, c2], across = 0): HandPose {
  return { fingers: [c1, c2], index, thumb: [thumb, across] };
}

/** `out` moved toward `to` by `t` (0..1). */
export function lerpHand(out: HandPose, to: HandPose, t: number): HandPose {
  if (t <= 0) return out;
  for (let i = 0; i < 2; i++) {
    out.fingers[i] += (to.fingers[i] - out.fingers[i]) * t;
    out.index[i] += (to.index[i] - out.index[i]) * t;
    out.thumb[i] += (to.thumb[i] - out.thumb[i]) * t;
  }
  return out;
}

export function copyHand(out: HandPose, from: HandPose): HandPose {
  out.fingers[0] = from.fingers[0];
  out.fingers[1] = from.fingers[1];
  out.index[0] = from.index[0];
  out.index[1] = from.index[1];
  out.thumb[0] = from.thumb[0];
  out.thumb[1] = from.thumb[1];
  return out;
}

const SCRATCH_X = new Vector3();
const SCRATCH_Y = new Vector3();
const SCRATCH_Z = new Vector3();
const SCRATCH_M = new Matrix4();
const M_POS = new Vector3();
const M_SCALE = new Vector3();
const M_Q = new Quaternion();
const M_E = new Euler();

/** A part's placement in its bone's frame: translate, turn (XYZ Euler), scale. */
function at(x: number, y: number, z: number, rx = 0, ry = 0, rz = 0, sx = 1, sy = 1, sz = 1): Matrix4 {
  return new Matrix4().compose(M_POS.set(x, y, z), M_Q.setFromEuler(M_E.set(rx, ry, rz)), M_SCALE.set(sx, sy, sz));
}

/**
 * A finger segment along +Z from the origin: a tube tapering from radius `r0`
 * to `r1` over `length`, both ends rounded (a lathe-turned profile). Pure.
 */
export function fingerSegment(r0: number, r1: number, length: number, radial = 6): LatheGeometry {
  const profile = [
    new Vector2(0, 0), new Vector2(r0 * 0.8, r0 * 0.4), new Vector2(r0, r0 * 1.1),
    new Vector2(r1, length - r1 * 0.9), new Vector2(0, length),
  ];
  return new LatheGeometry(profile, radial).rotateX(Math.PI / 2);
}

/** A finger: two segments in a chain, the second hinged at the end of the first. */
interface Finger { base: Bone; joint: Bone }

export class ViewArm {
  readonly group = new Group();
  /** The hand: place it with `pose`; its children are in the hand frame. */
  readonly hand = new Bone();
  /** The bones (unscaled, turned along shoulder → elbow and elbow → wrist). */
  readonly upper = new Bone();
  readonly fore = new Bone();
  /** Landmarks in the hand frame (for layout checks): the knuckle plate, and the index finger's tip. */
  readonly knuckles = new Object3D();
  readonly indexTip = new Object3D();
  /** The sleeves (scaled along the bone to its length) and the gauntlet, at the wrist end of the forearm. */
  private readonly upperSleeve = new Bone();
  private readonly foreSleeve = new Bone();
  private readonly cuff = new Bone();
  private readonly housing: Bone | null = null;
  private readonly fingers: Finger[] = [];
  private readonly thumb: Finger;
  /** −1 for the left arm: the hand is mirrored. */
  private readonly sx: number;
  private readonly elbow = new Vector3();
  private readonly axis = new Vector3();
  private readonly back = new Vector3();
  private readonly across = new Vector3();
  private readonly m4 = new Matrix4();

  constructor(readonly side: "left" | "right", rig: RigBuilder, slots: ArmSlots) {
    this.group.name = `ViewArm_${side}`;
    const sx = side === "left" ? -1 : 1;
    this.sx = sx;
    const mirror = sx < 0;
    // In the hand: placed for the right hand, mirrored for the left.
    const handPart = (geo: BufferGeometry, bone: Object3D, slot: Slot, m: Matrix4 | null = null) => rig.add(geo, bone, slot, m, mirror);

    // Sleeves: unit-height cylinders along +Y from the joint, scaled to the bone's length by `pose`.
    this.upper.add(this.upperSleeve);
    this.fore.add(this.foreSleeve);
    rig.add(new CylinderGeometry(ARM.rElbow, ARM.rShoulder, 1, 10, 1, true).translate(0, 0.5, 0), this.upperSleeve, slots.sleeve);
    rig.add(new CylinderGeometry(ARM.rWrist, ARM.rElbow, 1, 10, 1, true).translate(0, 0.5, 0), this.foreSleeve, slots.sleeve);
    // An elbow cap closes the joint between the two sleeves (at the forearm's start).
    rig.add(new SphereGeometry(ARM.rElbow * 0.98, 6, 4), this.fore, slots.sleeve);
    this.group.add(this.upper, this.fore, this.hand);

    // The glove's gauntlet rides on the forearm (it follows the arm, not the bent wrist): it flares over the sleeve's
    // end (the sleeve stops inside it) with a rolled rim and a strap in the trim. `pose` puts `cuff` at the wrist.
    this.fore.add(this.cuff);
    rig.add(new CylinderGeometry(0.036, 0.0415, 0.08, 12, 1, true), this.cuff, slots.glove, at(0, -0.04, 0, 0, 0, 0, 1.08, 1, 0.9));
    rig.add(new TorusGeometry(0.0415, 0.0042, 4, 12).rotateX(Math.PI / 2), this.cuff, slots.glove, at(0, -0.08, 0, 0, 0, 0, 1.08, 1, 0.9));
    rig.add(new CylinderGeometry(0.0408, 0.0418, 0.012, 12, 1, true), this.cuff, slots.trim, at(0, -0.058, 0, 0, 0, 0, 1.1, 1, 0.92));

    // The wrist: a rounded joint between the gauntlet and the palm. Palm: a chamfered slab; an armoured plate over the
    // knuckles and a panel in the trim on the back of the hand.
    handPart(new SphereGeometry(0.031, 8, 6), this.hand, slots.glove, at(0, -0.002, 0.006, 0, 0, 0, 1.12, 0.82, 1));
    handPart(chamferBox(0.08, 0.03, 0.084, 0.011, true), this.hand, slots.glove, at(0, 0, 0.05));
    handPart(chamferBox(0.07, 0.01, 0.026, 0.004), this.hand, slots.housing, at(0, 0.0145, 0.08, 0.12));
    handPart(chamferBox(0.052, 0.006, 0.038, 0.0025), this.hand, slots.trim, at(0, 0.0138, 0.042));
    this.knuckles.position.set(0, 0.0145, 0.08);
    this.hand.add(this.knuckles);

    // Fingers: two tapered, round-ended segments each; index on the thumb's side (+X), little finger outside.
    const lengths = [1, 1.08, 1.02, 0.84];
    const xs = [0.0265, 0.0088, -0.0088, -0.0262];
    for (let i = 0; i < 4; i++) {
      const base = new Bone();
      base.position.set(xs[i] * sx, -0.001, 0.086);
      const joint = new Bone();
      joint.position.set(0, 0, ARM.seg1 * lengths[i] - 0.008);
      base.add(joint);
      this.hand.add(base);
      handPart(fingerSegment(0.0098, 0.009, ARM.seg1), base, slots.glove, at(0, 0, 0, 0, 0, 0, 1, 1, lengths[i]));
      handPart(fingerSegment(0.009, 0.0078, ARM.seg2), joint, slots.glove, at(0, 0, 0, 0, 0, 0, 1, 1, lengths[i]));
      this.fingers.push({ base, joint });
    }
    this.indexTip.position.set(0, -0.004, ARM.seg2 * lengths[0]);
    this.fingers[0].joint.add(this.indexTip);
    // Thumb: from the heel of the palm on the thumb's side, angled forward and in.
    const tb = new Bone();
    tb.position.set(0.034 * sx, -0.007, 0.028);
    const tj = new Bone();
    tj.position.set(0, 0, 0.034);
    tb.add(tj);
    this.hand.add(tb);
    handPart(fingerSegment(0.0118, 0.0105, 0.042), tb, slots.glove);
    handPart(fingerSegment(0.0105, 0.009, 0.036), tj, slots.glove);
    this.thumb = { base: tb, joint: tj };

    if (side === "left") {
      // The shield emitter: a flat housing along the back of the forearm with a glowing strip and a lens.
      const housing = new Bone();
      this.fore.add(housing);
      rig.add(chamferBox(0.052, 0.13, 0.02, 0.005), housing, slots.housing);
      rig.add(chamferBox(0.012, 0.1, 0.004, 0.0015), housing, slots.emitter, at(0, -0.005, 0.011));
      rig.add(new CylinderGeometry(0.011, 0.013, 0.006, 10).rotateX(Math.PI / 2), housing, slots.emitter, at(0, 0.05, 0.012));
      this.housing = housing;
    }
    this.curl(handPose(1.2, 1.1, 0.4));
  }

  /** Curl the fingers, the index finger and the thumb (see `HandPose`). */
  curl(p: HandPose): void {
    for (let i = 0; i < this.fingers.length; i++) {
      const f = this.fingers[i];
      // The little finger curls a touch more, as a real grip does.
      const extra = i * 0.05;
      const c = i === 0 ? p.index : p.fingers;
      f.base.rotation.set(c[0] + extra, 0, 0);
      f.joint.rotation.set(c[1] + extra, 0, 0);
    }
    // The thumb turns about Y and Z too: mirrored for the left hand.
    const [bend, across] = p.thumb;
    this.thumb.base.rotation.set(0.35 + bend * 0.5, (-0.55 - bend * 0.25 - across) * this.sx, 0);
    this.thumb.joint.rotation.set(bend * 0.6, -0.2 * this.sx, 0);
  }

  /**
   * Place the arm (all in the parent's space): `shoulder`, the hand at
   * `wrist` turned by `handQuat` (the hand frame), the elbow bending toward
   * `pole` (unit). The forearm's back follows the back of the hand.
   */
  pose(shoulder: Vector3, wrist: Vector3, handQuat: Quaternion, pole: Vector3): void {
    this.hand.position.copy(wrist);
    this.hand.quaternion.copy(handQuat);
    const elbow = solveElbow(shoulder, wrist, ARM.upper, ARM.fore, pole, this.elbow);
    const upper = this.place(this.upper, shoulder, elbow, pole);
    this.upperSleeve.scale.set(1, Math.max(0.01, upper), 1);
    this.back.set(0, 1, 0).applyQuaternion(handQuat);
    const length = this.place(this.fore, elbow, wrist, this.back);
    this.foreSleeve.scale.set(1, Math.max(0.01, length - ARM.sleeveShort), 1);
    // The emitter lies along the forearm's back, a hand's width short of the wrist.
    this.cuff.position.set(0, length, 0);
    if (this.housing) this.housing.position.set(0, Math.max(0, length - 0.15), ARM.rWrist + 0.008);
  }

  /** Turn `bone` along `a` → `b` (its +Y) with its +Z toward `up`. Returns the length. */
  private place(bone: Object3D, a: Vector3, b: Vector3, up: Vector3): number {
    const axis = this.axis.subVectors(b, a);
    const length = axis.length();
    if (length < 1e-5) return 0;
    axis.multiplyScalar(1 / length);
    const z = this.across.copy(up).addScaledVector(axis, -up.dot(axis));
    if (z.lengthSq() < 1e-8) z.set(0, 0, 1).addScaledVector(axis, -axis.z);
    z.normalize();
    const x = SCRATCH_X.crossVectors(axis, z);
    this.m4.makeBasis(x, axis, z);
    bone.quaternion.setFromRotationMatrix(this.m4);
    bone.position.copy(a);
    return length;
  }

  /** The hand's frame from its knuckle direction and the back of the hand (any lengths). Written into `out`. */
  static handFrame(knuckles: Vector3, backOfHand: Vector3, out: Quaternion): Quaternion {
    const z = SCRATCH_Z.copy(knuckles).normalize();
    const y = SCRATCH_Y.copy(backOfHand).addScaledVector(z, -backOfHand.dot(z)).normalize();
    const x = SCRATCH_X.crossVectors(y, z);
    return out.setFromRotationMatrix(SCRATCH_M.makeBasis(x, y, z));
  }
}
