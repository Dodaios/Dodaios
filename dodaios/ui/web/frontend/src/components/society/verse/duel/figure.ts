/**
 * A duellist's body: a character from the library (the commander's skin for
 * the person, the trooper for the bot) with the blaster in its hands, posed
 * every frame from the combat view.
 *
 * The duel clip set (`A_Combat_*`, authored in the character pipeline) drives
 * the body through `FighterAnimator`: a bladed rifle stance, eight-way
 * locomotion with planted feet, step-turns, the dodge roll, flinches, the
 * stagger, the knockout fall and the get-up. On top of the clips, every frame:
 *
 * - the aim offset turns spine and chest toward the aim (pitch and yaw), the
 *   head follows the aim or, for the bot, the opponent;
 * - the blaster sits with its stock in the right shoulder pocket (read from
 *   the chest bone, so it moves with every flinch and lean) along the aim:
 *   raised to the eye in the sights, carried low across the chest sprinting,
 *   lowered by the hip behind the shield, tipped while venting, low behind
 *   cover, kicked back by a recoil spring per shot;
 * - both hands go to it by two-bone IK, calibrated against `A_Combat_Idle`
 *   frame 0 (where the blaster is level and straight ahead), so the grip and
 *   the hand rotations match the authored hold; the shield raises the left
 *   forearm with its emitter in front of the chest and shoves on a parry; a
 *   vent racks the receiver with the left hand;
 * - while a one-shot owns the body (roll, fall, get-up) the blaster rides in
 *   the right hand instead.
 */
import {
  AdditiveAnimationBlendMode, AnimationClip, AnimationMixer, AnimationUtils, Color, Group, LoopRepeat, Matrix4, Mesh,
  MeshBasicMaterial, PlaneGeometry, Quaternion, Vector3,
  type AnimationAction, type Bone, type Material, type MeshStandardMaterial, type Object3D, type Texture,
} from "three";
import type { Deck } from "../content/deck";
import { disposeInstance, type CharacterInstance } from "../actors/characters";
import { RoomLight } from "../actors/roomLight";
import { CloakRig } from "../actors/cloak";
import type { BotPresentation } from "../combat/bot/brain";
import type { CombatEvent } from "../combat/types";
import type { PlayerView } from "../combat/view";
import { buildBlaster, type Blaster } from "./blaster";
import { ADDITIVE_CLIPS, DUEL_CLIPS, FighterAnimator, locoClips, type ClipTable, type FighterFrame } from "./fighterAnim";

const UP = new Vector3(0, 1, 0);
/** Stock butt to grip along the barrel, metres (the blaster's stock, for a 1.78 m body). */
const STOCK = 0.29;

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
export function aimBone(bone: Object3D, child: Object3D, target: Vector3): void {
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
function turnBone(bone: Object3D | undefined, axis: Vector3, angle: number): void {
  if (!bone || Math.abs(angle) < 1e-5) return;
  const parentInv = bone.parent ? bone.parent.getWorldQuaternion(tmpP).invert() : tmpP.identity();
  const local = tmpA.copy(axis).applyQuaternion(parentInv).normalize();
  bone.quaternion.premultiply(tmpQ.setFromAxisAngle(local, angle));
  bone.updateMatrixWorld(true);
}

/** Give `bone` this world rotation (its parent must be up to date). */
function setWorldQuat(bone: Object3D, q: Quaternion): void {
  const parentInv = bone.parent ? bone.parent.getWorldQuaternion(tmpP).invert() : tmpP.identity();
  bone.quaternion.copy(parentInv.multiply(q));
  bone.updateMatrixWorld(true);
}

/** Additive copies of the flinch clips, one per source clip (the library shares clips between bodies). */
const additiveCache = new WeakMap<AnimationClip, AnimationClip>();
function additiveOf(clip: AnimationClip): AnimationClip {
  let out = additiveCache.get(clip);
  if (!out) {
    out = AnimationUtils.makeClipAdditive(clip.clone(), 0);
    out.blendMode = AdditiveAnimationBlendMode;
    additiveCache.set(clip, out);
  }
  return out;
}

interface Arm { upper: Bone; fore: Bone; hand: Bone; a: number; b: number }

/** The duellists on stage; `window.__verseDuelBodies()` reads them (QA hook, every build, like `__verseDuel`). */
const LIVE_BODIES = new Set<DuelFigure>();
if (typeof window !== "undefined") {
  Object.assign(window, { __verseDuelBodies: () => [...LIVE_BODIES].map((b) => b.qa()) });
}

/** Where the hands hold the blaster, in the blaster's frame (grip at the origin, +Z the barrel). */
interface Hold {
  wristR: Vector3;
  wristL: Vector3;
  handR: Quaternion;
  handL: Quaternion;
  /** The stock's shoulder pocket in the chest bone's frame. */
  pocket: Vector3;
}

export interface FigureLook {
  /** Recolour these material names (the trooper's armour and accents). */
  tint?: Readonly<Record<string, string>>;
  /** Make these materials glow in the colour (a visor). */
  glow?: Readonly<Record<string, string>>;
  /** The blaster's cell colour. */
  accent: Color;
}

/** What the figure is told besides the fighter's own state. */
export interface FigureCues {
  /** Look here (the opponent's head), world. */
  lookAt?: Vector3 | null;
  /** Bot presentation: hiding low behind cover, or peeking out of it toward `peekSide` (+1 left, -1 right). */
  cover?: "hide" | "peek" | null;
  peekSide?: number;
}

/**
 * Hand a frame's combat event to the bodies it moves: recoil on a shot, a
 * flinch on a hit (a stagger when the bolt was one parried back at its
 * shooter), the shield shove on a parry, the fall on a knockout. `parried`
 * remembers reflected bolts across frames.
 */
export function routeFigureEvent(
  e: CombatEvent, players: readonly PlayerView[], figureFor: (slot: number) => DuelFigure | null, parried: Set<number>,
): void {
  const at = (slot: number) => players.find((p) => p.slot === slot);
  switch (e.type) {
    case "shot":
      figureFor(e.player)?.anim.shot(e.ads);
      break;
    case "parry":
      parried.add(e.bolt);
      if (parried.size > 64) parried.delete(parried.values().next().value as number);
      figureFor(e.player)?.anim.parried();
      break;
    case "hit": {
      const p = at(e.target);
      if (p) figureFor(e.target)?.anim.hit(p.x, p.z, e.fromX, e.fromZ, e.headshot, parried.has(e.bolt));
      break;
    }
    case "death": {
      const p = at(e.player);
      const k = at(e.killer);
      if (p) figureFor(e.player)?.anim.knockedOut(p.x, p.z, k?.x ?? p.x, k?.z ?? p.z);
      break;
    }
    case "round_start":
      parried.clear();
      break;
    default:
      break;
  }
}

/**
 * The bot body's cues from its presentation: hiding or peeking, the peek's
 * side relative to its aim (+1 left), and the opponent's head to look at.
 */
export function botCues(pres: BotPresentation | null, bot: PlayerView, foe: PlayerView | undefined, floorY: number, out: FigureCues): FigureCues {
  out.cover = pres?.cover ?? null;
  out.peekSide = 0;
  if (pres?.cover === "peek" && pres.spot && pres.peek) {
    const left = (pres.peek.x - pres.spot.x) * Math.cos(bot.aimYaw) - (pres.peek.z - pres.spot.z) * Math.sin(bot.aimYaw);
    out.peekSide = Math.abs(left) > 0.05 ? Math.sign(left) : 0;
  }
  if (foe && foe.alive) {
    out.lookAt = (out.lookAt ?? new Vector3()).set(foe.x, floorY + 1.6, foe.z);
  } else {
    out.lookAt = null;
  }
  return out;
}

export class DuelFigure {
  readonly group = new Group();
  readonly blaster: Blaster;
  readonly anim: FighterAnimator;
  /** The combat slot this body shows (set by the layer). */
  slot = -1;
  /** The last frame's animation state (QA: `window.__verseDuelBodies`). */
  lastFrame: FighterFrame | null = null;
  private readonly mixer: AnimationMixer;
  private readonly actions = new Map<string, AnimationAction>();
  /** The skin's cloak, when it has one. */
  private readonly cloak: CloakRig | null;
  private readonly light = new RoomLight();
  private readonly bones: Record<string, Bone | undefined> = {};
  private right: Arm | null = null;
  private left: Arm | null = null;
  private hold: Hold | null = null;
  private readonly scale: number;
  private readonly shadow: Mesh<PlaneGeometry, MeshBasicMaterial>;
  // Scratch, reused every frame.
  private readonly grip = new Vector3();
  private readonly dir = new Vector3();
  private readonly fwd = new Vector3();
  private readonly lft = new Vector3();
  private readonly up = new Vector3();
  private readonly pocket = new Vector3();
  private readonly elbow = new Vector3();
  private readonly pole = new Vector3();
  private readonly target = new Vector3();
  private readonly qB = new Quaternion();
  private readonly qHand = new Quaternion();
  private readonly qAttach = new Quaternion();
  private readonly pAttach = new Vector3();
  private readonly m4 = new Matrix4();
  private readonly saved: Quaternion[] = Array.from({ length: 6 }, () => new Quaternion());

  constructor(readonly instance: CharacterInstance, look: FigureLook, shadow: Texture, clipTable?: ClipTable) {
    this.mixer = new AnimationMixer(instance.root);
    this.cloak = CloakRig.find(instance.root);
    this.scale = (instance.model.height || 1.78) / 1.78;
    for (const name of ["Hips", "Spine", "Chest", "Neck", "Head", "UpperArm_R", "ForeArm_R", "Hand_R", "UpperArm_L", "ForeArm_L", "Hand_L"]) {
      const o = instance.root.getObjectByName(name) as Bone | undefined;
      if (o) this.bones[name] = o;
    }
    const names = new Set(instance.clips.keys());
    this.anim = new FighterAnimator(locoClips(clipTable, names), (n) => names.has(n));
    for (const [name, clip] of instance.clips) {
      if (!name.startsWith("A_Combat_")) continue;
      const additive = ADDITIVE_CLIPS.includes(name);
      const action = this.mixer.clipAction(additive ? additiveOf(clip) : clip);
      action.setLoop(LoopRepeat, Infinity);
      action.setEffectiveTimeScale(0);
      action.setEffectiveWeight(0);
      action.play();
      this.actions.set(name, action);
    }
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
    this.calibrate();
    LIVE_BODIES.add(this);
  }

  /** QA: where the blaster points and what the body plays. */
  qa(): { slot: number; frame: FighterFrame | null; blasterDir: number[]; grip: number[]; root: number[] } {
    const d = new Vector3(0, 0, 1).applyQuaternion(this.blaster.group.quaternion);
    const g = this.blaster.group.position;
    const r = this.instance.root.position;
    return { slot: this.slot, frame: this.lastFrame, blasterDir: [d.x, d.y, d.z], grip: [g.x, g.y, g.z], root: [r.x, r.y, r.z] };
  }

  get materials(): Material[] {
    return [...[...this.instance.materials.values()].flat(), ...this.blaster.materials];
  }

  /** The arms, and the authored hold of the idle's frame 0 (blaster level, straight ahead along +Z). */
  private calibrate(): void {
    const b = this.bones;
    const root = this.instance.root;
    root.position.set(0, 0, 0);
    root.quaternion.identity();
    const idle = this.actions.get(DUEL_CLIPS.idle);
    if (idle) { idle.time = 0; idle.setEffectiveWeight(1); this.mixer.update(0); idle.setEffectiveWeight(0); }
    root.updateMatrixWorld(true);
    const arm = (u?: Bone, f?: Bone, h?: Bone): Arm | null => {
      if (!u || !f || !h) return null;
      const a = u.getWorldPosition(new Vector3()).distanceTo(f.getWorldPosition(new Vector3()));
      const c = f.getWorldPosition(new Vector3()).distanceTo(h.getWorldPosition(new Vector3()));
      return a > 0.05 && c > 0.05 ? { upper: u, fore: f, hand: h, a, b: c } : null;
    };
    this.right = arm(b.UpperArm_R, b.ForeArm_R, b.Hand_R);
    this.left = arm(b.UpperArm_L, b.ForeArm_L, b.Hand_L);
    if (!idle || !b.Hand_R || !b.Hand_L || !b.Chest) return;
    const s = this.scale;
    const wristR = b.Hand_R.getWorldPosition(new Vector3());
    const wristL = b.Hand_L.getWorldPosition(new Vector3());
    // The grip is ahead of and below the right wrist (anim_combat.py: WRIST_BACK, WRIST_UP).
    const grip = wristR.clone().add(new Vector3(0, -0.03 * s, 0.06 * s));
    const pocketWorld = grip.clone().add(new Vector3(0, 0, -STOCK * s));
    this.hold = {
      wristR: wristR.clone().sub(grip),
      wristL: wristL.clone().sub(grip),
      handR: b.Hand_R.getWorldQuaternion(new Quaternion()),
      handL: b.Hand_L.getWorldQuaternion(new Quaternion()),
      pocket: pocketWorld.applyMatrix4(b.Chest.matrixWorld.clone().invert()),
    };
  }

  private applyClips(f: FighterFrame): void {
    for (const a of this.actions.values()) a.setEffectiveWeight(0);
    for (const layer of [f.base, f.additive]) {
      for (const c of layer) {
        const a = this.actions.get(c.name);
        if (!a) continue;
        a.time = Math.min(c.time, a.getClip().duration);
        a.setEffectiveWeight(c.weight);
      }
    }
    this.mixer.update(0);
  }

  /**
   * Pose the body for one frame. `floorY` is the deck floor under the arena;
   * `deck` lights the body from the room's probe.
   */
  update(dtS: number, p: PlayerView, floorY: number, deck: Deck | null, timeS: number, cues: FigureCues = {}): void {
    const dt = Math.min(0.1, Math.max(0, dtS));
    const root = this.instance.root;
    const f = this.lastFrame = this.anim.update(dt, {
      x: p.x, z: p.z, vx: p.vx, vz: p.vz, aimYaw: p.aimYaw, aimPitch: p.aimPitch, alive: p.alive,
      dodging: p.dodging, dodgeProgress: p.dodgeProgress, sprinting: p.sprinting, shieldUp: p.shieldUp, ads: p.ads,
      venting: p.venting, cover: cues.cover ?? null, peekSide: cues.peekSide ?? 0,
    });
    root.position.set(p.x, floorY, p.z);
    root.quaternion.setFromAxisAngle(UP, f.legsYaw);
    root.updateMatrixWorld(true);
    this.applyClips(f);
    root.updateMatrixWorld(true);

    const b = this.bones;
    const s = this.scale;
    const aimYaw = p.aimYaw;
    // Body axes along the aim.
    this.fwd.set(Math.sin(aimYaw), 0, Math.cos(aimYaw));
    this.lft.set(Math.cos(aimYaw), 0, -Math.sin(aimYaw));
    const legsLeft = tmpB.set(Math.cos(f.legsYaw), 0, -Math.sin(f.legsYaw));
    const legsFwd = this.up.set(Math.sin(f.legsYaw), 0, Math.cos(f.legsYaw));

    // Lean into acceleration and out of cover, then the aim offset over spine and chest; the recoil rocks the chest.
    turnBone(b.Spine, legsLeft, f.leanFwd);
    turnBone(b.Spine, legsFwd, -f.leanSide - f.peek * 0.14);
    turnBone(b.Chest, legsFwd, -f.peek * 0.12);
    turnBone(b.Spine, UP, f.twist * 0.35);
    turnBone(b.Chest, UP, f.twist * 0.45);
    turnBone(b.Spine, this.lft, -f.pitch * 0.25);
    turnBone(b.Chest, this.lft, -f.pitch * 0.35 - f.recoil * 0.05);

    // The blaster.
    const bl = this.blaster.group;
    bl.visible = p.alive || f.ik < 1;
    const hold = this.hold;
    let yaw = aimYaw;
    let pitch = p.aimPitch;
    let roll = 0;
    const blendTo = (w: number, y: number, pi: number, r: number) => {
      if (w <= 0) return;
      yaw += wrap(y - yaw) * w;
      pitch += (pi - pitch) * w;
      roll += (r - roll) * w;
    };
    blendTo(f.cover, aimYaw + 0.25, -0.55, 0.1);
    blendTo(f.sprint, f.legsYaw + 0.7, -0.6, 0.45);
    blendTo(f.shield, aimYaw - 0.35, -0.85, 0.2);
    blendTo(f.vent * (1 - f.shield), aimYaw + 0.3, 0.5, -0.75);
    pitch += 0.09 * f.recoil * (1 - f.shield);
    this.dir.set(Math.sin(yaw) * Math.cos(pitch), Math.sin(pitch), Math.cos(yaw) * Math.cos(pitch));
    if (hold && b.Chest) {
      this.pocket.copy(hold.pocket).applyMatrix4(b.Chest.matrixWorld);
    } else {
      this.pocket.set(p.x - this.lft.x * 0.15, floorY + 1.36 * s, p.z - this.lft.z * 0.15);
    }
    // Sights: up to the eye and in toward the centre line; sprint: low across the chest; shield: down by the hip.
    const inward = f.ads * 0.06 + f.sprint * 0.1 - f.shield * 0.04;
    this.pocket.addScaledVector(this.lft, inward * s);
    this.pocket.y += (f.ads * 0.07 - f.sprint * 0.12 - f.shield * 0.2 - f.cover * 0.08 - f.vent * 0.03) * s;
    this.pocket.y += Math.sin(f.phase * Math.PI * 4) * 0.02 * f.sprint;
    this.pocket.addScaledVector(this.dir, -0.05 * f.recoil * (1 - 0.4 * f.ads));
    this.grip.copy(this.pocket).addScaledVector(this.dir, STOCK * s);
    this.m4.lookAt(tmpA.set(0, 0, 0), this.target.copy(this.dir).negate(), UP);
    this.qB.setFromRotationMatrix(this.m4);
    if (roll) this.qB.multiply(tmpQ.setFromAxisAngle(tmpA.set(0, 0, 1), roll));
    // While a one-shot owns the body the blaster rides in the right hand.
    if (hold && b.Hand_R && f.ik < 1) {
      b.Hand_R.getWorldQuaternion(this.qAttach).multiply(tmpQ.copy(hold.handR).invert());
      b.Hand_R.getWorldPosition(this.pAttach).sub(tmpA.copy(hold.wristR).applyQuaternion(this.qAttach));
      this.grip.lerpVectors(this.pAttach, this.grip, f.ik);
      this.qB.slerpQuaternions(this.qAttach, this.qB, f.ik);
    }
    bl.position.copy(this.grip);
    bl.quaternion.copy(this.qB);
    bl.updateMatrixWorld(true);

    // Hands on it.
    if (hold && f.ik > 0) {
      const r = this.right;
      if (r) {
        this.target.copy(hold.wristR).applyQuaternion(this.qB).add(this.grip);
        this.pole.set(-this.lft.x * 0.8, -1, -this.lft.z * 0.8).addScaledVector(this.dir, -0.25).normalize();
        this.reach(r, this.target, this.pole, this.qHand.copy(this.qB).multiply(hold.handR), f.ik);
      }
      const l = this.left;
      if (l) {
        if (f.shield > 0.01) {
          // The shield arm: forearm up in front of the chest, palm out, the emitter facing the aim.
          const chest = b.Chest ? b.Chest.getWorldPosition(tmpA) : tmpA.set(p.x, floorY + 1.25 * s, p.z);
          const shieldAt = this.elbow.copy(chest).addScaledVector(this.fwd, (0.34 + 0.13 * f.parryPush) * s)
            .addScaledVector(this.lft, 0.06 * s).addScaledVector(UP, 0.12 * s);
          const onGun = tmpB.copy(hold.wristL).applyQuaternion(this.qB).add(this.grip);
          this.target.lerpVectors(onGun, shieldAt, f.shield);
          tmpQ2.setFromAxisAngle(UP, aimYaw).multiply(tmpQ.setFromAxisAngle(tmpA.set(1, 0, 0), -Math.PI / 2))
            .multiply(tmpP.setFromAxisAngle(tmpB.set(0, 0, 1), Math.PI));
          this.qHand.copy(this.qB).multiply(hold.handL).slerp(tmpQ2.multiply(hold.handL), f.shield);
        } else {
          // A vent racks the receiver: reach to its left side, pull back, return.
          const v = f.vent;
          const k = f.ventPull;
          const reach = Math.min(1, k / 0.3);
          const pull = k < 0.3 ? 0 : k < 0.7 ? (k - 0.3) / 0.4 : 1 - (k - 0.7) / 0.3;
          const side = tmpB.set(0.07 * s, 0.03 * s, (0.1 - 0.07 * pull) * s);
          this.target.copy(hold.wristL).lerp(side, v * reach).applyQuaternion(this.qB).add(this.grip);
          this.qHand.copy(this.qB).multiply(hold.handL);
        }
        this.pole.set(this.lft.x * 0.6, -1, this.lft.z * 0.6).normalize();
        this.reach(l, this.target, this.pole, this.qHand, f.ik);
      }
    }

    // Head: toward what it looks at (the opponent, else the aim); in the sights it settles on the stock.
    if (f.ik > 0 && b.Head) {
      const head = b.Head.getWorldPosition(tmpA);
      let lookYaw = aimYaw;
      let lookPitch = p.aimPitch;
      if (cues.lookAt) {
        const dx = cues.lookAt.x - head.x;
        const dz = cues.lookAt.z - head.z;
        lookYaw = Math.atan2(dx, dz);
        lookPitch = Math.atan2(cues.lookAt.y - head.y, Math.hypot(dx, dz) || 1);
      }
      const yawRem = Math.max(-1.1, Math.min(1.1, wrap(lookYaw - f.legsYaw - f.twist * 0.8))) * f.ik;
      const pitchRem = Math.max(-0.7, Math.min(0.7, lookPitch - f.pitch * 0.6)) * f.ik;
      turnBone(b.Neck, UP, yawRem * 0.4);
      turnBone(b.Head, UP, yawRem * 0.6);
      const headLeft = tmpB.set(Math.cos(lookYaw), 0, -Math.sin(lookYaw));
      turnBone(b.Neck, headLeft, -pitchRem * 0.35);
      turnBone(b.Head, headLeft, -pitchRem * 0.65 + f.ads * 0.08);
      turnBone(b.Head, this.fwd, f.ads * 0.16);
    }
    this.blaster.setHeat(p.heat, p.venting, p.overheated, timeS);

    if (p.alive && f.ik > 0.5) this.cloak?.update(dt, p.x, p.z, f.legsYaw);
    this.shadow.position.set(p.x, floorY + 0.008, p.z);
    this.shadow.scale.setScalar(p.alive ? 0.95 : 1.6);
    if (deck) this.light.update(deck, p.x, floorY, p.z, dt);
  }

  /** Two-bone IK of one arm to a wrist target with a hand rotation, blended with the clip's pose by `w`. */
  private reach(arm: Arm, target: Vector3, pole: Vector3, handQ: Quaternion, w: number): void {
    const saved = this.saved;
    if (w < 1) { saved[0].copy(arm.upper.quaternion); saved[1].copy(arm.fore.quaternion); saved[2].copy(arm.hand.quaternion); }
    const s = arm.upper.getWorldPosition(new Vector3());
    solveElbow(s, target, arm.a, arm.b, pole, this.elbow);
    aimBone(arm.upper, arm.fore, this.elbow);
    aimBone(arm.fore, arm.hand, target);
    setWorldQuat(arm.hand, handQ);
    if (w < 1) {
      arm.upper.quaternion.slerpQuaternions(saved[0], arm.upper.quaternion, w);
      arm.fore.quaternion.slerpQuaternions(saved[1], arm.fore.quaternion, w);
      arm.hand.quaternion.slerpQuaternions(saved[2], arm.hand.quaternion, w);
      arm.upper.updateMatrixWorld(true);
    }
  }

  /** Where the blaster's muzzle is in the world (for the flash). */
  muzzle(out: Vector3): Vector3 {
    return out.copy(this.blaster.muzzle).applyMatrix4(this.blaster.group.matrixWorld);
  }

  dispose(): void {
    LIVE_BODIES.delete(this);
    this.mixer.stopAllAction();
    this.mixer.uncacheRoot(this.instance.root);
    this.blaster.dispose();
    this.shadow.geometry.dispose();
    this.shadow.material.dispose();
    disposeInstance(this.instance);
  }
}
