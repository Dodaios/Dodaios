import { describe, expect, it } from "vitest";
import { syntheticDeck } from "../testing/syntheticDeck";
import { socketPose } from "./actor";
import { clipFor } from "./clips";
import { litSlots, lookForLevel } from "./look";
import { angleDelta, avoidance, lerpAngle, PathFollower, sidestep, turnPace, turnToward, wrapAngle, yawTo } from "./locomotion";
import { parseContract } from "./characters";
import { patchRoomLight, probeAt, insidePolygon } from "./roomLight";
import { ShaderLib } from "three";

const deck = syntheticDeck();

describe("socket poses", () => {
  const seat = deck.sockets.find((s) => s.kind === "seat" && s.id === "pit_p_2")!;

  it("seats a body just behind the seat centre, facing the console", () => {
    const pose = socketPose(deck, seat, "sit_type");
    expect(pose.yaw).toBeCloseTo(Math.PI, 9);
    // Facing −z, so "behind" is +z.
    expect(pose.z).toBeCloseTo(seat.z + 0.06, 9);
    expect(pose.x).toBeCloseTo(seat.x, 9);
  });

  it("stands a waiting body behind the chair when the console has no stand socket", () => {
    const pose = socketPose(deck, seat, "stand_wait");
    expect(pose.z).toBeGreaterThan(seat.z + 0.5);
  });

  it("uses the console's own stand socket when the cook placed one", () => {
    const withStand = { ...deck, sockets: [...deck.sockets, { ...seat, kind: "stand" as const, x: seat.x + 1.5, z: seat.z + 0.4, yaw: 2.8 }] };
    expect(socketPose(withStand, seat, "stand_alert")).toMatchObject({ x: seat.x + 1.5, z: seat.z + 0.4, yaw: 2.8 });
  });
});

describe("clips", () => {
  it("plays the best clip the body has", () => {
    expect(clipFor("sit_type", new Set(["A_Sit_Idle", "A_Sit_Type"]))).toBe("A_Sit_Type");
    expect(clipFor("sit_type", new Set(["A_Sit_Idle"]))).toBe("A_Sit_Idle");
    expect(clipFor("stand_wait", new Set(["A_Idle"]))).toBe("A_Idle");
    expect(clipFor("sleep", new Set(["A_Idle"]))).toBeNull();
  });
});

describe("rank looks", () => {
  it("lights the plate slots of the rank, top row first", () => {
    expect(litSlots("010|000")).toEqual([1]);
    expect(litSlots("111|101")).toEqual([0, 1, 2, 3, 5]);
  });

  it("dresses by tier from the level", () => {
    expect(lookForLevel(1, null).tier).toBe("deck");
    expect(lookForLevel(14, "#ff0000")).toMatchObject({ tier: "line", accent: "#ff0000", plate: "101|000" });
    expect(lookForLevel(50, null).tier).toBe("flag");
  });
});

describe("locomotion", () => {
  it("measures yaw so that 0 faces +z and turns the short way round", () => {
    expect(yawTo(0, 0, 0, 1)).toBeCloseTo(0, 9);
    expect(yawTo(0, 0, 1, 0)).toBeCloseTo(Math.PI / 2, 9);
    expect(angleDelta(3, -3)).toBeCloseTo(2 * Math.PI - 6, 9);
    const turned = turnToward(0, Math.PI / 2, 2, 0.1);
    expect(turned).toBeGreaterThan(0);
    expect(turned).toBeLessThanOrEqual(0.2 + 1e-9);
  });

  it("keeps yaw wrapped and turns the short way (regression: walking at 35 % pace)", () => {
    expect(wrapAngle(3 * Math.PI)).toBeCloseTo(Math.PI, 9);
    expect(wrapAngle(-3.5)).toBeCloseTo(2 * Math.PI - 3.5, 9);
    // Facing 180° and heading −2.5 rad: 0.64 rad apart the short way, not 5.6.
    let yaw = Math.PI;
    for (let i = 0; i < 200; i++) {
      yaw = turnToward(yaw, -2.5, 5.5, 1 / 60);
      expect(yaw).toBeGreaterThan(-Math.PI - 1e-9);
      expect(yaw).toBeLessThanOrEqual(Math.PI + 1e-9);
    }
    expect(yaw).toBeCloseTo(-2.5, 3);
    expect(turnPace(Math.PI, -Math.PI + 0.01)).toBeGreaterThan(0.99);
    expect(turnPace(0, Math.PI / 2)).toBeCloseTo(0.35, 9);
    // Settling from 170° to −170° goes through 180°, not through 0.
    const mid = lerpAngle((170 * Math.PI) / 180, (-170 * Math.PI) / 180, 0.5);
    expect(Math.abs(mid)).toBeCloseTo(Math.PI, 9);
  });

  it("walks a path at the given distance per step and reports the end", () => {
    const f = new PathFollower([{ x: 0, z: 0 }, { x: 3, z: 0 }, { x: 3, z: 4 }]);
    let at = f.advance({ x: 0, z: 0 }, 2);
    expect(at).toEqual({ x: 2, z: 0 });
    expect(f.remaining(at)).toBeCloseTo(5, 9);
    at = f.advance(at, 3);
    expect(at.x).toBeCloseTo(3, 9);
    expect(at.z).toBeCloseTo(2, 9);
    at = f.advance(at, 10);
    expect(at).toEqual({ x: 3, z: 4 });
    expect(f.done).toBe(true);
  });

  it("steps aside from a body dead ahead and slows behind a walker", () => {
    const self = { x: 0, z: 0, yaw: 0 };
    const ahead = avoidance(self, [{ x: 0.02, z: 0.6, moving: true }]);
    expect(ahead.side).not.toBe(0);
    expect(ahead.speed).toBeLessThan(1);
    expect(avoidance(self, [{ x: 0, z: -0.6, moving: true }])).toEqual({ side: 0, speed: 1 });
    expect(avoidance(self, [{ x: 2, z: 0.5, moving: false }])).toEqual({ side: 0, speed: 1 });
  });

  it("never sidesteps into a wall", () => {
    const by = { x: -0.7, z: -3 };
    // Facing +z, left is +x: into the wall at x = 0.
    expect(sidestep(deck.nav, by, 0, 0.5)).toEqual(by);
    expect(sidestep(deck.nav, by, 0, -0.5).x).toBeCloseTo(-1.2, 9);
  });
});

describe("room light", () => {
  const rooms = [{ id: "a", name: "A", floorY: 0, polygon: [[0, 0], [10, 0], [10, 10], [0, 10]] as [number, number][], main: true }];
  const probe = (room: string, x: number) => ({ room, x, y: 1.4, z: 5, sh: Array.from({ length: 9 }, () => [0, 0, 0] as [number, number, number]) });

  it("finds the room a point is in", () => {
    expect(insidePolygon(5, 5, rooms[0].polygon)).toBe(true);
    expect(insidePolygon(15, 5, rooms[0].polygon)).toBe(false);
  });

  it("uses the probe of the room the actor stands in, else the nearest", () => {
    const probes = [probe("a", 9), probe("b", 11)];
    expect(probeAt({ rooms, probes }, 9.5, 0, 5)?.room).toBe("a");
    expect(probeAt({ rooms, probes }, 10.5, 0, 5)?.room).toBe("b");
  });
});

describe("room light shader patch", () => {
  it("replaces the environment's diffuse light with the room probe after the includes (regression: probes never applied)", () => {
    const patched = patchRoomLight(ShaderLib.physical.fragmentShader);
    expect(patched).toContain("uniform vec3 verseRoomSH[ 9 ];");
    const after = patched.slice(patched.indexOf("#include <lights_fragment_maps>"));
    expect(after.startsWith("#include <lights_fragment_maps>\n#if defined( RE_IndirectDiffuse ) && defined( USE_ENVMAP )")).toBe(true);
    expect(after).toContain("iblIrradiance = shGetIrradianceAt");
    expect(after).toContain("irradiance += shGetIrradianceAt");
    // It runs before the lights are summed.
    expect(patched.indexOf("iblIrradiance = shGetIrradianceAt")).toBeLessThan(patched.indexOf("#include <lights_fragment_end>"));
  });
});

describe("character contract", () => {
  it("accepts the character pipeline's file and rejects a broken one", () => {
    const tier = { M_Uniform: "#000", M_Trim: "#000", M_Cap: "#000", tile: "#000", cap: true };
    const good = { version: 1, seatHeight: 0.46, skeletons: {}, tiers: { deck: tier, line: tier, command: tier, flag: tier }, models: [{ id: "x", url: "x.glb", kind: "drone" }] };
    expect(parseContract(good).models).toHaveLength(1);
    expect(() => parseContract({ models: [] })).toThrow();
    expect(() => parseContract({ ...good, models: [{ id: "x" }] })).toThrow();
  });
});
