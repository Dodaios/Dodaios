import { describe, expect, it } from "vitest";
import { PIT, syntheticDeck } from "../testing/syntheticDeck";
import { driveStep } from "./drive";
import { isWalkable } from "./pathfind";

// The synthetic hall: a wall at x = 0 (|x| < 0.4) from the back to z = 4, a pit 1.4 m down with a stair at x 15–17.
const grid = syntheticDeck().nav;

describe("direct control over the nav grid", () => {
  it("walks the full distance over open floor", () => {
    const p = driveStep(grid, { x: -10, z: 6 }, 1.5, -0.5);
    expect(p.x).toBeCloseTo(-8.5, 9);
    expect(p.z).toBeCloseTo(5.5, 9);
  });

  it("stops at a wall", () => {
    const p = driveStep(grid, { x: -2, z: 0 }, 5, 0);
    expect(p.x).toBeLessThan(-0.3);
    expect(p.x).toBeGreaterThan(-0.7);
    expect(isWalkable(grid, p.x, p.z)).toBe(true);
  });

  it("never tunnels through a thin wall, however long the step", () => {
    const p = driveStep(grid, { x: -2, z: -3 }, 20, 0);
    expect(p.x).toBeLessThan(0);
  });

  it("slides along a wall it meets at an angle", () => {
    const p = driveStep(grid, { x: -0.6, z: -3 }, 1, 1);
    expect(p.x).toBeLessThan(-0.3);
    expect(p.z).toBeCloseTo(-2, 1);
  });

  it("does not drop over the pit's edge but takes the stair", () => {
    const edge = driveStep(grid, { x: 13, z: -6 }, 0, -3);
    expect(edge.z).toBeGreaterThan(PIT.z1 - 0.2);
    const stair = driveStep(grid, { x: 16, z: -4 }, 0, -4);
    expect(stair.z).toBeLessThan(PIT.z1 - 0.5);
  });

  it("stops short of whatever the caller says is in the way", () => {
    const p = driveStep(grid, { x: -10, z: 6 }, 2, 0, (q) => q.x < -9);
    expect(p.x).toBeLessThan(-9);
    expect(p.x).toBeGreaterThan(-9.2);
  });

  it("steps a body standing off the floor back onto it", () => {
    const p = driveStep(grid, { x: 0.05, z: -3 }, 0, 1);
    expect(Math.abs(p.x - 0.05)).toBeGreaterThan(0);
    const again = driveStep(grid, p, 0, 1);
    expect(isWalkable(grid, again.x, again.z)).toBe(true);
  });

  it("stays put without a move", () => {
    const from = { x: -10, z: 6 };
    expect(driveStep(grid, from, 0, 0)).toBe(from);
  });
});
