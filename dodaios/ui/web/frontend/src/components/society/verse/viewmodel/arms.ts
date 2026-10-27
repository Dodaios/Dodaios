/**
 * One of the commander's own arms in the first-person viewmodel: the bones
 * that drive the arm cut from their body (`armMesh.ts`).
 *
 * The bones are plain Bones in the viewmodel's rig, posed in the camera's
 * space every frame; the arm's skinned vertices follow them with the body's
 * own weights. Upper arm, forearm (a hinge at the elbow and a twist toward the
 * wrist, so turning the hand over rolls the forearm), hand, three phalanges
 * per finger and three thumb bones.
 *
 * Hand frame (the `hand` bone, origin at the wrist): +Z runs to the
 * knuckles, +Y is the back of the hand, +X the thumb's side for the right
 * hand; the left hand is the same hand mirrored (thumb on −X). Fingers curl
 * toward −Y (the palm).
 *
 * `pose` places the arm for a frame: shoulder, wrist and the hand's frame
 * given, the elbow is solved by two-bone IK toward a pole (it hangs down and
 * out, as an arm does) with the body's own bone lengths; a wrist out of reach
 * draws the shoulder after it (the shoulder is never in view) rather than
 * tearing the hand off the sleeve.
 */
import { Bone, Group, Matrix4, Object3D, Quaternion, Vector3 } from "three";
import { solveElbow } from "../duel/figure";
import { B_FORE, B_HAND, B_THUMB, B_TWIST, B_UPPER, BONES, fingerBone, type ArmRig } from "./armMesh";

/**
 * A hand's pose: the three outer fingers' two joints (knuckle, middle joint; the end joint follows the middle one,
 * as a real finger's does), the index finger's two joints (radians toward the palm), and the thumb's bend (0 open ..
 * 1 closed) and its swing across the palm (radians).
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

export const ARM = {
  /** The end joint of a finger bends this share of its middle joint. */
  distal: 0.75,
  /** Each finger from the index outward curls a little more, as a real grip does (a share of its curl per finger). */
  spread: 0.04,
  /** The thumb: how its three bones share the bend, and how far the swing carries it across the palm. */
  thumbBend: [0.25, 0.55, 0.75] as [number, number, number],
  thumbAcross: 1,
  /** A wrist out of reach pulls the shoulder after it until the arm is this share of its full length. */
  reach: 0.985,
  /** The shield emitter's housing (half its thickness) clears the sleeve's cloth by this, metres. */
  emitterClear: 0.009,
};

const SCRATCH_X = new Vector3();
const SCRATCH_Y = new Vector3();
const SCRATCH_Z = new Vector3();
const SCRATCH_M = new Matrix4();
const FINGER_M = new Matrix4();
const QX = new Quaternion();
const QY = new Quaternion();
const AXIS_X = new Vector3(1, 0, 0);
const AXIS_Y = new Vector3(0, 1, 0);

/** A chain bone's rest placement relative to its parent (from the bind frames). */
interface Rest { position: Vector3; quaternion: Quaternion }

export class ViewArm {
  readonly group = new Group();
  readonly side: "left" | "right";
  /** The arm's bones in the cut's order (`armMesh.ts`): what the skinned mesh binds to. */
  readonly bones: Bone[] = [];
  readonly upper: Bone;
  readonly fore: Bone;
  readonly twist: Bone;
  /** The hand: placed by `pose`; its children are in the hand frame. */
  readonly hand: Bone;
  /** Landmarks: the knuckles on the back of the hand, the index finger's pad, the shield emitter's seat on the forearm. */
  readonly knuckles = new Object3D();
  readonly indexTip = new Object3D();
  readonly emitter = new Object3D();
  /** Bone lengths, metres (the body's own). */
  readonly upperLength: number;
  readonly foreLength: number;
  private readonly rest: Rest[] = [];
  /** −1 for the left arm: the hand is mirrored. */
  private readonly sx: number;
  private readonly from = new Vector3();
  private readonly elbow = new Vector3();
  private readonly axis = new Vector3();
  private readonly back = new Vector3();
  private readonly across = new Vector3();
  private readonly m4 = new Matrix4();

  constructor(readonly rig: ArmRig) {
    this.side = rig.side;
    this.sx = rig.side === "left" ? -1 : 1;
    this.group.name = `ViewArm_${rig.side}`;
    this.upperLength = rig.upper;
    this.foreLength = rig.fore;
    for (let i = 0; i < BONES; i++) {
      const b = new Bone();
      b.name = `${rig.side}_${i}`;
      this.bones.push(b);
      this.rest.push({ position: new Vector3(), quaternion: new Quaternion() });
    }
    this.upper = this.bones[B_UPPER];
    this.fore = this.bones[B_FORE];
    this.twist = this.bones[B_TWIST];
    this.hand = this.bones[B_HAND];
    this.group.add(this.upper, this.fore, this.twist, this.hand);
    // Fingers and thumb hang from the hand in chains; their rest placements come from the bind frames.
    const chain = (first: number) => {
      for (let j = 0; j < 3; j++) {
        const i = first + j;
        const parent = j === 0 ? B_HAND : i - 1;
        const local = SCRATCH_M.copy(rig.bind[parent]).invert().multiply(rig.bind[i]);
        local.decompose(this.rest[i].position, this.rest[i].quaternion, SCRATCH_X);
        this.bones[parent].add(this.bones[i]);
        this.bones[i].position.copy(this.rest[i].position);
        this.bones[i].quaternion.copy(this.rest[i].quaternion);
      }
    };
    for (let f = 0; f < 4; f++) chain(fingerBone(f));
    chain(B_THUMB);
    this.knuckles.position.copy(rig.knuckles);
    this.hand.add(this.knuckles);
    // The index finger's pad, carried by its end bone.
    const toEnd = SCRATCH_M.copy(rig.bind[fingerBone(0) + 2]).invert().multiply(rig.bind[B_HAND]);
    this.indexTip.position.copy(rig.indexTip).applyMatrix4(toEnd);
    this.bones[fingerBone(0) + 2].add(this.indexTip);
    this.emitter.position.set(0, rig.emitterAt * rig.fore, rig.emitterLift + ARM.emitterClear);
    this.twist.add(this.emitter);
    this.curl(handPose(0.3, 0.3, 0.2));
  }

  /** The bind frames' inverses, in bone order (the skeleton's bone inverses). */
  inverses(): Matrix4[] {
    return this.rig.bind.map((m) => m.clone().invert());
  }

  /** Curl the fingers, the index finger and the thumb (see `HandPose`). */
  curl(p: HandPose): void {
    for (let f = 0; f < 4; f++) {
      const c = f === 0 ? p.index : p.fingers;
      const k = 1 + f * ARM.spread;
      const angles = [c[0] * k, c[1] * k, c[1] * k * ARM.distal];
      for (let j = 0; j < 3; j++) this.bend(fingerBone(f) + j, angles[j], 0);
    }
    // The thumb bends through its three bones; its root also swings across the palm (mirrored for the left hand).
    const [bend, swing] = p.thumb;
    for (let j = 0; j < 3; j++) this.bend(B_THUMB + j, bend * ARM.thumbBend[j], j === 0 ? swing * ARM.thumbAcross * this.sx : 0);
  }

  /**
   * Points along finger `f` (0 index .. 3 little) for its current curl, in the hand's frame: the middle joint, the
   * end joint, the middle of the end bone and the tip. Written into `out` (four vectors).
   */
  fingerPoints(f: number, out: Vector3[]): Vector3[] {
    const m = FINGER_M.identity();
    for (let j = 0; j < 3; j++) {
      const bone = this.bones[fingerBone(f) + j];
      bone.updateMatrix();
      m.multiply(bone.matrix);
      if (j === 1) out[0].setFromMatrixPosition(m);
    }
    out[1].setFromMatrixPosition(m);
    const tip = this.rig.tips[f];
    out[2].copy(tip).multiplyScalar(0.5).applyMatrix4(m);
    out[3].copy(tip).applyMatrix4(m);
    return out;
  }

  /** A chain bone at its rest placement, curled by `x` about its +X and swung by `y` about its +Y. */
  private bend(i: number, x: number, y: number): void {
    const b = this.bones[i];
    b.quaternion.copy(this.rest[i].quaternion).multiply(QY.setFromAxisAngle(AXIS_Y, y)).multiply(QX.setFromAxisAngle(AXIS_X, x));
  }

  /**
   * Place the arm (all in the parent's space): `shoulder`, the hand at
   * `wrist` turned by `handQuat` (the hand frame), the elbow bending toward
   * `pole` (unit). The forearm's twist follows the back of the hand.
   */
  pose(shoulder: Vector3, wrist: Vector3, handQuat: Quaternion, pole: Vector3): void {
    const a = this.upperLength;
    const b = this.foreLength;
    // Out of reach: the shoulder follows the wrist (never the hand off the sleeve).
    const from = this.from.copy(shoulder);
    const d = from.distanceTo(wrist);
    const max = (a + b) * ARM.reach;
    if (d > max) from.sub(wrist).multiplyScalar(max / d).add(wrist);
    this.hand.position.copy(wrist);
    this.hand.quaternion.copy(handQuat);
    const elbow = solveElbow(from, wrist, a, b, pole, this.elbow);
    // Upper arm: along shoulder → elbow, +Z toward the point of the elbow.
    this.place(this.upper, from, elbow, pole);
    // Forearm hinge: the upper arm's hinge axis (+X), along elbow → wrist.
    const hinge = SCRATCH_X.setFromMatrixColumn(this.m4.makeRotationFromQuaternion(this.upper.quaternion), 0);
    const y = SCRATCH_Y.subVectors(wrist, elbow);
    if (y.lengthSq() < 1e-10) y.set(0, -1, 0);
    y.normalize();
    hinge.addScaledVector(y, -hinge.dot(y)).normalize();
    const z = SCRATCH_Z.crossVectors(hinge, y);
    this.fore.quaternion.setFromRotationMatrix(this.m4.makeBasis(hinge, y, z));
    this.fore.position.copy(elbow);
    // Forearm twist: the same axis, its back toward the back of the hand.
    this.back.set(0, 1, 0).applyQuaternion(handQuat);
    this.place(this.twist, elbow, wrist, this.back);
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
