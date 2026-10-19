import { describe, expect, it } from "vitest";
import { REWARD_IDS } from "../progression/levelCatalog";
import { arrivalPose } from "./officeFloors";
import { buildHallLayout, LEVEL_HALL } from "./hallFloorLayout";
import { buildOfficeLayout, FURNITURE_SIZE, footprint } from "./officeLayout";
import { buildNavGrid, findPath, isWalkable } from "./officeNav";
import { floorForKey, PANEL_FLOORS } from "./ElevatorPanel";
import { callDirection } from "./ElevatorCallButton";
import { floorLevel, OFFICE_FLOORS } from "./officeStore";

describe("Level Hall floor", () => {
  const layout = buildHallLayout();
  const hall = layout.rooms.find((r) => r.kind === "levels")!;
  const grid = buildNavGrid(layout);

  it("is a floor of its own: the hall behind a door, a foyer with the elevator, nobody's desk", () => {
    expect(layout.variant).toBe("hall");
    expect(layout.rooms.map((r) => r.kind)).toEqual(["levels"]);
    expect(layout.departments).toEqual([]);
    expect(layout.lead.desks).toEqual([]);
    expect(layout.checkpoints.map((c) => c.id)).toEqual(["studio", "levels", "elevator"]);
    expect(hall.walled).toBe(true);
    expect(hall.maxX - hall.minX).toBeCloseTo(LEVEL_HALL.width, 9);
    expect(hall.maxZ - hall.minZ).toBeCloseTo(LEVEL_HALL.depth, 9);
    expect(hall.doors).toEqual([{ side: "south", at: 0, width: LEVEL_HALL.door }]);
    // The same plan every time.
    expect(buildHallLayout()).toEqual(layout);
    // Nothing of it is left on the agents floor.
    const below = buildOfficeLayout([]);
    expect(below.rooms.some((r) => r.kind === "levels")).toBe(false);
    expect(below.checkpoints.some((c) => c.id === "studio" || c.id === "levels")).toBe(false);
  });

  it("keeps the hall's fittings: rank wall, dais, a display case per reward up the runner, the guide", () => {
    const pedestals = layout.furniture.filter((f) => f.kind === "rewardPedestal");
    expect(pedestals.map((p) => p.id)).toEqual(REWARD_IDS.map((_, n) => `level-pedestal-${n}`));
    const cx = (hall.minX + hall.maxX) / 2;
    pedestals.forEach((p, n) => {
      const box = footprint(p);
      expect(box.minX > hall.minX && box.maxX < hall.maxX && box.minZ > hall.minZ && box.maxZ < hall.maxZ, p.id).toBe(true);
      expect(Math.sign(p.x - cx)).toBe(n % 2 === 0 ? -1 : 1);
      if (n >= 2) {
        expect(p.z).toBeLessThan(pedestals[n - 2].z);
        // Room to walk between two cases on the same side.
        expect(pedestals[n - 2].z - p.z).toBeGreaterThan(FURNITURE_SIZE.rewardPedestal.d + 0.9);
      }
    });
    const stage = layout.furniture.find((f) => f.kind === "studioStage")!;
    const studio = layout.checkpoints.find((c) => c.id === "studio")!;
    expect([studio.x, studio.z]).toEqual([stage.x, stage.z]);
    expect(stage.z).toBeLessThan(Math.min(...pedestals.map((p) => p.z)));
    expect(layout.furniture.find((f) => f.kind === "levelWall")!.z).toBeLessThan(stage.z);
    const guide = layout.furniture.find((f) => f.kind === "levelGuide")!;
    const levels = layout.checkpoints.find((c) => c.id === "levels")!;
    expect(guide.z).toBeGreaterThan(Math.max(...pedestals.map((p) => p.z)));
    expect(levels.z).toBeLessThan(guide.z);
    for (const item of layout.furniture.filter((f) => f.room === "levels")) {
      expect(item.x > hall.minX && item.x < hall.maxX && item.z > hall.minZ && item.z < hall.maxZ, item.id).toBe(true);
    }
    expect(new Set(layout.furniture.map((f) => f.id)).size).toBe(layout.furniture.length);
  });

  it("lets the person step out of the elevator and walk to both stations through the door", () => {
    const elevator = layout.furniture.find((f) => f.kind === "elevator")!;
    const stop = layout.checkpoints.find((c) => c.id === "elevator")!;
    expect(stop.z).toBeCloseTo(elevator.z, 9);
    expect(stop.x).toBeGreaterThan(elevator.x);
    expect(stop.z).toBeGreaterThan(hall.maxZ);
    // Arriving by elevator: at its stop, facing away from the doors (east).
    const pose = arrivalPose(layout, "elevator");
    expect([pose.x, pose.z]).toEqual([stop.x, stop.z]);
    expect(pose.heading).toBeCloseTo(Math.PI / 2, 9);
    expect(isWalkable(grid, pose)).toBe(true);
    expect(isWalkable(grid, layout.spawn)).toBe(true);
    // The doorway is open, the wall beside it is not.
    expect(isWalkable(grid, { x: 0, z: hall.maxZ })).toBe(true);
    expect(isWalkable(grid, { x: hall.minX + 1.5, z: hall.maxZ })).toBe(false);
    const studio = layout.checkpoints.find((c) => c.id === "studio")!;
    const levels = layout.checkpoints.find((c) => c.id === "levels")!;
    for (const target of [studio.approach!, { x: levels.x, z: levels.z }]) {
      expect(isWalkable(grid, target)).toBe(true);
      const path = findPath(grid, pose, target)!;
      expect(path).not.toBeNull();
      // The only way in is the door.
      const crossing = [pose, ...path].findIndex((p) => p.z < hall.maxZ);
      expect(crossing).toBeGreaterThan(0);
    }
    for (const cp of layout.checkpoints) {
      const solid = layout.furniture.filter((f) => FURNITURE_SIZE[f.kind].solid).map(footprint);
      const at = cp.approach ?? cp;
      expect(solid.some((o) => at.x >= o.minX && at.x <= o.maxX && at.z >= o.minZ && at.z <= o.maxZ), cp.id).toBe(false);
    }
  });

  it("is the top floor of the elevator: listed, numbered, reachable by its key", () => {
    expect(OFFICE_FLOORS).toEqual(["agents", "coding", "arcade", "hall"]);
    expect(floorLevel("hall")).toBe(3);
    expect(PANEL_FLOORS[0]).toBe("hall");
    expect(floorForKey("3")).toBe("hall");
    expect(floorForKey("0")).toBe("agents");
    expect(floorForKey("4")).toBeNull();
    expect(callDirection("hall")).toBe("down");
    expect(callDirection("arcade")).toBe("both");
    expect(callDirection("agents")).toBe("up");
  });
});
