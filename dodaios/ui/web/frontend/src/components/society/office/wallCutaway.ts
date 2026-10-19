/**
 * Which walls step out of the way while the person stands inside a walled
 * room: the sides of that room the camera looks in through. Like the open
 * front of a doll's house, they drop to a low kerb so the room stays
 * readable, and rise again when the person leaves or the camera turns.
 *
 * The rule is by side, not by sight line, so nothing flickers while the
 * person walks about inside: only crossing a doorway or orbiting the camera
 * changes the answer. Pure and tested; OfficeCameraRig applies it to every
 * object tagged `userData.officeWall` (see `wallKey`).
 */
import type { Point, Room, WallSegment } from "./officeLayout";

/** How close to a room's side line a wall run must lie to belong to that side. */
const ON_SIDE_M = 0.2;
/** The camera must stand this far beyond a side before that side is opened (no flicker when it is level with it). */
const BEYOND_M = 0.5;
/** A lowered wall keeps this share of its height: a kerb that still shows where the wall is. */
export const CUTAWAY_SCALE = 0.12;

/** The identity of a wall run, shared by the layout's segments and the tagged scene objects. */
export function wallKey(wall: Pick<WallSegment, "x1" | "z1" | "x2" | "z2">): string {
  return `${wall.x1.toFixed(2)}:${wall.z1.toFixed(2)}:${wall.x2.toFixed(2)}:${wall.z2.toFixed(2)}`;
}

/** The walled room the person stands in, or null (open rooms and the open office have nothing to open). */
export function walledRoomAt(rooms: readonly Room[], p: Point): Room | null {
  return rooms.find((r) => r.walled && p.x > r.minX && p.x < r.maxX && p.z > r.minZ && p.z < r.maxZ) ?? null;
}

/**
 * Keys of the wall runs to lower for a person at `person` seen by a camera
 * standing over `camera` (its position on the floor plane). Walls of the
 * neighbouring room that run along the same line are opened with it, or half
 * the side would stay up.
 */
export function cutawayWalls(rooms: readonly Room[], walls: readonly WallSegment[], person: Point, camera: Point): Set<string> {
  const cut = new Set<string>();
  const room = walledRoomAt(rooms, person);
  if (!room) return cut;
  const open = {
    north: camera.z < room.minZ - BEYOND_M, south: camera.z > room.maxZ + BEYOND_M,
    west: camera.x < room.minX - BEYOND_M, east: camera.x > room.maxX + BEYOND_M,
  };
  for (const wall of walls) {
    const horizontal = Math.abs(wall.z1 - wall.z2) < 1e-6;
    if (horizontal) {
      const overlaps = Math.min(Math.max(wall.x1, wall.x2), room.maxX) - Math.max(Math.min(wall.x1, wall.x2), room.minX) > 0.05;
      if (!overlaps) continue;
      if ((open.north && Math.abs(wall.z1 - room.minZ) < ON_SIDE_M) || (open.south && Math.abs(wall.z1 - room.maxZ) < ON_SIDE_M)) cut.add(wallKey(wall));
    } else {
      const overlaps = Math.min(Math.max(wall.z1, wall.z2), room.maxZ) - Math.max(Math.min(wall.z1, wall.z2), room.minZ) > 0.05;
      if (!overlaps) continue;
      if ((open.west && Math.abs(wall.x1 - room.minX) < ON_SIDE_M) || (open.east && Math.abs(wall.x1 - room.maxX) < ON_SIDE_M)) cut.add(wallKey(wall));
    }
  }
  return cut;
}

/** One frame of a wall's height towards its goal (1 = standing, CUTAWAY_SCALE = lowered); `snap` skips the glide. */
export function cutawayStep(current: number, lowered: boolean, dt: number, snap = false): number {
  const goal = lowered ? CUTAWAY_SCALE : 1;
  if (snap || Math.abs(goal - current) < 0.004) return goal;
  return goal + (current - goal) * Math.exp(-9 * dt);
}
