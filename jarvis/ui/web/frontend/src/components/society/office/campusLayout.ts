/**
 * The agents floor as a team campus.
 *
 *   ┌ booths ┬── Lead office ──┬──── Team room ────┬─ Wardrobe ─┬─── library ───┐
 *   │                          north street                                     │
 *   │ studio ┃ studio ║           ║ studio ┃ studio                             │
 *   │        ┃        ║ boulevard ║        ┃            a street of team rooms  │
 *   │═══════ main boulevard · ATRIUM: spawn point, step seating ═══════════════│
 *   │      café       │   Reception + lobby (elevator)   │ │    Break room      │
 *   └─────────────────┴──────────────────────────────────┴─┴────────────────────┘
 *
 * Every team (a society chat group) has a studio: a room of its own with a
 * name wall and the studio board at its back, low screens on both sides, a
 * planted front with the entrance, the desks sized to the team, a huddle zone
 * in front of the board, a sofa, a standing table and a storage cabinet.
 * Agents without a team share the pool studio. Studios stand shoulder to
 * shoulder in rows of four, two either side of the boulevard that runs from
 * the lobby to the team room, and open onto the street in front of them. The
 * main boulevard crosses at the atrium: the spawn point between two flights
 * of step seating. Every route between the lobby, the rooms and the studios
 * crosses that plaza.
 *
 * What is not a studio or a room is a commons people use: the café beside the
 * lobby, the library and the focus booths in the north corners, and in a cell
 * without a studio the free plot (the next team's place) or a garden court.
 *
 * The plan is four cells wide at every size; it grows southwards by a row of
 * studios whenever a row is full. Pure and deterministic: the same roster and
 * the same teams always give the same plan and the same seats.
 */
import {
  ambienceObstacles, bench, benchSeats, booth, boothPlace, cabinet, counter, counterStands, crate, highTable, island, olive, planter,
  screen, sofa, sofaSeats, steps, stepsSeats, tableStands, tree, BENCH_DEPTH, PLANTER_DEPTH, SOFA,
  type AgentsAmbienceItem, type AmbiencePlace,
} from "./agentsAmbience";
import {
  ARCH, archPosts, BENCH_DEPTH_Z, benchPlanters, byArrival, chairRect, DESK_HALF_GAP, DESK_PITCH_X, deskRect,
  executiveChairRect, EXECUTIVE_DESK_SIZE, FLOOR_EDGE, footprint, FURNITURE_SIZE, PARTNER_DESK_SIZE, RAIL_CLEARANCE,
  seatOf, SPAWN, STUDIO_BOARD_FACE, wallRect, wallsOf,
  type CampusZone, type Checkpoint, type Department, type DeskSlot, type Furniture, type FurnitureKind,
  type OfficeAgentInput, type OfficeLayout, type OfficeTeamInput, type Point, type Rect, type Room, type RoomKind,
  type Spot, type SpotKind, type SpotPose, type Studio, type WallSegment,
} from "./officeLayout";

/**
 * The campus grid, in metres. A cell holds one studio; two cells stand
 * shoulder to shoulder on each side of the boulevard. A street separates two
 * rows, and the plaza is the main boulevard with the atrium at its heart.
 */
export const CAMPUS = {
  cellW: 11, boulevard: 5, street: 3.6, plaza: 9, atrium: 16,
  /** The walk along both windows, between the benches at the glass and the outer studios. */
  promenade: 1.4,
  northDepth: 9.4, southDepth: 10.4,
  /** A studio, north to south: the huddle zone between its name wall and the first desks, then the desks, then the front zone with the sofa and the entrance. */
  studioHeader: 4, studioFront: 3.2,
  /** The opening in a studio's planted front. */
  studioDoor: 4.8,
  cellsPerRow: 4,
} as const;

/** Desks come in facing pairs; a bench holds up to four pairs, a studio up to four benches. */
const PAIRS_PER_BENCH = 4;
const MAX_BENCHES = 4;
/** The most agents one studio seats; a larger team's newest members sit in the pool. */
export const STUDIO_SEAT_CAP = MAX_BENCHES * PAIRS_PER_BENCH * 2;
/** The most studios the campus builds (three rows); later teams fold into the pool. */
export const MAX_STUDIOS = 12;
/** A cell's column for each slot of a row: the two cells beside the boulevard fill first, west before east. */
const SLOT_COLUMNS = [1, 2, 0, 3] as const;
/** How far the walkable floor's west edge (the navigation grid's origin) is moved off the plan's 0.05 m raster. */
const GRID_NUDGE = 0.025;
/** Zone colour of the pool studio (neutral linen), and the cycle the team studios take theirs from. */
const POOL_TINT = 2;
const TEAM_TINTS = [0, 1, 3, 4, 5, 6, 7, 8, 9, 10, 11] as const;

/** Who sits in one studio, before it has a place on the floor. */
export interface StudioPlan {
  id: string;
  /** The team whose studio this is; null for the pool. */
  teamId: string | null;
  /** The team's name; "" for the pool (the renderer names it). */
  name: string;
  leadId: string | null;
  /** Seated members in seating order (arrival). */
  members: OfficeAgentInput[];
}

function slug(id: string): string {
  return id.replace(/[^A-Za-z0-9_-]/g, "_");
}

/**
 * Sort the roster into studios. The first two lead-tier agents keep the lead
 * office. Teams are taken oldest first (then by id): an agent in several teams
 * sits in the oldest one. A team keeps its studio even when none of its
 * members can sit there (unknown ids, or everyone already seated elsewhere).
 * Whoever has no team, or no room left in theirs, sits in the pool, which
 * comes first and opens further pool studios only when it outgrows one.
 */
export function planStudios(agents: readonly OfficeAgentInput[], teams: readonly OfficeTeamInput[]): StudioPlan[] {
  const leads = agents.filter((a) => a.tier === "lead").sort(byArrival).slice(0, 2);
  const inOffice = new Set(leads.map((a) => a.agentId));
  const staff = agents.filter((a) => !inOffice.has(a.agentId)).sort(byArrival);
  const byId = new Map(staff.map((a) => [a.agentId, a]));
  const seen = new Set<string>();
  const ordered = [...teams]
    .sort((a, b) => a.createdMs - b.createdMs || a.id.localeCompare(b.id))
    .filter((team) => (seen.has(team.id) ? false : (seen.add(team.id), true)))
    .slice(0, MAX_STUDIOS - 1);

  const claimed = new Set<string>();
  const ids = new Set<string>(["studio-pool"]);
  const teamPlans: StudioPlan[] = ordered.map((team) => {
    const mine: OfficeAgentInput[] = [];
    for (const memberId of new Set(team.members)) {
      const agent = byId.get(memberId);
      if (!agent || claimed.has(memberId)) continue;
      mine.push(agent);
    }
    const seated = mine.sort(byArrival).slice(0, STUDIO_SEAT_CAP);
    for (const agent of seated) claimed.add(agent.agentId);
    let id = `studio-${slug(team.id)}`;
    for (let n = 2; ids.has(id); n += 1) id = `studio-${slug(team.id)}-${n}`;
    ids.add(id);
    return { id, teamId: team.id, name: team.name.trim(), leadId: team.leadId ?? null, members: seated };
  });

  const pool = staff.filter((a) => !claimed.has(a.agentId));
  const poolStudios = Math.min(MAX_STUDIOS - teamPlans.length, Math.max(1, Math.ceil(pool.length / STUDIO_SEAT_CAP)));
  const pools: StudioPlan[] = Array.from({ length: poolStudios }, (_, n) => ({
    id: n === 0 ? "studio-pool" : `studio-pool-${n + 1}`, teamId: null, name: "", leadId: null,
    members: pool.slice(n * STUDIO_SEAT_CAP, (n + 1) * STUDIO_SEAT_CAP),
  }));
  return [pools[0], ...teamPlans, ...pools.slice(1)];
}

/** A studio's desk cluster and depth for a head count. */
export interface StudioShape {
  /** Facing desk pairs per bench, north bench first. */
  benches: number[];
  seats: number;
  /** North to south: huddle zone, benches, front zone. A studio is always one cell wide. */
  depth: number;
}

/**
 * The desk cluster a studio of `members` gets: one free desk to grow into,
 * rounded up to whole pairs, spread evenly over as few benches as hold them.
 * At least two pairs, so even a new team's studio is a place to work.
 */
export function studioShape(members: number): StudioShape {
  const want = Math.min(STUDIO_SEAT_CAP, Math.max(0, members) + 1);
  const pairs = Math.max(2, Math.ceil(want / 2));
  const count = Math.ceil(pairs / PAIRS_PER_BENCH);
  const benches = Array.from({ length: count }, (_, i) => Math.floor(pairs / count) + (i < pairs % count ? 1 : 0));
  return { benches, seats: pairs * 2, depth: CAMPUS.studioHeader + count * BENCH_DEPTH_Z + CAMPUS.studioFront };
}

/** The x-range of each of the four cells, west to east: two shoulder to shoulder on each side of the boulevard. */
function cellRanges(): [number, number][] {
  const half = CAMPUS.boulevard / 2, w = CAMPUS.cellW;
  return [[-half - 2 * w, -half - w], [-half - w, -half], [half, half + w], [half + w, half + 2 * w]];
}

/** Desk slots of a studio: bench by bench, each pair facing across the bench, filled in arrival order. */
function studioDesks(id: string, cx: number, minZ: number, shape: StudioShape, members: readonly OfficeAgentInput[]): DeskSlot[] {
  const desks: DeskSlot[] = [];
  let seat = 0;
  shape.benches.forEach((pairs, benchIndex) => {
    const centreZ = minZ + CAMPUS.studioHeader + benchIndex * BENCH_DEPTH_Z + BENCH_DEPTH_Z / 2;
    const west = cx - (pairs * DESK_PITCH_X) / 2;
    for (let col = 0; col < pairs; col += 1) {
      for (const facing of ["north", "south"] as const) {
        // A north-facing agent sits on the south side of the pair, looking at its monitor.
        const z = facing === "north" ? centreZ + DESK_HALF_GAP : centreZ - DESK_HALF_GAP;
        desks.push({ id: `${id}:${benchIndex}:${facing}:${col}`, x: west + DESK_PITCH_X * (col + 0.5), z, facing, agentId: members[seat]?.agentId ?? null });
        seat += 1;
      }
    }
  });
  return desks;
}

/** A studio's name wall along its north edge: solid, and what the studio board hangs in front of. */
export function studioWallRect(dept: Rect): Rect {
  return { minX: dept.minX + 0.2, maxX: dept.maxX - 0.2, minZ: dept.minZ + 0.02, maxZ: dept.minZ + 0.2 };
}

/** Where a studio's name is lettered on its wall and where its board hangs: the west and the east half. */
export function studioWallParts(dept: Rect): { nameX: number; boardX: number; span: number } {
  const span = dept.maxX - dept.minX - 0.4;
  const cx = (dept.minX + dept.maxX) / 2;
  return { nameX: cx - span / 4, boardX: cx + span / 4, span };
}

/** Standing places in front of a studio board: a front row of four and a back row of three. */
const HUDDLE_OFFSETS: readonly (readonly [number, number])[] = [
  [-0.4, 1.45], [0.4, 1.45], [-1.2, 1.45], [1.2, 1.45], [0, 2.3], [-0.8, 2.3], [0.8, 2.3],
];

/** Wall runs of all rooms, each run once: two rooms sharing a wall line would otherwise both draw (and both block) it. */
function uniqueWalls(rooms: readonly Room[]): WallSegment[] {
  const seen = new Set<string>();
  return rooms.flatMap(wallsOf).filter((wall) => {
    const key = [`${wall.x1.toFixed(3)},${wall.z1.toFixed(3)}`, `${wall.x2.toFixed(3)},${wall.z2.toFixed(3)}`].sort().join("|");
    return seen.has(key) ? false : (seen.add(key), true);
  });
}

/** Build the agents floor for a roster and its teams. */
export function buildCampusLayout(agents: readonly OfficeAgentInput[], teams: readonly OfficeTeamInput[]): OfficeLayout {
  const plans = planStudios(agents, teams);
  const shapes = plans.map((plan) => studioShape(plan.members.length));
  const cells = cellRanges();
  const planMinX = cells[0][0] - CAMPUS.promenade, planMaxX = cells[3][1] + CAMPUS.promenade;
  const perRow = CAMPUS.cellsPerRow;
  const rowCount = Math.max(1, Math.ceil(plans.length / perRow));
  const minRowDepth = studioShape(0).depth;
  // The studios of a row share its depth, so their fronts line up along the street.
  const rowDepth = Array.from({ length: rowCount }, (_, r) =>
    Math.max(minRowDepth, ...shapes.slice(r * perRow, (r + 1) * perRow).map((s) => s.depth)));

  // Depth: north strip, a street, the rows with a street after each — except one gap, which is the plaza.
  const depth = CAMPUS.northDepth + CAMPUS.street + rowDepth.reduce((sum, d) => sum + d, 0)
    + (rowCount - 1) * CAMPUS.street + CAMPUS.plaza + CAMPUS.southDepth;
  const topZ = -depth / 2, bottomZ = depth / 2;
  const northMaxZ = topZ + CAMPUS.northDepth, southMinZ = bottomZ - CAMPUS.southDepth;
  /** Row starts and the plaza's centre line when the plaza follows row `after` (0-based). */
  const place = (after: number) => {
    const starts: number[] = [];
    let z = northMaxZ + CAMPUS.street, plazaZ = 0;
    for (let r = 0; r < rowCount; r += 1) {
      starts.push(z);
      z += rowDepth[r];
      if (r === after) plazaZ = z + CAMPUS.plaza / 2;
      z += r === after ? CAMPUS.plaza : CAMPUS.street;
    }
    return { starts, plazaZ };
  };
  // The plaza takes the gap nearest the floor's middle (the earlier one on a tie): with one row, the one in front of the lobby.
  let plazaAfter = 0;
  for (let r = 1; r < rowCount; r += 1) if (Math.abs(place(r).plazaZ) < Math.abs(place(plazaAfter).plazaZ) - 1e-9) plazaAfter = r;
  const { starts: rowZ, plazaZ } = place(plazaAfter);
  const half = CAMPUS.boulevard / 2;
  const plaza: Point = { x: 0, z: plazaZ };
  const plazaRect: Rect = { minX: planMinX, maxX: planMaxX, minZ: plazaZ - CAMPUS.plaza / 2, maxZ: plazaZ + CAMPUS.plaza / 2 };

  // ------------------------------------------------------------------ rooms
  const lead: Room = { id: "lead", kind: "lead", walled: true, minX: -17.2, maxX: -6.2, minZ: topZ, maxZ: northMaxZ,
    doors: [{ side: "south", at: -11.7, width: 1.8 }] };
  // The team room closes the boulevard: its door stands on the axis.
  const team: Room = { id: "team", kind: "team", walled: true, minX: -6.2, maxX: 6.2, minZ: topZ, maxZ: northMaxZ,
    doors: [{ side: "south", at: 0, width: 2.4 }] };
  const wardrobe: Room = { id: "wardrobe", kind: "wardrobe", walled: true, minX: 6.2, maxX: 14, minZ: topZ, maxZ: northMaxZ,
    doors: [{ side: "south", at: 10.1, width: 1.6 }] };
  // The lobby straddles the boulevard; the elevator, the brand wall and the award case stand along its west edge.
  // Its name arch stands against the back of the reception desk and carries the name over it, instead of standing
  // at the lobby's edge on the atrium.
  const reception: Room = { id: "reception", kind: "reception", walled: false, minX: -10.6, maxX: 10.6, minZ: southMinZ, maxZ: bottomZ, doors: [],
    arch: { x: -6, z: southMinZ + 1.95 } };
  const breakRoom: Room = { id: "break", kind: "break", walled: true, minX: 13.1, maxX: planMaxX, minZ: southMinZ, maxZ: bottomZ,
    doors: [{ side: "north", at: (13.1 + planMaxX) / 2, width: 2.4 }, { side: "west", at: southMinZ + CAMPUS.southDepth / 2, width: 2 }] };
  const rooms = [lead, team, wardrobe, reception, breakRoom];

  const departments: Department[] = [];
  const studios: Studio[] = [];
  const furniture: Furniture[] = [];
  const spots: Spot[] = [];
  const ambience: AgentsAmbienceItem[] = [];
  const zones: CampusZone[] = [
    { id: "boulevard", kind: "boulevard", minX: -half, maxX: half, minZ: northMaxZ, maxZ: southMinZ },
    { id: "plaza", kind: "plaza", ...plazaRect },
    { id: "atrium", kind: "atrium", minX: -CAMPUS.atrium / 2, maxX: CAMPUS.atrium / 2, minZ: plazaRect.minZ, maxZ: plazaRect.maxZ },
  ];
  const piece = (id: string, kind: FurnitureKind, room: RoomKind | "floor", x: number, z: number, rotationY = 0, size?: { w: number; d: number }): Furniture =>
    ({ id, kind, x, z, rotationY, room, ...(size ? { size } : {}) });
  /** Places at a commons piece or in a studio become spots on the open floor. */
  const use = (prefix: string, kind: SpotKind, pose: SpotPose, places: readonly AmbiencePlace[]) => {
    places.forEach((p, n) => spots.push({ id: `${prefix}-${n}`, kind, pose, x: p.x, z: p.z, facing: p.facing, room: "floor" }));
  };
  const add = <T extends AgentsAmbienceItem>(item: T): T => { ambience.push(item); return item; };

  // --------------------------------------------------------------- studios
  let teamIndex = 0;
  let plotPlaced = false;
  for (let r = 0; r < rowCount; r += 1) {
    const z0 = rowZ[r], z1 = rowZ[r] + rowDepth[r];
    /** The studio plan standing in column c of this row, if any. */
    const planAt = (column: number) => plans[r * perRow + SLOT_COLUMNS.indexOf(column as 0 | 1 | 2 | 3)];
    for (let slot = 0; slot < perRow; slot += 1) {
      const column = SLOT_COLUMNS[slot];
      const [x0, x1] = cells[column];
      const cx = (x0 + x1) / 2, cz = (z0 + z1) / 2;
      const index = r * perRow + slot;
      const plan = plans[index];
      if (!plan) {
        // A cell without a studio: the first one is the free plot where the next team will stand, the others are garden courts.
        if (!plotPlaced) {
          plotPlaced = true;
          zones.push({ id: "plot", kind: "plot", minX: x0 + 0.6, maxX: x1 - 0.6, minZ: z0 + 0.6, maxZ: z1 - 0.6 });
          // A place a team could move into tomorrow: the stand where one is started, facing the street, a stack of
          // moving crates and a plant already waiting at the back.
          furniture.push(piece("team-stand", "teamStand", "floor", cx, z1 - 2.6));
          furniture.push(piece("plot-plant", "plant", "floor", x1 - 1.7, z0 + 1.6));
          add(crate("plot-crates", x0 + 1.9, z0 + 1.7, "south"));
          continue;
        }
        const id = `garden-${r}-${slot}`;
        zones.push({ id, kind: "garden", minX: x0, maxX: x1, minZ: z0, maxZ: z1 });
        // A lawn with one large tree and two olives off to its sides, a bed of grasses along the back and two
        // benches facing each other in the middle; mirrored on the east half of the floor.
        const m = column >= 2 ? -1 : 1;
        add(tree(`${id}-tree`, cx - m * 3.1, z0 + 2.7));
        add(olive(`${id}-olive-a`, cx + m * 3.4, z0 + 2.1));
        add(olive(`${id}-olive-b`, cx + m * 2.9, z1 - 2.3));
        add(planter(`${id}-bed`, { minX: cx - 1.6, maxX: cx + 1.9, minZ: z0 + 0.8, maxZ: z0 + 0.8 + PLANTER_DEPTH }));
        use(`${id}-bench-w`, "couch", "sit", benchSeats(add(bench(`${id}-bench-w`, cx - 0.95, cz - 0.4, cz + 2.0, "east"))));
        use(`${id}-bench-e`, "couch", "sit", benchSeats(add(bench(`${id}-bench-e`, cx + 0.95, cz - 0.4, cz + 2.0, "west"))));
        spots.push({ id: `${id}-stand`, kind: "window", pose: "stand", room: "floor", x: cx - m * 1.5, z: z0 + 3.2, facing: m > 0 ? -Math.PI / 2 : Math.PI / 2 });
        continue;
      }
      const shape = shapes[index];
      const tint = plan.teamId === null ? POOL_TINT : TEAM_TINTS[teamIndex % TEAM_TINTS.length];
      if (plan.teamId !== null) teamIndex += 1;
      const dept: Department = {
        id: plan.id, label: plan.name, teamId: plan.teamId, tint,
        minX: x0, maxX: x1, minZ: z0, maxZ: z1,
        desks: studioDesks(plan.id, cx, z0, shape, plan.members),
      };
      departments.push(dept);

      // The studio board hangs in front of the east half of the name wall; the team gathers south of it.
      const { boardX } = studioWallParts(dept);
      const boardId = `studio-board:${dept.id}`;
      const boardZ = z0 + 0.23 + FURNITURE_SIZE.studioBoard.d / 2;
      furniture.push(piece(boardId, "studioBoard", "floor", boardX, boardZ));
      const face: Point = { x: boardX, z: boardZ + STUDIO_BOARD_FACE.z };
      const huddle: Spot[] = HUDDLE_OFFSETS.slice(0, Math.min(HUDDLE_OFFSETS.length, Math.max(4, plan.members.length + 1))).map(([dx, dz], n) => ({
        id: `huddle:${dept.id}:${n}`, kind: "huddle", pose: "stand", room: "floor",
        x: face.x + dx, z: face.z + dz, facing: Math.atan2(-dx, -dz),
      }));
      spots.push(...huddle);
      studios.push({
        deptId: dept.id, teamId: plan.teamId, name: plan.name, members: plan.members.map((a) => a.agentId), leadId: plan.leadId,
        board: { id: boardId, x: face.x, z: face.z, facing: 0 }, huddleSpotIds: huddle.map((s) => s.id),
        centre: { x: cx, z: cz },
      });

      // Low screens close both sides. Two studios shoulder to shoulder share the one between them (the west
      // studio builds it, in neutral oak); a side on the boulevard, the window or an empty cell has the studio's own.
      const sideZ = [z0 + 0.22, z1 - 0.2] as const;
      const westShared = (column === 1 || column === 3) && !!planAt(column - 1);
      const eastShared = (column === 0 || column === 2) && !!planAt(column + 1);
      if (!westShared) add(screen(`${dept.id}-screen-w`, x0 + 0.06, sideZ[0], x0 + 0.06, sideZ[1], tint));
      if (eastShared) add(screen(`${dept.id}-screen-e`, x1, sideZ[0], x1, sideZ[1]));
      else add(screen(`${dept.id}-screen-e`, x1 - 0.06, sideZ[0], x1 - 0.06, sideZ[1], tint));
      // The front is planted, with the entrance in its middle.
      const frontZ = { minZ: z1 - 0.2 - PLANTER_DEPTH, maxZ: z1 - 0.2 };
      const wing = (CAMPUS.cellW - CAMPUS.studioDoor) / 2;
      add(planter(`${dept.id}-front-w`, { minX: x0 + 0.3, maxX: x0 + wing, ...frontZ }));
      add(planter(`${dept.id}-front-e`, { minX: x1 - wing, maxX: x1 - 0.3, ...frontZ }));
      // Inside: storage in the corner under the name, a sofa along the west screen by the entrance and a standing table opposite.
      add(cabinet(`${dept.id}-cabinet`, x0 + 0.42, z0 + 1.45, "east", tint));
      use(`${dept.id}-sofa`, "couch", "sit", sofaSeats(add(sofa(`${dept.id}-sofa`, x0 + 0.24 + SOFA.d / 2, z1 - 2.1, "east", tint))));
      use(`${dept.id}-table`, "coffee", "stand", tableStands(add(highTable(`${dept.id}-table`, x1 - 1.6, z1 - 2.1)), [-Math.PI / 2, Math.PI]));
    }
  }

  // ------------------------------------------------------ streets and plaza
  // An olive tree closes every street at both windows.
  const streetZ = [northMaxZ + CAMPUS.street / 2, ...rowZ.map((z, r) => (r === plazaAfter ? plazaZ : z + rowDepth[r] + CAMPUS.street / 2))];
  streetZ.forEach((z, i) => {
    add(olive(`olive-west-${i}`, planMinX - 0.8, z));
    add(olive(`olive-east-${i}`, planMaxX + 0.8, z));
  });
  rowZ.forEach((z, r) => {
    const z1 = z + rowDepth[r], zc = (z + z1) / 2;
    // Along both windows: a bench on one side of the window spot and a planter on the other (swapped between west and east).
    ([[z + 0.4, zc - 0.85], [zc + 0.85, z1 - 0.4]] as const).forEach(([a, b], run) => {
      const out = 0.95;
      if (run === 0) {
        add(bench(`bench-west-${r}`, planMinX - out - BENCH_DEPTH / 2, a, b, "east"));
        add(planter(`planter-east-${r}`, { minX: planMaxX + out, maxX: planMaxX + out + PLANTER_DEPTH, minZ: a, maxZ: b }));
      } else {
        add(planter(`planter-west-${r}`, { minX: planMinX - out - PLANTER_DEPTH, maxX: planMinX - out, minZ: a, maxZ: b }));
        add(bench(`bench-east-${r}`, planMaxX + out + BENCH_DEPTH / 2, a, b, "west"));
      }
    });
    spots.push({ id: `window-west-${r}`, kind: "window", pose: "stand", room: "floor", x: planMinX - FLOOR_EDGE + 0.9, z: zc, facing: -Math.PI / 2 });
    spots.push({ id: `window-east-${r}`, kind: "window", pose: "stand", room: "floor", x: planMaxX + FLOOR_EDGE - 0.9, z: zc, facing: Math.PI / 2 });
  });
  // The atrium, the campus's heart: the spawn point between two flights of step seating that face it, a large
  // tree behind each. Further out the main boulevard has a planted median with a standing table and an olive.
  for (const sx of [-1, 1] as const) {
    const name = sx < 0 ? "west" : "east";
    use(`atrium-steps-${name}`, "couch", "sit", stepsSeats(add(steps(`atrium-steps-${name}`, sx * 5.6, plazaZ, 5, sx < 0 ? "east" : "west"))));
    add(tree(`atrium-tree-${name}`, sx * 7.9, plazaZ));
    const [a, b] = [sx * 12.4, sx * 17.2].sort((p, q) => p - q);
    add(planter(`median-${name}`, { minX: a, maxX: b, minZ: plazaZ - PLANTER_DEPTH / 2, maxZ: plazaZ + PLANTER_DEPTH / 2 }));
    add(olive(`median-${name}-olive`, sx * 18.3, plazaZ));
    use(`median-${name}-table`, "coffee", "stand", tableStands(add(highTable(`median-${name}-table`, sx * 11.2, plazaZ)), [0, Math.PI]));
  }

  // -------------------------------------------------------------- the commons
  // North-west corner: the focus booths. Three booths under the window, a sofa on a rug and a standing table.
  const boothsZone: CampusZone = { id: "booths", kind: "booths", minX: planMinX, maxX: lead.minX, minZ: topZ, maxZ: northMaxZ };
  zones.push(boothsZone);
  [0, 1, 2].forEach((n) => {
    const item = add(booth(`booth-${n}`, planMinX + 1.0 + n * 1.65, topZ + 1.0, "south", [1, 3, 5][n]));
    spots.push({ id: `booth-${n}`, kind: "window", pose: "stand", room: "floor", ...boothPlace(item) });
  });
  furniture.push(piece("booths-rug", "rug", "floor", planMinX + 2.9, topZ + 5.9, 0, { w: 4.4, d: 3.4 }));
  use("booths-sofa", "couch", "sit", sofaSeats(add(sofa("booths-sofa", planMinX + 0.3 + SOFA.d / 2, topZ + 5.9, "east"))));
  use("booths-table", "coffee", "stand", tableStands(add(highTable("booths-table", planMinX + 4.4, topZ + 5.6)), [-Math.PI / 2, 0]));
  add(olive("booths-olive", lead.minX - 0.9, topZ + 1.2));

  // North-east corner: the library. Two bookcases under the window, reading chairs by the east window, a sofa and a
  // low table on a rug.
  const lx0 = wardrobe.maxX, lx1 = planMaxX;
  zones.push({ id: "library", kind: "library", minX: lx0, maxX: lx1, minZ: topZ, maxZ: northMaxZ });
  const nookSeat = (x: number, z: number): AmbiencePlace => ({ x: x - 0.14, z: z + 0.08, facing: -Math.PI / 2 });
  furniture.push(
    piece("library-shelf-w", "breakBookcase", "floor", lx0 + 2.3, topZ + 0.12 + FURNITURE_SIZE.breakBookcase.d / 2),
    piece("library-shelf-e", "breakBookcase", "floor", lx0 + 5.7, topZ + 0.12 + FURNITURE_SIZE.breakBookcase.d / 2),
    piece("library-rug", "rug", "floor", lx0 + 3.6, topZ + 4.7, 0, { w: 5.2, d: 3.6 }),
    piece("library-table", "lobbyTable", "floor", lx0 + 2.6, topZ + 4.7, Math.PI / 2),
    // The reading chairs turn their backs to the east window and face the room.
    piece("library-nook-n", "readingNook", "floor", lx1 - 0.75, topZ + 3.4, -Math.PI / 2),
    piece("library-nook-s", "readingNook", "floor", lx1 - 0.75, topZ + 6.0, -Math.PI / 2),
    piece("library-plant", "designerPlant", "floor", lx1 - 0.8, topZ + 0.9),
  );
  use("library-sofa", "couch", "sit", sofaSeats(add(sofa("library-sofa", lx0 + 0.3 + SOFA.d / 2, topZ + 4.7, "east"))));
  use("library-nook", "couch", "sit", [nookSeat(lx1 - 0.75, topZ + 3.4), nookSeat(lx1 - 0.75, topZ + 6.0)]);
  use("library-shelf", "shelf", "stand", [{ x: lx0 + 2.3, z: topZ + 1.25, facing: Math.PI }, { x: lx0 + 5.7, z: topZ + 1.25, facing: Math.PI }]);

  // South-west, beside the lobby: the café. The kitchen run under the west window with the island in front of it,
  // standing tables, two sofas along the south window, a large tree in two corners and grasses towards the plaza.
  const cx0 = planMinX, cx1 = reception.minX, cz0 = southMinZ;
  zones.push({ id: "cafe", kind: "cafe", minX: cx0, maxX: cx1, minZ: cz0, maxZ: bottomZ });
  use("cafe-counter", "coffee", "stand", counterStands(add(counter("cafe-counter", cx0 + 0.45, cz0 + 5.4, 4.6, "east")), [-1.1, 1.1]));
  use("cafe-island", "coffee", "stand", counterStands(add(island("cafe-island", cx0 + 2.7, cz0 + 5.4, "east")), [-0.7, 0.7]));
  ([[5.6, 2.7], [8.0, 5.2], [5.8, 7.6]] as const).forEach(([dx, dz], n) => {
    use(`cafe-table-${n}`, "coffee", "stand", tableStands(add(highTable(`cafe-table-${n}`, cx0 + dx, cz0 + dz)), [Math.PI / 2, -Math.PI / 2]));
  });
  use("cafe-sofa-w", "couch", "sit", sofaSeats(add(sofa("cafe-sofa-w", cx1 - 5.2, bottomZ - 0.25 - SOFA.d / 2, "north"))));
  use("cafe-sofa-e", "couch", "sit", sofaSeats(add(sofa("cafe-sofa-e", cx1 - 2.7, bottomZ - 0.25 - SOFA.d / 2, "north"))));
  add(tree("cafe-tree-n", cx1 - 1.4, cz0 + 1.3));
  add(tree("cafe-tree-s", cx0 + 1.0, bottomZ - 1.1));
  add(planter("cafe-bed", { minX: cx0 + 3.2, maxX: cx0 + 8.4, minZ: cz0 + 0.3, maxZ: cz0 + 0.3 + PLANTER_DEPTH }));

  // ------------------------------------------------------------- lead office
  const leadAgents = agents.filter((a) => a.tier === "lead").sort(byArrival).slice(0, 2);
  const ex0 = lead.minX, ex1 = lead.maxX, lcx = (ex0 + ex1) / 2, lz0 = topZ;
  const leadDeskZ = lz0 + 2.6;
  // The executive desk faces south, towards the door. A second lead gets a partner desk to its east; there is never an empty one.
  const leadDesks: DeskSlot[] = [
    { id: "lead:0", x: lcx, z: leadDeskZ, facing: "south", agentId: leadAgents[0]?.agentId ?? null, size: EXECUTIVE_DESK_SIZE },
    ...(leadAgents[1] ? [{ id: "lead:1", x: lcx + 2.65, z: leadDeskZ, facing: "south" as const, agentId: leadAgents[1].agentId, size: PARTNER_DESK_SIZE }] : []),
  ];
  furniture.push(
    // A panelled feature wall with lit bookcases and the star emblem, a rug under the executive desk, guest
    // armchairs, the bar and a leather lounge along the west wall, a globe and a lamp in the east, palms by the door.
    piece("lead-wall", "leadWall", "lead", lcx, lz0 + 0.1 + FURNITURE_SIZE.leadWall.d / 2),
    piece("lead-rug", "executiveRug", "lead", lcx, lz0 + 3.55, 0, { w: 4.6, d: 3.9 }),
    piece("lead-guest-w", "guestChair", "lead", lcx - 0.72, leadDeskZ + 1.2, Math.PI),
    piece("lead-guest-e", "guestChair", "lead", lcx + 0.72, leadDeskZ + 1.2, Math.PI),
    piece("lead-sofa", "chesterfield", "lead", ex0 + 0.6, lz0 + 4.55, Math.PI / 2),
    piece("lead-table", "loungeTable", "lead", ex0 + 1.62, lz0 + 4.55, Math.PI / 2),
    piece("lead-lamp", "floorLamp", "lead", ex0 + 0.4, lz0 + 3.1),
    piece("lead-bar", "executiveBar", "lead", ex0 + 0.36, lz0 + 1.85, Math.PI / 2),
    piece("lead-globe", "globe", "lead", ex1 - 0.75, lz0 + 4.3),
    piece("lead-lamp-e", "floorLamp", "lead", ex1 - 0.34, lz0 + 2.9),
    piece("lead-plant", "plant", "lead", ex0 + 0.55, northMaxZ - 0.55),
    piece("lead-plant-e", "plant", "lead", ex1 - 0.55, northMaxZ - 0.55),
    // The office dog's baskets: here beside the bookcase, in the team room and in the break room.
    piece("lead-dog", "dogBed", "lead", ex1 - 0.58, lz0 + 0.98),
  );
  spots.push({ id: "shelf-lead", kind: "shelf", pose: "stand", x: lcx + 2.65, z: topZ + 1.05, facing: Math.PI, room: "lead" });

  // --------------------------------------------------------------- team room
  const tableZ = topZ + 4.9;
  furniture.push(
    // A walnut table on a wool rug, the board on a slat wall, a credenza under the display and one along the
    // west wall, fiddle-leaf figs in both corners by the door.
    piece("team-rug", "teamRug", "team", 0, tableZ, 0, { w: 5.4, d: 4.0 }),
    piece("team-table", "meetingTable", "team", 0, tableZ),
    piece("team-wall", "teamWall", "team", 0, topZ + 0.06 + FURNITURE_SIZE.teamWall.d / 2),
    piece("team-board", "teamBoard", "team", 0, topZ + 0.25),
    piece("team-credenza", "credenza", "team", 2.7, topZ + 0.19 + FURNITURE_SIZE.credenza.d / 2),
    piece("team-credenza-w", "credenza", "team", team.minX + 0.07 + FURNITURE_SIZE.credenza.d / 2, tableZ, Math.PI / 2),
    piece("team-plant", "designerPlant", "team", team.maxX - 0.6, northMaxZ - 0.6),
    piece("team-plant-w", "designerPlant", "team", team.minX + 0.6, northMaxZ - 0.6, Math.PI / 2),
    piece("team-dog", "dogBed", "team", team.minX + 0.62, topZ + 0.95),
  );
  spots.push({ id: "board", kind: "board", pose: "stand", x: -0.6, z: topZ + 1.2, facing: Math.PI, room: "team" });
  // Meeting chairs: three per long side of the team table.
  for (let i = 0; i < 3; i += 1) {
    const x = -1.1 + i * 1.1;
    spots.push({ id: `meeting-n${i}`, kind: "meeting", pose: "sit", x, z: tableZ - 1.25, facing: 0, room: "team" });
    spots.push({ id: `meeting-s${i}`, kind: "meeting", pose: "sit", x, z: tableZ + 1.25, facing: Math.PI, room: "team" });
  }

  // ---------------------------------------------------------------- wardrobe
  const wx0 = wardrobe.minX, wx1 = wardrobe.maxX, wcx = (wx0 + wx1) / 2;
  const mirrorZ = topZ + 3.6;
  // Where the person stands to change: on the round rug in front of the mirror.
  const dressAt: Point = { x: wx0 + 2.0, z: mirrorZ };
  furniture.push(
    // An open oak wardrobe along the north wall, a bulb-lit mirror on the west wall with a round rug in front of
    // it, a tailor's dummy, a bench on the east side, a fig and a coat stand by the door.
    piece("wardrobe-wall", "wardrobeWall", "wardrobe", wcx, topZ + 0.06 + FURNITURE_SIZE.wardrobeWall.d / 2),
    piece("wardrobe-rug", "roundRug", "wardrobe", dressAt.x, dressAt.z, 0, { w: 2.8, d: 2.8 }),
    piece("wardrobe-mirror", "dressingMirror", "wardrobe", wx0 + 0.06 + FURNITURE_SIZE.dressingMirror.d / 2, mirrorZ, Math.PI / 2),
    piece("wardrobe-dummy", "tailorDummy", "wardrobe", wx1 - 0.6, topZ + 1.4, -Math.PI / 4),
    piece("wardrobe-bench", "dressingBench", "wardrobe", wx1 - 0.06 - FURNITURE_SIZE.dressingBench.d / 2, topZ + 3.9, -Math.PI / 2),
    piece("wardrobe-plant", "designerPlant", "wardrobe", wx0 + 0.5, northMaxZ - 0.5),
    piece("wardrobe-stand", "coatStand", "wardrobe", wx1 - 0.4, northMaxZ - 0.45),
  );
  spots.push({ id: "shelf-wardrobe", kind: "shelf", pose: "stand", x: wcx - 1.0, z: topZ + 1.3, facing: Math.PI, room: "wardrobe" });

  // ------------------------------------------------------------------- lobby
  const rx0 = reception.minX, rx1 = reception.maxX;
  const deskAt: Point = { x: reception.arch?.x ?? rx0 + 4.6, z: southMinZ + 2.5 };
  const loungeX = 5.4, loungeZ = southMinZ + 5.6;
  furniture.push(
    // West edge, north to south: the brand wall, the way into the café, the elevator with its mat and the award
    // case. The reception desk stands west of the boulevard's axis, the waiting lounge east of it.
    piece("elevator", "elevator", "reception", rx0 + 0.25, bottomZ - 2.6, Math.PI / 2),
    piece("reception-desk", "receptionDesk", "reception", deskAt.x, deskAt.z),
    piece("lobby-brand-wall", "brandWall", "reception", rx0 + 0.22, southMinZ + 2.55, Math.PI / 2),
    piece("lobby-awards", "awardCase", "reception", rx0 + 0.26, bottomZ - 0.7, Math.PI / 2),
    piece("lobby-mat", "entranceMat", "reception", rx0 + 1.3, bottomZ - 2.6, 0, { w: 1.1, d: 1.9 }),
    piece("lobby-olive-s", "oliveTree", "reception", rx0 + 2.9, bottomZ - 0.75),
    piece("lobby-olive-se", "oliveTree", "reception", rx1 - 0.75, bottomZ - 0.75),
    piece("lobby-rug", "lobbyRug", "reception", loungeX, loungeZ + 0.75, 0, { w: 4.8, d: 2.9 }),
    piece("lobby-sofa", "lobbySofa", "reception", loungeX, loungeZ),
    piece("lobby-table", "lobbyTable", "reception", loungeX, loungeZ + 1.05),
    piece("lobby-chair-w", "lobbyArmchair", "reception", loungeX - 1.8, loungeZ + 1.1, Math.PI / 2),
    piece("lobby-chair-e", "lobbyArmchair", "reception", loungeX + 1.8, loungeZ + 1.1, -Math.PI / 2),
    piece("lobby-side-table", "sideTable", "reception", loungeX - 1.5, loungeZ - 0.05),
    piece("lobby-lamp", "lobbyLamp", "reception", loungeX + 1.5, loungeZ - 0.1),
  );
  spots.push(
    // Two on the sofa (facing south), one in each armchair (facing the table).
    { id: "couch-lobby-1", kind: "couch", pose: "sit", x: loungeX - 0.55, z: loungeZ + 0.15, facing: 0, room: "reception" },
    { id: "couch-lobby-2", kind: "couch", pose: "sit", x: loungeX + 0.55, z: loungeZ + 0.15, facing: 0, room: "reception" },
    { id: "couch-lobby-w", kind: "couch", pose: "sit", x: loungeX - 1.78, z: loungeZ + 1.1, facing: Math.PI / 2, room: "reception" },
    { id: "couch-lobby-e", kind: "couch", pose: "sit", x: loungeX + 1.78, z: loungeZ + 1.1, facing: -Math.PI / 2, room: "reception" },
  );

  // -------------------------------------------------------------- break room
  const bx0 = breakRoom.minX, bx1 = breakRoom.maxX, bz0 = southMinZ;
  const barX = bx1 - 2.9;
  furniture.push(
    // An L-shaped sectional in the south-west round an oak coffee table on a kilim; the bookcase wall, the
    // reading nook and the dog's basket in the north-west; the coffee bar with the treat jar on the north wall;
    // foosball, beanbags, the water station and the arcade on its pixel mat in the east; monsteras in two corners.
    piece("break-rug", "breakRug", "break", bx0 + 3.4, bottomZ - 3.1, 0, { w: 5.2, d: 4.2 }),
    piece("break-sofa-a", "breakSofa", "break", bx0 + 3.3, bottomZ - 1.7, Math.PI),
    piece("break-sofa-b", "breakSofa", "break", bx0 + 1.75, bottomZ - 3.25, Math.PI / 2),
    piece("break-sofa-corner", "breakSofaCorner", "break", bx0 + 1.75, bottomZ - 1.7, Math.PI),
    piece("break-table", "breakTable", "break", bx0 + 3.35, bottomZ - 3.2),
    piece("coffee-bar", "coffeeBar", "break", barX, bz0 + 0.5),
    piece("break-treats", "treatJar", "break", barX + 2.05, bz0 + 0.5),
    piece("water-cooler", "waterCooler", "break", bx1 - 0.45, bz0 + 2.6, -Math.PI / 2),
    piece("arcade", "arcade", "break", bx1 - 0.6, bottomZ - 0.7, -Math.PI / 2),
    piece("arcade-mat", "arcadeMat", "break", bx1 - 1.5, bottomZ - 0.7, 0, { w: 1.1, d: 1.2 }),
    piece("foosball", "foosball", "break", bx1 - 3.0, bz0 + 4.8),
    piece("beanbag-a", "beanbag", "break", bx1 - 3.7, bottomZ - 1.9),
    piece("beanbag-b", "beanbag", "break", bx1 - 2.5, bottomZ - 1.25),
    piece("break-shelf", "breakBookcase", "break", bx0 + 2.4, bz0 + 0.06 + FURNITURE_SIZE.breakBookcase.d / 2),
    piece("break-nook", "readingNook", "break", bx0 + 0.53, bz0 + 0.58),
    piece("break-dog", "dogBed", "break", bx0 + 0.62, bz0 + 1.6),
    piece("break-plant", "breakPlant", "break", bx0 + 0.6, bottomZ - 0.6),
    piece("break-plant-e", "breakPlant", "break", bx1 - 0.45, bz0 + 7.0),
  );
  spots.push(
    // Sofa module A faces north, module B faces east; the reading nook's armchair faces south, into the room.
    { id: "couch-a1", kind: "couch", pose: "sit", x: bx0 + 2.7, z: bottomZ - 1.85, facing: Math.PI, room: "break" },
    { id: "couch-a2", kind: "couch", pose: "sit", x: bx0 + 3.7, z: bottomZ - 1.85, facing: Math.PI, room: "break" },
    { id: "couch-b1", kind: "couch", pose: "sit", x: bx0 + 1.9, z: bottomZ - 3.7, facing: Math.PI / 2, room: "break" },
    { id: "couch-b2", kind: "couch", pose: "sleep", x: bx0 + 1.9, z: bottomZ - 2.65, facing: Math.PI / 2, room: "break" },
    { id: "couch-nook", kind: "couch", pose: "sit", x: bx0 + 0.61, z: bz0 + 0.72, facing: 0, room: "break" },
    { id: "coffee-1", kind: "coffee", pose: "stand", x: barX - 0.6, z: bz0 + 1.4, facing: Math.PI, room: "break" },
    { id: "coffee-2", kind: "coffee", pose: "stand", x: barX + 0.6, z: bz0 + 1.4, facing: Math.PI, room: "break" },
    { id: "cooler", kind: "cooler", pose: "stand", x: bx1 - 1.2, z: bz0 + 2.6, facing: Math.PI / 2, room: "break" },
    { id: "arcade", kind: "arcade", pose: "stand", x: bx1 - 1.45, z: bottomZ - 0.7, facing: Math.PI / 2, room: "break" },
    { id: "beanbag-a", kind: "beanbag", pose: "sit", x: bx1 - 3.7, z: bottomZ - 1.9, facing: Math.PI * 1.25, room: "break" },
    { id: "beanbag-b", kind: "beanbag", pose: "sit", x: bx1 - 2.5, z: bottomZ - 1.25, facing: Math.PI * 1.25, room: "break" },
    { id: "shelf-break", kind: "shelf", pose: "stand", x: bx0 + 2.2, z: bz0 + 1.1, facing: Math.PI, room: "break" },
  );

  // ------------------------------------------------------------- spawn point
  furniture.push(
    // In the middle of the atrium: the pad, and the terminal on it facing the lobby.
    piece("spawn-pad", "spawnPad", "floor", plaza.x, plaza.z),
    piece("spawn-terminal", "spawnTerminal", "floor", plaza.x, plaza.z),
  );

  // ------------------------------------------------------------- checkpoints
  const elevator = furniture.find((f) => f.id === "elevator")!;
  // The spawn point's ring surrounds the terminal; "walk there" and newcomers stand south of it, facing the screen.
  const arrival: Point = { x: plaza.x, z: plaza.z + SPAWN.approach };
  // Every stop is the place in front of the thing the person uses there.
  const checkpoints: Checkpoint[] = [
    { id: "spawn", room: "floor", x: plaza.x, z: plaza.z, radius: SPAWN.reach, approach: arrival },
    // The reception desk is the one directory and help station.
    { id: "manage", room: "reception", x: deskAt.x, z: deskAt.z + 1.7, radius: 1.2 },
    // In front of the team board.
    { id: "team", room: "team", x: 0.9, z: topZ + 1.6, radius: 1.1 },
    // In front of the dressing mirror.
    { id: "wardrobe", room: "wardrobe", x: dressAt.x, z: dressAt.z, radius: 1.5 },
    // Across the executive desk, behind the guest chairs.
    { id: "lead", room: "lead", x: lcx, z: leadDeskZ + 2.4, radius: 1.3 },
    // At the coffee bar.
    { id: "break", room: "break", x: barX, z: bz0 + 2.0, radius: 1.6 },
    // The elevator's doors face east into the lobby; its checkpoint is the floor in front of them.
    { id: "elevator", room: "reception", x: elevator.x + 0.95, z: elevator.z, radius: 1.0 },
  ];

  // --------------------------------------------------------------- obstacles
  const walls = uniqueWalls(rooms);
  const benchDesks = departments.flatMap((d) => d.desks);
  const obstacles: Rect[] = [
    ...walls.map(wallRect),
    ...[...leadDesks, ...benchDesks].map(deskRect),
    ...leadDesks.map(executiveChairRect),
    // Bench desk chairs and the meeting chairs: nobody walks through a chair.
    ...benchDesks.map((d) => chairRect(seatOf(d))),
    ...spots.filter((s) => s.kind === "meeting").map((s) => chairRect(s)),
    ...departments.map(studioWallRect),
    ...furniture.filter((f) => FURNITURE_SIZE[f.kind].solid).map(footprint),
    // Oak planter boxes at the bench ends.
    ...departments.flatMap(benchPlanters).map((p) => p.rect),
    ...ambience.flatMap(ambienceObstacles),
    // The posts of the lobby's name arch are solid too; nobody walks through them.
    ...rooms.filter((r) => !r.walled).flatMap(archPosts).map((p) => ({
      minX: p.x - ARCH.post / 2, maxX: p.x + ARCH.post / 2, minZ: p.z - ARCH.post / 2, maxZ: p.z + ARCH.post / 2,
    })),
  ];

  return {
    variant: "agents", departments, studios, zones, ambience,
    lead: { minX: lead.minX, maxX: lead.maxX, minZ: lead.minZ, maxZ: lead.maxZ, desks: leadDesks },
    rooms, walls, furniture, spots, checkpoints, obstacles,
    // The person starts in front of the elevator.
    spawn: { x: rx0 + 1.4, z: bottomZ - 2.6 },
    arrival,
    floor: {
      // The navigation grid starts at this corner. Desks stand on a 0.85 m raster from their studio's centre, so
      // the place beside a chair would fall exactly on a cell boundary for every other cluster width; an eighth
      // of a cell keeps all of them clear of one.
      minX: planMinX - FLOOR_EDGE + RAIL_CLEARANCE - GRID_NUDGE, maxX: planMaxX + FLOOR_EDGE - RAIL_CLEARANCE,
      minZ: topZ - FLOOR_EDGE + RAIL_CLEARANCE, maxZ: bottomZ + FLOOR_EDGE - RAIL_CLEARANCE,
    },
    bounds: { minX: planMinX - FLOOR_EDGE, maxX: planMaxX + FLOOR_EDGE, minZ: topZ - FLOOR_EDGE, maxZ: bottomZ + FLOOR_EDGE },
  };
}
