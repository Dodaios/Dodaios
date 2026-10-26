/**
 * The first-person viewmodel: who is drawn (arms in, own body out), the walk
 * bob, idle sway, look lag and recoil maths, the arm's IK and hand frames,
 * and the rig posed in the viewmodel camera's frustum on the deck and in a
 * duel (hip, sights, shield, a shot).
 */
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import { Box3, Color, Frustum, Matrix4, Mesh, PerspectiveCamera, Quaternion, Sprite, Vector3 } from "three";
import type { PlayerView } from "../combat/view";
import { ARM, fingerSegment, handPose, ViewArm } from "./arms";
import { chamferBox, RigBuilder } from "./rigMesh";
import {
  HIDE_BODY_BELOW_M, HIDE_BODY_FIRST_SHARE, idleSway, MOTION, springStep, turnBetween, ViewmodelMotion, viewmodelVisibility,
  walkBob, zeroOffsets, type MotionInput,
} from "./motion";
import { Viewmodel, VIEWMODEL, type ViewmodelFrame } from "./viewmodel";

const still: MotionInput = { dt: 1 / 60, speed: 0, walkSpeed: 1.4, turnYaw: 0, turnPitch: 0, ads: 0, reduced: false };

describe("viewmodel visibility", () => {
  it("shows the arms only in first person at eye level, once the body is hidden", () => {
    const third = viewmodelVisibility({ eyeOn: true, firstShare: 0, thirdDistance: 2.4, duelFirstShare: null });
    expect(third).toMatchObject({ arms: false, hideOwnBody: false, mode: "deck" });
    const blending = viewmodelVisibility({ eyeOn: true, firstShare: HIDE_BODY_FIRST_SHARE + 0.01, thirdDistance: 1.2, duelFirstShare: null });
    expect(blending.arms).toBe(true);
    expect(blending.hideOwnBody).toBe(true);
    expect(blending.raise).toBeGreaterThan(0);
    expect(blending.raise).toBeLessThan(0.1);
    const first = viewmodelVisibility({ eyeOn: true, firstShare: 1, thirdDistance: 1.2, duelFirstShare: null });
    expect(first).toMatchObject({ arms: true, hideOwnBody: true, raise: 1 });
    // Never both bodies, never neither: the arms come in exactly where the body goes.
    for (let s = 0; s <= 1; s += 0.05) {
      const v = viewmodelVisibility({ eyeOn: true, firstShare: s, thirdDistance: 2, duelFirstShare: null });
      expect(v.arms).toBe(v.hideOwnBody);
    }
  });

  it("hides the body when a wall pushes the shoulder camera into it, without arms", () => {
    const v = viewmodelVisibility({ eyeOn: true, firstShare: 0, thirdDistance: HIDE_BODY_BELOW_M - 0.1, duelFirstShare: null });
    expect(v).toMatchObject({ arms: false, hideOwnBody: true });
  });

  it("draws nothing of its own without the eye-level view", () => {
    const v = viewmodelVisibility({ eyeOn: false, firstShare: 1, thirdDistance: 0.2, duelFirstShare: null });
    expect(v).toMatchObject({ arms: false, hideOwnBody: false });
  });

  it("follows the duel camera's person during a duel", () => {
    expect(viewmodelVisibility({ eyeOn: true, firstShare: 1, thirdDistance: 1.2, duelFirstShare: 0 })).toMatchObject({ arms: false, hideOwnBody: false, mode: "duel" });
    expect(viewmodelVisibility({ eyeOn: true, firstShare: 0, thirdDistance: 2.4, duelFirstShare: 1 })).toMatchObject({ arms: true, hideOwnBody: true, mode: "duel" });
  });
});

describe("viewmodel motion", () => {
  it("bobs with the stride: a dip at every footfall, a sway once per stride, nothing standing", () => {
    const none = walkBob(1.3, 0, zeroOffsets());
    expect(Math.abs(none.x) + Math.abs(none.y) + Math.abs(none.roll)).toBe(0);
    const mid = walkBob(Math.PI / 2, 1, zeroOffsets());
    expect(mid.y).toBeCloseTo(-MOTION.bobY, 9);
    const plant = walkBob(0, 1, zeroOffsets());
    expect(plant.y).toBeCloseTo(0, 9);
    expect(plant.x).toBeCloseTo(MOTION.bobX, 9);
    expect(walkBob(Math.PI, 1, zeroOffsets()).x).toBeCloseTo(-MOTION.bobX, 9);
    // Twice the speed, twice the bob.
    expect(walkBob(Math.PI / 2, 2, zeroOffsets()).y).toBeCloseTo(2 * mid.y, 9);
  });

  it("breathes a few millimetres while standing", () => {
    for (let t = 0; t < 12; t += 0.37) {
      const o = idleSway(t, 1, zeroOffsets());
      expect(Math.abs(o.y)).toBeLessThanOrEqual(MOTION.idleY + 1e-12);
      expect(Math.abs(o.x)).toBeLessThanOrEqual(MOTION.idleX + 1e-12);
    }
  });

  it("walks the stride phase with the ground covered and eases the bob in", () => {
    const m = new ViewmodelMotion();
    for (let i = 0; i < 60; i++) m.step({ ...still, speed: 1.4 });
    // One second at 1.4 m/s: 1.4 / stepM steps, π per step.
    expect(m.bob).toBeGreaterThan(0.95);
    const standing = new ViewmodelMotion();
    for (let i = 0; i < 60; i++) standing.step(still);
    expect(standing.bob).toBe(0);
    const running = new ViewmodelMotion();
    for (let i = 0; i < 120; i++) running.step({ ...still, speed: 6 });
    expect(running.bob).toBeLessThanOrEqual(MOTION.bobMax + 1e-9);
  });

  it("settles a damped spring and survives a long frame", () => {
    let [x, v] = [0, 10];
    for (let i = 0; i < 120; i++) [x, v] = springStep(x, v, 1 / 60, MOTION.recoilK, MOTION.recoilC);
    expect(Math.abs(x)).toBeLessThan(1e-3);
    [x, v] = springStep(0, 10, 0.5, MOTION.recoilK, MOTION.recoilC);
    expect(Number.isFinite(x) && Math.abs(x) < 1).toBe(true);
  });

  it("kicks back and up on a shot and comes back to rest", () => {
    const m = new ViewmodelMotion();
    m.fire(1);
    let peakZ = 0;
    let peakPitch = 0;
    for (let i = 0; i < 6; i++) {
      const o = m.step(still);
      peakZ = Math.max(peakZ, o.z);
      peakPitch = Math.max(peakPitch, o.pitch);
    }
    // Toward the eye (+z) and muzzle up, by a centimetre or more.
    expect(peakZ).toBeGreaterThan(0.01);
    expect(peakPitch).toBeGreaterThan(0.02);
    for (let i = 0; i < 90; i++) m.step(still);
    expect(Math.abs(m.offsets.z)).toBeLessThan(1e-3);
    // The sights steady it.
    const ads = new ViewmodelMotion();
    ads.fire(1);
    let adsPeak = 0;
    for (let i = 0; i < 6; i++) adsPeak = Math.max(adsPeak, ads.step({ ...still, ads: 1 }).z);
    expect(adsPeak).toBeLessThan(peakZ);
  });

  it("trails a turn of the view and lets it go", () => {
    const m = new ViewmodelMotion();
    const o = m.step({ ...still, turnYaw: 0.05 });
    // Turned right: the arms are left behind (to the left), muzzle still pointing back left.
    expect(o.x).toBeLessThan(0);
    expect(o.yaw).toBeGreaterThan(0);
    const up = new ViewmodelMotion().step({ ...still, turnPitch: 0.05 });
    expect(up.y).toBeLessThan(0);
    for (let i = 0; i < 60; i++) m.step(still);
    expect(Math.abs(m.lagYaw)).toBeLessThan(1e-4);
    // A flick never throws the arms out of frame.
    const flick = new ViewmodelMotion();
    flick.step({ ...still, turnYaw: 3 });
    expect(Math.abs(flick.lagYaw)).toBeLessThanOrEqual(MOTION.lagMax);
  });

  it("drops bob, sway and lag and softens the recoil for reduced motion", () => {
    const m = new ViewmodelMotion();
    for (let i = 0; i < 60; i++) m.step({ ...still, speed: 1.4, turnYaw: 0.02, reduced: true });
    expect(m.bob).toBe(0);
    expect(m.lagYaw).toBe(0);
    expect(m.offsets.x).toBe(0);
    expect(m.offsets.y).toBe(0);
    const full = new ViewmodelMotion();
    const calm = new ViewmodelMotion();
    full.fire(1);
    calm.fire(1);
    const a = full.step(still).z;
    const b = calm.step({ ...still, reduced: true }).z;
    expect(b).toBeCloseTo(a * MOTION.reducedRecoil, 9);
  });

  it("measures the view's turn between frames, right positive, ignoring cuts", () => {
    // The deck's yaw grows to the left, so a right turn lowers it.
    expect(turnBetween(0.5, 0, 0.45, 0).yaw).toBeCloseTo(0.05, 9);
    expect(turnBetween(0, 0, 0, 0.1).pitch).toBeCloseTo(0.1, 9);
    // Across ±π.
    expect(turnBetween(Math.PI - 0.01, 0, -Math.PI + 0.01, 0).yaw).toBeCloseTo(-0.02, 9);
    expect(turnBetween(0, 0, 2, 0)).toEqual({ yaw: 0, pitch: 0 });
  });
});

describe("viewmodel arms", () => {
  it("turns finger segments along +Z, round at both ends", () => {
    const geo = fingerSegment(0.01, 0.008, 0.04);
    geo.computeBoundingBox();
    const box = geo.boundingBox as Box3;
    expect(box.min.z).toBeCloseTo(0, 6);
    expect(box.max.z).toBeCloseTo(0.04, 6);
    expect(box.max.x).toBeLessThanOrEqual(0.01);
    expect(box.max.x).toBeGreaterThan(0.008);
    geo.dispose();
  });

  it("chamfers a box with 44 flat triangles", () => {
    const geo = chamferBox(0.1, 0.04, 0.2, 0.01);
    expect(geo.getAttribute("position").count / 3).toBe(44);
    geo.computeBoundingBox();
    expect(geo.boundingBox?.max.z).toBeCloseTo(0.1, 6);
    expect(geo.boundingBox?.max.y).toBeCloseTo(0.02, 6);
    geo.dispose();
  });

  it("poses the index finger and the thumb apart from the other fingers", () => {
    const arm = new ViewArm("right", new RigBuilder(), SLOTS);
    const bones = arm as unknown as { fingers: { base: { rotation: { x: number } } }[]; thumb: { base: { rotation: { y: number } } } };
    arm.curl(handPose(1.5, 1.4, 0.7, [0.3, 0.7], 0.2));
    expect(bones.fingers[0].base.rotation.x).toBeCloseTo(0.3, 6);
    expect(bones.fingers[1].base.rotation.x).toBeGreaterThan(1.5);
    const thumbY = bones.thumb.base.rotation.y;
    arm.curl(handPose(1.5, 1.4, 0.7, [0.3, 0.7], 0));
    expect(bones.thumb.base.rotation.y).not.toBeCloseTo(thumbY, 3);
    // The left hand is the right one mirrored: its thumb swings the other way.
    const left = new ViewArm("left", new RigBuilder(), SLOTS);
    left.curl(handPose(1.5, 1.4, 0.7, [0.3, 0.7], 0));
    expect((left as unknown as typeof bones).thumb.base.rotation.y).toBeCloseTo(-bones.thumb.base.rotation.y, 6);
  });

  it("reaches the wrist with a two-bone arm whose elbow bends toward the pole", () => {
    const arm = new ViewArm("right", new RigBuilder(), SLOTS);
    const shoulder = new Vector3(0.2, -0.38, 0);
    const wrist = new Vector3(0.12, -0.12, -0.4);
    const q = ViewArm.handFrame(new Vector3(0, 0, -1), new Vector3(0, 1, 0), new Quaternion());
    arm.pose(shoulder, wrist, q, new Vector3(1, -0.6, 0).normalize());
    arm.group.updateMatrixWorld(true);
    expect(arm.hand.position.distanceTo(wrist)).toBeLessThan(1e-9);
    const elbow = arm.fore.position;
    expect(elbow.distanceTo(shoulder)).toBeCloseTo(ARM.upper, 6);
    expect(elbow.distanceTo(wrist)).toBeCloseTo(ARM.fore, 6);
    // The elbow hangs out and down, as an arm does.
    expect(elbow.x).toBeGreaterThan((shoulder.x + wrist.x) / 2);
    // The hand frame: knuckles ahead (−Z), back of the hand up.
    const knuckles = new Vector3(0, 0, 1).applyQuaternion(q);
    expect(knuckles.z).toBeCloseTo(-1, 6);

  });
});

const SLOTS = { sleeve: 0, trim: 1, glove: 2, housing: 3, emitter: 4 };

function player(over: Partial<PlayerView> = {}): PlayerView {
  return {
    slot: 0, id: "a", local: true, side: 0, x: 0, z: 0, yaw: 0, pitch: 0, aimYaw: 0, aimPitch: 0, vx: 0, vz: 0, speed: 0,
    alive: true, health: 100, healthMax: 100, shieldUp: false, shieldEnergy: 1, shieldBroken: false, parrying: false, ads: 0,
    sprinting: false, dodging: false, dodgeProgress: 0, venting: false, overheated: false, heat: 0, ...over,
  };
}

describe("viewmodel rig", () => {
  // jsdom has no 2D canvas: the reticle and flash textures stay blank.
  let spy: ReturnType<typeof vi.spyOn> | null = null;
  beforeAll(() => { spy = vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null); });
  afterAll(() => { spy?.mockRestore(); });

  function frameFor(over: Partial<ViewmodelFrame> = {}): ViewmodelFrame {
    return {
      visibility: { arms: true, mode: "deck", hideOwnBody: true, raise: 1 },
      player: null, speed: 0, walkSpeed: 1.4, x: 0, y: 0, z: 0, deck: null, reduced: false, frozen: false, ...over,
    };
  }

  function eye(): PerspectiveCamera {
    const c = new PerspectiveCamera(60, 16 / 9, 0.05, 500);
    c.position.set(3, 1.65, -2);
    c.lookAt(3, 1.65, -10);
    c.updateMatrixWorld();
    return c;
  }

  /** Whether a world point of the rig is in the viewmodel camera's view. */
  function inView(vm: Viewmodel, p: Vector3): boolean {
    const cam = vm.camera;
    cam.updateMatrixWorld();
    const f = new Frustum().setFromProjectionMatrix(new Matrix4().multiplyMatrices(cam.projectionMatrix, cam.matrixWorldInverse));
    return f.containsPoint(p);
  }

  function world(o: { getWorldPosition(v: Vector3): Vector3 }): Vector3 {
    return o.getWorldPosition(new Vector3());
  }

  it("draws nothing until first person asks for the arms", () => {
    const vm = new Viewmodel({ uniform: "#3b3f47", trim: "#5a5f68" }, new Color(1, 0.6, 0.15));
    vm.prepare(eye(), 1 / 60, null);
    expect(vm.visible).toBe(false);
    vm.set(frameFor({ visibility: { arms: false, mode: "deck", hideOwnBody: false, raise: 0 } }));
    vm.prepare(eye(), 1 / 60, null);
    expect(vm.visible).toBe(false);
    vm.dispose();
  });

  it("puts both hands in the lower corners on the deck, the blaster away", () => {
    const vm = new Viewmodel({ uniform: "#3b3f47", trim: "#5a5f68" }, new Color(1, 0.6, 0.15));
    vm.set(frameFor());
    vm.prepare(eye(), 1 / 60, null);
    expect(vm.visible).toBe(true);
    const parts = vm as unknown as { right: ViewArm; left: ViewArm; gun: { visible: boolean } };
    expect(parts.gun.visible).toBe(false);
    vm.scene.updateMatrixWorld(true);
    // The knuckles are in view; the right hand right of centre, the left hand left of it, both below the eye line.
    const r = world(parts.right.knuckles);
    const l = world(parts.left.knuckles);
    expect(inView(vm, r)).toBe(true);
    expect(inView(vm, l)).toBe(true);
    const toCam = (p: Vector3) => p.clone().applyMatrix4(vm.camera.matrixWorldInverse);
    expect(toCam(r).x).toBeGreaterThan(0.05);
    expect(toCam(l).x).toBeLessThan(-0.05);
    expect(toCam(r).y).toBeLessThan(0);
    vm.dispose();
  });

  it("holds the blaster in a duel: muzzle and both hands in view at the hip; the sight on the eye line in the sights", () => {
    const vm = new Viewmodel({ uniform: "#3b3f47", trim: "#5a5f68" }, new Color(1, 0.6, 0.15));
    const parts = vm as unknown as { right: ViewArm; left: ViewArm; blaster: { group: { localToWorld(v: Vector3): Vector3 }; muzzle: Vector3; sight: Vector3 } };
    const duelFrame = (p: PlayerView) => frameFor({ visibility: { arms: true, mode: "duel", hideOwnBody: true, raise: 1 }, player: p });
    const cam = eye();
    vm.set(duelFrame(player()));
    for (let i = 0; i < 30; i++) vm.prepare(cam, 1 / 60, null);
    vm.scene.updateMatrixWorld(true);
    const muzzle = parts.blaster.group.localToWorld(parts.blaster.muzzle.clone());
    expect(inView(vm, muzzle)).toBe(true);
    expect(inView(vm, world(parts.left.hand))).toBe(true);
    // The right hand sits on the grip at the bottom right.
    const right = world(parts.right.hand).applyMatrix4(vm.camera.matrixWorldInverse);
    expect(right.x).toBeGreaterThan(0.08);
    expect(right.y).toBeLessThan(-0.1);
    // Aiming down the sights: the sight's window on the view axis at adsDistance.
    vm.set(duelFrame(player({ ads: 1 })));
    for (let i = 0; i < 60; i++) vm.prepare(cam, 1 / 60, null);
    vm.scene.updateMatrixWorld(true);
    const sight = parts.blaster.group.localToWorld(parts.blaster.sight.clone()).applyMatrix4(vm.camera.matrixWorldInverse);
    expect(Math.abs(sight.x)).toBeLessThan(0.004);
    expect(Math.abs(sight.y)).toBeLessThan(0.004);
    expect(-sight.z).toBeCloseTo(VIEWMODEL.adsDistance, 2);
    vm.dispose();
  });

  it("raises the left forearm with the shield up and kicks with a shot", () => {
    const vm = new Viewmodel({ uniform: "#3b3f47", trim: "#5a5f68" }, new Color(1, 0.6, 0.15));
    const parts = vm as unknown as { left: ViewArm; gun: { position: Vector3 } };
    const cam = eye();
    const duelFrame = (p: PlayerView) => frameFor({ visibility: { arms: true, mode: "duel", hideOwnBody: true, raise: 1 }, player: p });
    vm.set(duelFrame(player()));
    for (let i = 0; i < 30; i++) vm.prepare(cam, 1 / 60, null);
    vm.scene.updateMatrixWorld(true);
    const restY = world(parts.left.hand).applyMatrix4(vm.camera.matrixWorldInverse).y;
    const restZ = parts.gun.position.z;
    vm.set(duelFrame(player({ shieldUp: true })));
    for (let i = 0; i < 30; i++) vm.prepare(cam, 1 / 60, null);
    vm.scene.updateMatrixWorld(true);
    expect(world(parts.left.hand).applyMatrix4(vm.camera.matrixWorldInverse).y).toBeGreaterThan(restY + 0.03);
    // The emitter's strip lights.
    expect(vm.emitterGlow).toBeGreaterThan(3);
    vm.set(duelFrame(player()));
    for (let i = 0; i < 30; i++) vm.prepare(cam, 1 / 60, null);
    vm.shot(1, false);
    let back = -Infinity;
    for (let i = 0; i < 5; i++) { vm.prepare(cam, 1 / 60, null); back = Math.max(back, parts.gun.position.z); }
    expect(back).toBeGreaterThan(restZ + 0.01);
    vm.dispose();
  });

  /** The rig's skinned vertices in normalised device coordinates, split into the blaster's and the arms'. */
  function screen(vm: Viewmodel): { gun: Vector3[]; arms: Vector3[] } {
    vm.scene.updateMatrixWorld(true);
    vm.camera.updateMatrixWorld();
    const mesh = vm.mesh;
    const gunBone = (vm as unknown as { gunBone: object }).gunBone;
    const gunIndex = mesh.skeleton.bones.indexOf(gunBone as never);
    const skin = mesh.geometry.getAttribute("skinIndex");
    const out = { gun: [] as Vector3[], arms: [] as Vector3[] };
    for (let i = 0; i < skin.count; i += 3) {
      const p = mesh.getVertexPosition(i, new Vector3()).project(vm.camera);
      (skin.getX(i) === gunIndex ? out.gun : out.arms).push(p);
    }
    return out;
  }
  const onScreen = (p: Vector3) => Math.abs(p.x) <= 1 && Math.abs(p.y) <= 1 && p.z < 1;
  const duelFrame = (p: PlayerView) => frameFor({ visibility: { arms: true, mode: "duel", hideOwnBody: true, raise: 1 }, player: p });

  it("draws the arms and the blaster as one skinned mesh within the budget", () => {
    const vm = new Viewmodel({ uniform: "#3b3f47", trim: "#5a5f68" }, new Color(1, 0.6, 0.15));
    vm.set(duelFrame(player()));
    vm.shot(1, false);
    vm.shot(2, false);
    for (let i = 0; i < 3; i++) vm.prepare(eye(), 1 / 60, null);
    let draws = 0;
    let triangles = 0;
    vm.scene.traverseVisible((o) => {
      if ((o as Mesh).isMesh) {
        const g = (o as Mesh).geometry;
        draws += Array.isArray((o as Mesh).material) ? g.groups.length : 1;
        triangles += (g.index ? g.index.count : g.getAttribute("position").count) / 3;
      } else if ((o as Sprite).isSprite) {
        draws++;
      }
    });
    // The rig, the sight's reticle and the muzzle flash.
    expect(draws).toBeLessThanOrEqual(3);
    expect(triangles).toBeLessThanOrEqual(3000);
    expect(vm.mesh.isSkinnedMesh).toBe(true);
    vm.dispose();
  });

  it("keeps the centre of the screen clear at the hip, the blaster low on the right", () => {
    const vm = new Viewmodel({ uniform: "#3b3f47", trim: "#5a5f68" }, new Color(1, 0.6, 0.15));
    vm.set(duelFrame(player()));
    for (let i = 0; i < 30; i++) vm.prepare(eye(), 1 / 60, null);
    const { gun, arms } = screen(vm);
    const all = [...gun, ...arms].filter(onScreen);
    // Nothing of the rig around the crosshair: the middle fifth across, down to below the screen's middle.
    expect(all.filter((p) => Math.abs(p.x) < 0.12 && p.y > -0.2)).toHaveLength(0);
    // The left half of the screen stays clear above its bottom quarter (the support arm comes up from below).
    expect(all.filter((p) => p.x < -0.05 && p.y > -0.5)).toHaveLength(0);
    // The blaster is right of centre and below the crosshair.
    const seen = gun.filter(onScreen);
    expect(seen.reduce((s, p) => s + p.x, 0) / seen.length).toBeGreaterThan(0.2);
    expect(Math.max(...gun.map((p) => p.y))).toBeLessThan(0);
    vm.dispose();
  });

  it("keeps the blaster in view, lowered and canted, in a sprint", () => {
    const vm = new Viewmodel({ uniform: "#3b3f47", trim: "#5a5f68" }, new Color(1, 0.6, 0.15));
    const parts = vm as unknown as { blaster: { group: { localToWorld(v: Vector3): Vector3 }; muzzle: Vector3 } };
    vm.set(duelFrame(player({ sprinting: true, speed: 6 })));
    for (let i = 0; i < 60; i++) vm.prepare(eye(), 1 / 60, null);
    const { gun } = screen(vm);
    // Most of the blaster is on screen, and its muzzle too.
    expect(gun.filter(onScreen).length / gun.length).toBeGreaterThan(0.6);
    expect(inView(vm, parts.blaster.group.localToWorld(parts.blaster.muzzle.clone()))).toBe(true);
    vm.dispose();
  });

  it("rests the right index finger on the trigger", () => {
    const vm = new Viewmodel({ uniform: "#3b3f47", trim: "#5a5f68" }, new Color(1, 0.6, 0.15));
    const parts = vm as unknown as { right: ViewArm };
    vm.set(duelFrame(player()));
    for (let i = 0; i < 30; i++) vm.prepare(eye(), 1 / 60, null);
    vm.scene.updateMatrixWorld(true);
    const tip = world(parts.right.indexTip);
    expect(tip.distanceTo(world(vm.trigger))).toBeLessThan(0.012);
    vm.dispose();
  });
});
