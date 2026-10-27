/**
 * The three views (bird's-eye, third and first person): the switch's state
 * machine and keys, the wheel's hand-over between third and first person,
 * the first-person camera, the shared shooter mouse look (eye level and
 * duel), the body facing the view while walking, the input mapping with the
 * pointer locked or free, and the tool rail's switch.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DuelCamera, DUEL_CAMERA } from "../../duel/duelCamera";
import { Toolbar } from "../../hud/DeckBar";
import { CommanderControl } from "../../life/control";
import { LOOK_SENSITIVITY, MOUSE_LOOK_RATE, clampSensitivity, lookDelta, requestMouseLook } from "./mouseLook";
import { attachOrbitInput, wheelFactor } from "./orbitInput";
import { SHOULDER, ShoulderRig, type SegmentTest } from "./shoulderRig";
import {
  STRAFE_LEAN, VIEW_ORDER, bodyFacing, controlModeOf, cycleView, isShooterView, keyForView, normalizeView, resolveView,
  viewForKey, zoomStep,
} from "./viewMode";

const body = (x: number, z: number, heading = Math.PI, moving = false) => ({ x, y: 0, z, heading, moving });
const LIMITS = { min: SHOULDER.minDistance, max: SHOULDER.maxDistance, handover: SHOULDER.handover };
/** One 100 px wheel notch in and out. */
const IN = wheelFactor(-100, 0);
const OUT = wheelFactor(100, 0);
const settle = (rig: ShoulderRig, seconds = 1, test?: SegmentTest) => {
  for (let i = 0; i < seconds * 60; i++) rig.update(1 / 60, body(0, 0), test);
};

describe("view state machine", () => {
  it("cycles bird's-eye, third and first person with V, skipping first person without an eye-level scene", () => {
    expect(VIEW_ORDER).toEqual(["overview", "third", "first"]);
    expect(cycleView("overview", true)).toBe("third");
    expect(cycleView("third", true)).toBe("first");
    expect(cycleView("first", true)).toBe("overview");
    expect(cycleView("overview", false)).toBe("third");
    expect(cycleView("third", false)).toBe("overview");
    // A remembered first person on a deck without the scene counts as third.
    expect(cycleView("first", false)).toBe("overview");
  });

  it("picks a view directly with 1, 2 and 3 (top row and keypad) and shows those keys", () => {
    expect(viewForKey("Digit1")).toBe("overview");
    expect(viewForKey("Numpad2")).toBe("third");
    expect(viewForKey("Digit3")).toBe("first");
    expect(viewForKey("KeyV")).toBeNull();
    expect(VIEW_ORDER.map(keyForView)).toEqual(["1", "2", "3"]);
  });

  it("shows first person only where it can, and gives shooter look to the eye-level views", () => {
    expect(resolveView("first", false)).toBe("third");
    expect(resolveView("first", true)).toBe("first");
    expect(controlModeOf("overview")).toBe("overview");
    expect(controlModeOf("third")).toBe("follow");
    expect(controlModeOf("first")).toBe("follow");
    expect(isShooterView("third", true)).toBe(true);
    expect(isShooterView("first", true)).toBe(true);
    expect(isShooterView("overview", true)).toBe(false);
    expect(isShooterView("third", false)).toBe(false);
    expect(normalizeView("first")).toBe("first");
    expect(normalizeView("ego")).toBe("third");
    expect(normalizeView(undefined)).toBe("third");
  });
});

describe("zoom and the hand-over between third and first person", () => {
  it("scales the third-person distance inside its range", () => {
    let s = zoomStep({ person: "third", distance: 2.4, push: 0 }, OUT, LIMITS);
    expect(s.distance).toBeCloseTo(2.4 * OUT);
    for (let i = 0; i < 30; i++) s = zoomStep(s, OUT, LIMITS);
    expect(s).toEqual({ person: "third", distance: SHOULDER.maxDistance, push: 0 });
    expect(zoomStep(s, 1, LIMITS)).toBe(s);
    expect(zoomStep(s, Number.NaN, LIMITS)).toBe(s);
  });

  it("goes to first person only when pushed on past the closest distance", () => {
    let s = zoomStep({ person: "third", distance: 1.25, push: 0 }, IN, LIMITS);
    // The notch that reaches the closest distance stops there.
    expect(s.person).toBe("third");
    expect(s.distance).toBe(SHOULDER.minDistance);
    // A step back out clears the push.
    expect(zoomStep(s, OUT, LIMITS).push).toBe(0);
    s = zoomStep(s, IN, LIMITS);
    expect(s).toEqual({ person: "first", distance: SHOULDER.minDistance, push: 0 });
  });

  it("stays in first person scrolling in and comes back out to third at the closest distance", () => {
    const first = { person: "first" as const, distance: SHOULDER.minDistance, push: 0 };
    expect(zoomStep(first, IN, LIMITS).person).toBe("first");
    // A small trackpad nudge out is not enough; a notch is.
    const nudge = zoomStep(first, wheelFactor(20, 0), LIMITS);
    expect(nudge.person).toBe("first");
    expect(zoomStep(nudge, wheelFactor(80, 0), LIMITS)).toEqual({ person: "third", distance: SHOULDER.minDistance, push: 0 });
    expect(zoomStep(first, OUT, LIMITS).person).toBe("third");
  });

  it("hands over through the rig and reports the new person", () => {
    const rig = new ShoulderRig();
    rig.distance = 1.3;
    expect(rig.zoom(IN)).toBeNull();
    expect(rig.zoom(IN)).toBe("first");
    expect(rig.person).toBe("first");
    expect(rig.zoom(IN)).toBeNull();
    expect(rig.zoom(OUT)).toBe("third");
    expect(rig.distance).toBe(SHOULDER.minDistance);
  });

  it("eases the wheel's distance instead of jumping", () => {
    const rig = new ShoulderRig();
    rig.snapBehind(Math.PI);
    rig.update(1 / 60, body(0, 0));
    rig.distance = 4;
    rig.update(1 / 60, body(0, 0));
    expect(rig.actual).toBeGreaterThan(SHOULDER.distance);
    expect(rig.actual).toBeLessThan(3);
    settle(rig);
    expect(rig.actual).toBeCloseTo(4, 2);
    rig.distance = 1.5;
    rig.update(1 / 60, body(0, 0));
    expect(rig.actual).toBeGreaterThan(3);
    settle(rig);
    expect(rig.actual).toBeCloseTo(1.5, 2);
  });
});

describe("first-person camera", () => {
  it("sits at eye height just in front of the face and looks where the mouse points", () => {
    const rig = new ShoulderRig();
    rig.setPerson("first");
    rig.snapBehind(Math.PI);
    rig.update(1 / 60, body(2, 3));
    expect(rig.firstShare).toBe(1);
    expect(rig.position.x).toBeCloseTo(2);
    expect(rig.position.y).toBeCloseTo(SHOULDER.eyeHeight);
    expect(rig.position.z).toBeCloseTo(3 - SHOULDER.eyeForward);
    // Level and straight ahead (−Z).
    expect(rig.target.y).toBeCloseTo(rig.position.y);
    expect(rig.target.z).toBeLessThan(rig.position.z);
  });

  it("blends from the shoulder into the eyes, field of view included", () => {
    const rig = new ShoulderRig();
    rig.snapBehind(Math.PI);
    settle(rig, 0.2);
    expect(rig.hfov()).toBeCloseTo(SHOULDER.hfovDeg);
    rig.setPerson("first");
    rig.update(1 / 60, body(0, 0));
    expect(rig.firstShare).toBeGreaterThan(0);
    expect(rig.firstShare).toBeLessThan(1);
    expect(rig.position.z).toBeGreaterThan(0.2);
    settle(rig, 0.6);
    expect(rig.firstShare).toBe(1);
    expect(rig.position.z).toBeCloseTo(-SHOULDER.eyeForward);
    expect(rig.hfov()).toBeCloseTo(SHOULDER.firstHfovDeg);
    rig.fovFirst = 100;
    expect(rig.hfov()).toBeCloseTo(100);
    rig.fovFirst = 500;
    expect(rig.hfov()).toBeCloseTo(SHOULDER.maxHfovDeg);
  });

  it("looks further up and down than third person, and comes back inside third person's limits", () => {
    const rig = new ShoulderRig();
    rig.setPerson("first");
    rig.look(0, 1e6, true);
    expect(rig.pitch).toBeCloseTo(SHOULDER.firstMaxPitch);
    rig.setPerson("third");
    rig.update(1 / 60, body(0, 0));
    expect(rig.pitch).toBeCloseTo(SHOULDER.maxPitch);
  });

  it("never puts the eyes through a wall the face is against", () => {
    const rig = new ShoulderRig();
    rig.setPerson("first");
    rig.snapBehind(Math.PI);
    // A wall 0.08 m in front of the body's axis (z = −0.08).
    const test: SegmentTest = (from, to) => (to.z < -0.08 && from.z >= -0.08 ? (from.z + 0.08) / (from.z - to.z) : null);
    rig.update(1 / 60, body(0, 0), test);
    expect(rig.position.z).toBeGreaterThanOrEqual(-0.08);
  });
});

describe("shooter mouse look", () => {
  it("applies the sensitivity and the inverted axis the same way everywhere", () => {
    expect(lookDelta(10, 10, { sensitivity: 1, invertY: false })).toEqual({ yaw: 10 * MOUSE_LOOK_RATE, pitch: 10 * MOUSE_LOOK_RATE });
    expect(lookDelta(10, 10, { sensitivity: 2, invertY: true })).toEqual({ yaw: 20 * MOUSE_LOOK_RATE, pitch: -20 * MOUSE_LOOK_RATE });
    expect(clampSensitivity(99)).toBe(LOOK_SENSITIVITY.max);
    expect(clampSensitivity(Number.NaN)).toBe(1);
  });

  it("turns the eye-level views and the duel by the same angle for the same mouse movement", () => {
    const rig = new ShoulderRig();
    const duel = new DuelCamera();
    rig.sensitivity = duel.sensitivity = 1.7;
    const yaw0 = rig.yaw;
    rig.look(50, 0, true);
    duel.look(50, 0);
    expect(DUEL_CAMERA.lookRate).toBe(SHOULDER.lockRate);
    expect(yaw0 - rig.yaw).toBeCloseTo(-duel.yaw, 9);
    // Mouse down looks down in both (the duel's pitch is positive up).
    rig.look(0, 30, true);
    duel.look(0, 30);
    expect(rig.pitch).toBeGreaterThan(SHOULDER.pitch);
    expect(duel.pitch).toBeLessThan(0);
  });

  it("asks for raw mouse movement and falls back to a plain lock where it is refused", async () => {
    const el = document.createElement("div");
    const calls: unknown[] = [];
    el.requestPointerLock = vi.fn((options?: unknown) => {
      calls.push(options);
      return options ? Promise.reject(new Error("not supported")) : Promise.resolve();
    }) as unknown as typeof el.requestPointerLock;
    requestMouseLook(el);
    await new Promise((r) => setTimeout(r, 0));
    expect(calls).toEqual([{ unadjustedMovement: true }, undefined]);
  });
});

describe("the commander faces the view while walking", () => {
  const view = Math.PI; // looking toward −Z

  it("faces the view walking forward and leans at most 45 degrees into a strafe", () => {
    expect(bodyFacing(view, { x: 0, z: -1 })).toEqual({ yaw: Math.PI, reverse: false });
    const right = bodyFacing(view, { x: 1, z: 0 }); // the view's right is +X
    expect(right.reverse).toBe(false);
    expect(Math.abs(Math.atan2(Math.sin(right.yaw - view), Math.cos(right.yaw - view)))).toBeCloseTo(STRAFE_LEAN);
  });

  it("walks backwards facing the view, the walk played in reverse", () => {
    const back = bodyFacing(view, { x: 0, z: 1 });
    expect(back.reverse).toBe(true);
    expect(Math.cos(back.yaw - view)).toBeCloseTo(1);
    const out = { yaw: 0, reverse: false };
    expect(bodyFacing(view, { x: 0, z: 1 }, out)).toBe(out);
  });

  it("walks relative to the view in first person as in third (strafing with A and D)", () => {
    const rig = new ShoulderRig();
    rig.setPerson("first");
    rig.yaw = Math.PI / 2; // looking toward +X
    const control = new CommanderControl();
    control.setKey("right", true);
    // Looking toward +X, the screen's right is +Z.
    const d = control.directionFrom(rig)!;
    expect(d.x).toBeCloseTo(0);
    expect(d.z).toBeCloseTo(1);
  });
});

describe("shooter input mapping", () => {
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
    const e = new MouseEvent(type, { bubbles: true, clientX: Number(init.clientX ?? 0), clientY: Number(init.clientY ?? 0), button: Number(init.button ?? 0), buttons: Number(init.buttons ?? 0) });
    for (const key of ["pointerId", "pointerType", "movementX", "movementY"]) {
      if (key in init) Object.defineProperty(e, key, { value: init[key] });
    }
    el.dispatchEvent(e);
  };
  const callbacks = () => ({ tap: vi.fn(), hover: vi.fn(), leave: vi.fn(), moved: vi.fn(), aim: vi.fn(), capture: vi.fn(), zoom: vi.fn() });

  it("takes the mouse on a click with the mouse free; a finger still taps", () => {
    const rig = new ShoulderRig();
    const cb = callbacks();
    const detach = attachOrbitInput(el, rig, cb);
    pointer("pointerdown", { clientX: 100, clientY: 120, pointerId: 1, pointerType: "mouse" });
    pointer("pointerup", { clientX: 100, clientY: 120, pointerId: 1, pointerType: "mouse" });
    expect(cb.capture).toHaveBeenCalledTimes(1);
    expect(cb.tap).not.toHaveBeenCalled();
    pointer("pointerdown", { clientX: 100, clientY: 120, pointerId: 2, pointerType: "touch" });
    pointer("pointerup", { clientX: 100, clientY: 120, pointerId: 2, pointerType: "touch" });
    expect(cb.tap).toHaveBeenCalledWith(100, 120);
    detach();
  });

  it("with the mouse taken: movement turns the view, the left button aims at the crosshair, the right does nothing", () => {
    const rig = new ShoulderRig();
    const cb = callbacks();
    const detach = attachOrbitInput(el, rig, cb);
    lockedTo = el;
    const yaw = rig.yaw;
    pointer("pointermove", { movementX: -40, movementY: 0, pointerId: 1, pointerType: "mouse" });
    const turned = rig.yaw - yaw;
    expect(Math.atan2(Math.sin(turned), Math.cos(turned))).toBeCloseTo(40 * SHOULDER.lockRate);
    pointer("pointerdown", { clientX: 5, clientY: 5, pointerId: 1, pointerType: "mouse", button: 2 });
    expect(cb.aim).not.toHaveBeenCalled();
    pointer("pointerdown", { clientX: 5, clientY: 5, pointerId: 1, pointerType: "mouse", button: 0 });
    expect(cb.aim).toHaveBeenCalledWith(400, 300);
    expect(cb.tap).not.toHaveBeenCalled();
    expect(cb.capture).not.toHaveBeenCalled();
    detach();
  });

  it("with the mouse taken: the left button pressed while the right is held (a pointermove chord) still aims; no menu", () => {
    const rig = new ShoulderRig();
    const cb = callbacks();
    const detach = attachOrbitInput(el, rig, cb);
    lockedTo = el;
    pointer("pointerdown", { pointerId: 1, pointerType: "mouse", button: 2, buttons: 2 });
    expect(cb.aim).not.toHaveBeenCalled();
    pointer("pointermove", { pointerId: 1, pointerType: "mouse", button: 0, buttons: 3 });
    expect(cb.aim).toHaveBeenCalledTimes(1);
    pointer("pointermove", { pointerId: 1, pointerType: "mouse", buttons: 3, movementX: 4 });
    expect(cb.aim).toHaveBeenCalledTimes(1);
    const menu = new MouseEvent("contextmenu", { bubbles: true, cancelable: true, button: 2 });
    el.dispatchEvent(menu);
    expect(menu.defaultPrevented).toBe(true);
    detach();
  });

  it("zooms through the stage so it can hand over (wheel down moves out)", () => {
    const rig = new ShoulderRig();
    const cb = callbacks();
    const detach = attachOrbitInput(el, rig, cb);
    el.dispatchEvent(new WheelEvent("wheel", { deltaY: 100, cancelable: true }));
    expect(cb.zoom).toHaveBeenCalledWith(OUT);
    expect(OUT).toBeGreaterThan(1);
    expect(rig.distance).toBe(SHOULDER.distance);
    detach();
  });
});

describe("the view switch on the tool rail", () => {
  afterEach(cleanup);
  const t = (key: string) => key;
  const props = { t, onLift: vi.fn(), onCommander: vi.fn(), onHelp: vi.fn() };

  it("shows the three views with their keys, the one on screen pressed", () => {
    const onView = vi.fn();
    render(<Toolbar {...props} view="first" firstAvailable onView={onView} />);
    const buttons = screen.getByRole("group", { name: "verse.tools.view" }).querySelectorAll("button");
    expect([...buttons].map((b) => b.dataset.view)).toEqual(["overview", "third", "first"]);
    expect([...buttons].map((b) => b.getAttribute("aria-pressed"))).toEqual(["false", "false", "true"]);
    expect([...buttons].map((b) => b.querySelector("kbd")?.textContent)).toEqual(["1", "2", "3"]);
    fireEvent.click(buttons[0]);
    expect(onView).toHaveBeenCalledWith("overview");
  });

  it("offers first person only where the deck can show it", () => {
    render(<Toolbar {...props} view="third" firstAvailable={false} onView={vi.fn()} />);
    const first = screen.getByTitle("verse.tools.first_unavailable") as HTMLButtonElement;
    expect(first.disabled).toBe(true);
  });
});
