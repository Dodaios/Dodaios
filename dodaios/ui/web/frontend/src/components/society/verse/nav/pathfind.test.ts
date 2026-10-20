import { describe, expect, it } from "vitest";
import { syntheticDeck } from "../testing/syntheticDeck";
import { aStar, cellIndex, findPath, isWalkable, lineOfSight, nearestWalkable, pathLength, stringPull } from "./pathfind";

const grid = syntheticDeck().nav;

describe("grid lookups", () => {
  it("knows the wall and the gap", () => {
    expect(isWalkable(grid, 0, 0)).toBe(false);
    expect(isWalkable(grid, 0, 8)).toBe(true);
    expect(isWalkable(grid, -5, 0)).toBe(true);
    expect(cellIndex(grid, 100, 0)).toBe(-1);
  });

  it("moves a point inside the wall to the nearest open cell", () => {
    const p = nearestWalkable(grid, { x: 0.05, z: 0 });
    expect(p).not.toBeNull();
    expect(isWalkable(grid, p!.x, p!.z)).toBe(true);
    expect(Math.abs(p!.x)).toBeLessThan(0.7);
  });
});

describe("line of sight", () => {
  it("is blocked by the wall and open past its end", () => {
    expect(lineOfSight(grid, { x: -5, z: 0 }, { x: 5, z: 0 })).toBe(false);
    expect(lineOfSight(grid, { x: -5, z: 8 }, { x: 5, z: 8 })).toBe(true);
    expect(lineOfSight(grid, { x: -5, z: -5 }, { x: -5, z: 5 })).toBe(true);
  });
});

describe("paths", () => {
  it("routes around the wall through the gap, in a few straight legs", () => {
    const path = findPath(grid, { x: -6, z: -6 }, { x: 6, z: -6 });
    expect(path).not.toBeNull();
    const p = path!;
    expect(p[0]).toEqual({ x: -6, z: -6 });
    expect(p[p.length - 1]).toEqual({ x: 6, z: -6 });
    expect(p.length).toBeLessThanOrEqual(5);
    // It must pass the wall's end (z > 4) and never cross it.
    expect(p.some((q) => q.z > 4)).toBe(true);
    for (let i = 1; i < p.length; i++) expect(lineOfSight(grid, p[i - 1], p[i])).toBe(true);
    // Near the shortest route: around the end of the wall and back.
    const ideal = 2 * Math.hypot(6, 10.4);
    expect(pathLength(p)).toBeLessThan(ideal * 1.08);
  });

  it("goes straight when nothing is in the way", () => {
    expect(findPath(grid, { x: -10, z: 0 }, { x: -2, z: 3 })).toEqual([{ x: -10, z: 0 }, { x: -2, z: 3 }]);
  });

  it("walks to the nearest open spot when the goal is inside a wall", () => {
    const p = findPath(grid, { x: -6, z: 0 }, { x: 0, z: 0 });
    expect(p).not.toBeNull();
    const end = p![p!.length - 1];
    expect(isWalkable(grid, end.x, end.z)).toBe(true);
  });

  it("returns null for an unreachable goal", () => {
    const sealed = { ...grid, walkable: grid.walkable.slice() };
    // Close the gap.
    for (let r = 0; r < sealed.rows; r++) for (let c = 0; c < sealed.cols; c++) {
      const x = sealed.x0 + (c + 0.5) * sealed.cell;
      if (Math.abs(x) < 0.4) sealed.walkable[r * sealed.cols + c] = 0;
    }
    expect(aStar(sealed, cellIndex(sealed, -5, 0), cellIndex(sealed, 5, 0))).toBeNull();
    expect(findPath(sealed, { x: -5, z: 0 }, { x: 5, z: 0 })).toBeNull();
  });

  it("string-pulls a staircase into its corners only", () => {
    const stairs = Array.from({ length: 20 }, (_, i) => ({ x: -10 + i * 0.2, z: -5 + (i % 2) * 0.2 }));
    expect(stringPull(grid, stairs)).toEqual([stairs[0], stairs[19]]);
  });
});
