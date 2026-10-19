import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { buildBridgeDeck, bridgeHull, COMMAND, RAIL_R, READY_ROOM } from "./bridgeDeck";
import { buildNavGrid, findPath, isFree, lineOfSight } from "../../nav/shipNav";
import { insidePolygon } from "../../plan/builder";
import { rectContains, type Vec2 } from "../../plan/types";
import { DESTINATION_IDS } from "../../space/destinations";

function cross(o: Vec2, a: Vec2, b: Vec2): number {
  return (a.x - o.x) * (b.z - o.z) - (a.z - o.z) * (b.x - o.x);
}

describe("bridge deck plan", () => {
  const plan = buildBridgeDeck();
  const grid = buildNavGrid(plan);

  it("has a convex hull with the bow at z = 0", () => {
    const hull = bridgeHull();
    const signs = hull.map((p, i) => Math.sign(cross(p, hull[(i + 1) % hull.length], hull[(i + 2) % hull.length])));
    expect(new Set(signs.filter((s) => s !== 0)).size).toBe(1);
    expect(Math.min(...hull.map((p) => p.z))).toBeCloseTo(0, 6);
    expect(plan.bounds.z0).toBeCloseTo(0, 6);
  });

  it("reaches every place and station from the turbolift", () => {
    const misses: string[] = [];
    for (const place of plan.places) if (!findPath(grid, plan.lift, place)) misses.push(place.id);
    for (const station of plan.stations) if (!findPath(grid, plan.lift, station)) misses.push(station.id);
    expect(misses).toEqual([]);
    expect(isFree(grid, plan.lift)).toBe(true);
    expect(isFree(grid, plan.arrival)).toBe(true);
  });

  it("keeps ids unique and everything inside the hull", () => {
    const ids = [
      ...plan.props.map((x) => `prop:${x.id}`), ...plan.places.map((x) => `place:${x.id}`),
      ...plan.stations.map((x) => `station:${x.id}`), ...plan.rooms.map((x) => `room:${x.id}`), ...plan.walls.map((x) => `wall:${x.id}`),
    ];
    expect(new Set(ids).size).toBe(ids.length);
    for (const p of [...plan.places, ...plan.stations, ...plan.props]) expect(insidePolygon(plan.hull, p)).toBe(true);
  });

  it("seats the captain inside the horseshoe rail", () => {
    const seat = plan.places.find((p) => p.kind === "captain");
    expect(seat).toBeDefined();
    if (!seat) return;
    expect(Math.hypot(seat.x - COMMAND.x, seat.z - COMMAND.z)).toBeLessThan(RAIL_R - 1);
    expect(isFree(grid, seat)).toBe(true);
    // The rail is real: straight back to the lift is blocked, the way round (through the bow-side gap) is not.
    expect(plan.walls.filter((w) => w.kind === "rail").length).toBeGreaterThan(6);
    expect(lineOfSight(grid, seat, plan.lift)).toBe(false);
    expect(findPath(grid, plan.lift, seat)).not.toBeNull();
    const chair = plan.props.find((p) => p.kind === "captainChair");
    expect(chair && Math.hypot(chair.x - seat.x, chair.z - seat.z)).toBeLessThan(0.01);
    expect(plan.stations.find((s) => s.kind === "captain")?.propId).toBe(chair?.id);
  });

  it("has the bridge's stations, the turbolift centred on the stern wall", () => {
    const kinds = plan.stations.map((s) => s.kind);
    for (const k of ["captain", "firstOfficer", "helm", "ops", "lift"] as const) expect(kinds).toContain(k);
    const lift = plan.stations.find((s) => s.kind === "lift");
    expect(lift?.x).toBeCloseTo(0, 6);
    expect(plan.doors.find((d) => d.id === "lift-door")?.at.x).toBeCloseTo(0, 6);
    expect(plan.lift.z).toBeGreaterThan(plan.bounds.z1 - 2.5);
    expect(plan.props.some((p) => p.kind === "starChart" && !p.ref)).toBe(true);
    expect(plan.props.filter((p) => p.kind === "viewscreen").length).toBeGreaterThan(3);
  });

  it("puts the ready room off the side with a desk, a window and a door", () => {
    const room = plan.rooms.find((r) => r.kind === "readyroom");
    expect(room?.rect).toEqual(READY_ROOM);
    const desk = plan.props.find((p) => p.ref === "desk" && p.kind === "helmConsole");
    expect(desk && rectContains(READY_ROOM, desk)).toBe(true);
    expect(plan.places.some((p) => p.kind === "window" && rectContains(READY_ROOM, p))).toBe(true);
    expect(plan.doors.some((d) => d.id === "ready-door")).toBe(true);
    expect(plan.walls.some((w) => w.kind === "hull" && w.windows && w.a.x === READY_ROOM.x1 && w.b.x === READY_ROOM.x1)).toBe(true);
  });

  it("invents no crew", () => {
    expect(plan.divisions).toEqual([]);
    expect(plan.seatOf.size).toBe(0);
    expect(plan.places.some((p) => p.owner)).toBe(false);
  });
});

describe("bridge strings", () => {
  const dir = join(__dirname, "..", "..", "..", "..", "..", "i18n", "locales", "ship");
  const files = readdirSync(dir).filter((f) => /^bridge\.[a-z]+\.json$/.test(f));
  const flatten = (obj: Record<string, unknown>, prefix = ""): string[] => Object.entries(obj).flatMap(([k, v]) =>
    v && typeof v === "object" ? flatten(v as Record<string, unknown>, `${prefix}${k}.`) : [`${prefix}${k}`]);
  const load = (f: string) => JSON.parse(readFileSync(join(dir, f), "utf8")) as Record<string, unknown>;

  it("ships the same keys in all five languages", () => {
    expect(files.sort()).toEqual(["bridge.de.json", "bridge.en.json", "bridge.es.json", "bridge.pt.json", "bridge.zh.json"]);
    const en = flatten(load("bridge.en.json")).sort();
    for (const f of files) expect(flatten(load(f)).sort()).toEqual(en);
  });

  it("names and describes every destination", () => {
    const en = new Set(flatten(load("bridge.en.json")));
    for (const id of DESTINATION_IDS) {
      expect(en.has(`ship.bridge.destination.${id}.name`)).toBe(true);
      expect(en.has(`ship.bridge.destination.${id}.about`)).toBe(true);
    }
  });
});
