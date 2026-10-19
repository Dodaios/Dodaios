import { describe, expect, it } from "vitest";
import { buildOfficeLayout, type OfficeAgentInput } from "./officeLayout";
import {
  MAP_PAINT, STATE_RING, ZOOM_DEFAULT_M, ZOOM_MAX_M, ZOOM_MIN_M, bearingOf, centredTransform, clampToEdge, clampToRect,
  clampZoom, columnLabel, compassPosition, compassTicks, drawAgentToken, drawEdgeArrow, drawFloorArt, drawMapLabel, drawPlayerArrow,
  fitSheet, fitTransform, minimapCentre, gridLabel, initialOf, inkOn, mapGrid, mapToWorld, pickNearest, placeAt, relativeBearing, shade,
  worldToMap, yawToBearing, zoomStep,
} from "./minimap";

const agent = (id: string, provider: string, extra: Partial<OfficeAgentInput> = {}): OfficeAgentInput => ({
  agentId: id, name: id, tier: "specialist", providerLabel: provider, state: "idle", createdMs: Number(id.replace(/\D/g, "")) || 0, ...extra,
});

/** A 2D context stand-in that records every call and property write, in order. */
function recorder(): { ctx: CanvasRenderingContext2D; log: string[] } {
  const log: string[] = [];
  const state: Record<string, unknown> = {};
  const ctx = new Proxy(state, {
    get(target, prop: string) {
      if (prop in target) return target[prop];
      if (prop === "createRadialGradient" || prop === "createLinearGradient") return undefined;
      return (...args: unknown[]) => { log.push(`${prop}(${args.map((a) => (typeof a === "number" ? a.toFixed(1) : String(a))).join(",")})`); };
    },
    set(target, prop: string, value) {
      target[prop] = value;
      log.push(`${prop}=${String(value)}`);
      return true;
    },
  });
  return { ctx: ctx as unknown as CanvasRenderingContext2D, log };
}

describe("map transforms", () => {
  const bounds = { minX: -10, maxX: 10, minZ: -20, maxZ: 20 };

  it("fits a rect keeping the aspect and centring it inside the padding", () => {
    const t = fitTransform(bounds, 220, 300, 10);
    expect(t.scale).toBeCloseTo(7); // (300 - 20) / 40
    const nw = worldToMap(t, { x: -10, z: -20 });
    const se = worldToMap(t, { x: 10, z: 20 });
    expect(nw.y).toBeCloseTo(10);
    expect(se.y).toBeCloseTo(290);
    expect(nw.x + se.x).toBeCloseTo(220);
  });

  it("centres the player and shows the zoom's metres across the shorter side", () => {
    const t = centredTransform({ x: 12, z: -4 }, 26, 200, 200);
    expect(worldToMap(t, { x: 12, z: -4 })).toEqual({ x: 100, y: 100 });
    expect(t.scale).toBeCloseTo(200 / 26);
    // 13 m east of the player is the right edge; north (−z) is up.
    expect(worldToMap(t, { x: 25, z: -4 }).x).toBeCloseTo(200);
    expect(worldToMap(t, { x: 12, z: -5 }).y).toBeLessThan(100);
  });

  it("round-trips between world and map", () => {
    const t = centredTransform({ x: 3, z: 7 }, 40, 200, 160);
    for (const p of [{ x: 3.5, z: -7.25 }, { x: -10, z: 20 }, { x: 0, z: 0 }]) {
      const back = mapToWorld(t, worldToMap(t, p));
      expect(back.x).toBeCloseTo(p.x);
      expect(back.z).toBeCloseTo(p.z);
    }
  });

  it("clamps a click on the railing onto the walkable floor", () => {
    expect(clampToRect({ x: 50, z: -50 }, bounds)).toEqual({ x: 10, z: -20 });
  });

  it("zooms within 16–60 m", () => {
    expect(clampZoom(5)).toBe(ZOOM_MIN_M);
    expect(clampZoom(500)).toBe(ZOOM_MAX_M);
    expect(clampZoom(Number.NaN)).toBe(ZOOM_DEFAULT_M);
    expect(zoomStep(26, 1)).toBeLessThan(26);
    expect(zoomStep(26, -1)).toBeGreaterThan(26);
    expect(zoomStep(ZOOM_MIN_M, 1)).toBe(ZOOM_MIN_M);
    expect(zoomStep(ZOOM_MAX_M, -1)).toBe(ZOOM_MAX_M);
  });
});

describe("edge clamping of off-screen agents", () => {
  it("leaves a point inside the inset area alone", () => {
    const m = clampToEdge({ x: 120, y: 80 }, 200, 200, 12);
    expect(m).toMatchObject({ x: 120, y: 80, clamped: false });
  });

  it("pulls a point far east onto the right edge, arrow pointing right", () => {
    const m = clampToEdge({ x: 900, y: 100 }, 200, 200, 12);
    expect(m.clamped).toBe(true);
    expect(m.x).toBeCloseTo(188);
    expect(m.y).toBeCloseTo(100);
    expect(m.angle).toBeCloseTo(0);
  });

  it("keeps the direction for a diagonal point and hits the nearer edge", () => {
    // Far south-west, steeper than 45°: the bottom edge is reached first.
    const m = clampToEdge({ x: 100 - 300, y: 100 + 600 }, 200, 200, 10);
    expect(m.clamped).toBe(true);
    expect(m.y).toBeCloseTo(190);
    expect(m.x).toBeCloseTo(100 - 45);
    expect(m.angle).toBeCloseTo(Math.atan2(600, -300));
    // Straight north: top edge, arrow pointing up.
    const up = clampToEdge({ x: 100, y: -500 }, 200, 200, 10);
    expect(up.y).toBeCloseTo(10);
    expect(up.angle).toBeCloseTo(-Math.PI / 2);
  });
});

describe("compass", () => {
  it("measures bearings clockwise from north (−z)", () => {
    expect(bearingOf(0, -1)).toBeCloseTo(0);
    expect(bearingOf(1, 0)).toBeCloseTo(90);
    expect(bearingOf(0, 1)).toBeCloseTo(180);
    expect(bearingOf(-1, 0)).toBeCloseTo(270);
    expect(bearingOf(-1, -1)).toBeCloseTo(315);
  });

  it("reads yaw 0 as facing south and yaw π as facing north", () => {
    expect(yawToBearing(0)).toBeCloseTo(180);
    expect(yawToBearing(Math.PI) % 360).toBeCloseTo(0);
    expect(yawToBearing(Math.PI / 2)).toBeCloseTo(90);
  });

  it("wraps relative bearings around north", () => {
    expect(relativeBearing(10, 350)).toBeCloseTo(20);
    expect(relativeBearing(350, 10)).toBeCloseTo(-20);
    expect(relativeBearing(180, 0)).toBeCloseTo(-180);
    expect(relativeBearing(90, 90)).toBeCloseTo(0);
  });

  it("lays out ticks every 15° with the winds on the 45s, across north", () => {
    const ticks = compassTicks(350, 90, 15);
    expect(ticks.map((t) => t.deg)).toEqual([315, 330, 345, 0, 15, 30]);
    expect(ticks.find((t) => t.deg === 0)?.point).toBe("n");
    expect(ticks.find((t) => t.deg === 315)?.point).toBe("nw");
    expect(ticks.find((t) => t.deg === 330)?.point).toBeUndefined();
    const north = ticks.find((t) => t.deg === 0)!;
    expect(north.at).toBeCloseTo(0.5 + 10 / 90);
    for (const t of ticks) {
      expect(t.at).toBeGreaterThanOrEqual(0);
      expect(t.at).toBeLessThanOrEqual(1);
    }
  });

  it("places pips by bearing and hides those outside the span", () => {
    expect(compassPosition(0, 0, 150)).toBeCloseTo(0.5);
    expect(compassPosition(5, 355, 150)).toBeCloseTo(0.5 + 10 / 150);
    expect(compassPosition(180, 0, 150)).toBeNull();
  });
});

describe("full-map grid", () => {
  const bounds = { minX: -20, maxX: 20, minZ: -30, maxZ: 31 };

  it("uses square cells: 8 lettered columns and as many rows as the depth needs", () => {
    const grid = mapGrid(bounds, 8);
    expect(grid.cell).toBeCloseTo(5);
    expect(grid.columns).toBe(8);
    expect(grid.rows).toBe(13); // 61 m / 5 m → 12.2 → 13
  });

  it("labels columns A… and rows 1…", () => {
    expect([0, 1, 7, 25, 26, 27].map(columnLabel)).toEqual(["A", "B", "H", "Z", "AA", "AB"]);
    const grid = mapGrid(bounds, 8);
    expect(gridLabel(grid, { x: -19.9, z: -29.9 })).toBe("A1");
    expect(gridLabel(grid, { x: 0.1, z: 0.1 })).toBe("E7");
    expect(gridLabel(grid, { x: 19.99, z: 30.9 })).toBe("H13");
    // Points off the grid clamp onto its edge cells.
    expect(gridLabel(grid, { x: 999, z: -999 })).toBe("H1");
  });
});

describe("hit testing", () => {
  const items = [{ id: "a", x: 100, y: 100 }, { id: "b", x: 104, y: 100 }, { id: "c", x: 150, y: 150 }];

  it("picks the closest marker within the radius", () => {
    expect(pickNearest(items, { x: 103, y: 100 }, 10)?.id).toBe("b");
    expect(pickNearest(items, { x: 101, y: 101 }, 10)?.id).toBe("a");
    expect(pickNearest(items, { x: 150, y: 157 }, 8)?.id).toBe("c");
    expect(pickNearest(items, { x: 150, y: 170 }, 8)).toBeNull();
  });

  it("hits an off-screen agent at its clamped edge position", () => {
    const t = centredTransform({ x: 0, z: 0 }, 20, 200, 200);
    const far = worldToMap(t, { x: 80, z: 0 });
    const edge = clampToEdge(far, 200, 200, 12);
    expect(pickNearest([{ id: "far", x: edge.x, y: edge.y }], { x: 186, y: 101 }, 10)?.id).toBe("far");
  });

  it("names the place under a point: checkpoint, then room, then studio, then the campus zone", () => {
    const layout = buildOfficeLayout([agent("a1", "codex"), agent("a2", "gemini")], {
      teams: [{ id: "t1", name: "Core", members: ["a1"], createdMs: 1 }],
    });
    const manage = layout.checkpoints.find((c) => c.id === "manage")!;
    expect(placeAt(layout, manage)).toEqual({ kind: "checkpoint", id: "manage" });
    const lead = layout.rooms.find((r) => r.kind === "lead")!;
    expect(placeAt(layout, { x: lead.minX + 0.3, z: lead.minZ + 0.3 })).toEqual({ kind: "room", id: "lead" });
    // The pool studio has no name of its own; a team's studio carries the team's.
    const [pool, core] = layout.departments;
    expect(placeAt(layout, { x: pool.minX + 0.2, z: pool.minZ + 0.2 })).toEqual({ kind: "department", label: "" });
    expect(placeAt(layout, { x: core.minX + 0.2, z: core.minZ + 0.2 })).toEqual({ kind: "department", label: "Core" });
    // Between the studios: the most specific zone wins where they overlap.
    const zone = (kind: string) => layout.zones!.find((z) => z.kind === kind)!;
    const mid = (kind: string) => ({ x: (zone(kind).minX + zone(kind).maxX) / 2, z: (zone(kind).minZ + zone(kind).maxZ) / 2 });
    const atrium = zone("atrium");
    expect(placeAt(layout, { x: atrium.minX + 0.5, z: atrium.minZ + 0.5 })).toEqual({ kind: "zone", id: "atrium" });
    expect(placeAt(layout, { x: zone("plaza").minX + 0.5, z: atrium.minZ + 0.5 })).toEqual({ kind: "zone", id: "plaza" });
    expect(placeAt(layout, { x: 0, z: zone("boulevard").minZ + 0.5 })).toEqual({ kind: "zone", id: "boulevard" });
    for (const kind of ["plot", "garden", "booths", "library", "cafe"] as const) expect(placeAt(layout, mid(kind)), kind).toEqual({ kind: "zone", id: kind });
    expect(placeAt(layout, { x: layout.bounds.minX + 0.01, z: 0 })).toBeNull();
    // The coding floor has no zones: open floor stays nameless.
    const coding = buildOfficeLayout([], { variant: "coding" });
    expect(placeAt(coding, coding.arrival)).toEqual({ kind: "checkpoint", id: "launch" });
    expect(placeAt(coding, { x: 0, z: coding.arrival.z + 1.4 })).toBeNull();
  });
});

describe("the minimap's framing", () => {
  const bounds = { minX: -26, maxX: 26, minZ: -23.5, maxZ: 23.5 };

  it("follows the person in the middle of the floor and stays on the floor at its edges", () => {
    // In the open: centred on the person.
    expect(minimapCentre({ x: 3, z: -2 }, bounds, 26)).toEqual({ x: 3, z: -2 });
    // At the elevator by the south window: the card stops a step past the edge instead of showing half a card of night.
    const south = minimapCentre({ x: -9, z: 20.9 }, bounds, 26);
    expect(south.x).toBe(-9);
    expect(south.z).toBeCloseTo(23.5 + 1.5 - 13, 9);
    // In a corner both axes hold.
    expect(minimapCentre({ x: 25, z: -23 }, bounds, 26)).toEqual({ x: 26 + 1.5 - 13, z: -23.5 - 1.5 + 13 });
    // The person is still on the card.
    const t = centredTransform(south, 26, 200, 200);
    const me = worldToMap(t, { x: -9, z: 20.9 });
    expect(me.y).toBeGreaterThan(100);
    expect(me.y).toBeLessThan(200);
  });

  it("centres a floor that is narrower than the view", () => {
    const hall = { minX: -6.2, maxX: 6.2, minZ: -21.8, maxZ: 21.8 };
    const centre = minimapCentre({ x: -3.4, z: 17 }, hall, 26);
    expect(centre.x).toBeCloseTo(0, 9);
    expect(centre.z).toBeCloseTo(21.8 + 1.5 - 13, 9);
    // Zoomed out past the whole floor, the floor sits in the middle whatever the person does.
    expect(minimapCentre({ x: 20, z: 20 }, bounds, 90)).toEqual({ x: 0, z: 0 });
  });
});

describe("the full map's sheet", () => {
  it("takes the plan's shape, so no band of the sheet stays empty", () => {
    const pad = 30, head = 46;
    // A nearly square plan in a wide space: full height, only as wide as the plan needs.
    const square = fitSheet({ minX: 0, maxX: 52, minZ: 0, maxZ: 47 }, 1400, 800, pad, head);
    expect(square.height).toBe(800);
    expect((square.width - pad * 2) / (square.height - head - pad * 2)).toBeCloseTo(52 / 47, 1);
    expect(square.width).toBeLessThan(1000);
    // A plan taller than wide gets a narrow sheet; a wide plan is held by the width instead.
    const tall = fitSheet({ minX: 0, maxX: 52, minZ: 0, maxZ: 81 }, 1400, 800, pad, head);
    expect(tall.width).toBeLessThan(square.width);
    const wide = fitSheet({ minX: 0, maxX: 120, minZ: 0, maxZ: 30 }, 900, 800, pad, head);
    expect(wide.width).toBe(900);
    expect(wide.height).toBeLessThan(800);
    expect((wide.width - pad * 2) / (wide.height - head - pad * 2)).toBeCloseTo(4, 1);
    // Never wider than the cap, never taller than the space.
    expect(fitSheet({ minX: 0, maxX: 100, minZ: 0, maxZ: 40 }, 3000, 900, pad, head).width).toBe(1200);
  });

  it("keeps a long name over its own place: smaller first, then cut", () => {
    const calls: string[] = [];
    let font = "";
    const ctx = {
      set font(value: string) { font = value; },
      get font() { return font; },
      // Seven pixels a letter at 12 px, scaling with the size.
      measureText: (text: string) => ({ width: text.length * 7 * (Number(/([0-9.]+)px/.exec(font)?.[1] ?? 12) / 12) }),
      strokeText: (text: string) => { calls.push(text); },
      fillText: (text: string) => { calls.push(text); },
    } as unknown as CanvasRenderingContext2D;
    drawMapLabel(ctx, "CORE", 0, 0, 12, 800, 80);
    expect(calls.at(-1)).toBe("CORE");
    expect(font).toContain("12px");
    drawMapLabel(ctx, "PLATFORM TEAM", 0, 0, 12, 800, 80);
    expect(calls.at(-1)).toBe("PLATFORM TEAM");
    expect(font).not.toContain(" 12px");
    drawMapLabel(ctx, "THE VERY LONG NAME OF A TEAM", 0, 0, 12, 800, 80);
    expect(calls.at(-1)!.endsWith("…")).toBe(true);
    expect(calls.at(-1)!.length).toBeLessThan(20);
  });
});

describe("colour helpers", () => {
  it("shades hex colours and passes anything else through", () => {
    expect(shade("#808080", -1)).toBe("#000000");
    expect(shade("#808080", 1)).toBe("#ffffff");
    expect(shade("#fff", -0.5)).toBe("#808080");
    expect(shade("hsl(1 2% 3%)", -0.3)).toBe("hsl(1 2% 3%)");
  });

  it("picks readable ink and initials", () => {
    expect(inkOn("#ffffff")).not.toBe("#ffffff");
    expect(inkOn("#1b1f2a")).toBe("#ffffff");
    expect(initialOf("  ada")).toBe("A");
    expect(initialOf("")).toBe("?");
  });
});

describe("drawing", () => {
  const layout = buildOfficeLayout([agent("a1", "codex"), agent("a2", "codex", { state: "working" }), agent("l", "", { tier: "lead" })]);

  it("paints the floor art with every wall segment", () => {
    const { ctx, log } = recorder();
    const t = fitTransform(layout.bounds, 220, 300);
    drawFloorArt(ctx, layout, t, layout.bounds);
    expect(log[0]).toBe("globalAlpha=1");
    expect(log).toContain(`fillStyle=${MAP_PAINT.space}`);
    expect(log).toContain(`fillStyle=${MAP_PAINT.floor}`);
    expect(log).toContain(`strokeStyle=${MAP_PAINT.wall}`);
    // Walls are the only straight segments started with moveTo after the planks; at least one per wall.
    expect(log.filter((l) => l.startsWith("moveTo")).length).toBeGreaterThanOrEqual(layout.walls.length);
    expect(log[log.length - 1]).not.toMatch(/^globalAlpha=0/);
  });

  it("paints the campus: paved boulevards, planted ground, the free plot, the atrium, trees and every studio's name wall", () => {
    const { ctx, log } = recorder();
    drawFloorArt(ctx, layout, fitTransform(layout.bounds, 420, 360), layout.bounds);
    for (const colour of [MAP_PAINT.paving, MAP_PAINT.moss, MAP_PAINT.felt, MAP_PAINT.tile, MAP_PAINT.plot, MAP_PAINT.atrium, MAP_PAINT.olive,
      MAP_PAINT.tree, MAP_PAINT.bench, MAP_PAINT.screen, MAP_PAINT.oak, MAP_PAINT.sofa, MAP_PAINT.counter]) {
      expect(log, colour).toContain(`fillStyle=${colour}`);
    }
    // The plot is outlined dashed, in the bronze of the atrium's ring.
    expect(log).toContain(`strokeStyle=${MAP_PAINT.inlay}`);
    expect(log.some((l) => l.startsWith("setLineDash(") && l !== "setLineDash()")).toBe(true);
    // A round mark per tree and per standing table, besides the atrium's disc.
    const round = layout.ambience!.filter((i) => i.kind === "olive" || i.kind === "tree" || i.kind === "hightable").length;
    expect(log.filter((l) => l.startsWith("arc(")).length).toBeGreaterThanOrEqual(round + 1);
    // The coding floor paints none of it.
    const above = recorder();
    const coding = buildOfficeLayout([agent("p1", "Website")], { variant: "coding" });
    drawFloorArt(above.ctx, coding, fitTransform(coding.bounds, 220, 300), coding.bounds);
    for (const colour of [MAP_PAINT.paving, MAP_PAINT.moss, MAP_PAINT.plot, MAP_PAINT.olive]) expect(above.log).not.toContain(`fillStyle=${colour}`);
  });

  it("rings tokens by state, dashes the paused one and prints the initial", () => {
    const { ctx, log } = recorder();
    const base = { x: 50, y: 50, colour: "#336699", selected: false };
    drawAgentToken(ctx, { ...base, id: "w", name: "Wes", state: "working" }, 6, null);
    drawAgentToken(ctx, { ...base, id: "q", name: "quinn", state: "waiting", selected: true }, 6, 0.5);
    drawAgentToken(ctx, { ...base, id: "p", name: "Pia", state: "paused" }, 6, null);
    expect(log).toContain(`strokeStyle=${STATE_RING.working}`);
    expect(log).toContain(`strokeStyle=${STATE_RING.waiting}`);
    expect(log.some((l) => l.startsWith("setLineDash(2,2"))).toBe(true);
    expect(log.some((l) => l.startsWith("fillText(W,"))).toBe(true);
    expect(log.some((l) => l.startsWith("fillText(Q,"))).toBe(true);
    // The selected token gets a halo ring with a pulse-dependent alpha.
    expect(log).toContain("strokeStyle=rgba(255,255,255,0.450)");
  });

  it("points the player arrow and the edge arrow the right way", () => {
    const { ctx, log } = recorder();
    // Heading π looks north: the arrow tip lies above the player.
    drawPlayerArrow(ctx, 100, 100, Math.PI, 9);
    const tip = log.find((l) => l.startsWith("moveTo"))!;
    const [, y] = tip.slice("moveTo(".length, -1).split(",").map(Number);
    expect(y).toBeLessThan(100);

    const edge = recorder();
    drawEdgeArrow(edge.ctx, 188, 100, 0, { colour: "#336699", state: "idle", selected: false });
    const edgeTip = edge.log.find((l) => l.startsWith("moveTo"))!;
    const [ex] = edgeTip.slice("moveTo(".length, -1).split(",").map(Number);
    expect(ex).toBeGreaterThan(188);
  });
});
