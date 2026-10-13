import { afterEach, describe, expect, it } from "vitest";
import { agentPositions, bodiesExcept, bodiesNear, companions, extraBodies, placeAgent } from "./walkerRegistry";

describe("bodiesExcept", () => {
  afterEach(() => { agentPositions.clear(); extraBodies.clear(); });

  it("counts every agent, the hovering Gigi included, but never the caller itself", () => {
    agentPositions.set("gigi", { x: 1, z: 1 });
    agentPositions.set("walker", { x: 2, z: 2 });
    expect(Array.from(bodiesExcept(null, null))).toEqual([{ x: 1, z: 1 }, { x: 2, z: 2 }]);
    expect(Array.from(bodiesExcept("walker", { x: 5, z: 5 }))).toEqual([{ x: 1, z: 1 }, { x: 5, z: 5 }]);
  });

  it("counts the office dog as a body for everyone but the dog itself", () => {
    extraBodies.set("office-dog", { x: 3, z: 3 });
    expect(Array.from(bodiesExcept(null, null))).toEqual([{ x: 3, z: 3 }]);
    expect(Array.from(bodiesExcept("office-dog", { x: 5, z: 5 }))).toEqual([{ x: 5, z: 5 }]);
  });
});

describe("bodiesNear", () => {
  afterEach(() => { agentPositions.clear(); extraBodies.clear(); companions.clear(); });

  it("lists the same bodies as bodiesExcept within reach, into the caller's own array", () => {
    agentPositions.set("near", { x: 1, z: 1 });
    agentPositions.set("far", { x: 30, z: 1 });
    agentPositions.set("self", { x: 0, z: 0 });
    agentPositions.set("pet", { x: 0.5, z: 0.5 });
    companions.add("pet");
    extraBodies.set("office-dog", { x: -1, z: 2 });
    const person = { x: 2, z: -2 };
    const out: { x: number; z: number }[] = [{ x: 99, z: 99 }];
    const got = bodiesNear("self", { x: 0, z: 0 }, 7, person, out);
    expect(got).toBe(out);
    expect(got).toEqual([{ x: 1, z: 1 }, { x: -1, z: 2 }, person]);
    expect(new Set(bodiesNear("self", { x: 0, z: 0 }, Infinity, person))).toEqual(new Set(bodiesExcept("self", person)));
    expect(bodiesNear("office-dog", { x: 0, z: 0 }, 7, null)).toEqual([{ x: 1, z: 1 }, { x: 0, z: 0 }]);
  });
});

describe("placeAgent", () => {
  afterEach(() => { agentPositions.clear(); });

  it("moves an agent's entry in place instead of making a new one every frame", () => {
    placeAgent("a", 1, 2);
    const entry = agentPositions.get("a");
    expect(entry).toEqual({ x: 1, z: 2 });
    placeAgent("a", 3, 4);
    expect(agentPositions.get("a")).toBe(entry);
    expect(entry).toEqual({ x: 3, z: 4 });
  });
});
