/**
 * The first-person viewmodel (docs/verse/realtime.md, "First-person
 * viewmodel"): the commander's own arms, and in a duel the blaster in their
 * hands, drawn in a pass of their own after the deck.
 *
 * It is a tiny scene with its own camera: the camera takes the eye camera's
 * orientation (so the room's light and reflections fall on the arms the way
 * they fall on the deck) but sits at the origin with its own near plane and
 * field of view, and the pass clears depth before it draws, so the arms never
 * sink into a wall and never stretch with a wide field-of-view setting.
 *
 * Both arms and the blaster are one skinned mesh under one palette material
 * (`rigMesh.ts`): one draw call, plus the sight's reticle and the muzzle
 * flash in a duel.
 *
 * The rig is posed in the camera's space every frame (x right, y up, −z ahead):
 * on the deck both hands hang loose low in the frame and swing with the walk;
 * in a duel the right hand holds the blaster's grip with the index finger on
 * the trigger and the left clamps its shroud, blended between hip (low on the
 * right, the centre of the screen clear), sights (the sight's window moves
 * onto the eye line), sprint (lowered and canted, still in view), shield (the
 * left forearm comes up with its emitter lit, the blaster lowered) and vent
 * (the blaster tips up, the left hand slaps the receiver). Walk bob, idle
 * sway, look lag and recoil (`motion.ts`) ride on top; a shot also flashes at
 * the muzzle and lights the hands. The frame path allocates nothing.
 */
import {
  AdditiveBlending, Bone, CanvasTexture, Color, DirectionalLight, Euler, Group, Matrix4, Mesh, MeshBasicMaterial, MeshStandardMaterial,
  PerspectiveCamera, PointLight, Quaternion, Scene, Sprite, SpriteMaterial, Vector3, type SkinnedMesh, type Texture,
} from "three";
import type { Deck } from "../content/deck";
import { RoomLight } from "../actors/roomLight";
import type { PlayerView } from "../combat/view";
import { buildBlaster, type Blaster } from "../duel/blaster";
import { radialTexture } from "../duel/effects";
import { verticalFov } from "../engine/realtime/shoulderRig";
import { copyHand, handPose, lerpHand, ViewArm, type ArmSlots, type HandPose } from "./arms";
import { turnBetween, ViewmodelMotion, type Visibility } from "./motion";
import { chamferBox, RigBuilder, RigPalette, type Slot } from "./rigMesh";

/** A pose of the blaster (its grip, the right hand's hold) in the camera's space. */
export interface GunPose { x: number; y: number; z: number; pitch: number; yaw: number; roll: number }

/**
 * The viewmodel's layout. Plain mutable data so a QA run can tune it live
 * (`window.__verseViewmodel` in development builds, then `retune()`).
 */
export const VIEWMODEL = {
  /** Horizontal field of view of the viewmodel camera, degrees (fixed: the arms keep their shape whatever the person's setting). */
  hfovDeg: 88,
  /** ... and while aiming down the sights (the sight comes a little closer). */
  adsHfovDeg: 76,
  near: 0.01,
  far: 4,
  /** The blaster's size in the hands, relative to the duel's model. */
  gunScale: 0.6,
  /** Distance from the eye to the sight's window when aiming down the sights, metres. */
  adsDistance: 0.3,
  /** Time constant of the pose blends (sprint, shield, vent), seconds. */
  blendS: 0.075,
  /** How long a muzzle flash shows, seconds. */
  flashS: 0.07,
  /** Reflection strength of the deck's environment on the arms and blaster, and the share of the blaster's glow kept. */
  envGain: 0.6,
  glowGain: 0.08,
  /**
   * A soft key light over the shoulder (in the view's frame, so the arms always read): divided by the deck's
   * exposure, it lights the arms the same on every deck.
   */
  fill: 1.2,
  /**
   * The blaster at the hip (low on the right, the muzzle toward the crosshair, the centre clear), lowered and canted
   * in a sprint (still in view), lowered behind the shield, rolled over to vent, dropped when knocked out.
   */
  hip: { x: 0.155, y: -0.115, z: -0.46, pitch: 0.08, yaw: 0.07, roll: 0.1 } as GunPose,
  sprint: { x: 0.15, y: -0.135, z: -0.36, pitch: -0.12, yaw: 0.62, roll: 0.62 } as GunPose,
  shield: { x: 0.2, y: -0.22, z: -0.32, pitch: -0.45, yaw: 0.3, roll: 0.35 } as GunPose,
  vent: { x: 0.12, y: -0.12, z: -0.34, pitch: 0.25, yaw: 0.2, roll: -0.4 } as GunPose,
  down: { x: 0.16, y: -0.7, z: -0.25, pitch: -0.9, yaw: 0.3, roll: 0.3 } as GunPose,
  /** The left wrist with the shield up, camera space. */
  shieldWrist: { x: -0.13, y: -0.07, z: -0.42 },
  /** The wrists on the deck (the left mirrors x), camera space. */
  deckWrist: { x: 0.2, y: -0.2, z: -0.42 },
  /**
   * Shoulders, below and behind the eyes, and the elbows' pull (down and out). The support arm's shoulder sits in
   * toward the middle and low, so its forearm comes up from the bottom edge to the shroud instead of across the screen.
   */
  shoulderR: new Vector3(0.22, -0.38, -0.02),
  shoulderL: new Vector3(-0.02, -0.52, 0.06),
  poleR: new Vector3(1, -0.6, 0.1),
  poleL: new Vector3(-0.4, -1, 0.2),
  /**
   * The hands: the right hand's hold on the grip (along the grip, along the knuckles, out to the side), the left's
   * beside the shroud (out to its left, up, ahead), hand frames as knuckle and back-of-hand directions, and the hand
   * poses (`HandPose`: three fingers, the index finger, the thumb).
   */
  hands: {
    grip: [-0.03, -0.075, 0.036],
    /** The right hand on the grip: three fingers wrapped, the index finger straight along the guard onto the trigger, the thumb over the far side. */
    gripPose: handPose(1.5, 1.4, 0.75, [0, 1.5], 0.15),
    fore: [0.042, 0.012, -0.06],
    foreKnuckles: [-0.15, 0.25, 1],
    foreBack: [1, -0.15, 0],
    /** The left hand under the shroud: fingers curled round it, the thumb along its top. */
    forePose: handPose(1.25, 1.0, 0.35, [1.1, 0.9], -0.2),
    ventKnuckles: [0, 0.35, 1],
    ventBack: [1, 0.1, 0],
    /** The open hand slapping the receiver, and raised palm forward behind the shield. */
    ventPose: handPose(0.35, 0.3, 0.1, [0.3, 0.25], -0.3),
    shieldPose: handPose(0.15, 0.1, 0.2, [0.1, 0.05], -0.4),
    deckKnuckles: [-0.35, 0.25, -1],
    deckBack: [0.35, 1, 0.1],
    /** Relaxed hands: the index a little straighter than the rest, the thumb resting along it. */
    deckPose: handPose(1.3, 1.15, 0.6, [1.05, 0.95], 0),
    shieldKnuckles: [0.15, 1, -0.2],
    shieldBack: [0.2, 0.15, 1],
  },
};

/** The trigger blade, in the blaster model's own (unscaled) frame: in front of the grip, under the receiver. */
const TRIGGER = { x: 0, y: -0.049, z: 0.04, rx: 0.3 };

const SHOULDER_R = new Vector3();
const SHOULDER_L = new Vector3();
const POLE_R = new Vector3();
const POLE_L = new Vector3();

/** The person's colours for the arms: the uniform's cloth and trim (CSS colours). */
export interface ArmColours {
  uniform: string;
  trim: string;
}

export interface ViewmodelFrame {
  visibility: Visibility;
  /** The duel's local player, or null on the deck. */
  player: PlayerView | null;
  /** Ground speed, metres per second, and the walk speed the bob is measured against. */
  speed: number;
  walkSpeed: number;
  /** Where the body stands (for the room's light), world metres. */
  x: number;
  y: number;
  z: number;
  /** The deck on screen (its room probes light the arms). */
  deck: Deck | null;
  reduced: boolean;
  /** The duel's clock is stopped (paused): the arms hold still. */
  frozen: boolean;
}

function lerpPose(out: GunPose, to: GunPose, t: number): void {
  if (t <= 0) return;
  out.x += (to.x - out.x) * t;
  out.y += (to.y - out.y) * t;
  out.z += (to.z - out.z) * t;
  out.pitch += (to.pitch - out.pitch) * t;
  out.yaw += (to.yaw - out.yaw) * t;
  out.roll += (to.roll - out.roll) * t;
}

function reticleTexture(): Texture {
  const size = 64;
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext("2d");
  if (ctx) {
    ctx.strokeStyle = "rgba(255,255,255,0.85)";
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.arc(size / 2, size / 2, size * 0.3, 0, Math.PI * 2);
    ctx.stroke();
    ctx.fillStyle = "rgba(255,255,255,1)";
    ctx.beginPath();
    ctx.arc(size / 2, size / 2, size * 0.055, 0, Math.PI * 2);
    ctx.fill();
  }
  return new CanvasTexture(canvas);
}

/** A glowing surface of the blaster mirrored into the palette each frame. */
interface Glow { slot: Slot; material: MeshStandardMaterial }

export class Viewmodel {
  readonly scene = new Scene();
  readonly camera: PerspectiveCamera;
  /** Draw the pass this frame (set by `prepare`). */
  visible = false;
  /** Both arms and the blaster: one skinned mesh. */
  readonly mesh: SkinnedMesh;
  private readonly rig = new Group();
  private readonly right: ViewArm;
  private readonly left: ViewArm;
  private readonly blaster: Blaster;
  private readonly gun = new Group();
  /** The blaster's bone (inside its scaled group): collapsed to a point when the hands are empty. */
  private readonly gunBone = new Bone();
  /** A landmark on the trigger, in the blaster's frame. */
  readonly trigger = new Group();
  private readonly palette = new RigPalette("M_View_Rig");
  private readonly slots: ArmSlots;
  private readonly glows: Glow[] = [];
  private readonly reticle: MeshBasicMaterial;
  private readonly flash: Sprite;
  private readonly flashLight = new PointLight(0xffa040, 0, 1.2, 2);
  private readonly key = new DirectionalLight(0xfff2e0, 0);
  private readonly light = new RoomLight();
  private readonly motion = new ViewmodelMotion();
  private readonly textures: Texture[] = [];
  private readonly emitterColour = new Color(0.35, 0.75, 1.6);
  private readonly tmpColour = new Color();
  private frame: ViewmodelFrame | null = null;
  private shots = 0;
  private flashT = 0;
  private time = 0;
  private ventT = 0;
  private readonly w = { sprint: 0, shield: 0, vent: 0, down: 0 };
  private primed = false;
  private prevYaw = 0;
  private prevPitch = 0;
  // Scratch, reused every frame.
  private readonly pose: GunPose = { ...VIEWMODEL.hip };
  private readonly ads: GunPose = { ...VIEWMODEL.hip };
  private readonly handL: HandPose = handPose(0, 0, 0);
  private readonly euler = new Euler(0, 0, 0, "YXZ");
  private readonly qGun = new Quaternion();
  private readonly qTmp = new Quaternion();
  private readonly qBase = new Quaternion().setFromAxisAngle(new Vector3(0, 1, 0), Math.PI);
  private readonly qHandR = new Quaternion();
  private readonly qHandL = new Quaternion();
  private readonly qDeckR = new Quaternion();
  private readonly qDeckL = new Quaternion();
  private readonly qShieldL = new Quaternion();
  private readonly wristR = new Vector3();
  private readonly wristL = new Vector3();
  private readonly v = new Vector3();
  private readonly dir = new Vector3();
  /** The hands' holds in the blaster's frame: wrist points and hand frames. */
  private readonly holdR = { at: new Vector3(), q: new Quaternion() };
  private readonly holdL = { at: new Vector3(), q: new Quaternion() };
  private readonly ventL = { at: new Vector3(), q: new Quaternion() };
  /** The emitter strip's glow this frame (for checks). */
  emitterGlow = 0;

  constructor(colours: ArmColours, accent: Color) {
    this.camera = new PerspectiveCamera(60, 1, VIEWMODEL.near, VIEWMODEL.far);
    this.scene.name = "Viewmodel";
    const pal = this.palette;
    this.slots = {
      sleeve: pal.slot("sleeve"), trim: pal.slot("trim"), glove: pal.slot("glove"), housing: pal.slot("housing"), emitter: pal.slot("emitter"),
    };
    pal.surface(this.slots.glove, new Color(0x2b2c31), 0.46, 0.05);
    pal.surface(this.slots.housing, new Color(0x2a2e34), 0.35, 0.85);
    pal.surface(this.slots.emitter, new Color(0x050505), 0.4, 0);
    this.setColours(colours);

    const rig = new RigBuilder();
    this.right = new ViewArm("right", rig, this.slots);
    this.left = new ViewArm("left", rig, this.slots);

    // The blaster: the duel's model (chamfered for the close view). Its parts are baked into the rig on the gun's
    // bone; the stock stays out (it would hide the right hand); the sight's pane becomes a see-through reticle.
    this.blaster = buildBlaster(accent, { bevel: true });
    const bg = this.blaster.group;
    bg.updateMatrixWorld(true);
    const baked: Mesh[] = [];
    bg.traverse((o) => {
      const m = o as Mesh;
      if (!m.isMesh || m === this.blaster.sightGlass) return;
      baked.push(m);
      if (this.blaster.stock.includes(m)) return;
      const mat = m.material as MeshStandardMaterial;
      const slot = pal.slot(mat.name);
      pal.surface(slot, mat.color, mat.roughness, mat.metalness);
      if (mat.emissiveIntensity > 0 && mat.emissive.getHex() !== 0) {
        if (!this.glows.some((g) => g.slot === slot)) this.glows.push({ slot, material: mat });
      }
      rig.add(m.geometry.clone(), this.gunBone, slot, m.matrixWorld.clone());
    });
    for (const m of baked) m.removeFromParent();
    // The trigger (the duel's model has none: from metres away it never shows).
    const steel = pal.slot("M_Blaster_Steel");
    const s = this.blasterScale();
    rig.add(chamferBox(0.006, 0.018, 0.007, 0.002), this.gunBone, steel, new Matrix4().makeScale(s, s, s)
      .multiply(new Matrix4().makeTranslation(TRIGGER.x, TRIGGER.y, TRIGGER.z)).multiply(new Matrix4().makeRotationX(TRIGGER.rx)));
    this.trigger.position.set(TRIGGER.x, TRIGGER.y - 0.004, TRIGGER.z + 0.002).multiplyScalar(s);
    bg.add(this.gunBone, this.trigger);

    const reticleMap = reticleTexture();
    this.textures.push(reticleMap);
    this.reticle = new MeshBasicMaterial({
      map: reticleMap, color: new Color(1.6, 0.85, 0.25), transparent: true, blending: AdditiveBlending, depthWrite: false,
    });
    this.blaster.sightGlass.material = this.reticle;
    this.gun.add(bg);
    // The muzzle flash: a short additive burst at the muzzle, and the light it throws on the hands.
    const flashMap = radialTexture([[0, "rgba(255,255,255,1)"], [0.25, "rgba(255,190,90,0.9)"], [1, "rgba(255,120,30,0)"]]);
    this.textures.push(flashMap);
    this.flash = new Sprite(new SpriteMaterial({ map: flashMap, color: new Color(2.4, 1.5, 0.6), blending: AdditiveBlending, depthWrite: false, transparent: true }));
    this.flash.scale.setScalar(0.11);
    this.flash.visible = false;
    bg.add(this.flash);
    this.flash.position.copy(this.blaster.muzzle).setZ(this.blaster.muzzle.z + 0.04);
    bg.add(this.flashLight);
    this.flashLight.position.copy(this.blaster.muzzle);

    this.rig.add(this.right.group, this.left.group, this.gun, this.key, this.key.target);
    this.key.position.set(-0.4, 1, 0.5);
    this.mesh = rig.build(pal.material);
    // The mesh stays at the origin: its vertices follow the bones in the rig.
    this.scene.add(this.rig, this.mesh);
    this.rig.traverse((o) => { o.frustumCulled = false; });
    this.light.attach([pal.material]);
    this.retune();
  }

  /** The blaster model's own scale (the duel draws it a little larger than true size): its muzzle over its unscaled one. */
  private blasterScale(): number {
    return this.blaster.muzzle.z / 0.49;
  }

  /** The person's colours changed (a promotion): repaint the sleeves. */
  setColours(colours: ArmColours): void {
    this.palette.surface(this.slots.sleeve, this.tmpColour.set(colours.uniform), 0.78, 0);
    this.palette.surface(this.slots.trim, this.tmpColour.set(colours.trim), 0.55, 0.2);
  }

  /** This frame's state (the layer fills it before the eye view renders). */
  set(frame: ViewmodelFrame): void {
    this.frame = frame;
  }

  /** A shot left the blaster (the duel counts them): kick and flash. */
  shot(count: number, ads: boolean): void {
    if (count === this.shots) return;
    const fresh = count > this.shots && this.primed;
    this.shots = count;
    if (!fresh) return;
    this.motion.fire(ads ? 0.75 : 1);
    this.flashT = VIEWMODEL.flashS;
    this.flash.material.rotation = Math.random() * Math.PI * 2;
  }

  /** Apply VIEWMODEL's layout: the blaster's size, the shoulders, the hands' holds on the blaster (in its frame). */
  retune(): void {
    const s = VIEWMODEL.gunScale;
    this.blaster.group.scale.setScalar(s);
    SHOULDER_R.copy(VIEWMODEL.shoulderR);
    SHOULDER_L.copy(VIEWMODEL.shoulderL);
    POLE_R.copy(VIEWMODEL.poleR).normalize();
    POLE_L.copy(VIEWMODEL.poleL).normalize();
    // Right hand: the grip's axis runs up and back (the grip rakes 0.28 rad); the back of the hand faces the
    // blaster's right (−X), the knuckles wrap the grip's front and the fingers curl round to its left side.
    const up = new Vector3(0, Math.cos(0.28), -Math.sin(0.28));
    const backR = new Vector3(-1, 0, 0);
    const knR = new Vector3().crossVectors(up, backR);
    const h = VIEWMODEL.hands;
    const vec = (a: readonly number[]) => new Vector3(a[0], a[1], a[2]);
    const grip = new Vector3(0, -0.06, -0.01).multiplyScalar(this.blasterScale() * s);
    this.holdR.at.copy(grip).addScaledVector(up, h.grip[0]).addScaledVector(knR, h.grip[1]).addScaledVector(backR, h.grip[2]);
    ViewArm.handFrame(knR, backR, this.holdR.q);
    // Left hand: a clamp on the shroud from its left, the thumb over the top, the knuckles along the barrel, the back
    // of the hand outward; the fingers curl in under the shroud.
    const fore = this.blaster.fore.clone().multiplyScalar(s);
    const knL = vec(h.foreKnuckles).normalize();
    const backL = vec(h.foreBack).normalize();
    this.holdL.at.set(fore.x + h.fore[0], fore.y + h.fore[1], fore.z + h.fore[2]).addScaledVector(knL, -0.05);
    ViewArm.handFrame(knL, backL, this.holdL.q);
    // Venting: the left hand leaves the shroud and slaps the receiver's side, palm flat against it.
    const vents = new Vector3(0.05, 0.02, 0.12).multiplyScalar(this.blasterScale() * s);
    const knV = vec(h.ventKnuckles).normalize();
    const backV = vec(h.ventBack).normalize();
    this.ventL.at.copy(vents).addScaledVector(backV, 0.018).addScaledVector(knV, -0.05);
    ViewArm.handFrame(knV, backV, this.ventL.q);
    // On the deck: relaxed hands, knuckles ahead, the backs of the hands up and out (the left mirrors the right).
    const dk = vec(h.deckKnuckles);
    const db = vec(h.deckBack);
    ViewArm.handFrame(dk, db, this.qDeckR);
    ViewArm.handFrame(dk.setX(-dk.x), db.setX(-db.x), this.qDeckL);
    // Shield up: the left forearm vertical before the face's left, the palm forward, the back of the hand (and the
    // emitter on the forearm's back) toward the eyes.
    ViewArm.handFrame(vec(h.shieldKnuckles), vec(h.shieldBack), this.qShieldL);
    // The aiming pose: the sight's window on the eye line at adsDistance.
    const sight = this.blaster.sight.clone().multiplyScalar(s).applyQuaternion(this.qBase);
    this.ads.x = -sight.x;
    this.ads.y = -sight.y;
    this.ads.z = -VIEWMODEL.adsDistance - sight.z;
    this.ads.pitch = 0;
    this.ads.yaw = 0;
    this.ads.roll = 0;
  }

  /**
   * Called by the eye view once its camera is placed for the frame: follow
   * its orientation, step the motion, pose the rig. `dt` in seconds.
   */
  prepare(eye: PerspectiveCamera, dt: number, environment: Texture | null): void {
    const f = this.frame;
    this.visible = !!f && f.visibility.arms;
    // The view's turn since the last frame (for the look lag), from the eye camera's direction.
    eye.getWorldDirection(this.dir);
    const yaw = Math.atan2(this.dir.x, this.dir.z);
    const pitch = Math.asin(Math.max(-1, Math.min(1, this.dir.y)));
    const turn = this.primed ? turnBetween(this.prevYaw, this.prevPitch, yaw, pitch) : { yaw: 0, pitch: 0 };
    this.prevYaw = yaw;
    this.prevPitch = pitch;
    if (!f || !this.visible) {
      this.primed = false;
      this.motion.reset();
      return;
    }
    this.primed = true;
    const step = f.frozen ? 0 : Math.min(0.1, Math.max(0, dt));
    this.time += step;
    this.scene.environment = environment;
    this.camera.quaternion.copy(eye.quaternion);
    this.camera.position.set(0, 0, 0);
    const aspect = eye.aspect || 1;
    const p = f.player;
    const ads = p ? p.ads : 0;
    const hfov = VIEWMODEL.hfovDeg + (VIEWMODEL.adsHfovDeg - VIEWMODEL.hfovDeg) * ads;
    const fov = verticalFov(aspect, hfov, 30);
    if (Math.abs(this.camera.aspect - aspect) > 1e-4 || Math.abs(this.camera.fov - fov) > 1e-3) {
      this.camera.aspect = aspect;
      this.camera.fov = fov;
      this.camera.updateProjectionMatrix();
    }
    this.camera.updateMatrixWorld();
    this.rig.quaternion.copy(eye.quaternion);
    this.rig.updateMatrixWorld();

    const o = this.motion.step({
      dt: step, speed: f.speed, walkSpeed: f.walkSpeed, turnYaw: step ? turn.yaw : 0, turnPitch: step ? turn.pitch : 0, ads, reduced: f.reduced,
    });
    // Pose weights ease in and out.
    const w = this.w;
    const k = step ? 1 - Math.exp(-step / VIEWMODEL.blendS) : 0;
    const duel = f.visibility.mode === "duel" && !!p;
    w.sprint += ((p?.sprinting ? 1 : 0) - w.sprint) * k;
    w.shield += ((p?.shieldUp && p.alive ? 1 : 0) - w.shield) * k;
    w.vent += ((p?.venting && p.alive ? 1 : 0) - w.vent) * k;
    w.down += ((p && !p.alive ? 1 : 0) - w.down) * k;
    this.ventT = p?.venting ? this.ventT + step : 0;
    // The arms rise into view as the camera blends into the head; a dodge dips them.
    const raise = f.visibility.raise;
    // The deck's exposure scales everything drawn; the viewmodel's own lights are divided by it.
    const exposure = Math.pow(2, f.deck?.exposure ?? 0);
    const dip = (1 - raise) * 0.35 + (p?.dodging ? Math.sin(p.dodgeProgress * Math.PI) * 0.12 : 0);

    // Empty hands on the deck: the blaster's part of the mesh collapses to a point, its reticle and flash hide.
    this.gun.visible = duel;
    this.gunBone.scale.setScalar(duel ? 1 : 1e-5);
    if (duel && p) this.poseDuel(p, o, dip);
    else this.poseDeck(o, dip);

    // Muzzle flash and its light.
    this.flashT = Math.max(0, this.flashT - step);
    const fl = this.flashT / VIEWMODEL.flashS;
    this.flash.visible = duel && fl > 0;
    this.flash.scale.setScalar(0.1 + 0.14 * fl);
    this.flashLight.intensity = duel ? (fl * 1.6) / exposure : 0;
    this.key.intensity = VIEWMODEL.fill / exposure;
    // The left forearm's emitter: dim at rest, bright while the shield is up.
    this.emitterGlow = 0.5 + w.shield * (4 + (p ? p.shieldEnergy * 4 : 0)) + (p?.parrying ? 6 : 0);
    this.palette.emit(this.slots.emitter, this.emitterColour, this.emitterGlow);
    if (duel && p) {
      // The duel model's heat drives its materials; their glow goes into the palette, toned down: a hand's breadth
      // from the eye the glow tuned to read at shoulder distance would flood the bloom.
      this.blaster.setHeat(p.heat, p.venting, p.overheated, this.time);
      for (const g of this.glows) this.palette.emit(g.slot, g.material.emissive, g.material.emissiveIntensity * VIEWMODEL.glowGain);
    }
    // The room's reflections: the deck's environment is captured in the open room, the hands are in the body's shade.
    this.palette.material.envMapIntensity = VIEWMODEL.envGain;
    if (f.deck) this.light.update(f.deck, f.x, f.y, f.z, step);
  }

  private poseDuel(p: PlayerView, o: { x: number; y: number; z: number; pitch: number; yaw: number; roll: number }, dip: number): void {
    const w = this.w;
    const pose = this.pose;
    Object.assign(pose, VIEWMODEL.hip);
    lerpPose(pose, this.ads, p.ads);
    lerpPose(pose, VIEWMODEL.sprint, w.sprint);
    lerpPose(pose, VIEWMODEL.shield, w.shield);
    // Venting tips the blaster up; knocked out, it drops away.
    lerpPose(pose, VIEWMODEL.vent, w.vent);
    lerpPose(pose, VIEWMODEL.down, w.down);
    pose.x += o.x;
    pose.y += o.y - dip;
    pose.z += o.z;
    this.euler.set(pose.pitch + o.pitch, pose.yaw + o.yaw, pose.roll + o.roll, "YXZ");
    this.qGun.setFromEuler(this.euler).multiply(this.qBase);
    this.gun.position.set(pose.x, pose.y, pose.z);
    this.gun.quaternion.copy(this.qGun);
    this.gun.updateMatrixWorld();

    // Right hand on the grip, the index finger on the trigger.
    this.wristR.copy(this.holdR.at).applyQuaternion(this.qGun).add(this.gun.position);
    this.qHandR.copy(this.qGun).multiply(this.holdR.q);
    const h = VIEWMODEL.hands;
    this.right.curl(h.gripPose);
    this.right.pose(SHOULDER_R, this.wristR, this.qHandR, POLE_R);

    // Left hand: on the shroud, against the receiver while venting, up before the face behind the shield.
    this.wristL.copy(this.holdL.at).applyQuaternion(this.qGun).add(this.gun.position);
    this.qHandL.copy(this.qGun).multiply(this.holdL.q);
    const hand = copyHand(this.handL, h.forePose);
    if (w.vent > 1e-3) {
      // A slap: the hand swings out and in against the receiver in the first quarter second, then rests there.
      const t = Math.min(1, this.ventT / 0.2);
      const swing = Math.sin(t * Math.PI) * 0.06;
      this.v.copy(this.ventL.at).setX(this.ventL.at.x + swing).applyQuaternion(this.qGun).add(this.gun.position);
      this.wristL.lerp(this.v, w.vent);
      this.qTmp.copy(this.qGun).multiply(this.ventL.q);
      this.qHandL.slerp(this.qTmp, w.vent);
      lerpHand(hand, h.ventPose, w.vent);
    }
    if (w.shield > 1e-3) {
      const sw = VIEWMODEL.shieldWrist;
      this.v.set(sw.x + o.x, sw.y + o.y - dip, sw.z + o.z);
      this.wristL.lerp(this.v, w.shield);
      this.qHandL.slerp(this.qShieldL, w.shield);
      lerpHand(hand, h.shieldPose, w.shield);
    }
    if (w.down > 1e-3) this.wristL.y -= w.down * 0.5;
    this.left.curl(hand);
    this.left.pose(SHOULDER_L, this.wristL, this.qHandL, POLE_L);
  }

  private poseDeck(o: { x: number; y: number; z: number; pitch: number; yaw: number; roll: number }, dip: number): void {
    // Loose hands low in the frame; while walking they swing against each other with the stride.
    const swing = Math.sin(this.motion.phase) * 0.05 * Math.min(1, this.motion.bob);
    const c = VIEWMODEL.hands.deckPose;
    this.right.curl(c);
    this.left.curl(c);
    const d = VIEWMODEL.deckWrist;
    // The deck's arms hang from the shoulders' usual place (the duel's support shoulder sits in for the hold).
    this.v.set(-VIEWMODEL.shoulderR.x, VIEWMODEL.shoulderR.y, VIEWMODEL.shoulderR.z);
    this.wristR.set(d.x + o.x, d.y + o.y - dip + Math.abs(swing) * 0.2, d.z + o.z - swing);
    this.wristL.set(-d.x + o.x, d.y + o.y - dip + Math.abs(swing) * 0.2, d.z + o.z + swing);
    this.right.pose(SHOULDER_R, this.wristR, this.qDeckR, POLE_R);
    this.left.pose(this.v, this.wristL, this.qDeckL, DECK_POLE_L.set(-POLE_R.x, POLE_R.y, POLE_R.z));
  }

  dispose(): void {
    this.mesh.geometry.dispose();
    this.mesh.skeleton.dispose();
    this.palette.dispose();
    this.blaster.dispose();
    for (const m of [this.reticle, this.flash.material]) m.dispose();
    for (const t of this.textures) t.dispose();
  }
}

const DECK_POLE_L = new Vector3();
