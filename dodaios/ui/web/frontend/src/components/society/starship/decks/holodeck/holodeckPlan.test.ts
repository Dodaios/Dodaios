import { describe, expect, it } from "vitest";
import { ARCADE_GAMES } from "../../../arcade/arcadeGames";
import { insidePolygon } from "../../plan/builder";
import { buildNavGrid, findPath, isFree } from "../../nav/shipNav";
import { Matrix4 } from "three";
import { GeoBatch } from "../../render/kit/geo";
import { buildProps } from "../../render/deck/props";
import { buildHolodeck, cabinetStationId, emitterId } from "./holodeckPlan";
import { buildArch } from "./holodeckProps";

describe("holodeck plan", () => {
  const plan = buildHolodeck();

  it("gives every game one emitter and one cabinet station", () => {
    const stations = plan.stations.filter((s) => s.kind === "holoCabinet");
    expect(stations.map((s) => s.ref).sort()).toEqual(ARCADE_GAMES.map((g) => g.id).sort());
    for (const game of ARCADE_GAMES) {
      const station = plan.stations.find((s) => s.id === cabinetStationId(game.id));
      expect(station?.propId).toBe(emitterId(game.id));
      const prop = plan.props.find((p) => p.id === emitterId(game.id));
      expect(prop?.kind).toBe("cabinet");
      expect(prop?.ref).toBe(game.id);
    }
  });

  it("stands the player 0.9 m in front of each emitter, facing it", () => {
    for (const s of plan.stations.filter((st) => st.kind === "holoCabinet")) {
      const p = plan.props.find((q) => q.id === s.propId)!;
      const ahead = (s.x - p.x) * Math.sin(p.yaw) + (s.z - p.z) * Math.cos(p.yaw);
      expect(ahead).toBeCloseTo(p.d / 2 + 0.9, 5);
    }
  });

  it("has the turbolift centred on the stern wall", () => {
    const lift = plan.stations.find((s) => s.kind === "lift");
    expect(lift?.x).toBe(0);
    expect(plan.lift.x).toBe(0);
    expect(plan.props.find((p) => p.kind === "liftDoors")?.z).toBeCloseTo(plan.bounds.z1 - 0.3, 5);
    expect(plan.doors.some((d) => d.id === "lift-door")).toBe(true);
  });

  it("reaches every station and place from the turbolift", () => {
    const grid = buildNavGrid(plan);
    expect(isFree(grid, plan.lift)).toBe(true);
    const misses = [...plan.stations, ...plan.places].filter((t) => !findPath(grid, plan.lift, t)).map((t) => t.id);
    expect(misses).toEqual([]);
  });

  it("keeps ids unique and everything inside the hull", () => {
    const ids = [...plan.props.map((x) => `prop:${x.id}`), ...plan.places.map((x) => `place:${x.id}`), ...plan.stations.map((x) => `station:${x.id}`)];
    expect(new Set(ids).size).toBe(ids.length);
    for (const p of [...plan.props, ...plan.places, ...plan.stations]) expect(insidePolygon(plan.hull, p)).toBe(true);
  });

  it("is a black holo chamber nobody is seated in", () => {
    expect(plan.rooms.find((r) => r.kind === "holodeck")?.floor).toBe("holo");
    expect(plan.divisions).toEqual([]);
    expect(plan.places.some((p) => p.kind === "console")).toBe(false);
  });

  it("builds the emitters and the arch into the deck's batch", () => {
    const batch = new GeoBatch();
    buildProps(plan, batch);
    buildArch(batch.frame(new Matrix4()));
    const parts = batch.merged();
    expect(parts.some((p) => p.finish === "glow")).toBe(true);
    for (const p of parts) expect(p.geometry.attributes.position.count).toBeGreaterThan(0);
  });
});
