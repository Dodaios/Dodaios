/**
 * The commander's own arms for the first-person viewmodel, built
 * procedurally (a few hundred triangles each): an upper arm and a tapered
 * forearm in the uniform's cloth, a cuff in the uniform's trim, and a gloved
 * hand (palm, knuckle roll, four two-segment fingers and a thumb) whose
 * fingers curl by a parameter, so one hand closes around a grip, cradles a
 * shroud or hangs loose. The left forearm carries the shield emitter.
 *
 * Hand frame (the `hand` group, origin at the wrist): +Z runs to the
 * knuckles, +Y is the back of the hand, +X the thumb's side for the right
 * hand; the left hand is the same hand mirrored (thumb on −X). Fingers curl
 * toward −Y (the palm).
 *
 * `pose` places the arm for a frame: shoulder, wrist and the hand's frame
 * given, the elbow is solved by two-bone IK toward a pole (it hangs down and
 * out, as an arm does), and the forearm turns about its axis so its back (and
 * the emitter) faces the way the back of the hand does.
 */
import {
  BoxGeometry, CapsuleGeometry, CylinderGeometry, Group, LatheGeometry, Matrix4, Mesh, SphereGeometry, TorusGeometry, Vector2, Vector3,
  type BufferGeometry, type Material, type Quaternion,
} from "three";
import { RoundedBoxGeometry } from "three/examples/jsm/geometries/RoundedBoxGeometry.js";
import { solveElbow } from "../duel/figure";

export interface ArmMaterials {
  /** The uniform's cloth (sleeves). */
  sleeve: Material;
  /** The uniform's trim (the sleeve's cuff band, the glove's seam). */
  trim: Material;
  /** Glove leather. */
  glove: Material;
  /** The shield emitter's housing and its glowing strip (left forearm only). */
  housing: Material;
  emitter: Material;
}

export const ARM = {
  /** Upper arm and forearm lengths, metres (the upper arm is never in view; it is long enough that the hands reach the blaster). */
  upper: 0.36,
  fore: 0.3,
  /** Sleeve radii: shoulder, elbow, wrist. */
  rShoulder: 0.05,
  rElbow: 0.043,
  rWrist: 0.035,
  /** Finger capsule radius and segment lengths. */
  finger: 0.0092,
  seg1: 0.042,
  seg2: 0.036,
  /** The forearm's sleeve stops this far short of the wrist, inside the glove's gauntlet. */
  sleeveShort: 0.06,
};

const SCRATCH_X = new Vector3();
const SCRATCH_Y = new Vector3();
const SCRATCH_Z = new Vector3();
const SCRATCH_M = new Matrix4();

/**
 * A finger segment along +Z from the origin: a tube tapering from radius `r0`
 * to `r1` over `length`, both ends rounded (a lathe-turned profile). Pure.
 */
export function fingerSegment(r0: number, r1: number, length: number, radial = 7): LatheGeometry {
  const profile = [
    new Vector2(0, 0), new Vector2(r0 * 0.75, r0 * 0.33), new Vector2(r0, r0),
    new Vector2(r1, length - r1), new Vector2(r1 * 0.75, length - r1 * 0.33), new Vector2(0, length),
  ];
  return new LatheGeometry(profile, radial).rotateX(Math.PI / 2);
}

/** Position a cuff part along the forearm (y) and squash it to the forearm's oval (x across, z front to back). */
function placed(mesh: Mesh, y: number, sx: number, sz: number): Mesh {
  mesh.position.set(0, y, 0);
  mesh.scale.set(sx, 1, sz);
  return mesh;
}

/** A finger: two segments in a chain, the second hinged at the end of the first. */
interface Finger { base: Group; joint: Group }

export class ViewArm {
  readonly group = new Group();
  /** The hand: place it with `pose`; its children are in the hand frame. */
  readonly hand = new Group();
  /** The bones (unscaled, turned along shoulder → elbow and elbow → wrist). */
  readonly upper = new Group();
  readonly fore = new Group();
  /** The glove's gauntlet, on the forearm at the wrist. */
  private readonly cuff = new Group();
  /** The left forearm's emitter strip (null on the right arm). */
  readonly emitterStrip: Mesh | null = null;
  private readonly upperSleeve: Mesh;
  private readonly foreSleeve: Mesh;
  private readonly housing: Mesh | null = null;
  private readonly fingers: Finger[] = [];
  private readonly thumb: Finger;
  private readonly geometries: BufferGeometry[] = [];
  private readonly elbow = new Vector3();
  private readonly axis = new Vector3();
  private readonly back = new Vector3();
  private readonly across = new Vector3();
  private readonly m4 = new Matrix4();

  constructor(readonly side: "left" | "right", mats: ArmMaterials) {
    this.group.name = `ViewArm_${side}`;
    const g = <T extends BufferGeometry>(geo: T): T => { this.geometries.push(geo); return geo; };
    // Sleeves: unit-height cylinders along +Y from the joint, scaled to the bone's length by `pose`.
    this.upperSleeve = new Mesh(g(new CylinderGeometry(ARM.rElbow, ARM.rShoulder, 1, 12, 1, true).translate(0, 0.5, 0)), mats.sleeve);
    this.foreSleeve = new Mesh(g(new CylinderGeometry(ARM.rWrist, ARM.rElbow, 1, 12, 1, true).translate(0, 0.5, 0)), mats.sleeve);
    this.upper.add(this.upperSleeve);
    this.fore.add(this.foreSleeve);
    // An elbow cap closes the joint between the two sleeves (at the forearm's start).
    const elbowCap = new Mesh(g(new CapsuleGeometry(ARM.rElbow * 0.98, 0.001, 3, 10)), mats.sleeve);
    this.fore.add(elbowCap);
    this.group.add(this.upper, this.fore, this.hand);

    // The glove's gauntlet rides on the forearm (it follows the arm, not the bent wrist): it flares over the sleeve's
    // end (the sleeve stops inside it) with a rolled rim and a strap. `pose` puts `cuff` at the wrist.
    this.cuff.add(
      placed(new Mesh(g(new CylinderGeometry(0.036, 0.0415, 0.08, 18, 1, true).translate(0, -0.04, 0)), mats.glove), 0, 1.08, 0.9),
      placed(new Mesh(g(new TorusGeometry(0.0415, 0.0042, 6, 18).rotateX(Math.PI / 2)), mats.glove), -0.08, 1.08, 0.9),
      placed(new Mesh(g(new CylinderGeometry(0.0408, 0.0418, 0.012, 18, 1, true)), mats.housing), -0.058, 1.1, 0.92),
    );
    this.fore.add(this.cuff);
    // The wrist: a rounded joint between the gauntlet and the palm.
    const wristBall = new Mesh(g(new SphereGeometry(0.031, 10, 7)), mats.glove);
    wristBall.position.set(0, -0.002, 0.006);
    wristBall.scale.set(1.12, 0.82, 1);
    // Palm: a rounded slab; an armoured plate over the knuckles and a panel on the back of the hand.
    const palm = new Mesh(g(new RoundedBoxGeometry(0.08, 0.03, 0.084, 2, 0.013)), mats.glove);
    palm.position.set(0, 0, 0.05);
    const plate = new Mesh(g(new RoundedBoxGeometry(0.07, 0.01, 0.026, 2, 0.0045)), mats.housing);
    plate.position.set(0, 0.0145, 0.08);
    plate.rotation.set(0.12, 0, 0);
    const panel = new Mesh(g(new RoundedBoxGeometry(0.052, 0.006, 0.038, 2, 0.0028)), mats.trim);
    panel.position.set(0, 0.0138, 0.042);
    this.hand.add(wristBall, palm, plate, panel);

    // Fingers: two tapered, round-ended segments each; index on the thumb's side (+X), little finger outside.
    const seg1 = g(fingerSegment(0.0098, 0.009, ARM.seg1));
    const seg2 = g(fingerSegment(0.009, 0.0078, ARM.seg2));
    const lengths = [1, 1.08, 1.02, 0.84];
    const xs = [0.0265, 0.0088, -0.0088, -0.0262];
    for (let i = 0; i < 4; i++) {
      const base = new Group();
      base.position.set(xs[i], -0.001, 0.086);
      const s1 = new Mesh(seg1, mats.glove);
      s1.scale.set(1, 1, lengths[i]);
      const joint = new Group();
      joint.position.set(0, 0, ARM.seg1 * lengths[i] - 0.008);
      const s2 = new Mesh(seg2, mats.glove);
      s2.scale.set(1, 1, lengths[i]);
      joint.add(s2);
      base.add(s1, joint);
      this.hand.add(base);
      this.fingers.push({ base, joint });
    }
    // Thumb: from the heel of the palm on the thumb's side, angled forward and in.
    const tb = new Group();
    tb.position.set(0.034, -0.007, 0.028);
    const t1 = new Mesh(g(fingerSegment(0.0118, 0.0105, 0.042)), mats.glove);
    const tj = new Group();
    tj.position.set(0, 0, 0.034);
    const t2 = new Mesh(g(fingerSegment(0.0105, 0.009, 0.036)), mats.glove);
    tj.add(t2);
    tb.add(t1, tj);
    this.hand.add(tb);
    this.thumb = { base: tb, joint: tj };

    if (side === "left") {
      // The shield emitter: a flat housing along the back of the forearm with a glowing strip and a lens.
      const housing = new Mesh(g(new BoxGeometry(0.052, 0.13, 0.02)), mats.housing);
      const strip = new Mesh(g(new BoxGeometry(0.012, 0.1, 0.004)), mats.emitter);
      strip.position.set(0, -0.005, 0.011);
      const lens = new Mesh(g(new CylinderGeometry(0.011, 0.013, 0.006, 12).rotateX(Math.PI / 2)), mats.emitter);
      lens.position.set(0, 0.05, 0.012);
      housing.add(strip, lens);
      this.fore.add(housing);
      this.housing = housing;
      this.emitterStrip = strip;
      this.hand.scale.x = -1;
    }
    this.group.traverse((o) => { o.frustumCulled = false; });
    this.curl(1.2, 1.1, 0.4);
  }

  /** Curl the fingers: first and second joints (radians toward the palm), and the thumb's bend (0 open .. 1 closed). */
  curl(c1: number, c2: number, thumb: number): void {
    for (let i = 0; i < this.fingers.length; i++) {
      const f = this.fingers[i];
      // The little finger curls a touch more, as a real grip does.
      const extra = i * 0.05;
      f.base.rotation.set(c1 + extra, 0, 0);
      f.joint.rotation.set(c2 + extra, 0, 0);
    }
    this.thumb.base.rotation.set(0.35 + thumb * 0.5, -0.55 - thumb * 0.25, 0);
    this.thumb.joint.rotation.set(thumb * 0.6, -0.2, 0);
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
    this.place(this.upper, this.upperSleeve, shoulder, elbow, pole);
    this.back.set(0, 1, 0).applyQuaternion(handQuat);
    const length = this.place(this.fore, this.foreSleeve, elbow, wrist, this.back, ARM.sleeveShort);
    // The emitter lies along the forearm's back, a hand's width short of the wrist.
    this.cuff.position.set(0, length, 0);
    if (this.housing) this.housing.position.set(0, Math.max(0, length - 0.15), ARM.rWrist + 0.008);
  }

  /** Turn `bone` along `a` → `b` (its +Y) with its +Z toward `up`; the sleeve scales to the length. Returns the length. */
  private place(bone: Group, sleeve: Mesh, a: Vector3, b: Vector3, up: Vector3, short = 0): number {
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
    sleeve.scale.set(1, Math.max(0.01, length - short), 1);
    return length;
  }

  /** The hand's frame from its knuckle direction and the back of the hand (any lengths). Written into `out`. */
  static handFrame(knuckles: Vector3, backOfHand: Vector3, out: Quaternion): Quaternion {
    const z = SCRATCH_Z.copy(knuckles).normalize();
    const y = SCRATCH_Y.copy(backOfHand).addScaledVector(z, -backOfHand.dot(z)).normalize();
    const x = SCRATCH_X.crossVectors(y, z);
    return out.setFromRotationMatrix(SCRATCH_M.makeBasis(x, y, z));
  }

  dispose(): void {
    for (const geo of this.geometries) geo.dispose();
  }
}
