import { describe, expect, it } from "vitest";

import { agentsRug, AGENTS_RUGS } from "./AgentsFloorLook";
import {
  ambienceObstacles, bench, BENCH_DEPTH, BENCH_H, benchSeats, booth, BOOTH, boothPlace, counter, counterStands, highTable, HIGH_TABLE,
  olive, OLIVE_BOX, OLIVE_H, ownSize, planter, PLANTER_H, screen, SCREEN, sofa, SOFA, sofaSeats, steps, STEPS, stepsSeats, tableStands,
  toFloor, tree, TREE_BOX, yawOf,
} from "./agentsAmbience";
import { buildOfficeLayout, type OfficeAgentInput } from "./officeLayout";
import { CODING_STUDIOS, DEPARTMENT_ZONES } from "./officePalette";

const agent = (id: string, provider: string): OfficeAgentInput => ({
  agentId: id, name: id, tier: "specialist", providerLabel: provider, state: "working", createdMs: 0,
});
const near = (a: number, b: number) => expect(a).toBeCloseTo(b, 9);

describe("agents floor fittings as data", () => {
  it("builds trees, benches and planters as boxes on the floor plan", () => {
    const pot = olive("t", 2, -3);
    expect([pot.kind, pot.h]).toEqual(["olive", OLIVE_H]);
    near(pot.maxX - pot.minX, OLIVE_BOX);
    near(pot.maxZ - pot.minZ, OLIVE_BOX);
    expect([(pot.minX + pot.maxX) / 2, (pot.minZ + pot.maxZ) / 2]).toEqual([2, -3]);
    const big = tree("b", 0, 0);
    near(big.maxX - big.minX, TREE_BOX);
    expect(big.h).toBeGreaterThan(pot.h);
    // A bench runs north-south whichever end is named first, and faces east or west.
    const seat = bench("b", 5, 4, 1, "west");
    expect([seat.kind, seat.facing, seat.h]).toEqual(["bench", "west", BENCH_H]);
    expect([seat.minZ, seat.maxZ]).toEqual([1, 4]);
    near(seat.maxX - seat.minX, BENCH_DEPTH);
    expect(benchSeats(seat).map((p) => p.z)).toEqual([1.75, 3.25]);
    near(benchSeats(seat)[0].facing, -Math.PI / 2);
    const box = planter("p", { minX: 0, maxX: 3, minZ: 1, maxZ: 1.34 });
    expect([box.kind, box.h, box.minX, box.maxX, box.minZ, box.maxZ]).toEqual(["planter", PLANTER_H, 0, 3, 1, 1.34]);
    // A screen is a thin box along its line, north-south or east-west, and may wear a studio's colour.
    const line = screen("s", 4, 1, 4, 7, 3);
    near(line.maxX - line.minX, SCREEN.t);
    near(line.maxZ - line.minZ, 6 + SCREEN.t);
    expect(line.tint).toBe(3);
    expect("tint" in screen("n", 0, 0, 5, 0)).toBe(false);
  });

  it("turns a piece's footprint with the way it faces, and finds its own frame on the floor", () => {
    for (const facing of ["north", "south"] as const) {
      const piece = sofa("s", 10, 20, facing);
      near(piece.maxX - piece.minX, SOFA.w);
      near(piece.maxZ - piece.minZ, SOFA.d);
    }
    for (const facing of ["east", "west"] as const) {
      const piece = sofa("s", 10, 20, facing);
      near(piece.maxX - piece.minX, SOFA.d);
      near(piece.maxZ - piece.minZ, SOFA.w);
      expect(ownSize(piece).w).toBeCloseTo(SOFA.w, 9);
    }
    // Local +z is the front: one metre in front of an east-facing piece is one metre east of it.
    const east = sofa("e", 10, 20, "east"), north = sofa("n", 10, 20, "north");
    near(toFloor(east, 0, 1).x, 11);
    near(toFloor(east, 0, 1).z, 20);
    near(toFloor(north, 0, 1).z, 19);
    // Local +x is the piece's own right-hand side seen from behind it: south of an east-facing piece's middle is -x.
    near(toFloor(east, 1, 0).z, 19);
    expect(yawOf("south")).toBe(0);
    near(yawOf("west"), -Math.PI / 2);
  });

  it("gives every piece the places people use it from", () => {
    // Two seats on a sofa, side by side, looking the way it faces.
    const couch = sofa("s", 0, 0, "east");
    const seats = sofaSeats(couch);
    expect(seats).toHaveLength(2);
    for (const seat of seats) {
      expect(seat.x > couch.minX && seat.x < couch.maxX && seat.z > couch.minZ && seat.z < couch.maxZ).toBe(true);
      near(seat.facing, Math.PI / 2);
    }
    near(Math.abs(seats[0].z - seats[1].z), 0.9);
    // Standing places round a table look at it from just outside its top.
    const table = highTable("t", 3, 3);
    for (const stand of tableStands(table, [0, Math.PI / 2, Math.PI])) {
      const d = Math.hypot(stand.x - 3, stand.z - 3);
      expect(d).toBeGreaterThan(HIGH_TABLE.r + 0.3);
      expect(d).toBeLessThan(HIGH_TABLE.r + 0.6);
      near(stand.x + Math.sin(stand.facing) * d, 3);
      near(stand.z + Math.cos(stand.facing) * d, 3);
    }
    // Step seating seats people on its lowest tier, at its front, looking out.
    const flight = steps("f", 0, 0, 5, "east");
    near(flight.maxX - flight.minX, STEPS.d);
    near(flight.maxZ - flight.minZ, 5);
    const tier = stepsSeats(flight);
    expect(tier.length).toBeGreaterThanOrEqual(4);
    for (const seat of tier) {
      near(seat.x, flight.maxX - STEPS.tier / 2);
      near(seat.facing, Math.PI / 2);
    }
    // In front of a counter, facing it.
    const run = counter("c", 0, 0, 4, "east");
    for (const stand of counterStands(run, [-1, 1])) {
      expect(stand.x).toBeGreaterThan(run.maxX + 0.4);
      near(Math.sin(stand.facing), -1);
    }
  });

  it("makes a focus booth three walls and an open front, so a person stands inside it", () => {
    const box = booth("b", 0, 0, "south", 1);
    const walls = ambienceObstacles(box);
    expect(walls).toHaveLength(3);
    const blocked = (x: number, z: number) => walls.some((w) => x >= w.minX && x <= w.maxX && z >= w.minZ && z <= w.maxZ);
    // The back (north) and both sides are solid; the middle and the front (south) are not.
    expect(blocked(0, -BOOTH.d / 2 + 0.02)).toBe(true);
    expect(blocked(-BOOTH.w / 2 + 0.02, 0)).toBe(true);
    expect(blocked(BOOTH.w / 2 - 0.02, 0)).toBe(true);
    expect(blocked(0, 0)).toBe(false);
    expect(blocked(0, BOOTH.d / 2 - 0.02)).toBe(false);
    const inside = boothPlace(box);
    expect(blocked(inside.x, inside.z)).toBe(false);
    // The person looks at the shelf on the back wall.
    near(Math.cos(inside.facing), -1);
    // Turned east, the open side is the east one.
    const turned = ambienceObstacles(booth("b", 0, 0, "east"));
    expect(turned.some((w) => w.maxX >= BOOTH.d / 2 - 1e-9 && w.minZ < 0 && w.maxZ > 0)).toBe(false);
    // Every other piece is simply its footprint.
    const couch = sofa("s", 1, 2, "north");
    expect(ambienceObstacles(couch)).toEqual([{ minX: couch.minX, maxX: couch.maxX, minZ: couch.minZ, maxZ: couch.maxZ }]);
  });
});

describe("agents floor fittings on the campus", () => {
  for (const count of [0, 12, 40]) {
    const layout = buildOfficeLayout(Array.from({ length: count }, (_, i) => agent(`a${i}`, `P${i % 5}`)), {
      teams: count > 0 ? [{ id: "t", name: "T", createdMs: 1, members: ["a1", "a2", "a3", "a4", "a5"] }] : [],
    });
    const items = layout.ambience!;

    it(`furnishes the atrium, the commons, every studio and the windows (${count} agents)`, () => {
      const has = (prefix: string, kind: string) => items.some((i) => i.id.startsWith(prefix) && i.kind === kind);
      expect(has("atrium-steps-west", "steps") && has("atrium-steps-east", "steps") && has("atrium-tree-", "tree")).toBe(true);
      expect(has("median-west", "planter") && has("median-east-olive", "olive") && has("median-west-table", "hightable")).toBe(true);
      expect(has("booth-", "booth") && has("booths-sofa", "sofa") && has("library-sofa", "sofa")).toBe(true);
      expect(has("cafe-counter", "counter") && has("cafe-island", "island") && has("cafe-table-", "hightable") && has("cafe-sofa-", "sofa")).toBe(true);
      expect(has("olive-west-0", "olive") && has("olive-east-0", "olive")).toBe(true);
      // Every studio: screens, planted front, cabinet, sofa, standing table.
      for (const dept of layout.departments) {
        const mine = (part: string) => items.find((i) => i.id === `${dept.id}-${part}`);
        expect([mine("front-w")?.kind, mine("front-e")?.kind, mine("cabinet")?.kind, mine("sofa")?.kind, mine("table")?.kind, mine("screen-e")?.kind])
          .toEqual(["planter", "planter", "cabinet", "sofa", "hightable", "screen"]);
        // The front planters leave the entrance between them.
        expect(mine("front-e")!.minX - mine("front-w")!.maxX).toBeGreaterThan(4);
      }
    });

    it(`puts a bench and a planter beside each window, swapped between west and east (${count} agents)`, () => {
      const kind = (id: string) => items.find((i) => i.id === id)?.kind;
      expect([kind("bench-west-0"), kind("planter-west-0"), kind("planter-east-0"), kind("bench-east-0")]).toEqual(["bench", "planter", "planter", "bench"]);
      const west = items.find((i) => i.id === "bench-west-0")!, westBox = items.find((i) => i.id === "planter-west-0")!;
      expect(west.maxZ).toBeLessThan(westBox.minZ);
      const east = items.find((i) => i.id === "bench-east-0")!, eastBox = items.find((i) => i.id === "planter-east-0")!;
      expect(eastBox.maxZ).toBeLessThan(east.minZ);
      expect([west.facing, east.facing]).toEqual(["east", "west"]);
    });
  }

  it("adds nothing to the coding floor", () => {
    expect(buildOfficeLayout([], { variant: "coding" }).ambience).toBeUndefined();
  });
});

describe("agents floor rugs", () => {
  it("gives the twelve studios a floor can hold twelve different rugs, none shared with the coding floor", () => {
    const rugs = Array.from({ length: 12 }, (_, i) => agentsRug(i));
    expect(AGENTS_RUGS).toHaveLength(12);
    expect(new Set(rugs.map((r) => `${r.weave}:${r.field}`)).size).toBe(12);
    expect(new Set(rugs.map((r) => r.field)).size).toBe(12);
    expect(new Set(rugs.map((r) => r.border)).size).toBe(12);
    const above = new Set(CODING_STUDIOS.map((s) => s.carpet));
    for (const rug of AGENTS_RUGS) expect(above.has(rug.field)).toBe(false);
    // Desk screens and seats take their zone from the same index.
    expect(DEPARTMENT_ZONES).toHaveLength(AGENTS_RUGS.length);
  });

  it("cycles for any tint index", () => {
    expect(agentsRug(AGENTS_RUGS.length)).toBe(agentsRug(0));
    expect(agentsRug(-1)).toBe(agentsRug(AGENTS_RUGS.length - 1));
  });
});
