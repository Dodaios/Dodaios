import { describe, expect, it } from "vitest";
import { Vector3 } from "three";
import { GROUND_Y, planCity } from "./cityPlan";
import { aimDirection, aimFromForward, cursorTurn, DEFAULT_BINDINGS, flightInput, keyLabel, loadBindings, moveAim, rebind, saveBindings, steerTowards } from "./courierControls";
import { engageAutopilot, FLIGHT, forwardOf, NO_INPUT, parkedState, stepFlight, type FlightInput, type FlightState } from "./courierFlight";
import { buildCourierWorld, rayDistance, sphereContact } from "./courierWorld";
import { buildOfficeLayout } from "./officeLayout";
import { buildNavGrid, findPath, isWalkable, randomWalkablePoint } from "./officeNav";
import { COURIER, onSkyPad } from "./skyPad";

const staff = Array.from({ length: 8 }, (_, i) => ({ agentId: `a${i}`, name: `Agent ${i}`, tier: "specialist" as const, providerLabel: "x", state: "idle" as const, createdMs: i }));
const layout = buildOfficeLayout(staff);
const pad = layout.skyPad!;
const world = buildCourierWorld(planCity(layout.bounds), layout.bounds, pad);
const home = pad.ship;

function fly(s: FlightState, input: Partial<FlightInput>, seconds: number, assist: "arcade" | "simulation" = "arcade") {
  for (let t = 0; t < seconds; t += 1 / 60) stepFlight(s, { ...NO_INPUT, ...input }, 1 / 60, assist, world, home);
  return s;
}

describe("the sky pad", () => {
  it("stands out of the agents floor's east side on the boulevard's line, outside the slab", () => {
    expect(pad.pad.x - pad.pad.r).toBeGreaterThan(layout.bounds.maxX);
    expect(pad.gap.minZ).toBeGreaterThan(layout.bounds.minZ);
    expect(pad.gap.maxZ).toBeLessThan(layout.bounds.maxZ);
    // The courier fits on the deck.
    expect(Math.hypot(COURIER.span / 2, COURIER.length / 2)).toBeLessThan(pad.pad.r);
  });

  it("is walkable from the floor to the hatch, and its courier is solid", () => {
    const grid = buildNavGrid(layout);
    expect(isWalkable(grid, pad.board)).toBe(true);
    expect(onSkyPad(pad, { x: pad.pad.x, z: pad.pad.z })).toBe(true);
    expect(isWalkable(grid, { x: pad.pad.x, z: pad.pad.z })).toBe(false);
    // Off the rim and beside the bridge is air.
    expect(isWalkable(grid, { x: pad.pad.x + pad.pad.r + 1, z: pad.pad.z })).toBe(false);
    expect(isWalkable(grid, { x: (layout.bounds.maxX + pad.bridge.maxX) / 2, z: pad.gap.maxZ + 2 })).toBe(false);
    const path = findPath(grid, layout.spawn, pad.board);
    expect(path).not.toBeNull();
    expect(path!.length).toBeGreaterThan(1);
  });

  it("never sends an idle wanderer out onto the pad", () => {
    const grid = buildNavGrid(layout);
    let seed = 7;
    const rng = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
    for (let i = 0; i < 300; i += 1) {
      const p = randomWalkablePoint(grid, rng)!;
      expect(p.x).toBeLessThanOrEqual(layout.floor.maxX);
    }
  });

  it("offers the courier as a checkpoint beside its hatch, nowhere else", () => {
    const ship = layout.checkpoints.filter((c) => c.id === "ship");
    expect(ship).toHaveLength(1);
    expect(ship[0].x).toBeCloseTo(pad.board.x);
    expect(buildOfficeLayout([]).skyPad).toBeDefined();
    expect(buildOfficeLayout(staff, { variant: "coding" }).skyPad).toBeUndefined();
  });
});

describe("the courier's world", () => {
  it("is solid where the city is and free in the plaza's air", () => {
    expect(sphereContact(world, pad.pad.x, 40, pad.pad.z, 2)).toBeNull();
    expect(sphereContact(world, pad.pad.x, GROUND_Y + 1, pad.pad.z, 2)).not.toBeNull();
    // Inside the office: pushed out.
    const c = (layout.bounds.minX + layout.bounds.maxX) / 2;
    expect(sphereContact(world, c, 1.5, (layout.bounds.minZ + layout.bounds.maxZ) / 2, 2)).not.toBeNull();
  });

  it("measures how far a ray runs before it meets the city", () => {
    const down = rayDistance(world, { x: pad.pad.x, y: 50, z: pad.pad.z }, { x: 0, y: -1, z: 0 }, 1000);
    expect(down).toBeCloseTo(50, 0);
  });
});

describe("the courier's flight", () => {
  it("stands on the pad until it is told to lift off, then climbs", () => {
    const s = parkedState(home);
    fly(s, {}, 1);
    expect(s.landed).toBe(true);
    expect(s.p.y).toBeCloseTo(COURIER.standHeight);
    fly(s, { lift: 1 }, 2);
    expect(s.landed).toBe(false);
    expect(s.p.y).toBeGreaterThan(COURIER.standHeight + 5);
  });

  it("in arcade, climbs and dives steeply and its lift goes straight up or down", () => {
    const s = parkedState(home);
    fly(s, { lift: 1 }, 2);
    fly(s, { throttle: 1 }, 2);
    // Full stick back for a second: the nose comes far up, and stays there when the stick is let go.
    fly(s, { pitch: 1 }, 0.8);
    const climb = forwardOf(s.q).y;
    expect(climb).toBeGreaterThan(0.6);
    fly(s, {}, 1);
    expect(forwardOf(s.q).y).toBeGreaterThan(climb - 0.1);
    // From level flight the sink key sinks fast, and a dive goes down steeply.
    const level = parkedState(home);
    fly(level, { lift: 1 }, 2);
    fly(level, { throttle: 1 }, 2);
    const y = level.p.y;
    fly(level, { lift: -1 }, 1);
    expect(level.p.y).toBeLessThan(y - 10);
    expect(level.v.y).toBeLessThan(-FLIGHT.lift * 0.5);
    fly(level, { pitch: -1 }, 0.8);
    expect(forwardOf(level.q).y).toBeLessThan(-0.6);
  });

  it("in arcade, flies where its nose points at the throttle's speed and levels its wings", () => {
    const s = parkedState(home);
    fly(s, { lift: 1 }, 3);
    fly(s, { throttle: 1 }, 4);
    fly(s, {}, 4);
    const nose = forwardOf(s.q);
    expect(s.v.length()).toBeGreaterThan(FLIGHT.cruise * 0.8);
    expect(s.v.clone().normalize().dot(nose)).toBeGreaterThan(0.95);
    // Wings level: the right wing's height is near zero.
    expect(Math.abs(new Vector3(1, 0, 0).applyQuaternion(s.q).y)).toBeLessThan(0.1);
  });

  it("in simulation, keeps drifting the old way after a turn", () => {
    const s = parkedState(home);
    fly(s, { lift: 1 }, 0.6, "simulation");
    fly(s, { lift: -1 }, 0.6, "simulation");
    fly(s, { throttle: 1 }, 3, "simulation");
    fly(s, { throttle: -1 }, 2, "simulation");
    const before = s.v.clone().normalize();
    fly(s, { yaw: 1 }, 1.2, "simulation");
    const nose = forwardOf(s.q);
    // The nose turned, the velocity mostly did not.
    expect(before.dot(nose)).toBeLessThan(0.9);
    expect(s.v.clone().normalize().dot(before)).toBeGreaterThan(0.95);
  });

  it("boosts past cruise speed and spends its charge doing so", () => {
    const s = parkedState(home);
    fly(s, { lift: 1 }, 3);
    fly(s, { throttle: 1, boost: true }, 3);
    expect(s.v.length()).toBeGreaterThan(FLIGHT.cruise * 1.2);
    expect(s.charge).toBeLessThan(0.6);
  });

  it("never passes through a tower, even at full boost, and flashes its shield", () => {
    const s = parkedState(home);
    const tower = planCity(layout.bounds).towers.find((t) => t.h > 120 && Math.hypot(t.x - home.x, t.z - home.z) > 150)!;
    // Aim at the tower from 120 m out at its mid height.
    const at = new Vector3(tower.x, GROUND_Y + tower.h / 2, tower.z);
    s.landed = false;
    s.p.set(tower.x + 120, at.y, tower.z);
    s.q.setFromAxisAngle(new Vector3(0, 1, 0), Math.PI / 2);
    s.throttle = 1;
    let crossed = false, flashed = false;
    for (let i = 0; i < 400; i += 1) {
      stepFlight(s, { ...NO_INPUT, throttle: 1, boost: true }, 1 / 60, "simulation", world, home);
      if (s.p.x < tower.x) crossed = true;
      if (s.shield > 0.2) flashed = true;
    }
    expect(crossed).toBe(false);
    expect(flashed).toBe(true);
  });

  it("lands itself on the pad from out over the city, gear down", () => {
    const s = parkedState(home);
    s.landed = false; s.gear = 0;
    s.p.set(home.x + 200, 30, home.z - 150);
    s.q.setFromAxisAngle(new Vector3(0, 1, 0), 2.1);
    engageAutopilot(s);
    for (let i = 0; i < 60 * 90 && !s.landed; i += 1) stepFlight(s, NO_INPUT, 1 / 60, "arcade", world, home);
    expect(s.landed).toBe(true);
    expect(s.p.distanceTo(new Vector3(home.x, COURIER.standHeight, home.z))).toBeLessThan(0.01);
    expect(s.gear).toBeCloseTo(1, 1);
  });

  it("lands itself from deep in the city, under the pad and beside the tower too", () => {
    for (const [dx, y, dz] of [[0, -60, 0], [-30, -120, 0], [180, -200, 90]] as const) {
      const s = parkedState(home);
      s.landed = false; s.gear = 0;
      s.p.set(home.x + dx, y, home.z + dz);
      engageAutopilot(s);
      for (let i = 0; i < 60 * 150 && !s.landed; i += 1) stepFlight(s, NO_INPUT, 1 / 60, "arcade", world, home);
      expect(s.landed, `from ${dx},${y},${dz}`).toBe(true);
    }
  });

  it("lets an impact's shake and flash fade while it lands itself and while it stands", () => {
    const s = parkedState(home);
    s.impact = 40; s.shield = 1;
    fly(s, {}, 2);
    expect(s.impact).toBe(0);
    expect(s.shield).toBe(0);
  });

  it("hands the controls back the moment the pilot touches them", () => {
    const s = parkedState(home);
    s.landed = false; s.p.set(home.x + 100, 40, home.z);
    engageAutopilot(s);
    stepFlight(s, { ...NO_INPUT, yaw: 1 }, 1 / 60, "arcade", world, home);
    expect(s.autopilot).toBeNull();
  });
});

describe("the courier's controls", () => {
  it("reads held keys and a gamepad into one input", () => {
    const input = flightInput(new Set(["KeyW", "KeyA"]), DEFAULT_BINDINGS, { axes: [0, 0, 0.9, 0], buttons: [{ value: 1, pressed: true }] }, false);
    expect(input.throttle).toBe(1);
    expect(input.yaw).toBe(-1);
    expect(input.roll).toBeGreaterThan(0.8);
    expect(input.boost).toBe(true);
    // A resting stick inside the dead zone is nothing.
    expect(flightInput(new Set(), DEFAULT_BINDINGS, { axes: [0.1, -0.1, 0, 0], buttons: [] }, false).yaw).toBe(0);
  });

  it("aims with the mouse: the ship turns to the aim and keeps flying there after the mouse stops", () => {
    const s = parkedState(home);
    fly(s, { lift: 1 }, 2);
    fly(s, { throttle: 1 }, 2);
    const aim = aimFromForward(forwardOf(s.q));
    // One short flick of the mouse up and to the right, then nothing more.
    moveAim(aim, 260, -180, false);
    const target = aimDirection(aim);
    for (let i = 0; i < 60 * 3; i += 1) stepFlight(s, steerTowards({ ...NO_INPUT }, s.q, target), 1 / 60, "arcade", world, home);
    // The nose came round onto the aim by itself: up and to the right.
    expect(forwardOf(s.q).angleTo(target)).toBeLessThan(0.12);
    expect(forwardOf(s.q).y).toBeGreaterThan(0.3);
    // And the velocity followed it.
    expect(s.v.clone().normalize().angleTo(target)).toBeLessThan(0.25);
    // Inverted pitch aims the other way.
    expect(moveAim({ yaw: 0, pitch: 0 }, 0, -100, true).pitch).toBeLessThan(0);
  });

  it("steers with the cursor when the mouse cannot be captured: a resting cursor off the middle keeps turning", () => {
    // In the still zone nothing turns.
    expect(cursorTurn({ yaw: 0, pitch: 0 }, 0.05, -0.05, 1)).toEqual({ yaw: 0, pitch: 0 });
    // Right of the middle turns right (yaw falls), above it pitches up, and each frame adds the same again.
    const aim = { yaw: 0, pitch: 0 };
    for (let i = 0; i < 30; i += 1) cursorTurn(aim, 0.6, 0.4, 1 / 60);
    const half = { ...aim };
    for (let i = 0; i < 30; i += 1) cursorTurn(aim, 0.6, 0.4, 1 / 60);
    expect(half.yaw).toBeLessThan(0);
    expect(half.pitch).toBeGreaterThan(0);
    expect(aim.yaw).toBeCloseTo(half.yaw * 2, 6);
    // Further out turns faster.
    expect(Math.abs(cursorTurn({ yaw: 0, pitch: 0 }, 1, 0, 1).yaw)).toBeGreaterThan(Math.abs(cursorTurn({ yaw: 0, pitch: 0 }, 0.5, 0, 1).yaw));
  });

  it("rebinds a key to one action and remembers it", () => {
    const next = rebind(DEFAULT_BINDINGS, "boost", "KeyW");
    expect(next.boost).toEqual(["KeyW"]);
    expect(next.throttleUp).toEqual([]);
    const store = new Map<string, string>();
    saveBindings(next, { setItem: (k, v) => store.set(k, v) });
    expect(loadBindings({ getItem: (k) => store.get(k) ?? null }).boost).toEqual(["KeyW"]);
    expect(loadBindings({ getItem: () => "{broken" }).boost).toEqual(DEFAULT_BINDINGS.boost);
    expect(keyLabel("KeyW")).toBe("W");
    expect(keyLabel("ArrowUp")).toBe("↑");
  });
});
