/**
 * The Level Hall's own floor, on top of the building: a small foyer with the
 * elevator, and behind its door the hall of honour.
 *
 *   ┌──────── Level Hall ────────┐
 *   │  rank wall · studio dais   │   north
 *   │  display cases either side │
 *   │  of the runner             │
 *   │  service guide             │
 *   ├────────── door ────────────┤
 *   │ elevator      foyer        │   south
 *   └────────────────────────────┘
 *
 * The hall's fittings, north to south: the rank wall on the north wall with
 * the studio's round dais in front of it (its checkpoint is the dais itself),
 * the runner down the middle with a display case per reward on either side —
 * the lowest unlock at the south end, the highest by the dais, so walking up
 * the runner is climbing the ranks — and at the runner's start the
 * double-sided service guide with its checkpoint on the runner side. Plants
 * frame the dais, olive trees the guide.
 *
 * Takes no input: the hall is the same for everyone; what it shows comes from
 * the level state at render time.
 */
import { REWARD_IDS } from "../progression/levelCatalog";
import {
  FLOOR_EDGE, footprint, FURNITURE_SIZE, RAIL_CLEARANCE, wallRect, wallsOf,
  type Checkpoint, type Furniture, type FurnitureKind, type OfficeLayout, type Rect, type Room, type Spot,
} from "./officeLayout";

/** The hall's width and depth, the foyer's depth, where the dais stands, and how far the runner stays from each end of the hall. */
export const LEVEL_HALL = { width: 9.2, depth: 34, foyer: 6.4, door: 2.4, stageZ: 4.5, stageR: 1.6, roadNorth: 8.2, roadSouth: 6.4, guideZ: 3.3 } as const;
/** The display cases stand this far either side of the hall's centre line, the runner between them. */
export const PEDESTAL_OFFSET_X = 1.8;

/** Build the Level Hall's floor. */
export function buildHallLayout(): OfficeLayout {
  const minX = -LEVEL_HALL.width / 2, maxX = LEVEL_HALL.width / 2;
  const total = LEVEL_HALL.depth + LEVEL_HALL.foyer;
  const topZ = -total / 2, bottomZ = total / 2;
  const hall: Room = { id: "levels", kind: "levels", walled: true, minX, maxX, minZ: topZ, maxZ: topZ + LEVEL_HALL.depth,
    doors: [{ side: "south", at: 0, width: LEVEL_HALL.door }] };
  const cx = 0;
  const piece = (id: string, kind: FurnitureKind, x: number, z: number, rotationY = 0, size?: { w: number; d: number }): Furniture =>
    ({ id, kind, x, z, rotationY, room: "levels", ...(size ? { size } : {}) });
  const stageZ = hall.minZ + LEVEL_HALL.stageZ;
  const roadMinZ = hall.minZ + LEVEL_HALL.roadNorth, roadMaxZ = hall.maxZ - LEVEL_HALL.roadSouth;
  const guideZ = hall.maxZ - LEVEL_HALL.guideZ;
  // Case n (0 = the lowest unlock) stands on the west side when n is even, the east side when odd, rising northwards.
  const rows = Math.ceil(REWARD_IDS.length / 2);
  const pitch = rows > 1 ? (roadMaxZ - roadMinZ - 1.2) / (rows - 1) : 0;
  const pedestals = REWARD_IDS.map((_, n) => piece(`level-pedestal-${n}`, "rewardPedestal",
    cx + (n % 2 === 0 ? -PEDESTAL_OFFSET_X : PEDESTAL_OFFSET_X), roadMaxZ - 0.6 - Math.floor(n / 2) * pitch, n % 2 === 0 ? Math.PI / 2 : -Math.PI / 2));
  // The foyer: the elevator on the west edge like on every floor (doors facing east), its mat, an olive tree in each south corner.
  const elevator: Furniture = { id: "elevator", kind: "elevator", x: minX + 0.25, z: bottomZ - 2.6, rotationY: Math.PI / 2, room: "floor" };
  const furniture: Furniture[] = [
    piece("level-wall", "levelWall", cx, hall.minZ + 0.08 + FURNITURE_SIZE.levelWall.d / 2),
    piece("level-stage", "studioStage", cx, stageZ),
    piece("level-road", "levelRoad", cx, (roadMinZ + roadMaxZ) / 2, 0, { w: 2.2, d: roadMaxZ - roadMinZ }),
    ...pedestals,
    // The guide faces up the runner; its back shows the same screen to whoever comes in through the door.
    piece("level-guide", "levelGuide", cx, guideZ, Math.PI),
    piece("level-plant-nw", "designerPlant", hall.minX + 0.6, hall.minZ + 0.7),
    piece("level-plant-ne", "designerPlant", hall.maxX - 0.6, hall.minZ + 0.7),
    piece("level-olive-sw", "oliveTree", hall.minX + 0.85, hall.maxZ - 0.85),
    piece("level-olive-se", "oliveTree", hall.maxX - 0.85, hall.maxZ - 0.85),
    elevator,
    { id: "foyer-mat", kind: "entranceMat", x: minX + 1.3, z: elevator.z, rotationY: 0, room: "floor", size: { w: 1.1, d: 1.9 } },
    { id: "foyer-olive", kind: "oliveTree", x: maxX - 0.8, z: bottomZ - 0.8, rotationY: 0, room: "floor" },
  ];
  const spots: Spot[] = [];
  const elevatorStop: Checkpoint = { id: "elevator", room: "floor", x: elevator.x + 0.95, z: elevator.z, radius: 1.0 };
  const checkpoints: Checkpoint[] = [
    { id: "studio", room: "levels", x: cx, z: stageZ, radius: LEVEL_HALL.stageR, approach: { x: cx, z: stageZ + 0.6 } },
    { id: "levels", room: "levels", x: cx, z: guideZ - 1.45, radius: 1.1 },
    elevatorStop,
  ];
  const walls = wallsOf(hall);
  const obstacles: Rect[] = [
    ...walls.map(wallRect),
    ...furniture.filter((f) => FURNITURE_SIZE[f.kind].solid).map(footprint),
  ];
  const start = { x: elevator.x + 1.15, z: elevator.z };
  return {
    variant: "hall",
    departments: [],
    // Nobody leads up here; the rect is the foyer so it stays a real place on the floor.
    lead: { minX, maxX, minZ: hall.maxZ, maxZ: bottomZ, desks: [] },
    rooms: [hall],
    walls,
    furniture,
    spots,
    checkpoints,
    obstacles,
    spawn: start,
    arrival: start,
    floor: {
      minX: minX - FLOOR_EDGE + RAIL_CLEARANCE, maxX: maxX + FLOOR_EDGE - RAIL_CLEARANCE,
      minZ: topZ - FLOOR_EDGE + RAIL_CLEARANCE, maxZ: bottomZ + FLOOR_EDGE - RAIL_CLEARANCE,
    },
    bounds: { minX: minX - FLOOR_EDGE, maxX: maxX + FLOOR_EDGE, minZ: topZ - FLOOR_EDGE, maxZ: bottomZ + FLOOR_EDGE },
  };
}
