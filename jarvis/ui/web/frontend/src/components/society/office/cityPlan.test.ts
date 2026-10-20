import { describe, expect, it } from "vitest";
import { CITY, distanceToRect, GROUND_Y, planCity, roofLimit, SINGULARITY, singularityPosition } from "./cityPlan";
import { cityUniforms, lensMaterial } from "./cityShaders";
import type { Rect } from "./officeLayout";

/** A small floor (the Level Hall's size), a typical campus and a large one, not centred on the origin. */
const FLOORS: Record<string, Rect> = {
  hall: { minX: -14, maxX: 14, minZ: -10, maxZ: 10 },
  campus: { minX: -6, maxX: 92, minZ: -4, maxZ: 64 },
  large: { minX: -70, maxX: 70, minZ: -45, maxZ: 45 },
};

describe("the city plan", () => {
  for (const [name, bounds] of Object.entries(FLOORS)) {
    const plan = planCity(bounds);

    it(`is a dense city and the same every time (${name})`, () => {
      expect(plan.towers.length).toBeGreaterThan(400);
      expect(planCity(bounds)).toEqual(plan);
    });

    it(`keeps the plaza round the building empty (${name})`, () => {
      for (const t of plan.towers) {
        const reach = Math.hypot(t.w, t.d) / 2;
        expect(distanceToRect(t.x, t.z, bounds) - reach).toBeGreaterThanOrEqual(CITY.clear - 0.01);
      }
    });

    it(`keeps every roof near the building far below the floor, the nearest lowest (${name})`, () => {
      for (const t of plan.towers) {
        const roof = GROUND_Y + t.h;
        const edge = distanceToRect(t.x, t.z, bounds);
        expect(roof).toBeLessThanOrEqual(roofLimit(edge) + 0.01);
        if (edge < CITY.lowReach) expect(roof).toBeLessThanOrEqual(CITY.nearRoof);
      }
      // A roof beside the plaza lies over a hundred metres down.
      expect(roofLimit(CITY.clear)).toBeLessThan(-150);
    });

    it(`puts no two towers on one spot (${name})`, () => {
      const sorted = [...plan.towers].sort((a, b) => a.x - b.x);
      for (let i = 0; i < sorted.length; i += 1) {
        const a = sorted[i];
        for (let j = i + 1; j < sorted.length && sorted[j].x - a.x < 40; j += 1) {
          const b = sorted[j];
          // Footprints as circles round their extent (rotated prisms included) for prisms, boxes for blocks.
          const overlapX = Math.abs(a.x - b.x) < (a.w + b.w) / 2 - 0.5;
          const overlapZ = Math.abs(a.z - b.z) < (a.d + b.d) / 2 - 0.5;
          expect(overlapX && overlapZ, `${a.x},${a.z} / ${b.x},${b.z}`).toBe(false);
        }
      }
    });

    it(`clears a crater for the singularity, ringed by spires, its disc and rings inside it (${name})`, () => {
      const s = singularityPosition(bounds);
      expect(plan.singularity).toEqual(s);
      const inCrater = plan.towers.filter((t) => Math.hypot(t.x - s.x, t.z - s.z) < SINGULARITY.crater);
      expect(inCrater).toEqual([]);
      expect(SINGULARITY.disc.outer).toBeLessThan(SINGULARITY.crater);
      for (const r of SINGULARITY.rings) expect(r.radius).toBeLessThan(SINGULARITY.crater);
      const spires = plan.towers.filter((t) => t.kind === "spire" && t.crown && t.accent === 2 && Math.hypot(t.x - s.x, t.z - s.z) <= SINGULARITY.spireRing[1] + 1);
      expect(spires.length).toBe(SINGULARITY.spires);
      // It hovers below the floor, well away from the building.
      expect(s.y).toBeLessThan(-100);
      expect(distanceToRect(s.x, s.z, bounds)).toBeGreaterThan(SINGULARITY.crater + CITY.clear);
    });

    it(`flies its traffic below the floor, outside the plaza and above the roofs it circles (${name})`, () => {
      expect(plan.lanes.length).toBeGreaterThanOrEqual(8);
      const half = Math.hypot(bounds.maxX - bounds.minX, bounds.maxZ - bounds.minZ) / 2;
      const buildingLanes = plan.lanes.slice(0, plan.lanes.length - 3);
      for (const lane of plan.lanes) {
        expect(lane.y + lane.bob).toBeLessThan(-50);
        expect(lane.cars).toBeGreaterThan(10);
        expect(Math.abs(lane.omega)).toBeGreaterThan(0);
      }
      for (const lane of buildingLanes) {
        expect(Math.min(lane.rx, lane.rz)).toBeGreaterThan(half + CITY.clear);
        for (const t of plan.towers) {
          // A tower under the lane's ellipse (within a tower's reach of it) stays below the lane.
          const dx = (t.x - lane.cx) / lane.rx, dz = (t.z - lane.cz) / lane.rz;
          const off = Math.abs(Math.hypot(dx, dz) - 1) * Math.min(lane.rx, lane.rz);
          if (off < Math.hypot(t.w, t.d) / 2 + 3) expect(GROUND_Y + t.h, `${t.x},${t.z}`).toBeLessThan(lane.y - lane.bob - 2.4);
        }
      }
    });

    it(`puts beacons on the tall roofs and beams only on far towers (${name})`, () => {
      expect(plan.beacons.length).toBeGreaterThan(20);
      for (const b of plan.beams) expect(distanceToRect(b.x, b.z, bounds)).toBeGreaterThan(CITY.lowReach * 0.6);
    });
  }

  it("keeps the same city round a floor that grows: only towers near the new plaza change", () => {
    const before = FLOORS.campus, after = { ...before, maxX: before.maxX + 9, maxZ: before.maxZ + 5 };
    const a = planCity(before), b = planCity(after);
    expect(b.singularity).toEqual(a.singularity);
    const key = (t: { x: number; z: number; h: number; kind: string }) => `${t.kind}@${t.x.toFixed(2)},${t.z.toFixed(2)}:${t.h.toFixed(2)}`;
    const kept = new Set(b.towers.map(key));
    const far = a.towers.filter((t) => distanceToRect(t.x, t.z, after) > CITY.lowReach + 20);
    const same = far.filter((t) => kept.has(key(t)));
    // Away from the building every tower stays exactly where and as tall as it was (lanes may trim a few).
    expect(same.length / far.length).toBeGreaterThan(0.9);
  });
});

describe("the singularity's lens", () => {
  it("draws its photon ring just outside the core, wherever the sheet's size puts it", () => {
    const size = SINGULARITY.core * 9;
    const lens = lensMaterial(cityUniforms({ x: 0, y: 0, z: 0 }), SINGULARITY.core, size);
    // The shader maps the sheet to -1..1; the core's share of that half width brings r = 1 to the core's edge.
    const coreShare = lens.uniforms.uCore.value as number, sheet = lens.uniforms.uSize.value as number;
    expect(coreShare * (sheet / 2)).toBeCloseTo(SINGULARITY.core, 6);
    expect(lens.vertexShader).toContain("position.xy / (uSize * 0.5)");
    lens.dispose();
  });
});
