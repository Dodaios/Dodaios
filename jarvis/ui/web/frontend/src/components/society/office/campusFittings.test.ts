import { describe, expect, it } from "vitest";

import { steps, type Compass } from "./agentsAmbience";
import { fittingParts } from "./CampusFittings";
import type { Placement } from "./CodingFloorAmbience";

type Bounds = { min: [number, number, number]; max: [number, number, number] };

/** World bounds of a unit box placed with a quarter-turn yaw (the fittings only ever turn by quarter turns). */
function boundsOf({ position, scale, rotation }: Placement): Bounds {
  const quarter = Math.round(Math.abs(rotation?.[1] ?? 0) / (Math.PI / 2)) % 2 === 1;
  const sx = quarter ? scale[2] : scale[0], sz = quarter ? scale[0] : scale[2];
  const half = [sx / 2, scale[1] / 2, sz / 2];
  return {
    min: [position[0] - half[0], position[1] - half[1], position[2] - half[2]],
    max: [position[0] + half[0], position[1] + half[1], position[2] + half[2]],
  };
}

const EPS = 1e-6;

/** Whether two boxes share a face plane, facing the same way, over an area: the pattern that z-fights into stripes. */
function flushOverArea(a: Bounds, b: Bounds): boolean {
  for (let axis = 0; axis < 3; axis += 1) {
    const others = [0, 1, 2].filter((o) => o !== axis);
    const overlap = others.every((o) => Math.min(a.max[o], b.max[o]) - Math.max(a.min[o], b.min[o]) > EPS);
    if (!overlap) continue;
    if (Math.abs(a.min[axis] - b.min[axis]) < EPS || Math.abs(a.max[axis] - b.max[axis]) < EPS) return true;
  }
  return false;
}

describe("campus fittings", () => {
  it.each<Compass>(["north", "south", "east", "west"])("step seating facing %s has no steel cheek flush with a tread", (facing) => {
    const parts = fittingParts([steps("s", 3, -2, 6, facing)]);
    expect(parts.steel.length).toBe(2);
    for (const cheek of parts.steel.map(boundsOf)) {
      for (const tread of parts.oak.map(boundsOf)) expect(flushOverArea(cheek, tread)).toBe(false);
    }
  });
});
