import { describe, expect, it } from "vitest";
import { buildEngineeringDeck, engineeringLayout, MAX_BAYS, MIN_BAYS, planBays, type EngineeringPane } from "./engineeringDeck";
import { buildNavGrid, findPath, isFree } from "../../nav/shipNav";
import { insidePolygon } from "../../plan/builder";
import type { DeckPlan } from "../../plan/types";

/** `n` panes spread round-robin over `workspaces` workspaces. */
function panes(n: number, workspaces: number): EngineeringPane[] {
  return Array.from({ length: n }, (_, i) => {
    const ws = i % Math.max(1, workspaces);
    return { agentId: `pane:w${ws}:h${i}`, workspaceId: `w${ws}`, workspace: `Workspace ${ws}` };
  });
}

function reachable(plan: DeckPlan) {
  const grid = buildNavGrid(plan);
  const misses: string[] = [];
  for (const place of plan.places) if (!findPath(grid, plan.lift, place)) misses.push(place.id);
  for (const station of plan.stations) if (!findPath(grid, plan.lift, station)) misses.push(station.id);
  return { grid, misses };
}

/** A clockwise convex polygon: every turn goes the same way. */
function convex(points: readonly { x: number; z: number }[]): boolean {
  let sign = 0;
  for (let i = 0; i < points.length; i += 1) {
    const a = points[i], b = points[(i + 1) % points.length], c = points[(i + 2) % points.length];
    const cross = (b.x - a.x) * (c.z - b.z) - (b.z - a.z) * (c.x - b.x);
    if (Math.abs(cross) < 1e-9) continue;
    if (sign === 0) sign = Math.sign(cross);
    else if (Math.sign(cross) !== sign) return false;
  }
  return true;
}

const CASES = [0, 3, 20].flatMap((n) => [1, 4, 8].map((ws) => [n, ws] as const));

describe("engineering deck plan", () => {
  it("gives every workspace a bay, at least four, at most six, the rest in Other", () => {
    expect(planBays([])).toHaveLength(MIN_BAYS);
    expect(planBays(panes(3, 1)).map((b) => b.kind)).toEqual(["workspace", "free", "free", "free"]);
    const many = planBays(panes(20, 8));
    expect(many).toHaveLength(MAX_BAYS);
    expect(many.map((b) => b.kind)).toEqual(["workspace", "workspace", "workspace", "workspace", "workspace", "other"]);
    expect(many[5].members).toHaveLength(panes(20, 8).filter((p) => ["w5", "w6", "w7"].includes(p.workspaceId)).length);
    expect(many[0].name).toBe("Workspace 0");
  });

  it.each(CASES)("seats every pane at its own console (%i panes over %i workspaces)", (n, ws) => {
    const plan = buildEngineeringDeck({ panes: panes(n, ws) });
    expect(plan.unseated).toEqual([]);
    for (const p of panes(n, ws)) {
      const seat = plan.seatOf.get(p.agentId);
      expect(seat?.owner).toBe(p.agentId);
      expect(seat?.kind).toBe("console");
      expect(plan.props.some((q) => q.kind === "bayConsole" && q.ref === p.agentId)).toBe(true);
    }
    // A pane sits in its own workspace's bay.
    const bays = planBays(panes(n, ws));
    for (const bay of bays) for (const id of bay.members) expect(plan.seatOf.get(id)?.division).toBe(bay.id);
    expect(plan.divisions.flatMap((d) => d.members).sort()).toEqual(panes(n, ws).map((p) => p.agentId).sort());
  });

  it.each(CASES)("reaches every place and station from the turbolift (%i panes over %i workspaces)", (n, ws) => {
    const plan = buildEngineeringDeck({ panes: panes(n, ws) });
    const { grid, misses } = reachable(plan);
    expect(misses).toEqual([]);
    expect(isFree(grid, plan.lift)).toBe(true);
    expect(isFree(grid, plan.arrival)).toBe(true);
  });

  it.each(CASES)("keeps ids unique and everything inside a convex hull (%i panes over %i workspaces)", (n, ws) => {
    const plan = buildEngineeringDeck({ panes: panes(n, ws) });
    expect(convex(plan.hull)).toBe(true);
    expect(plan.hull[0].z).toBe(0);
    const ids = [
      ...plan.props.map((x) => `prop:${x.id}`), ...plan.places.map((x) => `place:${x.id}`),
      ...plan.stations.map((x) => `station:${x.id}`), ...plan.rooms.map((x) => `room:${x.id}`), ...plan.walls.map((x) => `wall:${x.id}`),
    ];
    expect(new Set(ids).size).toBe(ids.length);
    for (const p of [...plan.places, ...plan.stations, ...plan.props]) expect(insidePolygon(plan.hull, p)).toBe(true);
    expect(plan.props.filter((p) => p.kind === "bayConsole").length).toBeLessThanOrEqual(64);
  });

  it("is deterministic", () => {
    const a = buildEngineeringDeck({ panes: panes(20, 4) });
    const b = buildEngineeringDeck({ panes: panes(20, 4) });
    expect(b.places.map((p) => [p.id, p.x, p.z, p.owner])).toEqual(a.places.map((p) => [p.id, p.x, p.z, p.owner]));
    expect(b.props.map((p) => [p.id, p.x, p.z, p.ref])).toEqual(a.props.map((p) => [p.id, p.x, p.z, p.ref]));
  });

  it("has the core, the systems display, the nook and the turbolift on the stern wall", () => {
    const plan = buildEngineeringDeck({ panes: panes(3, 1) });
    const layout = engineeringLayout(plan);
    expect(layout).toBeDefined();
    const reactor = plan.props.find((p) => p.kind === "reactor");
    expect(reactor && { x: reactor.x, z: reactor.z }).toEqual(layout?.centre);
    expect(plan.walls.filter((w) => w.kind === "rail").length).toBeGreaterThan(8);
    expect(plan.stations.find((s) => s.kind === "systems")?.propId).toBe("systems");
    expect(plan.props.find((p) => p.id === "systems")?.kind).toBe("systemsTable");
    expect(plan.places.some((p) => p.kind === "galley")).toBe(true);
    expect(plan.places.some((p) => p.kind === "window")).toBe(true);
    const lift = plan.props.find((p) => p.kind === "liftDoors");
    expect(lift?.x).toBe(0);
    expect(lift?.z).toBeCloseTo(plan.bounds.z1 - 0.3);
    expect(plan.stations.find((s) => s.kind === "lift")?.x).toBe(0);
    expect(plan.divisions).toHaveLength(1);
    expect(plan.divisions[0].colour).toMatch(/^#/);
  });

  it("widens a busy bay and opens a third row only when needed", () => {
    const small = buildEngineeringDeck({ panes: panes(6, 4) });
    const big = buildEngineeringDeck({ panes: panes(40, 1) });
    const span = (plan: DeckPlan, room: string) => {
      const arc = engineeringLayout(plan)?.bays.find((b) => b.room === room);
      return arc ? arc.a1 - arc.a0 : 0;
    };
    expect(span(big, "bay-ws-w0")).toBeGreaterThan(span(small, "bay-ws-w0"));
    expect(big.unseated).toEqual([]);
    expect(engineeringLayout(big)?.hullR).toBeGreaterThan(engineeringLayout(small)?.hullR ?? Infinity);
  });
});
