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
 * The arms are the commander's own, cut from their body (`armMesh.ts`): one
 * skinned mesh under one material with the body's painted atlas, its sleeves
 * in the rank tier's uniform, its real skin weights bending elbows, wrists and
 * knuckles. They arrive once the body has loaded (`attachArms`); until then
 * only the blaster shows. The blaster and the shield emitter on the left
 * forearm are a second skinned mesh under a palette material (`rigMesh.ts`).
 * Two draws on the deck; four in a duel with the sight's reticle and the
 * muzzle flash.
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
  AdditiveBlending, Bone, BufferAttribute, CanvasTexture, Color, CylinderGeometry, DirectionalLight, DoubleSide, Euler, Group, Matrix4, Mesh,
  MeshBasicMaterial, MeshStandardMaterial, PerspectiveCamera, PointLight, Quaternion, Scene, Skeleton, SkinnedMesh, Sprite, SpriteMaterial,
  Vector3, type Texture,
} from "three";
import type { Deck } from "../content/deck";
import { RoomLight } from "../actors/roomLight";
import type { PlayerView } from "../combat/view";
import { buildBlaster, type Blaster } from "../duel/blaster";
import { radialTexture } from "../duel/effects";
import { verticalFov } from "../engine/realtime/shoulderRig";
import { fingerBone, type ArmsSource, type ArmSlot } from "./armMesh";
import { copyHand, handPose, lerpHand, ViewArm, type HandPose } from "./arms";
import { turnBetween, ViewmodelMotion, type Visibility } from "./motion";
import { chamferBox, RigBuilder, RigPalette, type Slot } from "./rigMesh";

/** A pose of the blaster (its grip, the right hand's hold) in the camera's space. */
export interface GunPose { x: number; y: number; z: number; pitch: number; yaw: number; roll: number }

/**
 * The viewmodel's layout. Plain mutable data so a QA run can tune it live
 * (`window.__verseViewmodel` in development builds, then `retune()`).
 */
export const VIEWMODEL = {
  /** Gloves over the body's hands (a CSS colour multiplied into the hands' painted atlas), or null for bare hands. */
  gloves: "#1e1f23" as string | null,
  /** Horizontal field of view of the viewmodel camera, degrees (fixed: the arms keep their shape whatever the person's setting). */
  hfovDeg: 88,
  /** ... and while aiming down the sights (the sight comes a little closer). */
  adsHfovDeg: 76,
  near: 0.01,
  far: 4,
  /** A gloved finger's half thickness: how far off a held surface the closed fingers' joints and tips rest, metres. */
  fingerRadius: 0.0085,
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
  fill: 0.9,
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
  deckWrist: { x: 0.19, y: -0.2, z: -0.47 },
  /**
   * Shoulders, below and behind the eyes, and the elbows' pull (down and out). The support arm's shoulder sits in
   * toward the middle and low, so its forearm comes up from the bottom edge to the shroud instead of across the screen.
   */
  shoulderR: new Vector3(0.22, -0.38, -0.02),
  shoulderL: new Vector3(-0.02, -0.52, 0.06),
  poleR: new Vector3(1, -0.6, 0.1),
  poleL: new Vector3(-0.4, -1, 0.2),
  /**
   * The hands. Holds say where the held part sits in the hand's own frame (x toward the thumb on the right hand,
   * y the back of the hand, z the knuckles; metres from the wrist): the grip's centre across the right palm, the
   * shroud's axis over the left palm, the receiver's side under the slapping palm. Hand frames are knuckle and
   * back-of-hand directions in the blaster's frame (+Z the muzzle, +X its left) or the camera's; hand poses are
   * `HandPose` (three fingers, the index finger, the thumb). The right index finger's two joints are solved so its
   * pad rests on the trigger.
   */
  hands: {
    grip: [0.056, -0.032, 0.072],
    /** The right hand on the grip: three fingers wrapped round its front, the thumb over its far side. */
    gripPose: handPose(1.45, 1.5, 0.7, [0.4, 1.0], 0.35),
    fore: [-0.004, -0.04, 0.112],
    /** The left hand under the shroud: the knuckles along the barrel, the back of the hand down and out. */
    foreKnuckles: [0, 0.12, 1],
    foreBack: [0.55, -0.85, 0],
    /** The fingers curled up round the shroud's right side, the thumb along its left. */
    forePose: handPose(1.1, 1.0, 0.45, [0.95, 0.85], 0.1),
    vent: [0.0, -0.016, 0.07],
    ventKnuckles: [0, 0.35, 1],
    ventBack: [1, 0.1, 0],
    /** The open hand slapping the receiver, and raised palm forward behind the shield. */
    ventPose: handPose(0.35, 0.3, 0.1, [0.3, 0.25], -0.3),
    shieldPose: handPose(0.15, 0.1, 0.2, [0.1, 0.05], -0.4),
    deckKnuckles: [-0.25, 0.05, -1],
    deckBack: [0.55, 0.85, 0],
    /** Relaxed hands: the index a little straighter than the rest, the thumb resting along it. */
    deckPose: handPose(0.35, 0.55, 0.3, [0.25, 0.4], 0),
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

/**
 * The person's colours for the arms: the uniform's cloth and trim (CSS colours). Up close the sleeves and their cuffs
 * wear the cloth; the trim is kept for the layer's contract.
 */
export interface ArmColours {
  uniform: string;
  trim: string;
  /** A cuff of its own colour (the Sovereign's gold); without it the cuff wears the cloth. */
  cuff?: string;
  /** Bare hands of this colour instead of the gloves. */
  skin?: string;
}

/** The arms' own drawing: the bones of both arms, their skinned mesh and its material. */
interface Arms {
  right: ViewArm;
  left: ViewArm;
  mesh: SkinnedMesh;
  material: MeshStandardMaterial;
  source: ArmsSource;
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
  /** The blaster and the shield emitter: one skinned mesh under the palette. */
  readonly mesh: SkinnedMesh;
  private readonly rig = new Group();
  /** The commander's arms, once their body has loaded. */
  private arms: Arms | null = null;
  private readonly blaster: Blaster;
  private readonly gun = new Group();
  /** The blaster's bone (inside its scaled group): collapsed to a point when the hands are empty. */
  private readonly gunBone = new Bone();
  /** The shield emitter's bone: on the left forearm once the arms are in, collapsed until then. */
  private readonly housingBone = new Bone();
  /** A landmark on the trigger, in the blaster's frame. */
  readonly trigger = new Group();
  private readonly palette = new RigPalette("M_View_Rig");
  private readonly slots: { housing: Slot; emitter: Slot };
  private colours: ArmColours;
  private readonly glows: Glow[] = [];
  private readonly reticle: MeshBasicMaterial;
  private readonly flash: Sprite;
  private readonly flashLight = new PointLight(0xffa040, 0, 1.2, 2);
  private readonly key = new DirectionalLight(0xfff2e0, 0);
  private readonly light = new RoomLight();
  private readonly motion = new ViewmodelMotion();
  private readonly textures: Texture[] = [];
  private readonly emitterColour = new Color(0.35, 0.75, 1.6);
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
  /** The hands closed on the blaster (`solveHolds`): the right on the grip, its index on the trigger; the left on the shroud. */
  private readonly gripHand: HandPose = handPose(0, 0, 0);
  private readonly foreHand: HandPose = handPose(0, 0, 0);
  /** How far the solved index finger's pad is from the trigger, metres (for checks). */
  triggerReach = Infinity;
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
    this.slots = { housing: pal.slot("housing"), emitter: pal.slot("emitter") };
    pal.surface(this.slots.housing, new Color(0x2a2e34), 0.35, 0.85);
    pal.surface(this.slots.emitter, new Color(0x050505), 0.4, 0);
    this.colours = { ...colours };

    const rig = new RigBuilder();
    // The shield emitter: a flat housing along the back of the left forearm with a glowing strip and a lens.
    rig.add(chamferBox(0.046, 0.12, 0.016, 0.005), this.housingBone, this.slots.housing);
    rig.add(chamferBox(0.011, 0.092, 0.004, 0.0015), this.housingBone, this.slots.emitter, new Matrix4().makeTranslation(0, -0.005, 0.009));
    rig.add(new CylinderGeometry(0.01, 0.012, 0.006, 10).rotateX(Math.PI / 2), this.housingBone, this.slots.emitter, new Matrix4().makeTranslation(0, 0.046, 0.01));
    this.housingBone.scale.setScalar(1e-5);

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

    this.rig.add(this.gun, this.housingBone, this.key, this.key.target);
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
    this.colours = { ...colours };
    const arms = this.arms;
    if (!arms) return;
    // The atlas multiplies the material colour (as on the body): the uniform by the tier, the hands gloved (or the skin
    // as authored), each over the body's baked occlusion. The cuff's trim band wears the cloth too: up close its
    // sawtooth edge (`CUT.trimLift`) would show as a change of tone.
    const src = arms.source;
    const gloves = VIEWMODEL.gloves;
    const cloth = new Color(colours.uniform);
    const tint: Record<ArmSlot, Color> = {
      uniform: cloth, trim: colours.cuff ? new Color(colours.cuff) : cloth, skin: colours.skin ? new Color(colours.skin) : gloves ? new Color(gloves) : src.authored.skin, other: src.authored.other,
    };
    const order: ArmSlot[] = ["uniform", "trim", "skin", "other"];
    const attr = arms.mesh.geometry.getAttribute("color") as BufferAttribute;
    const c = attr.array as Float32Array;
    for (let i = 0; i < src.occlusion.length; i++) {
      const t = tint[order[src.slots[i]]];
      const ao = src.occlusion[i];
      c[i * 3] = t.r * ao;
      c[i * 3 + 1] = t.g * ao;
      c[i * 3 + 2] = t.b * ao;
    }
    attr.needsUpdate = true;
  }

  /** The arms are in (the body has loaded). */
  get hasArms(): boolean {
    return this.arms !== null;
  }

  /** The bones of the right and left arm (null before the body has loaded). */
  get right(): ViewArm | null {
    return this.arms?.right ?? null;
  }

  get left(): ViewArm | null {
    return this.arms?.left ?? null;
  }

  /** The arms' skinned mesh (null before the body has loaded). */
  get armsMesh(): SkinnedMesh | null {
    return this.arms?.mesh ?? null;
  }

  /**
   * The commander's body has loaded: rig and draw the arms cut from it (`cutArms`). The cut's geometry is taken over
   * (disposed with the viewmodel); its atlas stays the body's. Replaces arms attached before.
   */
  attachArms(source: ArmsSource): void {
    this.detachArms();
    const right = new ViewArm(source.right);
    const left = new ViewArm(source.left);
    const material = new MeshStandardMaterial({
      name: "M_View_Arms", map: source.map, normalMap: source.normalMap, roughnessMap: source.roughnessMap,
      vertexColors: true, roughness: 1, metalness: 0, side: DoubleSide,
    });
    material.normalScale.set(source.normalScale[0], source.normalScale[1]);
    const mesh = new SkinnedMesh(source.geometry, material);
    mesh.name = "ViewmodelArms";
    mesh.frustumCulled = false;
    const skeleton = new Skeleton([...right.bones, ...left.bones], [...right.inverses(), ...left.inverses()]);
    mesh.bind(skeleton, new Matrix4());
    this.rig.add(right.group, left.group);
    this.rig.traverse((o) => { o.frustumCulled = false; });
    this.scene.add(mesh);
    // The emitter rides on the left forearm.
    left.emitter.add(this.housingBone);
    this.housingBone.scale.setScalar(1);
    this.arms = { right, left, mesh, material, source };
    this.light.attach([material]);
    this.retune();
  }

  private detachArms(): void {
    const arms = this.arms;
    if (!arms) return;
    this.rig.add(this.housingBone);
    this.housingBone.scale.setScalar(1e-5);
    this.housingBone.position.set(0, 0, 0);
    this.rig.remove(arms.right.group, arms.left.group);
    this.scene.remove(arms.mesh);
    arms.mesh.geometry.dispose();
    arms.mesh.skeleton.dispose();
    arms.material.dispose();
    this.arms = null;
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
    this.setColours(this.colours);
    SHOULDER_R.copy(VIEWMODEL.shoulderR);
    SHOULDER_L.copy(VIEWMODEL.shoulderL);
    POLE_R.copy(VIEWMODEL.poleR).normalize();
    POLE_L.copy(VIEWMODEL.poleL).normalize();
    const h = VIEWMODEL.hands;
    const vec = (a: readonly number[]) => new Vector3(a[0], a[1], a[2]);
    const bs = this.blasterScale() * s;
    // A hold: the wrist where the held point sits at `at` in the hand's frame `q`.
    const hold = (out: { at: Vector3; q: Quaternion }, point: Vector3, at: readonly number[]) => {
      out.at.copy(point).sub(vec(at).applyQuaternion(out.q));
    };
    // Right hand: the grip's axis runs up and back (the grip rakes 0.28 rad) along the hand's width (the thumb's side
    // up); the back of the hand faces the blaster's right (−X), the knuckles wrap the grip's front and the fingers
    // curl round to its left side.
    const up = new Vector3(0, Math.cos(0.28), -Math.sin(0.28));
    const backR = new Vector3(-1, 0, 0);
    ViewArm.handFrame(new Vector3().crossVectors(up, backR), backR, this.holdR.q);
    hold(this.holdR, new Vector3(0, -0.06, -0.01).multiplyScalar(bs), h.grip);
    // Left hand: under the shroud, the knuckles along the barrel, the back of the hand down and out to the left; the
    // fingers curl up round the shroud's right side, the thumb lies along its left.
    ViewArm.handFrame(vec(h.foreKnuckles), vec(h.foreBack), this.holdL.q);
    hold(this.holdL, new Vector3(0, 0.012 * this.blasterScale(), this.blaster.fore.z).multiplyScalar(s), h.fore);
    // Venting: the left hand leaves the shroud and slaps the receiver's side, palm flat against it.
    ViewArm.handFrame(vec(h.ventKnuckles), vec(h.ventBack), this.ventL.q);
    hold(this.ventL, new Vector3(0.03, 0.0, 0.07).multiplyScalar(bs), h.vent);
    this.solveHolds();
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
   * Close the hands on the blaster (the holds are fixed in its frame, so this holds for every pose): a search over
   * the knuckle and middle joints of the fingers, so each finger's joints and tip rest on the held part's surface
   * without sinking in (the right hand's three outer fingers round the grip, the left hand's four round the shroud),
   * and the right index finger's pad on the trigger. Without arms: the layout's hand poses.
   */
  private solveHolds(): void {
    copyHand(this.gripHand, VIEWMODEL.hands.gripPose);
    copyHand(this.foreHand, VIEWMODEL.hands.forePose);
    const arms = this.arms;
    if (!arms) return;
    const bs = this.blasterScale() * VIEWMODEL.gunScale;
    // The grip: a box raked back 0.28 rad. The shroud: a cylinder along the barrel.
    const gripC = new Vector3(0, -0.06, -0.01).multiplyScalar(bs);
    const gripH = new Vector3(0.017, 0.0525, 0.021).multiplyScalar(bs);
    const unrake = new Quaternion().setFromAxisAngle(new Vector3(1, 0, 0), 0.28);
    const q = new Vector3();
    const grip = (p: Vector3): number => {
      q.subVectors(p, gripC).applyQuaternion(unrake);
      const x = Math.abs(q.x) - gripH.x;
      const y = Math.abs(q.y) - gripH.y;
      const z = Math.abs(q.z) - gripH.z;
      return Math.hypot(Math.max(x, 0), Math.max(y, 0), Math.max(z, 0)) + Math.min(Math.max(x, y, z), 0);
    };
    const shroudY = 0.012 * bs;
    const shroudR = 0.028 * bs;
    const shroud = (p: Vector3): number => Math.hypot(p.x, p.y - shroudY) - shroudR;
    const right = arms.right;
    this.wrap(right, this.holdR, this.gripHand.fingers, [1, 2, 3], grip);
    this.wrap(arms.left, this.holdL, this.foreHand.fingers, [1, 2, 3], shroud);
    this.wrap(arms.left, this.holdL, this.foreHand.index, [0], shroud);
    // The right index finger onto the trigger.
    const target = this.trigger.position.clone().multiplyScalar(VIEWMODEL.gunScale);
    const hand = new Matrix4().compose(this.holdR.at, this.holdR.q, new Vector3(1, 1, 1));
    const chain = [0, 1, 2].map((j) => right.bones[fingerBone(0) + j]);
    const m = new Matrix4();
    const tip = new Vector3();
    let best = Infinity;
    let ba = this.gripHand.index[0];
    let bb = this.gripHand.index[1];
    for (let a = 0; a <= 1.6; a += 0.02) {
      for (let b = 0; b <= 1.8; b += 0.02) {
        this.gripHand.index[0] = a;
        this.gripHand.index[1] = b;
        right.curl(this.gripHand);
        // The finger's pad (`indexTip`, on its end bone) against the trigger.
        m.copy(hand);
        for (const bone of chain) {
          bone.updateMatrix();
          m.multiply(bone.matrix);
        }
        const d = tip.copy(right.indexTip.position).applyMatrix4(m).distanceTo(target);
        if (d < best) {
          best = d;
          ba = a;
          bb = b;
        }
      }
    }
    this.gripHand.index[0] = ba;
    this.gripHand.index[1] = bb;
    right.curl(this.gripHand);
    this.triggerReach = best;
  }

  /**
   * Curl `fingers` of `arm` (holding at `hold`, in the blaster's frame) by the shared knuckle and middle joint
   * angles `out` that rest them on the surface `sdf` (signed distance, metres): each joint and the tip a finger's
   * thickness off it, sinking in costing eight times a gap.
   */
  private wrap(arm: ViewArm, hold: { at: Vector3; q: Quaternion }, out: [number, number], fingers: number[], sdf: (p: Vector3) => number): void {
    const hand = new Matrix4().compose(hold.at, hold.q, new Vector3(1, 1, 1));
    const pose = handPose(0, 0, 0);
    const pts = [new Vector3(), new Vector3(), new Vector3(), new Vector3()];
    let best = Infinity;
    let ba = out[0];
    let bb = out[1];
    for (let a = 0; a <= 1.7; a += 0.025) {
      for (let b = 0; b <= 1.9; b += 0.025) {
        pose.fingers[0] = pose.index[0] = a;
        pose.fingers[1] = pose.index[1] = b;
        arm.curl(pose);
        let cost = 0;
        for (const f of fingers) {
          arm.fingerPoints(f, pts);
          for (const p of pts) {
            const gap = sdf(p.applyMatrix4(hand)) - VIEWMODEL.fingerRadius;
            cost += gap < 0 ? 64 * gap * gap : gap * gap;
          }
        }
        if (cost < best) {
          best = cost;
          ba = a;
          bb = b;
        }
      }
    }
    out[0] = ba;
    out[1] = bb;
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
    if (this.arms) this.arms.material.envMapIntensity = VIEWMODEL.envGain;
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
    const arms = this.arms;
    arms?.right.curl(this.gripHand);
    arms?.right.pose(SHOULDER_R, this.wristR, this.qHandR, POLE_R);

    // Left hand: on the shroud, against the receiver while venting, up before the face behind the shield.
    this.wristL.copy(this.holdL.at).applyQuaternion(this.qGun).add(this.gun.position);
    this.qHandL.copy(this.qGun).multiply(this.holdL.q);
    const hand = copyHand(this.handL, this.foreHand);
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
    arms?.left.curl(hand);
    arms?.left.pose(SHOULDER_L, this.wristL, this.qHandL, POLE_L);
  }

  private poseDeck(o: { x: number; y: number; z: number; pitch: number; yaw: number; roll: number }, dip: number): void {
    // Loose hands low in the frame; while walking they swing against each other with the stride.
    const swing = Math.sin(this.motion.phase) * 0.05 * Math.min(1, this.motion.bob);
    const c = VIEWMODEL.hands.deckPose;
    const arms = this.arms;
    if (!arms) return;
    arms.right.curl(c);
    arms.left.curl(c);
    const d = VIEWMODEL.deckWrist;
    // The deck's arms hang from the shoulders' usual place (the duel's support shoulder sits in for the hold).
    this.v.set(-VIEWMODEL.shoulderR.x, VIEWMODEL.shoulderR.y, VIEWMODEL.shoulderR.z);
    this.wristR.set(d.x + o.x, d.y + o.y - dip + Math.abs(swing) * 0.2, d.z + o.z - swing);
    this.wristL.set(-d.x + o.x, d.y + o.y - dip + Math.abs(swing) * 0.2, d.z + o.z + swing);
    arms.right.pose(SHOULDER_R, this.wristR, this.qDeckR, POLE_R);
    arms.left.pose(this.v, this.wristL, this.qDeckL, DECK_POLE_L.set(-POLE_R.x, POLE_R.y, POLE_R.z));
  }

  dispose(): void {
    this.detachArms();
    this.mesh.geometry.dispose();
    this.mesh.skeleton.dispose();
    this.palette.dispose();
    this.blaster.dispose();
    for (const m of [this.reticle, this.flash.material]) m.dispose();
    for (const t of this.textures) t.dispose();
  }
}

const DECK_POLE_L = new Vector3();
