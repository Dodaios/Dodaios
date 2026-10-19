import { describe, expect, it } from "vitest";
import { RANKS } from "../../levels/ranks";
import { insidePolygon } from "../../plan/builder";
import { buildNavGrid, findPath, isFree } from "../../nav/shipNav";
import { Matrix4 } from "three";
import { GeoBatch } from "../../render/kit/geo";
import { buildProps } from "../../render/deck/props";
import { buildHonorsDeck, caseId, caseRanks } from "./honorsPlan";
import { buildRunner } from "./honorsProps";
import { insigniaSpec } from "./insignia";

describe("hall of honour plan", () => {
  const plan = buildHonorsDeck();

  it("keeps one display case for every officer and flag rank", () => {
    const wanted = RANKS.filter((r) => r.tier === "officer" || r.tier === "flag").map((r) => r.id);
    expect(caseRanks().map((r) => r.id)).toEqual(wanted);
    const cases = plan.stations.filter((s) => s.kind === "honorCase");
    expect(cases.map((s) => s.ref)).toEqual(wanted);
    for (const id of wanted) {
      const prop = plan.props.find((p) => p.id === caseId(id));
      expect(prop?.kind).toBe("honorCase");
      expect(prop?.ref).toBe(id);
    }
  });

  it("puts the rank wall at the bow with the dais before it, and higher ranks nearer the wall", () => {
    const wall = plan.props.find((p) => p.kind === "rankWall")!;
    const dais = plan.props.find((p) => p.kind === "dais")!;
    expect(wall.z).toBeLessThan(dais.z);
    expect(plan.stations.find((s) => s.kind === "rankWall")?.propId).toBe(wall.id);
    const zOf = (id: string) => plan.props.find((p) => p.id === caseId(id))!.z;
    expect(zOf("admiral")).toBeLessThan(zOf("ensign"));
  });

  it("has the turbolift centred on the stern wall", () => {
    expect(plan.stations.find((s) => s.kind === "lift")?.x).toBe(0);
    expect(plan.props.find((p) => p.kind === "liftDoors")?.z).toBeCloseTo(plan.bounds.z1 - 0.3, 5);
    expect(plan.lift.x).toBe(0);
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

  it("is a ceremonial hall nobody is seated in", () => {
    expect(plan.rooms.find((r) => r.kind === "hall")?.floor).toBe("honor");
    expect(plan.divisions).toEqual([]);
  });

  it("builds the wall, the dais, the cases and the runner into the deck's batch", () => {
    const batch = new GeoBatch();
    buildProps(plan, batch);
    buildRunner(batch.frame(new Matrix4()), 5, 38, 2.2);
    const finishes = batch.merged().map((p) => p.finish);
    expect(finishes).toContain("glass");
    expect(finishes).toContain("fabric");
  });

  it("gives every rank a distinct insignia", () => {
    const marks = RANKS.map((r) => JSON.stringify(insigniaSpec(r)));
    expect(new Set(marks).size).toBe(RANKS.length);
  });
});
