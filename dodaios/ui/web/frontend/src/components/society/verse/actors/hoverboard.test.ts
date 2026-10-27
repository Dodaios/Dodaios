import { describe, expect, it } from "vitest";
import {
  absorb, BOARD_BOOST, BOARD_LIFT, BOARD_SPEED, boardLean, boardSpeed, deployScale, deployStep, glide, hoverHeight,
} from "./hoverboard";
import { DEFAULT_WALK_SPEED } from "./characters";

describe("hoverboard motion", () => {
  it("rides several times faster than a walk, and faster still with Shift", () => {
    expect(boardSpeed(false)).toBe(BOARD_SPEED);
    expect(boardSpeed(true)).toBe(BOARD_BOOST);
    expect(BOARD_SPEED).toBeGreaterThan(DEFAULT_WALK_SPEED * 3.5);
    expect(BOARD_BOOST).toBeGreaterThan(BOARD_SPEED);
  });

  it("speeds up toward the held direction and reaches cruising speed within about a second", () => {
    const v = { x: 0, z: 0 };
    glide(v, { x: 0, z: -1 }, false, 1 / 60);
    expect(v.z).toBeLessThan(0);
    expect(Math.abs(v.z)).toBeLessThan(BOARD_SPEED * 0.1);
    for (let i = 0; i < 60; i++) glide(v, { x: 0, z: -1 }, false, 1 / 60);
    expect(Math.abs(v.z)).toBeGreaterThan(BOARD_SPEED * 0.9);
    expect(v.x).toBe(0);
  });

  it("coasts to a full stop once the keys are let go", () => {
    const v = { x: BOARD_SPEED, z: 0 };
    glide(v, null, false, 0.1);
    expect(v.x).toBeGreaterThan(0);
    expect(v.x).toBeLessThan(BOARD_SPEED);
    for (let i = 0; i < 300; i++) glide(v, null, false, 1 / 60);
    expect(v).toEqual({ x: 0, z: 0 });
  });

  it("loses the speed it could not travel against a wall", () => {
    const v = { x: 5, z: 0 };
    absorb(v, { x: 0.5, z: 0 }, { x: 0, z: 0 }, 0.1);
    expect(v).toEqual({ x: 0, z: 0 });
    const free = { x: 5, z: 0 };
    absorb(free, { x: 0.5, z: 0 }, { x: 0.5, z: 0 }, 0.1);
    expect(free).toEqual({ x: 5, z: 0 });
    // Sliding along a wall keeps the part that moved.
    const slide = { x: 4, z: 3 };
    absorb(slide, { x: 0.4, z: 0.3 }, { x: 0.4, z: 0 }, 0.1);
    expect(slide.x).toBeCloseTo(4);
    expect(slide.z).toBeCloseTo(0);
  });

  it("folds out and away over a short beat, at once with reduced motion", () => {
    let s = 0;
    s = deployStep(s, true, 0.1, false);
    expect(s).toBeGreaterThan(0);
    expect(s).toBeLessThan(1);
    for (let i = 0; i < 10; i++) s = deployStep(s, true, 0.1, false);
    expect(s).toBe(1);
    s = deployStep(s, false, 1, false);
    expect(s).toBe(0);
    expect(deployStep(0, true, 0.001, true)).toBe(1);
    expect(deployScale(0)).toBeCloseTo(0);
    expect(deployScale(1)).toBeCloseTo(1);
  });

  it("lifts the rider off the floor and keeps still with reduced motion", () => {
    expect(hoverHeight(0, 1, 0, false)).toBe(0);
    const h = hoverHeight(1, 1, 0, false);
    expect(h).toBeGreaterThan(BOARD_LIFT * 0.8);
    expect(h).toBeLessThan(BOARD_LIFT * 1.2);
    expect(hoverHeight(1, 1, 0, true)).toBe(BOARD_LIFT);
    expect(boardLean(BOARD_BOOST, 2, true)).toEqual({ pitch: 0, roll: 0 });
    const lean = boardLean(BOARD_SPEED, -2, false);
    expect(lean.pitch).toBeGreaterThan(0);
    expect(lean.roll).toBeGreaterThan(0);
  });
});
