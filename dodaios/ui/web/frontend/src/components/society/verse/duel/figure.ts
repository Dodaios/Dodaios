/**
 * A duellist's body: a character from the library (the commander's officer
 * body for the person, the trooper for the bot) with the blaster in its
 * hands, posed every frame from the combat view.
 *
 * The clip set has walk and idle but no aiming, so the upper body is posed
 * procedurally on top of the clips: the legs walk the way the body moves
 * (backwards when it backs off), the spine and chest twist and bend toward
 * the aim, the head follows it, and both arms reach the blaster by two-bone
 * IK (right hand on the grip, left hand on the shroud). Sprinting carries
 * the blaster low, the raised shield lowers it and puts the left palm
 * forward, venting tips it up. A dodge is a tucked roll along the move
 * direction; a knocked-out body falls backwards.
 */
import {
  AnimationMixer, Color, Group, LoopRepeat, Matrix4, Mesh, MeshBasicMaterial, PlaneGeometry, Quaternion, Vector3,
  type AnimationAction, type Bone, type Material, type MeshStandardMaterial, type Object3D, type Texture,
} from "three";
import type { Deck } from "../content/deck";
import { disposeInstance, type CharacterInstance } from "../actors/characters";
import { clipFor } from "../actors/clips";
import { RoomLight } from "../actors/roomLight";
import type { PlayerView } from "../combat/view";
import { buildBlaster, type Blaster } from "./blaster";

const UP = new Vector3(0, 1, 0);

function wrap(a: number): number {
  return Math.atan2(Math.sin(a), Math.cos(a));
}

/**
 * Two-bone IK in world space: where the elbow goes for a shoulder at `s`,
 * a target `t`, bone lengths `a` (upper) and `b` (lower), bending toward
 * `pole`. Pure; writes into `out`.
 */
export function solveElbow(s: Vector3, t: Vector3, a: number, b: number, pole: Vector3, out: Vector3): Vector3 {
  const dir = out.subVectors(t, s);
  let d = dir.length();
  if (d < 1e-5) return out.copy(s).addScaledVector(pole, a);
  dir.multiplyScalar(1 / d);
  d = Math.min(d, (a + b) * 0.999);
  const along = (a * a - b * b + d * d) / (2 * d);
  const h = Math.sqrt(Math.max(0, a * a - along * along));
  // The pole's part across the shoulder-target line.
  const px = pole.x - dir.x * pole.dot(dir);
  const py = pole.y - dir.y * pole.dot(dir);
  const pz = pole.z - dir.z * pole.dot(dir);
  const pl = Math.hypot(px, py, pz) || 1;
  return out.set(
    s.x + dir.x * along + (px / pl) * h,
    s.y + dir.y * along + (py / pl) * h,
    s.z + dir.z * along + (pz / pl) * h,
  );
}

const tmpA = new Vector3();
const tmpB = new Vector3();
const tmpQ = new Quaternion();
const tmpQ2 = new Quaternion();
const tmpP = new Quaternion();

/** Turn `bone` so the line from it to `child` points at `target` (world). The bone's parents must be up to date. */
function aimBone(bone: Object3D, child: Object3D, target: Vector3): void {
  const from = bone.getWorldPosition(tmpA);
  const cur = child.getWorldPosition(tmpB).sub(from);
  const want = target.clone().sub(from);
  if (cur.lengthSq() < 1e-10 || want.lengthSq() < 1e-10) return;
  cur.normalize();
  want.normalize();
  const delta = tmpQ.setFromUnitVectors(cur, want);
  const world = bone.getWorldQuaternion(tmpQ2);
  const parent = bone.parent ? bone.parent.getWorldQuaternion(tmpP).invert() : tmpP.identity();
  bone.quaternion.copy(parent.multiply(delta.multiply(world)));
  bone.updateMatrixWorld(true);
}

/** Rotate a bone about a world axis by `angle` (its parent must be up to date). */
function turnBone(bone: Object3D, axis: Vector3, angle: number): void {
  if (Math.abs(angle) < 1e-5) return;
  const parentInv = bone.parent ? bone.parent.getWorldQuaternion(tmpP).invert() : tmpP.identity();
  const local = tmpA.copy(axis).applyQuaternion(parentInv).normalize();
  bone.quaternion.premultiply(tmpQ.setFromAxisAngle(local, angle));
  bone.updateMatrixWorld(true);
}

interface Arm { upper: Bone; fore: Bone; hand: Bone; a: number; b: number }

export interface FigureLook {
  /** Recolour these material names (the trooper's armour and accents). */
  tint?: Readonly<Record<string, string>>;
  /** Make these materials glow in the colour (a visor). */
  glow?: Readonly<Record<string, string>>;
  /** The blaster's cell colour. */
  accent: Color;
}

export class DuelFigure {
  readonly group = new Group();
  readonly blaster: Blaster;
  private readonly mixer: AnimationMixer;
  private readonly light = new RoomLight();
  private idle: AnimationAction | null = null;
  private walk: AnimationAction | null = null;
  private readonly bones: Record<string, Bone | undefined> = {};
  private right: Arm | null = null;
  private left: Arm | null = null;
  private legsYaw = 0;
  private walkWeight = 0;
  private deathT = 0;
  private primed = false;
  private readonly shadow: Mesh<PlaneGeometry, MeshBasicMaterial>;
  private readonly walkSpeed: number;
  // Scratch, reused every frame.
  private readonly grip = new Vector3();
  private readonly fore = new Vector3();
  private readonly elbow = new Vector3();
  private readonly pole = new Vector3();
  private readonly aim = new Vector3();
  private readonly side = new Vector3();
  private readonly qRoll = new Quaternion();
  private readonly qYaw = new Quaternion();
  private readonly m4 = new Matrix4();

  constructor(readonly instance: CharacterInstance, look: FigureLook, shadow: Texture) {
    this.mixer = new AnimationMixer(instance.root);
    this.walkSpeed = instance.walkSpeed || 1.4;
    for (const name of ["Hips", "Spine", "Chest", "Neck", "Head", "UpperArm_R", "ForeArm_R", "Hand_R", "UpperArm_L", "ForeArm_L", "Hand_L"]) {
      const o = instance.root.getObjectByName(name) as Bone | undefined;
      if (o) this.bones[name] = o;
    }
    const names = new Set(instance.clips.keys());
    const idleName = clipFor("idle", names);
    const walkName = clipFor("walk", names);
    if (idleName) { this.idle = this.mixer.clipAction(instance.clips.get(idleName)!); this.idle.setLoop(LoopRepeat, Infinity).play(); }
    if (walkName) { this.walk = this.mixer.clipAction(instance.clips.get(walkName)!); this.walk.setLoop(LoopRepeat, Infinity).play(); this.walk.weight = 0; }
    for (const [name, colour] of Object.entries(look.tint ?? {})) {
      for (const m of instance.materials.get(name) ?? []) (m as MeshStandardMaterial).color?.set(colour);
    }
    for (const [name, colour] of Object.entries(look.glow ?? {})) {
      for (const m of instance.materials.get(name) ?? []) {
        const s = m as MeshStandardMaterial;
        if (s.emissive) { s.emissive.set(colour); s.emissiveIntensity = 3; }
      }
    }
    this.blaster = buildBlaster(look.accent);
    this.group.add(instance.root);
    this.group.add(this.blaster.group);
    this.light.attach([...[...instance.materials.values()].flat(), ...this.blaster.materials]);
    this.shadow = new Mesh(new PlaneGeometry(1, 1), new MeshBasicMaterial({ map: shadow, color: 0x000000, transparent: true, opacity: 0.55, depthWrite: false }));
    this.shadow.rotation.x = -Math.PI / 2;
    this.group.add(this.shadow);
    for (const mesh of instance.meshes) mesh.frustumCulled = false;
    this.setupArms();
  }

  get materials(): Material[] {
    return [...[...this.instance.materials.values()].flat(), ...this.blaster.materials];
  }

  private setupArms(): void {
    const b = this.bones;
    const root = this.instance.root;
    root.position.set(0, 0, 0);
    root.rotation.set(0, 0, 0);
    root.updateMatrixWorld(true);
    const arm = (u?: Bone, f?: Bone, h?: Bone): Arm | null => {
      if (!u || !f || !h) return null;
      const a = u.getWorldPosition(new Vector3()).distanceTo(f.getWorldPosition(new Vector3()));
      const c = f.getWorldPosition(new Vector3()).distanceTo(h.getWorldPosition(new Vector3()));
      return a > 0.05 && c > 0.05 ? { upper: u, fore: f, hand: h, a, b: c } : null;
    };
    let right = arm(b.UpperArm_R, b.ForeArm_R, b.Hand_R);
    let left = arm(b.UpperArm_L, b.ForeArm_L, b.Hand_L);
    // A body facing +Z has its right side toward -X; if the rig's "_R" sits on +X the sides are named the other way.
    if (right && left && right.upper.getWorldPosition(new Vector3()).x > left.upper.getWorldPosition(new Vector3()).x) [right, left] = [left, right];
    this.right = right;
    this.left = left;
  }

  /**
   * Pose the body for one frame. `floorY` is the deck floor under the arena;
   * `deck` lights the body from the room's probe.
   */
  update(dtS: number, p: PlayerView, floorY: number, deck: Deck | null, timeS: number): void {
    const dt = Math.min(0.1, Math.max(0, dtS));
    const root = this.instance.root;
    const aimYaw = p.aimYaw;
    const aimPitch = p.aimPitch;

    // Legs: walk the way the body moves; backing off plays the walk backwards.
    const moving = p.speed > 0.35 && p.alive && !p.dodging;
    let reverse = false;
    if (moving) {
      const moveYaw = Math.atan2(p.vx, p.vz);
      let want = moveYaw;
      if (Math.abs(wrap(moveYaw - aimYaw)) > (100 * Math.PI) / 180) { want = moveYaw + Math.PI; reverse = true; }
      // Never twist further than the spine can carry.
      const lim = (80 * Math.PI) / 180;
      const off = wrap(want - aimYaw);
      if (Math.abs(off) > lim) want = aimYaw + Math.sign(off) * lim;
      this.legsYaw = this.primed ? this.legsYaw + wrap(want - this.legsYaw) * Math.min(1, dt * 12) : want;
    } else {
      this.legsYaw = this.primed ? this.legsYaw + wrap(aimYaw - this.legsYaw) * Math.min(1, dt * 8) : aimYaw;
    }
    this.primed = true;
    this.walkWeight += ((moving ? 1 : 0) - this.walkWeight) * Math.min(1, dt * 10);
    if (this.walk && this.idle) {
      this.walk.weight = this.walkWeight;
      this.idle.weight = 1 - this.walkWeight;
      const rate = Math.min(3.2, Math.max(0.6, (p.speed / this.walkSpeed) * 0.72));
      this.walk.timeScale = reverse ? -rate : rate;
    }
    this.mixer.update(dt);

    // Root: on the floor at the player's position, facing the legs' way; a roll or a fall turns it on top.
    const x = p.x;
    const z = p.z;
    this.qYaw.setFromAxisAngle(UP, this.legsYaw);
    root.position.set(x, floorY, z);
    root.quaternion.copy(this.qYaw);
    if (p.dodging) {
      const sp = Math.hypot(p.vx, p.vz);
      const dx = sp > 0.1 ? p.vx / sp : Math.sin(aimYaw);
      const dz = sp > 0.1 ? p.vz / sp : Math.cos(aimYaw);
      const t = p.dodgeProgress;
      const e = t * t * (3 - 2 * t);
      const axis = this.side.set(dz, 0, -dx).normalize();
      this.qRoll.setFromAxisAngle(axis, e * Math.PI * 2);
      const pivotY = 0.5;
      const tuck = Math.sin(t * Math.PI) * 0.18;
      const off = tmpA.set(0, -pivotY, 0).applyQuaternion(this.qRoll);
      root.position.set(x + off.x, floorY + pivotY - tuck * 0.5 + off.y, z + off.z);
      root.quaternion.copy(this.qRoll).multiply(this.qYaw);
    }
    if (!p.alive) {
      this.deathT = Math.min(1, this.deathT + dt / 0.6);
      const e = 1 - (1 - this.deathT) * (1 - this.deathT);
      const axis = this.side.set(-Math.cos(aimYaw), 0, Math.sin(aimYaw));
      this.qRoll.setFromAxisAngle(axis, e * (Math.PI / 2) * 0.96);
      root.quaternion.copy(this.qRoll).multiply(this.qYaw);
      root.position.y = floorY + e * 0.12;
    } else {
      this.deathT = 0;
    }
    root.updateMatrixWorld(true);

    const b = this.bones;
    const posing = p.alive && !p.dodging;
    if (posing) {
      // Upper body toward the aim: twist over spine and chest, bend with the pitch.
      const twist = wrap(aimYaw - this.legsYaw);
      if (b.Spine) turnBone(b.Spine, UP, twist * 0.45);
      if (b.Chest) turnBone(b.Chest, UP, twist * 0.55);
      const rightAxis = this.side.set(-Math.cos(aimYaw), 0, Math.sin(aimYaw));
      const bend = p.sprinting ? 0.12 : -aimPitch * 0.5;
      if (b.Chest) turnBone(b.Chest, rightAxis, -bend * 0.6);
      if (b.Spine) turnBone(b.Spine, rightAxis, -bend * 0.4);
      if (b.Head) turnBone(b.Head, rightAxis, aimPitch * 0.35);
    }

    // The blaster: held at the shoulder along the aim; low while sprinting, lowered behind a raised shield, tipped up venting.
    const bl = this.blaster.group;
    bl.visible = p.alive;
    let yaw = aimYaw;
    let pitch = aimPitch;
    let roll = 0;
    let reach = 0.3;
    if (p.sprinting) { pitch = -0.55; yaw = aimYaw - 0.5; reach = 0.16; roll = 0.4; }
    else if (p.shieldUp) { pitch = -0.75; yaw = aimYaw - 0.35; reach = 0.16; roll = 0.2; }
    else if (p.venting) { pitch = 0.55; yaw = aimYaw - 0.25; roll = -0.7; reach = 0.22; }
    const dir = this.aim.set(Math.sin(yaw) * Math.cos(pitch), Math.sin(pitch), Math.cos(yaw) * Math.cos(pitch));
    const rx = -Math.cos(aimYaw);
    const rz = Math.sin(aimYaw);
    const shoulderY = floorY + (p.sprinting ? 1.2 : 1.3) + (p.ads > 0.5 ? 0.06 : 0);
    this.grip.set(x + rx * 0.27 + dir.x * reach, shoulderY - 0.06 + dir.y * reach, z + rz * 0.27 + dir.z * reach);
    if (posing) {
      bl.position.copy(this.grip);
      this.m4.lookAt(tmpA.set(0, 0, 0), tmpB.copy(dir).negate(), UP);
      bl.quaternion.setFromRotationMatrix(this.m4);
      if (roll) bl.quaternion.multiply(tmpQ.setFromAxisAngle(tmpA.set(0, 0, 1), roll));
      bl.updateMatrixWorld(true);
      this.fore.copy(this.blaster.fore).applyMatrix4(bl.matrixWorld);
      // Right hand on the grip, elbow out and down; left hand on the shroud (on the shield's face while it is up).
      const r = this.right;
      if (r) {
        const s = r.upper.getWorldPosition(new Vector3());
        this.pole.set(rx * 0.7, -1, rz * 0.7).addScaledVector(dir, -0.2).normalize();
        solveElbow(s, this.grip, r.a, r.b, this.pole, this.elbow);
        aimBone(r.upper, r.fore, this.elbow);
        aimBone(r.fore, r.hand, this.grip);
      }
      const l = this.left;
      if (l) {
        const target = p.shieldUp
          ? tmpB.set(x + Math.sin(aimYaw) * 0.42 - rx * 0.05, floorY + 1.3, z + Math.cos(aimYaw) * 0.42 - rz * 0.05)
          : this.fore;
        const s = l.upper.getWorldPosition(new Vector3());
        this.pole.set(-rx * 0.6, -1, -rz * 0.6).normalize();
        const t = target.clone();
        solveElbow(s, t, l.a, l.b, this.pole, this.elbow);
        aimBone(l.upper, l.fore, this.elbow);
        aimBone(l.fore, l.hand, t);
      }
    } else if (p.alive && b.Hand_R) {
      // Rolling: the blaster stays in the right hand.
      b.Hand_R.getWorldPosition(bl.position);
      bl.quaternion.copy(root.quaternion);
      bl.updateMatrixWorld(true);
    }
    this.blaster.setHeat(p.heat, p.venting, p.overheated, timeS);

    this.shadow.position.set(x, floorY + 0.008, z);
    this.shadow.scale.setScalar(p.alive ? 0.95 : 1.6);
    if (deck) this.light.update(deck, x, floorY, z, dt);
  }

  /** Where the blaster's muzzle is in the world (for the flash). */
  muzzle(out: Vector3): Vector3 {
    return out.copy(this.blaster.muzzle).applyMatrix4(this.blaster.group.matrixWorld);
  }

  dispose(): void {
    this.mixer.stopAllAction();
    this.mixer.uncacheRoot(this.instance.root);
    this.blaster.dispose();
    this.shadow.geometry.dispose();
    this.shadow.material.dispose();
    disposeInstance(this.instance);
  }
}
