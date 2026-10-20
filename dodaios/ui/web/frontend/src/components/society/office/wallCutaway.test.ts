import { describe, expect, it } from "vitest";
import { roomAt, wallsOf, type Room } from "./officeLayout";
import { campusLimits, cornersInView } from "./officeCamera.testkit";
import { CAMERA_LIMITS, OVERVIEW_SPAN, cameraLimitsFor, campusOverview, followBlend, frameDistance } from "./officeCamera";
import { buildOfficeLayout } from "./officeLayout";
import { rosterOf } from "./officeFixtures";
import { CUTAWAY_SCALE, cutawayStep, cutawayWalls, walledRoomAt, wallKey } from "./wallCutaway";
import { campusOf } from "./officeFixtures";

// Two walled rooms side by side sharing a wall line, and an open lobby south of them.
const west: Room = { id: "lead", kind: "lead", walled: true, minX: 0, maxX: 8, minZ: 0, maxZ: 6, doors: [{ side: "south", at: 4, width: 1.6 }] };
const east: Room = { id: "team", kind: "team", walled: true, minX: 8, maxX: 16, minZ: 0, maxZ: 6, doors: [{ side: "south", at: 12, width: 1.8 }] };
const lobby: Room = { id: "reception", kind: "reception", walled: false, minX: 0, maxX: 16, minZ: 10, maxZ: 16, doors: [] };
const rooms = [west, east, lobby];
const walls = rooms.flatMap(wallsOf);
/** Keys of the wall runs matching `test`; two rooms' runs along one shared line have one key. */
const keysOn = (test: (w: (typeof walls)[number]) => boolean) => [...new Set(walls.filter(test).map(wallKey))].sort();

describe("which walls step aside", () => {
  it("opens the sides of the person's room that the camera looks in through", () => {
    // The home view: the camera stands south-east of the room.
    const cut = cutawayWalls(rooms, walls, { x: 4, z: 3 }, { x: 20, z: 18 });
    const south = keysOn((w) => w.z1 === 6 && w.z2 === 6 && Math.max(w.x1, w.x2) <= 8);
    // The shared wall line x = 8 holds a run of each room: both step aside.
    const shared = keysOn((w) => w.x1 === 8 && w.x2 === 8);
    expect(walls.filter((w) => w.x1 === 8 && w.x2 === 8)).toHaveLength(2);
    expect([...cut].sort()).toEqual([...south, ...shared].sort());
    // The far sides stay up: they are the room's backdrop.
    expect(cut.has(wallKey(walls.find((w) => w.z1 === 0 && w.x1 === 0)!))).toBe(false);
    expect(cut.has(wallKey(walls.find((w) => w.x1 === 0 && w.x2 === 0)!))).toBe(false);
  });

  it("leaves every wall standing while the person is on the open floor or in an open room", () => {
    expect(cutawayWalls(rooms, walls, { x: 4, z: 8 }, { x: 20, z: 18 }).size).toBe(0);
    expect(cutawayWalls(rooms, walls, { x: 4, z: 12 }, { x: 20, z: 18 }).size).toBe(0);
    expect(walledRoomAt(rooms, { x: 4, z: 12 })).toBeNull();
    expect(walledRoomAt(rooms, { x: 4, z: 3 })?.kind).toBe("lead");
  });

  it("follows the camera round the room and never flickers while the person walks about inside", () => {
    const fromNorthWest = cutawayWalls(rooms, walls, { x: 12, z: 3 }, { x: -6, z: -9 });
    expect([...fromNorthWest].sort()).toEqual(keysOn((w) => (w.z1 === 0 && w.z2 === 0 && Math.min(w.x1, w.x2) >= 8) || (w.x1 === 8 && w.x2 === 8)));
    const here = cutawayWalls(rooms, walls, { x: 9, z: 1 }, { x: 20, z: 18 });
    const there = cutawayWalls(rooms, walls, { x: 15, z: 5.5 }, { x: 20, z: 18 });
    expect([...here].sort()).toEqual([...there].sort());
    // A camera straight above the room looks in through no side.
    expect(cutawayWalls(rooms, walls, { x: 12, z: 3 }, { x: 12, z: 3 }).size).toBe(0);
  });

  it("opens the rooms of the real campus for someone standing in them", () => {
    const { layout } = campusOf(20, [6, 5]);
    for (const room of layout.rooms.filter((r) => r.walled)) {
      const inside = { x: (room.minX + room.maxX) / 2, z: (room.minZ + room.maxZ) / 2 };
      expect(roomAt(layout, inside)?.kind).toBe(room.kind);
      const camera = { x: inside.x + 14, z: inside.z + 17 };
      const cut = cutawayWalls(layout.rooms, layout.walls, inside, camera);
      expect(cut.size, room.kind).toBeGreaterThan(0);
      // Only walls along this room's own sides are touched.
      for (const wall of layout.walls.filter((w) => cut.has(wallKey(w)))) {
        const onSide = Math.abs(wall.z1 - room.maxZ) < 0.2 || Math.abs(wall.x1 - room.maxX) < 0.2 || Math.abs(wall.z1 - room.minZ) < 0.2 || Math.abs(wall.x1 - room.minX) < 0.2;
        expect(onSide, room.kind).toBe(true);
      }
    }
  });

  it("glides a wall down to a kerb and back up, and places it at once for reduced motion", () => {
    let h = 1;
    for (let i = 0; i < 60; i += 1) h = cutawayStep(h, true, 1 / 60);
    expect(h).toBe(CUTAWAY_SCALE);
    const mid = cutawayStep(1, true, 1 / 60);
    expect(mid).toBeLessThan(1);
    expect(mid).toBeGreaterThan(CUTAWAY_SCALE);
    for (let i = 0; i < 60; i += 1) h = cutawayStep(h, false, 1 / 60);
    expect(h).toBe(1);
    expect(cutawayStep(1, true, 1 / 60, true)).toBe(CUTAWAY_SCALE);
    expect(cutawayStep(CUTAWAY_SCALE, false, 1 / 60, true)).toBe(1);
  });
});

describe("the camera on a campus", () => {
  it("fits the whole floor to the viewport in the overview, at any size and viewport shape", () => {
    const floors = [
      campusOf(4, []).layout.bounds, campusOf(14, [5, 4, 3]).layout.bounds,
      // The tall plan: forty agents in eight teams.
      campusOf(40, [5, 5, 5, 5, 5, 5, 5, 5]).layout.bounds, campusOf(90, [12, 11, 10, 9, 8, 8, 7, 7]).layout.bounds,
      buildOfficeLayout(rosterOf(10), { variant: "coding" }).bounds,
    ];
    for (const bounds of floors) {
      // A wide window, a squarer one, and the IDE's narrow side panel.
      for (const aspect of [16 / 9, 4 / 3, 0.62]) {
        const label = `${(bounds.maxX - bounds.minX).toFixed(0)} x ${(bounds.maxZ - bounds.minZ).toFixed(0)} m, aspect ${aspect.toFixed(2)}`;
        const pose = campusOverview(bounds, aspect);
        const { inside, box } = cornersInView(bounds, pose, aspect);
        expect(inside, label).toBe(true);
        // In the middle of the view, not in its lower half.
        expect(Math.abs(box.minX + box.maxX) / 2, label).toBeLessThan(0.02);
        expect(Math.abs(box.minY + box.maxY) / 2, label).toBeLessThan(0.02);
        // As large as it goes: it spans 85 % of whichever axis binds.
        const span = Math.max(box.maxX - box.minX, box.maxY - box.minY) / 2;
        expect(span, label).toBeGreaterThan(OVERVIEW_SPAN - 0.01);
        expect(span, label).toBeLessThan(OVERVIEW_SPAN + 0.01);
        // The look-at point stays on the floor, and the wheel can reach this view.
        expect(pose.target[1]).toBe(0);
        const distance = Math.hypot(pose.position[0] - pose.target[0], pose.position[1], pose.position[2] - pose.target[2]);
        expect(distance, label).toBeLessThanOrEqual(cameraLimitsFor(bounds, aspect).maxDistance);
      }
    }
  });

  it("stands much closer than a view that merely holds every corner", () => {
    const bounds = campusOf(14, [5, 4, 3]).layout.bounds;
    const pose = campusOverview(bounds, 16 / 9);
    const distance = Math.hypot(pose.position[0] - pose.target[0], pose.position[1], pose.position[2] - pose.target[2]);
    expect(distance).toBeLessThan(frameDistance(bounds, 16 / 9) * 0.9);
  });

  it("lets the wheel back away far enough for that overview, and never less than before", () => {
    const small = campusOf(4, []).layout.bounds;
    const large = campusOf(90, [12, 11, 10, 9, 8, 8, 7, 7]).layout.bounds;
    for (const bounds of [small, large]) {
      const limits = cameraLimitsFor(bounds, 16 / 9);
      expect(limits.maxDistance).toBeGreaterThanOrEqual(CAMERA_LIMITS.maxDistance);
      expect(limits.maxDistance).toBeGreaterThan(frameDistance(bounds, 16 / 9));
      expect(limits).toMatchObject({ minDistance: CAMERA_LIMITS.minDistance, minPolar: CAMERA_LIMITS.minPolar, maxPolar: CAMERA_LIMITS.maxPolar });
    }
    // A portrait viewport needs more room than a wide one.
    expect(frameDistance(large, 0.62)).toBeGreaterThan(frameDistance(large, 16 / 9));
    expect(campusLimits(large).maxDistance).toBeGreaterThanOrEqual(cameraLimitsFor(large, 16 / 9).maxDistance);
  });

  it("follows at the same pace whatever the frame rate, and eases out", () => {
    // One 33 ms frame closes as much of the gap as two 16.5 ms frames.
    const one = followBlend(0.033);
    const two = 1 - (1 - followBlend(0.0165)) ** 2;
    expect(one).toBeCloseTo(two, 9);
    expect(followBlend(0)).toBe(0);
    expect(followBlend(0.016)).toBeGreaterThan(0.1);
    expect(followBlend(0.016)).toBeLessThan(0.15);
    expect(followBlend(10)).toBeCloseTo(1, 6);
  });
});
