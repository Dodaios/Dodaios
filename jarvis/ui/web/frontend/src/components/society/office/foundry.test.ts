import { describe, expect, it } from "vitest";
import { Color } from "three";

import { signalColour } from "./FoundryConsoles";
import { droneRoutes } from "./FoundryLife";
import { deptByAgent, freshOutput } from "./FoundryPulses";
import { CORE_RING, foundryFrame, pointAlong } from "./foundryLayout";
import { BAY_SIGNALS, FOUNDRY, baySignal, glowColour } from "./foundryPalette";
import { buildOfficeLayout, type OfficeAgentInput, type Point } from "./officeLayout";

const agent = (id: string, provider: string): OfficeAgentInput => ({
  agentId: id, name: id, tier: "specialist", providerLabel: provider, state: "working", createdMs: 0,
});

const luminance = (c: Color) => 0.2126 * c.r + 0.7152 * c.g + 0.0722 * c.b;

/** Do the segments ab and cd cross at a point inside both (touching ends do not count)? */
function crosses(a: Point, b: Point, c: Point, d: Point): boolean {
  const cross = (o: Point, p: Point, q: Point) => (p.x - o.x) * (q.z - o.z) - (p.z - o.z) * (q.x - o.x);
  const d1 = cross(c, d, a), d2 = cross(c, d, b), d3 = cross(a, b, c), d4 = cross(a, b, d);
  return ((d1 > 1e-9 && d2 < -1e-9) || (d1 < -1e-9 && d2 > 1e-9)) && ((d3 > 1e-9 && d4 < -1e-9) || (d3 < -1e-9 && d4 > 1e-9));
}

describe("Foundry deck layout", () => {
  for (const count of [0, 9, 40]) {
    const layout = buildOfficeLayout(Array.from({ length: count }, (_, i) => agent(`a${i}`, `W${i % 6}`)), { variant: "coding" });
    const frame = foundryFrame(layout)!;

    it(`puts the Core on the spawn terminal in the middle of the concourse (${count} agents)`, () => {
      const terminal = layout.furniture.find((f) => f.kind === "spawnTerminal")!;
      expect(frame.core).toEqual({ x: terminal.x, z: terminal.z });
      expect(frame.core.x).toBeGreaterThan(frame.concourse.minX + CORE_RING.outer);
      expect(frame.core.x).toBeLessThan(frame.concourse.maxX - CORE_RING.outer);
      for (const dept of layout.departments) {
        const overlap = dept.minX < frame.concourse.maxX && dept.maxX > frame.concourse.minX;
        expect(overlap, dept.id).toBe(false);
      }
    });

    it(`runs one rail per bay from its edge to the Core's ring, inside the concourse (${count} agents)`, () => {
      expect(frame.rails.map((r) => r.deptId).sort()).toEqual(layout.departments.map((d) => d.id).sort());
      for (const rail of frame.rails) {
        const dept = layout.departments.find((d) => d.id === rail.deptId)!;
        const start = rail.points[0], end = rail.points[rail.points.length - 1];
        expect([dept.minX, dept.maxX]).toContain(start.x);
        expect(Math.hypot(end.x - frame.core.x, end.z - frame.core.z)).toBeCloseTo(CORE_RING.outer, 5);
        for (const p of rail.points) {
          expect(p.x).toBeGreaterThanOrEqual(frame.concourse.minX - 1e-9);
          expect(p.x).toBeLessThanOrEqual(frame.concourse.maxX + 1e-9);
        }
        expect(rail.lengths[rail.lengths.length - 1]).toBeGreaterThan(0);
      }
    });

    it(`lays the rails like circuit traces: no two cross (${count} agents)`, () => {
      const segments = frame.rails.flatMap((rail) => rail.points.slice(1).map((b, i) => ({ id: rail.deptId, a: rail.points[i], b })));
      for (const s of segments) {
        for (const t of segments) {
          if (s.id === t.id) continue;
          expect(crosses(s.a, s.b, t.a, t.b), `${s.id} × ${t.id}`).toBe(false);
        }
      }
    });
  }

  it("draws nothing on the agents floor", () => {
    expect(foundryFrame(buildOfficeLayout([agent("a", "P")]))).toBeNull();
  });

  it("walks a rail from its start to its end", () => {
    const frame = foundryFrame(buildOfficeLayout([agent("a", "W")], { variant: "coding" }))!;
    const rail = frame.rails[0];
    const start = pointAlong(rail, -1), end = pointAlong(rail, 1e6);
    expect({ x: start.x, z: start.z }).toEqual(rail.points[0]);
    expect({ x: end.x, z: end.z }).toEqual(rail.points[rail.points.length - 1]);
    const mid = pointAlong(rail, rail.lengths[rail.lengths.length - 1] / 2);
    expect(Math.hypot(mid.dx, mid.dz)).toBeCloseTo(1, 5);
  });
});

describe("Foundry deck colours", () => {
  it("gives every bay its own signal colour, none close to the status amber or red", () => {
    expect(new Set(BAY_SIGNALS).size).toBe(BAY_SIGNALS.length);
    expect(baySignal(BAY_SIGNALS.length)).toBe(baySignal(0));
    expect(baySignal(-1)).toBe(baySignal(BAY_SIGNALS.length - 1));
    for (const signal of BAY_SIGNALS) {
      for (const status of [FOUNDRY.status.asking, FOUNDRY.status.failed]) {
        const a = new Color(signal), b = new Color(status);
        expect(Math.hypot(a.r - b.r, a.g - b.g, a.b - b.b), `${signal} vs ${status}`).toBeGreaterThan(0.45);
      }
    }
  });

  it("scales any hue to the same luminance, so every signal blooms alike", () => {
    for (const hex of [...BAY_SIGNALS, FOUNDRY.status.asking, FOUNDRY.status.failed, FOUNDRY.gold]) {
      expect(luminance(glowColour(hex, 1.3))).toBeCloseTo(1.3, 5);
    }
  });

  it("lights a desk by its pane: bay colour at work, amber blinking when asking, red when failed, dark when free", () => {
    const bay = glowColour(BAY_SIGNALS[1], 0.8);
    const out = new Color();
    const working = signalColour("working", bay, 0, out).clone();
    expect(working.r / working.g).toBeCloseTo(bay.r / bay.g, 5);
    const on = signalColour("waiting", bay, 0.1, out).clone();
    const off = signalColour("waiting", bay, 0.7, out).clone();
    expect(luminance(on)).toBeGreaterThan(luminance(off) * 2);
    const failed = signalColour("error", bay, 0, out).clone();
    expect(failed.r).toBeGreaterThan(failed.g * 3);
    expect(luminance(signalColour("free", bay, 0, out))).toBeLessThan(0.01);
  });
});

describe("Foundry deck life", () => {
  it("sends packets only for output that moved on, never for the first reading", () => {
    const seen = new Map<string, number>();
    const pane = (key: string, at: number | null) => ({ workspace_id: "w", history_id: `h-${key}`, key, last_output_at: at });
    expect(freshOutput([pane("a", 10), pane("b", 5)], seen, true)).toEqual([]);
    expect(freshOutput([pane("a", 10), pane("b", 6)], seen, false)).toEqual(["pane:w:h-b"]);
    expect(freshOutput([pane("a", 11), pane("b", 6), pane("c", 3)], seen, false)).toEqual(["pane:w:h-a"]);
    expect(freshOutput([pane("a", null)], seen, false)).toEqual([]);
    // Closed panes are forgotten: the record never outgrows the roster.
    expect([...seen.keys()]).toEqual([]);
  });

  it("finds each seated pane's bay", () => {
    const layout = buildOfficeLayout([agent("a", "W1"), agent("b", "W2")], { variant: "coding" });
    const bays = deptByAgent(layout.departments);
    expect(bays.size).toBe(2);
    expect(bays.get("a")).not.toBe(bays.get("b"));
  });

  it("flies the drones over the deck, above head height", () => {
    const layout = buildOfficeLayout([], { variant: "coding" });
    const routes = droneRoutes(layout.bounds, 4);
    expect(routes).toHaveLength(4);
    for (const r of routes) {
      expect(r.y).toBeGreaterThan(3.5);
      expect(r.cx - r.rx).toBeGreaterThanOrEqual(layout.bounds.minX);
      expect(r.cx + r.rx).toBeLessThanOrEqual(layout.bounds.maxX);
      expect(r.cz - r.rz).toBeGreaterThanOrEqual(layout.bounds.minZ);
      expect(r.cz + r.rz).toBeLessThanOrEqual(layout.bounds.maxZ);
    }
  });
});
