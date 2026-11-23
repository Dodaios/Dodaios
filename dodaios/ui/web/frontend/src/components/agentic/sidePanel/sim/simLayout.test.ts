import { describe, expect, it } from "vitest";

import {
  CAMERA_PITCH, CELL_M, LOOK_AT_Y, SIM_STATIONS, assignSlots, cameraDistance, chooseShape, layoutSimulation,
  phaseOf, stationOf, type SimShape, type SimSlots, type SimStation,
} from "./simLayout";

const crowd = (counts: Partial<Record<SimStation, number>>) =>
  SIM_STATIONS.flatMap((place) =>
    Array.from({ length: counts[place] ?? 0 }, (_, index) => ({ id: `${place}-${index}`, place })));

const NOBODY: SimSlots = new Map();
const ACROSS: SimShape = { flow: "across", lines: 3 };
const DOWN: SimShape = { flow: "down", lines: 3 };

describe("stationOf", () => {
  it("stands an agent that works at Building, wherever its pull request is", () => {
    expect(stationOf("ready", "working")).toBe("building");
    expect(stationOf("review", "working")).toBe("building");
    expect(stationOf("finished", "working")).toBe("building");
  });

  it("leaves an agent that rests, asks or failed where its work is", () => {
    expect(stationOf("ready", "idle")).toBe("ready");
    expect(stationOf("checks", "failed")).toBe("checks");
    expect(stationOf("review", "attention")).toBe("review");
    expect(stationOf("finished", "idle")).toBe("finished");
  });
});

describe("assignSlots", () => {
  it("gives the agents of a station its first squares, in the order they are listed", () => {
    const slots = assignSlots(NOBODY, crowd({ building: 3, ready: 2 }));
    expect(slots.get("building-0")).toEqual({ place: "building", slot: 0 });
    expect(slots.get("building-2")).toEqual({ place: "building", slot: 2 });
    expect(slots.get("ready-1")).toEqual({ place: "ready", slot: 1 });
  });

  it("keeps every agent on its square when the board lists them in another order", () => {
    const agents = crowd({ building: 6 });
    const first = assignSlots(NOBODY, agents);
    const second = assignSlots(first, [...agents].reverse());
    for (const agent of agents) expect(second.get(agent.id)).toEqual(first.get(agent.id));
  });

  it("moves nobody up when an agent leaves, and seats the next arrival on the free square", () => {
    const agents = crowd({ building: 4 });
    const first = assignSlots(NOBODY, agents);
    const without = assignSlots(first, agents.filter((agent) => agent.id !== "building-1"));
    expect(without.get("building-3")).toEqual({ place: "building", slot: 3 });
    const arrived = assignSlots(without, [...agents.filter((agent) => agent.id !== "building-1"), { id: "new", place: "building" }]);
    expect(arrived.get("new")).toEqual({ place: "building", slot: 1 });
  });

  it("moves only the agent whose work moved on", () => {
    const first = assignSlots(NOBODY, crowd({ building: 3, checks: 1 }));
    const moved = crowd({ building: 3, checks: 1 }).map((agent) =>
      agent.id === "building-1" ? { ...agent, place: "checks" as const } : agent);
    const second = assignSlots(first, moved);
    expect(second.get("building-1")).toEqual({ place: "checks", slot: 1 });
    for (const id of ["building-0", "building-2", "checks-0"]) expect(second.get(id)).toEqual(first.get(id));
  });
});

describe("layoutSimulation", () => {
  it("lays the five stations out in the order work travels, left to right or back to front", () => {
    const slots = assignSlots(NOBODY, crowd({ building: 4, checks: 1, review: 2, ready: 1, finished: 3 }));
    const across = layoutSimulation(slots, ACROSS);
    expect(across.fields.map((field) => field.column)).toEqual(["building", "checks", "review", "ready", "finished"]);
    expect(across.fields.map((field) => field.count)).toEqual([4, 1, 2, 1, 3]);
    for (const [index, field] of across.fields.entries()) {
      if (index > 0) expect(field.x).toBeGreaterThan(across.fields[index - 1].x);
      expect(field.z).toBe(0);
    }
    const down = layoutSimulation(slots, DOWN);
    for (const [index, field] of down.fields.entries()) {
      if (index > 0) expect(field.z).toBeGreaterThan(down.fields[index - 1].z);
      expect(field.x).toBe(0);
    }
    // One arrow between each station and the next.
    expect(across.links).toHaveLength(4);
    expect(down.links).toHaveLength(4);
  });

  it.each([ACROSS, DOWN])("stands every agent inside its station, on a square of its own (%o)", (shape) => {
    const agents = crowd({ building: 11, checks: 2, review: 5, ready: 1, finished: 7 });
    const layout = layoutSimulation(assignSlots(NOBODY, agents), shape);
    expect(layout.spots.size).toBe(agents.length);
    for (const agent of agents) {
      const spot = layout.spots.get(agent.id)!;
      const field = layout.fields.find((entry) => entry.column === agent.place)!;
      expect(Math.abs(spot.x - field.x)).toBeLessThanOrEqual(field.width / 2 - CELL_M / 2 + 1e-9);
      expect(Math.abs(spot.z - field.z)).toBeLessThanOrEqual(field.depth / 2 - CELL_M / 2 + 1e-9);
    }
    const spots = [...layout.spots.values()];
    for (const [index, a] of spots.entries()) {
      for (const b of spots.slice(index + 1)) {
        expect(Math.max(Math.abs(a.x - b.x), Math.abs(a.z - b.z))).toBeGreaterThanOrEqual(CELL_M - 1e-9);
      }
    }
    for (const [index, a] of layout.fields.entries()) {
      for (const b of layout.fields.slice(index + 1)) {
        const apartX = Math.abs(a.x - b.x) >= (a.width + b.width) / 2 - 1e-9;
        const apartZ = Math.abs(a.z - b.z) >= (a.depth + b.depth) / 2 - 1e-9;
        expect(apartX || apartZ).toBe(true);
      }
    }
  });

  it.each([ACROSS, DOWN])("moves no agent of a station when another one joins it (%o)", (shape) => {
    const agents = crowd({ building: 5, review: 2 });
    const first = assignSlots(NOBODY, agents);
    const before = layoutSimulation(first, shape);
    const after = layoutSimulation(assignSlots(first, [...agents, { id: "late", place: "building" }]), shape);
    const station = (layout: typeof before) => layout.fields.find((field) => field.column === "building")!;
    // Measured from the station's own front left corner: the floor may recentre, the station does not reshuffle.
    const within = (layout: typeof before, id: string) => {
      const field = station(layout);
      const spot = layout.spots.get(id)!;
      return [spot.x - (field.x - field.width / 2), spot.z - (field.z + field.depth / 2)];
    };
    for (let index = 0; index < 5; index += 1) {
      const [x0, z0] = within(before, `building-${index}`);
      const [x1, z1] = within(after, `building-${index}`);
      expect(x1).toBeCloseTo(x0, 9);
      expect(z1).toBeCloseTo(z0, 9);
    }
  });

  it("gives an empty station the room of one agent", () => {
    const layout = layoutSimulation(NOBODY, ACROSS);
    expect(layout.fields).toHaveLength(5);
    expect(layout.spots.size).toBe(0);
    for (const field of layout.fields) expect(field.width).toBeGreaterThanOrEqual(CELL_M);
  });
});

describe("chooseShape", () => {
  const slots = assignSlots(NOBODY, crowd({ building: 12, checks: 2, review: 3, ready: 2, finished: 6 }));

  it("runs the path across a wide panel and down a narrow one", () => {
    expect(chooseShape(slots, 3).flow).toBe("across");
    expect(chooseShape(slots, 0.5).flow).toBe("down");
  });

  it("keeps the shape in use while it still fits, and gives it up when the panel changes for good", () => {
    const wide = chooseShape(slots, 3);
    expect(chooseShape(slots, 2.75, wide)).toEqual(wide);
    const more = assignSlots(slots, [...crowd({ building: 13, checks: 2, review: 3, ready: 2, finished: 6 })]);
    expect(chooseShape(more, 3, wide)).toEqual(wide);
    expect(chooseShape(slots, 0.5, wide).flow).toBe("down");
  });
});

describe("cameraDistance", () => {
  const FOV = 32;

  it("stands far enough back that every corner of the floor is in the picture", () => {
    const layout = layoutSimulation(assignSlots(NOBODY, crowd({ building: 6, checks: 2, review: 5, ready: 1 })), ACROSS);
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
