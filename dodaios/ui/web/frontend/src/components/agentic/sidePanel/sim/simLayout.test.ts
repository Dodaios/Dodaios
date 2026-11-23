import { describe, expect, it } from "vitest";

import { BOARD_COLUMNS, type BoardColumn } from "../agentBoard";
import { CAMERA_PITCH, CELL_M, LOOK_AT_Y, cameraDistance, layoutSimulation, phaseOf } from "./simLayout";

const crowd = (counts: Partial<Record<BoardColumn, number>>) =>
  BOARD_COLUMNS.flatMap((place) =>
    Array.from({ length: counts[place] ?? 0 }, (_, index) => ({ id: `${place}-${index}`, place })));

describe("layoutSimulation", () => {
  it("stands every agent inside the field its work is in", () => {
    const agents = crowd({ building: 7, checks: 1, review: 3, ready: 12 });
    const layout = layoutSimulation(agents);
    expect(layout.fields.map((field) => field.column)).toEqual([...BOARD_COLUMNS]);
    expect(layout.spots.size).toBe(agents.length);
    for (const agent of agents) {
      const spot = layout.spots.get(agent.id)!;
      const field = layout.fields.find((entry) => entry.column === agent.place)!;
      expect(Math.abs(spot.x - field.x)).toBeLessThanOrEqual(field.width / 2 - CELL_M / 2 + 1e-9);
      expect(Math.abs(spot.z - field.z)).toBeLessThanOrEqual(field.depth / 2 - CELL_M / 2 + 1e-9);
    }
  });

  it("gives every agent a square of its own", () => {
    const layout = layoutSimulation(crowd({ building: 9, checks: 9, review: 9, ready: 9 }));
    const spots = [...layout.spots.values()];
    for (const [index, a] of spots.entries()) {
      for (const b of spots.slice(index + 1)) {
        expect(Math.max(Math.abs(a.x - b.x), Math.abs(a.z - b.z))).toBeGreaterThanOrEqual(CELL_M - 1e-9);
      }
    }
  });

  it("fills a field from the front, in the order the board lists its agents", () => {
    const layout = layoutSimulation(crowd({ building: 9 }));
    const first = layout.spots.get("building-0")!;
    const last = layout.spots.get("building-8")!;
    // The viewer stands at +z: the first agent is nearest.
    expect(first.z).toBeGreaterThan(last.z);
    for (const spot of layout.spots.values()) expect(spot.z).toBeLessThanOrEqual(first.z + 1e-9);
  });

  it("gives a full field the floor and an empty one the room of a single agent", () => {
    for (const aspect of [0.5, 1, 2, 4]) {
      const layout = layoutSimulation(crowd({ building: 28, checks: 1, ready: 1 }), aspect);
      expect(layout.fields.map((field) => field.count)).toEqual([28, 1, 0, 1]);
      const area = layout.fields.map((field) => field.width * field.depth);
      const floor = area.reduce((sum, value) => sum + value, 0);
      // Nearly all the work is in one column: so is most of the floor.
      expect(area[0] / floor).toBeGreaterThan(0.5);
      for (const field of layout.fields) {
        expect(field.width).toBeGreaterThanOrEqual(CELL_M);
        expect(field.depth).toBeGreaterThanOrEqual(CELL_M);
      }
    }
  });

  it("never lets two fields overlap", () => {
    for (const aspect of [0.4, 0.8, 1.5, 3]) {
      const { fields } = layoutSimulation(crowd({ building: 13, checks: 2, review: 7, ready: 1 }), aspect);
      for (const [index, a] of fields.entries()) {
        for (const b of fields.slice(index + 1)) {
          const apartX = Math.abs(a.x - b.x) >= (a.width + b.width) / 2 - 1e-9;
          const apartZ = Math.abs(a.z - b.z) >= (a.depth + b.depth) / 2 - 1e-9;
          expect(apartX || apartZ).toBe(true);
        }
      }
    }
  });

  it("lays the floor wide for a wide panel and deep for a narrow one", () => {
    const agents = crowd({ building: 4, checks: 4, review: 4, ready: 4 });
    const wide = layoutSimulation(agents, 4);
    const narrow = layoutSimulation(agents, 0.5);
    expect(wide.width / wide.depth).toBeGreaterThan(narrow.width / narrow.depth);
    // In a narrow side panel the fields no longer stand in one row.
    expect(new Set(narrow.fields.map((field) => field.z)).size).toBeGreaterThan(1);
    expect(new Set(wide.fields.map((field) => field.z)).size).toBe(1);
  });

  it("draws an empty floor too", () => {
    const layout = layoutSimulation([]);
    expect(layout.fields).toHaveLength(4);
    expect(layout.spots.size).toBe(0);
    expect(layout.width).toBeGreaterThan(0);
  });
});

describe("cameraDistance", () => {
  const FOV = 32;

  it("stands far enough back that every corner of the floor is in the picture", () => {
    const layout = layoutSimulation(crowd({ building: 6, checks: 2, review: 5, ready: 1 }), 1.5);
    const aspect = 1.5;
    const distance = cameraDistance(layout, aspect, FOV);
    const half = Math.tan((FOV * Math.PI) / 360);
    const sin = Math.sin(CAMERA_PITCH);
    const cos = Math.cos(CAMERA_PITCH);
    for (const x of [-layout.width / 2, layout.width / 2]) {
      for (const z of [-layout.depth / 2, layout.depth / 2]) {
        const y = -LOOK_AT_Y;
        const ahead = distance - (y * sin + z * cos);
        expect(Math.abs(x) / ahead).toBeLessThanOrEqual(half * aspect);
        expect(Math.abs(y * cos - z * sin) / ahead).toBeLessThanOrEqual(half);
      }
    }
  });

  it("steps back for a larger floor and for a narrower panel", () => {
    const small = { width: 8, depth: 4 };
    const large = { width: 24, depth: 12 };
    expect(cameraDistance(large, 2, FOV)).toBeGreaterThan(cameraDistance(small, 2, FOV));
    expect(cameraDistance(small, 0.6, FOV)).toBeGreaterThan(cameraDistance(small, 2, FOV));
  });
});

describe("phaseOf", () => {
  it("is the same for the same agent and differs between agents", () => {
    expect(phaseOf("thread:a")).toBe(phaseOf("thread:a"));
    expect(phaseOf("thread:a")).not.toBe(phaseOf("thread:b"));
    for (const id of ["", "x", "pane:1@w1", "thread:abc"]) {
      expect(phaseOf(id)).toBeGreaterThanOrEqual(0);
      expect(phaseOf(id)).toBeLessThan(1);
    }
  });
});
