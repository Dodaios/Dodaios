/**
 * The game at eye level (docs/verse/realtime.md, "Runtime"): projection of
 * labels through the perspective camera and their occlusion, picking by
 * raycast against real BVH geometry, the station the use key works, the
 * camera rig's settings, the pointer-lock input, the view fallbacks and the
 * person's view settings.
 */
import { act, cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BoxGeometry, PerspectiveCamera, PlaneGeometry } from "three";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";
import { MeshBVH } from "three-mesh-bvh";
import { StageRuntime, type FrameStats } from "../../runtime";
import { syntheticDeck } from "../../testing/syntheticDeck";
import { worldToPlate } from "../plateMath";
import { plateToScreen } from "../view";
import { COMPACT_EYE_MIN, eyeCapable, stageView } from "../stageView";
import { CommanderControl, stationWithin } from "../../life/control";
import type { Station } from "../../content/deck";
import { FloatingLabels, PROMPT_AT } from "../../hud/FloatingLabels";
import { statsText } from "../../hud/DeckBar";
import { eyePull } from "../../effects/LightsLayer";
import { eyePick } from "./eyePick";
import { attachOrbitInput } from "./orbitInput";
import { LOOK_SENSITIVITY, SHOULDER, ShoulderRig } from "./shoulderRig";
import { normalizeViewPrefs, useViewSettings, VIEW_DEFAULTS, VIEW_SETTINGS_KEY } from "./viewSettings";

const W = 1600;
const H = 900;

/** A 40 × 40 m floor at y = 0 and a wall 3 m high across x −3..3, its front face at z = −4.9. */
function room(): MeshBVH {
  const floor = new PlaneGeometry(40, 40).rotateX(-Math.PI / 2);
  const wall = new BoxGeometry(6, 3, 0.2).translate(0, 1.5, -5);
  const merged = mergeGeometries([floor, wall], false);
  if (!merged) throw new Error("merge failed");
  return new MeshBVH(merged);
}

/** A stage looking down −Z from behind the commander's shoulder, at the room. */
function eyeStage(): StageRuntime {
  const runtime = new StageRuntime();
  runtime.deck = syntheticDeck();
  runtime.view.resize({ width: W, height: H, dpr: 1 });
  const camera = new PerspectiveCamera(50, W / H, 0.05, 500);
  camera.position.set(0, 1.8, 3);
  camera.lookAt(0, 1.5, -10);
  camera.updateMatrixWorld();
  camera.updateProjectionMatrix();
  runtime.eye = { camera, collider: room() };
  return runtime;
}

describe("projection through the eye-level camera", () => {
  it("puts the point the camera looks at in the middle of the screen", () => {
    const at = eyeStage().toScreen(0, 1.5, -10)!;
    expect(at.x).toBeCloseTo(W / 2, 3);
    expect(at.y).toBeCloseTo(H / 2, 3);
  });

  it("puts points left and above where they belong on screen", () => {
    const r = eyeStage();
    const left = r.toScreen(-2, 1.5, -10)!;
    const up = r.toScreen(0, 3.5, -10)!;
    expect(left.x).toBeLessThan(W / 2);
    expect(up.y).toBeLessThan(H / 2);
  });

  it("gives nothing for a point behind the camera", () => {
    expect(eyeStage().toScreen(0, 1.8, 10)).toBeNull();
  });

  it("writes into the point it is given, so the frame loop allocates nothing", () => {
    const out = { x: 0, y: 0 };
    expect(eyeStage().toScreen(0, 1.5, -10, out)).toBe(out);
  });

  it("projects through the plate when the eye-level view is off", () => {
    const r = eyeStage();
    r.eye = null;
    const deck = r.deck!;
    const p = worldToPlate(deck.camera, 3, 1, -2);
    const want = plateToScreen(r.view.current, r.view.vp, p.u, p.v);
    expect(r.toScreen(3, 1, -2)).toEqual(want);
    expect(r.ray(10, 10)).toBeNull();
  });
});

describe("line of sight", () => {
  it("hides points behind the wall and keeps those in front", () => {
    const r = eyeStage();
    expect(r.inSight(0, 1.5, -8)).toBe(false);
    expect(r.inSight(0, 1.5, -3)).toBe(true);
    // Beside the wall there is nothing in the way.
    expect(r.inSight(6, 1.5, -8)).toBe(true);
  });

  it("forgives geometry just at the point (a head against a wall)", () => {
    const r = eyeStage();
    expect(r.inSight(0, 1.5, -5)).toBe(true);
    expect(r.inSight(0, 1.5, -5, 0)).toBe(false);
  });

  it("sees everything on the plate and without collision geometry", () => {
    const r = eyeStage();
    r.eye = { camera: r.eye!.camera, collider: null };
    expect(r.inSight(0, 1.5, -8)).toBe(true);
    r.eye = null;
    expect(r.inSight(0, 1.5, -8)).toBe(true);
  });
});

describe("picking by raycast through the screen", () => {
  const stations: Station[] = [{ id: "helm", kind: "agents_list", room: null, x: 2, y: 0, z: -2, sockets: {} }];
  const pick = (r: StageRuntime, x: number, y: number, z: number, bodies: { id: string; x: number; y: number; z: number; height: number }[] = []) => {
    const at = r.toScreen(x, y, z)!;
    const ray = r.ray(at.x, at.y)!;
    return eyePick(ray.ray, stations, bodies, () => true, r.eye!.collider);
  };

  it("walks to a floor point clicked", () => {
    const hit = pick(eyeStage(), -4, 0, -1);
    expect(hit?.kind).toBe("floor");
    if (hit?.kind !== "floor") return;
    expect(hit.x).toBeCloseTo(-4, 2);
    expect(hit.z).toBeCloseTo(-1, 2);
  });

  it("uses a station clicked on or near its spot", () => {
    expect(pick(eyeStage(), 2.6, 0, -2.4)).toEqual({ kind: "station", id: "helm" });
  });

  it("picks a crew member in plain view, never one behind the wall", () => {
    const r = eyeStage();
    const near = { id: "near", x: -1, y: 0, z: -1, height: 1.8 };
    const hidden = { id: "hidden", x: 0, y: 0, z: -8, height: 1.8 };
    expect(pick(r, -1, 1, -1, [near, hidden])).toEqual({ kind: "crew", id: "near" });
    expect(pick(r, 0, 1, -8, [near, hidden])?.kind).not.toBe("crew");
  });

  it("does nothing on a wall", () => {
    expect(pick(eyeStage(), -1, 2, -4.9)).toBeNull();
  });
});

describe("which view the stage shows", () => {
  const base = { compact: false, realtime: true, failed: false };

  it("walks an exported deck at eye level on the full-size stage, bird's-eye on the plate", () => {
    expect(stageView({ ...base, mode: "follow" })).toBe("eye");
    expect(stageView({ ...base, mode: "overview" })).toBe("plate");
  });

  it("walks a roomy IDE side panel at eye level too, a small or unmeasured one stays on the plate", () => {
    const min = COMPACT_EYE_MIN;
    expect(min).toEqual({ width: 480, height: 360 });
    expect(stageView({ ...base, compact: true, width: min.width, height: min.height, mode: "follow" })).toBe("eye");
    expect(eyeCapable({ ...base, compact: true, width: 900, height: 700 })).toBe(true);
    expect(eyeCapable({ ...base, compact: true, width: min.width - 1, height: 700 })).toBe(false);
    expect(eyeCapable({ ...base, compact: true, width: 900, height: min.height - 1 })).toBe(false);
    expect(eyeCapable({ ...base, compact: true })).toBe(false);
    expect(eyeCapable({ ...base, compact: true, width: 900, height: 700, failed: true })).toBe(false);
    expect(eyeCapable({ ...base, compact: true, width: 900, height: 700, realtime: false })).toBe(false);
    // The full-size stage never asks for a size.
    expect(eyeCapable({ ...base, width: 10, height: 10 })).toBe(true);
  });

  it("keeps a small IDE panel, decks without an export and failed decks on the plate", () => {
    expect(stageView({ ...base, compact: true, mode: "follow" })).toBe("plate");
    expect(stageView({ ...base, realtime: false, mode: "follow" })).toBe("plate");
    expect(stageView({ ...base, failed: true, mode: "follow" })).toBe("plate");
    expect(eyeCapable(base)).toBe(true);
    expect(eyeCapable({ ...base, failed: true })).toBe(false);
  });
});

describe("the use key", () => {
  // The commander at the origin: a console 1 m behind them, another 1.6 m ahead (−Z).
  const behind: Station = { id: "behind", kind: "games", room: null, x: 0, y: 0, z: 1, sockets: {} };
  const ahead: Station = { id: "ahead", kind: "agents_list", room: null, x: 0, y: 0, z: -1.6, sockets: {} };

  it("works the nearest station without a facing, the one in front with one", () => {
    expect(stationWithin([behind, ahead], 0, 0)?.id).toBe("behind");
    expect(stationWithin([behind, ahead], 0, 0, undefined, { x: 0, z: -1 })?.id).toBe("ahead");
    expect(stationWithin([behind, ahead], 0, 0, undefined, { x: 0, z: 1 })?.id).toBe("behind");
  });

  it("still works a station behind when it is the only one in reach", () => {
    expect(stationWithin([behind], 0, 0, undefined, { x: 0, z: -1 })?.id).toBe("behind");
  });
});

describe("camera rig settings", () => {
  it("turns faster with a higher sensitivity and clamps it", () => {
    const a = new ShoulderRig();
    const b = new ShoulderRig();
    b.sensitivity = 2;
    a.look(10, 0);
    b.look(10, 0);
    expect(Math.PI - b.yaw).toBeCloseTo(2 * (Math.PI - a.yaw), 9);
    const c = new ShoulderRig();
    c.sensitivity = 100;
    c.look(10, 0);
    expect(Math.PI - c.yaw).toBeCloseTo(10 * SHOULDER.dragRate * LOOK_SENSITIVITY.max, 9);
  });

  it("looks up when the mouse moves down with the vertical axis inverted", () => {
    const rig = new ShoulderRig();
    rig.look(0, 10);
    expect(rig.pitch).toBeGreaterThan(SHOULDER.pitch);
    const inverted = new ShoulderRig();
    inverted.invertY = true;
    inverted.look(0, 10);
    expect(inverted.pitch).toBeLessThan(SHOULDER.pitch);
  });

  it("turns toward a crew member and reuses the direction it is given", () => {
    const rig = new ShoulderRig();
    rig.faceToward(0, 0, 3, 0);
    expect(rig.yaw).toBeCloseTo(Math.PI / 2);
    const out = { x: 0, z: 0 };
    expect(rig.walkDirection(0, -1, out)).toBe(out);
    expect(out.x).toBeCloseTo(1);
    const control = new CommanderControl();
    control.setKey("up", true);
    expect(control.directionFrom(rig, out)).toBe(out);
    expect(control.direction(out)).toBe(out);
    expect(out).toEqual({ x: 0, z: -1 });
  });

  it("frames the same shot whatever object carries the pose", () => {
    const a = new ShoulderRig();
    const b = new ShoulderRig();
    a.snapBehind(1);
    b.snapBehind(1);
    const pose = { x: 2, y: 0, z: 1, heading: 1, moving: false };
    a.update(1 / 60, pose);
    pose.x = 2;
    b.update(1 / 60, { ...pose });
    expect(a.position).toEqual(b.position);
    expect(a.target).toEqual(b.target);
  });
});

describe("view settings", () => {
  beforeEach(() => {
    window.localStorage.clear();
    useViewSettings.getState().reset();
  });

  it("reads anything stored as valid settings", () => {
    expect(normalizeViewPrefs(null)).toEqual(VIEW_DEFAULTS);
    expect(normalizeViewPrefs({ sensitivity: 99, invertY: "yes", quality: "ultra", fovThird: 400, fovFirst: "wide", volume: 7, view: "top" })).toEqual({
      ...VIEW_DEFAULTS, sensitivity: LOOK_SENSITIVITY.max, fovThird: SHOULDER.maxHfovDeg, volume: 1,
    });
    expect(normalizeViewPrefs({ sensitivity: 0.5, invertY: true, quality: "low", fovThird: 64, fovFirst: 95, volume: 0.25, view: "first" })).toEqual({
      sensitivity: 0.5, invertY: true, quality: "low", fovThird: 64, fovFirst: 95, volume: 0.25, view: "first",
    });
  });

  it("keeps the person's choice in this browser and resets it", () => {
    useViewSettings.getState().set({ invertY: true, sensitivity: 1.5, view: "first" });
    expect(JSON.parse(window.localStorage.getItem(VIEW_SETTINGS_KEY)!)).toEqual({ ...VIEW_DEFAULTS, sensitivity: 1.5, invertY: true, view: "first" });
    expect(useViewSettings.getState().invertY).toBe(true);
    useViewSettings.getState().reset();
    expect(useViewSettings.getState().sensitivity).toBe(1);
    // Reset puts the settings back, never the view on screen.
    expect(useViewSettings.getState().view).toBe("first");
  });
});

describe("eye-level effects and readout", () => {
  it("pulls lamp sprites toward the camera, never more than half the way", () => {
    expect(eyePull("blink", 0.6, 10)).toBeCloseTo(0.3);
    expect(eyePull("pulse", 6, 20)).toBeCloseTo(3);
    expect(eyePull("pulse", 6, 2)).toBeCloseTo(1);
  });

  it("shows the frame rate and the eye level's tier in the development readout", () => {
    const stats: FrameStats = { drawCalls: 250, triangles: 812_000, frameMs: 16.7, cpuMs: 1.4, tiles: 0, tilesLoading: 0, plateLevel: "3D", actors: 9, tier: "high" };
    expect(statsText(stats)).toBe("60 fps  16.7 ms (1.4 cpu)  250 calls  812.0k tris\neye level, high tier  9 actors");
    expect(statsText({ ...stats, plateLevel: "M2", tiles: 12, tier: "" })).toContain("12 tiles M2 (0 loading)");
  });
});

describe("pointer input at eye level", () => {
  let el: HTMLDivElement;
  let lockedTo: Element | null = null;

  beforeEach(() => {
    el = document.createElement("div");
    Object.defineProperty(el, "clientWidth", { value: 800 });
    Object.defineProperty(el, "clientHeight", { value: 600 });
    el.getBoundingClientRect = () => ({ left: 0, top: 0, right: 800, bottom: 600, width: 800, height: 600, x: 0, y: 0, toJSON: () => ({}) });
    el.setPointerCapture = vi.fn();
    el.hasPointerCapture = () => false;
    el.releasePointerCapture = vi.fn();
    document.body.appendChild(el);
    Object.defineProperty(document, "pointerLockElement", { configurable: true, get: () => lockedTo });
  });
  afterEach(() => {
    el.remove();
    lockedTo = null;
  });

  const pointer = (type: string, init: Record<string, number | string>) => {
    const e = new MouseEvent(type, { bubbles: true, clientX: Number(init.clientX ?? 0), clientY: Number(init.clientY ?? 0), button: Number(init.button ?? 0) });
    for (const key of ["pointerId", "pointerType", "movementX", "movementY"]) {
      if (key in init) Object.defineProperty(e, key, { value: init[key] });
    }
    el.dispatchEvent(e);
  };

  it("taps where the pointer was pressed and released, and turns on a drag", () => {
    const rig = new ShoulderRig();
    const cb = { tap: vi.fn(), hover: vi.fn(), leave: vi.fn(), moved: vi.fn() };
    const detach = attachOrbitInput(el, rig, cb);
    pointer("pointerdown", { clientX: 100, clientY: 120, pointerId: 1, pointerType: "mouse" });
    pointer("pointerup", { clientX: 100, clientY: 120, pointerId: 1, pointerType: "mouse" });
    expect(cb.tap).toHaveBeenCalledWith(100, 120);
    const yaw = rig.yaw;
    pointer("pointerdown", { clientX: 100, clientY: 120, pointerId: 2, pointerType: "mouse" });
    pointer("pointermove", { clientX: 160, clientY: 120, pointerId: 2, pointerType: "mouse" });
    pointer("pointerup", { clientX: 160, clientY: 120, pointerId: 2, pointerType: "mouse" });
    expect(rig.yaw).not.toBe(yaw);
    expect(cb.moved).toHaveBeenCalled();
    expect(cb.tap).toHaveBeenCalledTimes(1);
    detach();
  });

  it("with the pointer locked turns on plain movement and works what is under the reticle", () => {
    const rig = new ShoulderRig();
    const cb = { tap: vi.fn(), hover: vi.fn(), leave: vi.fn(), moved: vi.fn() };
    const detach = attachOrbitInput(el, rig, cb);
    lockedTo = el;
    const yaw = rig.yaw;
    pointer("pointermove", { movementX: 40, movementY: 0, pointerId: 1, pointerType: "mouse" });
    expect(rig.yaw).toBeCloseTo(yaw - 40 * SHOULDER.lockRate);
    expect(cb.hover).toHaveBeenCalledWith(400, 300);
    pointer("pointerdown", { clientX: 5, clientY: 5, pointerId: 1, pointerType: "mouse", button: 0 });
    expect(cb.tap).toHaveBeenCalledWith(400, 300);
    detach();
  });
});

describe("floating labels at eye level", () => {
  afterEach(cleanup);

  it("places a visible crew member's plate over their head and hides one behind the wall", () => {
    const runtime = eyeStage();
    runtime.poses.set("seen", { id: "seen", x: -1, y: 0, z: -2, yaw: 0, height: 1.7, moving: false });
    runtime.poses.set("hidden", { id: "hidden", x: 0, y: 0, z: -9, yaw: 0, height: 1.7, moving: false });
    const plate = (id: string) => ({ id, name: id, rank: "Ensign", status: "On duty", statusKey: "working", accent: null });
    const { container } = render(<FloatingLabels runtime={runtime} plates={[plate("seen"), plate("hidden")]} station={null} deck={runtime.deck} />);
    act(() => { for (const fn of runtime.afterFrame) fn(); });
    const [seen, hidden] = [...container.querySelectorAll<HTMLElement>(".verse-plate")];
    const head = runtime.toScreen(-1, 1.82, -2)!;
    expect(seen.style.transform).toBe(`translate(${Math.round(head.x)}px, ${Math.round(head.y)}px)`);
    expect(hidden.style.transform).toBe("translate(-9999px, -9999px)");
  });

  it("offers the station within reach as a prompt below the middle of the view, never on the commander's back", () => {
    const runtime = eyeStage();
    const station: Station = { id: "lift", kind: "lift", room: null, x: 0, y: 0, z: 0, sockets: {} };
    const { container, rerender } = render(<FloatingLabels runtime={runtime} plates={[]} station={{ station, name: "Turbolift", action: "Ride", key: "E" }} deck={runtime.deck} />);
    act(() => { for (const fn of runtime.afterFrame) fn(); });
    const label = container.querySelector<HTMLElement>(".verse-plate")!;
    expect(label.style.transform).toBe(`translate(${W / 2}px, ${Math.round(H * PROMPT_AT)}px)`);
    // Pointed at (no key), it rides on the station's spot.
    rerender(<FloatingLabels runtime={runtime} plates={[]} station={{ station, name: "Turbolift", action: "Ride", key: null }} deck={runtime.deck} />);
    act(() => { for (const fn of runtime.afterFrame) fn(); });
    const spot = runtime.toScreen(0, 1.2, 0)!;
    expect(label.style.transform).toBe(`translate(${Math.round(spot.x)}px, ${Math.round(spot.y)}px)`);
  });

  it("hides a pointed-at station label whose spot is behind the camera", () => {
    const runtime = eyeStage();
    const station: Station = { id: "aft", kind: "games", room: null, x: 0, y: 0, z: 8, sockets: {} };
    const { container } = render(<FloatingLabels runtime={runtime} plates={[]} station={{ station, name: "Simulator", action: "Play", key: null }} deck={runtime.deck} />);
    act(() => { for (const fn of runtime.afterFrame) fn(); });
    expect(container.querySelector<HTMLElement>(".verse-plate")!.style.transform).toBe("translate(-9999px, -9999px)");
  });
});
