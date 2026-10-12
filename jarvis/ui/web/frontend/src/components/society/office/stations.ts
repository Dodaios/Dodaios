/**
 * Stations: the things in the office the person can use. A station is never a
 * marker of its own — it IS an object of the room (the reception desk, the
 * spawn terminal, the team board, the wardrobe mirror, the coffee bar, a team
 * studio's board, …). This module binds every checkpoint and every studio
 * board of a floor plan to that object: which scene groups carry its rim,
 * where the invisible click target sits, and where the person stands to use
 * it. Pure and tested; the renderer (StationObjects), the HUD prompt and the
 * player's nearest-interactable test all read this one list.
 */
import { FURNITURE_SIZE, type Checkpoint, type Furniture, type FurnitureKind, type OfficeLayout, type Point } from "./officeLayout";
import type { Selection } from "./officeStore";

export type StationIcon = "spawn" | "launch" | "reception" | "team" | "wardrobe" | "lead" | "break" | "elevator" | "mission" | "studio" | "levels";

/** A box in world space: centre, size (x-extent × height × z-extent before rotation) and rotation about +y. */
export interface StationBox { x: number; y: number; z: number; w: number; h: number; d: number; rotationY: number }

export interface Station {
  /** Stable React key and lookup id: `<selection kind>:<selection id>`. */
  key: string;
  /** What using the station selects. */
  selection: Selection;
  icon: StationIcon;
  /** The i18n id of its name and action (`cp_<id>`, `use_<id>`): the checkpoint id, or `board` for a studio board. */
  id: string;
  /** A studio board is called after its team; every other station is named by its i18n key. */
  name: string | null;
  /** Centre and radius of the place where E reaches the station. */
  x: number;
  z: number;
  radius: number;
  /** Where "walk there" ends. */
  approach: Point;
  /** Names of the scene groups that are the station (`prop:<furniture id>`, `desk:<desk id>`); they light up. */
  objects: string[];
  /** Invisible click and hover targets; empty when nothing in the room stands for the station. */
  hits: StationBox[];
}

/**
 * The furniture kind that stands for each checkpoint, most typical first. The
 * piece of one of these kinds nearest to the checkpoint is the station, so a
 * floor plan may rename or move its pieces without touching this table.
 */
const STATION_PROPS: Readonly<Record<string, readonly FurnitureKind[]>> = {
  spawn: ["spawnTerminal"],
  launch: ["spawnTerminal"],
  manage: ["receptionDesk", "agentTotem"],
  create: ["receptionDesk"],
  team: ["teamBoard"],
  wardrobe: ["dressingMirror", "mirror"],
  break: ["coffeeBar"],
  elevator: ["elevator"],
  mission: ["commandWall"],
  studio: ["studioStage"],
  levels: ["levelGuide"],
};

const STATION_ICONS: Readonly<Record<string, StationIcon>> = {
  spawn: "spawn", launch: "launch", manage: "reception", team: "team", wardrobe: "wardrobe", lead: "lead", break: "break",
  elevator: "elevator", mission: "mission", studio: "studio", levels: "levels",
};

/** A flat piece (a stage, a pad) still needs something a pointer can hit. */
const MIN_HIT_HEIGHT = 0.12;
/** The lead desk's click target is its visitor-side front panel, so the monitors and the chair keep their own clicks. */
const DESK_FRONT = { h: 0.74, d: 0.1, gap: 0.04 } as const;
const DEFAULT_LEAD_DESK = { w: 2.4, d: 1.05 } as const;
/** How far in front of a studio board the person stands, and how far around that spot E reaches. */
export const BOARD_STAND_M = 1.05;
export const BOARD_REACH_M = 1.25;

export function selectionKey(selection: Selection): string {
  return `${selection.kind}:${selection.id}`;
}

function boxOf(item: Furniture): StationBox {
  const size = FURNITURE_SIZE[item.kind];
  const h = Math.max(size.h, MIN_HIT_HEIGHT);
  return { x: item.x, y: h / 2, z: item.z, w: item.size?.w ?? size.w, h, d: item.size?.d ?? size.d, rotationY: item.rotationY };
}

function propFor(layout: OfficeLayout, checkpoint: Checkpoint): Furniture | null {
  const kinds = STATION_PROPS[checkpoint.id];
  if (!kinds) return null;
  let best: Furniture | null = null;
  let bestDistance = Infinity;
  for (const item of layout.furniture) {
    if (!kinds.includes(item.kind)) continue;
    const d = Math.hypot(item.x - checkpoint.x, item.z - checkpoint.z);
    if (d < bestDistance) { best = item; bestDistance = d; }
  }
  return best;
}

/** The reception desk is one station whatever a floor plan calls its checkpoint. */
const RECEPTION_IDS: ReadonlySet<string> = new Set(["manage", "create"]);

/** Is this selection the reception (the directory)? */
export function isReception(selection: Selection | null): boolean {
  return selection?.kind === "checkpoint" && RECEPTION_IDS.has(selection.id);
}

function checkpointStation(layout: OfficeLayout, checkpoint: Checkpoint): Station {
  const id = RECEPTION_IDS.has(checkpoint.id) ? "manage" : checkpoint.id as string;
  const base = {
    key: `checkpoint:${checkpoint.id}`,
    selection: { kind: "checkpoint", id: checkpoint.id } as Selection,
    icon: STATION_ICONS[id] ?? "reception",
    id,
    name: null,
    x: checkpoint.x, z: checkpoint.z, radius: checkpoint.radius,
    approach: checkpoint.approach ?? { x: checkpoint.x, z: checkpoint.z },
  };
  if (checkpoint.id === "lead") {
    // The lead's desks are desk slots, not furniture: each one is drawn under a `desk:<id>` group.
    const desks = layout.lead.desks;
    return {
      ...base,
      objects: desks.map((desk) => `desk:${desk.id}`),
      hits: desks.map((desk) => {
        const size = desk.size ?? DEFAULT_LEAD_DESK;
        // The seated lead looks at its monitors; visitors stand on the far side of the desk from the chair.
        const towardsVisitor = desk.facing === "north" ? -1 : 1;
        return {
          x: desk.x, y: DESK_FRONT.h / 2, z: desk.z + towardsVisitor * (size.d / 2 + DESK_FRONT.gap),
          w: size.w, h: DESK_FRONT.h, d: DESK_FRONT.d, rotationY: 0,
        };
      }),
    };
  }
  const prop = propFor(layout, checkpoint);
  return { ...base, objects: prop ? [`prop:${prop.id}`] : [], hits: prop ? [boxOf(prop)] : [] };
}

function boardStations(layout: OfficeLayout): Station[] {
  const out: Station[] = [];
  for (const studio of layout.studios ?? []) {
    const board = studio.board;
    if (!board) continue;
    const item = layout.furniture.find((f) => f.id === board.id);
    const size = FURNITURE_SIZE.studioBoard;
    const front = { x: board.x + Math.sin(board.facing) * BOARD_STAND_M, z: board.z + Math.cos(board.facing) * BOARD_STAND_M };
    out.push({
      key: `team:${board.id}`,
      selection: { kind: "team", id: board.id },
      icon: "team",
      id: "board",
      name: studio.name || null,
      x: front.x, z: front.z, radius: BOARD_REACH_M,
      approach: front,
      objects: [`prop:${board.id}`],
      hits: [item ? boxOf(item) : { x: board.x, y: size.h / 2, z: board.z, w: size.w, h: size.h, d: size.d, rotationY: board.facing }],
    });
  }
  return out;
}

/**
 * The free plot's stand ("start a team here"): the furniture piece whose id starts with this, whatever its kind.
 * Its station selects `{ kind: "team", id: <furniture id> }` like a studio board, but there is no team behind it
 * yet: it opens the new-team form.
 */
export const TEAM_STAND_ID = "team-stand";
/** The i18n id of the stand's station (`cp_found`, `use_found`). */
export const TEAM_STAND_STATION = "found";
/** How far in front of the stand's face the person stands. */
const STAND_FRONT_M = 0.95;

function standStations(layout: OfficeLayout): Station[] {
  return layout.furniture.filter((item) => item.id.startsWith(TEAM_STAND_ID)).map((item) => {
    const box = boxOf(item);
    const reach = box.d / 2 + STAND_FRONT_M;
    // A piece's front faces its local +z (rotationY 0 = south, towards the camera).
    const front = { x: item.x + Math.sin(item.rotationY) * reach, z: item.z + Math.cos(item.rotationY) * reach };
    return {
      key: `team:${item.id}`,
      selection: { kind: "team", id: item.id } as Selection,
      icon: "team" as const,
      id: TEAM_STAND_STATION,
      name: null,
      x: front.x, z: front.z, radius: BOARD_REACH_M,
      approach: front,
      objects: [`prop:${item.id}`],
      hits: [box],
    };
  });
}

/** Is this selection the free plot's stand, where a new team is started? */
export function isTeamStand(layout: OfficeLayout, selection: Selection | null): boolean {
  return stationOf(layout, selection)?.id === TEAM_STAND_STATION;
}

const cache = new WeakMap<OfficeLayout, Station[]>();

/** Every station of a floor plan: its checkpoints first, then the team studios' boards and the free plot's stand. Cached per plan. */
export function stationsFor(layout: OfficeLayout): Station[] {
  let stations = cache.get(layout);
  if (!stations) {
    stations = [...layout.checkpoints.map((checkpoint) => checkpointStation(layout, checkpoint)), ...boardStations(layout), ...standStations(layout)];
    cache.set(layout, stations);
  }
  return stations;
}

export function stationOf(layout: OfficeLayout, selection: Selection | null): Station | null {
  if (!selection || (selection.kind !== "checkpoint" && selection.kind !== "team")) return null;
  const key = selectionKey(selection);
  return stationsFor(layout).find((station) => station.key === key) ?? null;
}

/** How long called agents (one called over, a coffee break) stay before they drift back to their day. */
export const CALL_MS = 25_000;

/** Game cabinets are played standing this far in front of the screen (it faces the cabinet's local +z). */
const CABINET_STAND_M = 0.85;

/**
 * The closest thing the person can use from where they stand (E): a station
 * whose reach they are in, an agent within talking range, or a game cabinet
 * they stand in front of. `agents` are the walkers' positions; `skip` are
 * agents that keep the person company (their pet), which are never a target.
 */
export function nearestInteractable(
  layout: OfficeLayout, at: Point, agents: Iterable<readonly [string, Point]>, skip: { has: (id: string) => boolean },
  ranges: { agent: number; arcade: number },
): Selection | null {
  let best: Selection | null = null;
  let bestDistance = Infinity;
  for (const station of stationsFor(layout)) {
    const d = Math.hypot(station.x - at.x, station.z - at.z);
    if (d <= station.radius && d < bestDistance) { best = station.selection; bestDistance = d; }
  }
  for (const [id, p] of agents) {
    if (skip.has(id)) continue;
    const d = Math.hypot(p.x - at.x, p.z - at.z);
    if (d <= ranges.agent && d < bestDistance) { best = { kind: "agent", id }; bestDistance = d; }
  }
  for (const item of layout.furniture) {
    // The break room's cabinet, and every game cabinet on the arcade floor.
    if (item.kind !== "arcade" && item.kind !== "retroCabinet") continue;
    const fx = item.x + Math.sin(item.rotationY) * CABINET_STAND_M, fz = item.z + Math.cos(item.rotationY) * CABINET_STAND_M;
    const d = Math.hypot(fx - at.x, fz - at.z);
    if (d <= ranges.arcade && d < bestDistance) { best = { kind: "arcade", id: item.id }; bestDistance = d; }
  }
  return best;
}

/**
 * The spawn terminal's screen, in the terminal's own frame (SpawnPoint.tsx
 * draws it there): the camera dives into it before the create dialog opens.
 */
export const SPAWN_SCREEN = { y: 1.42, z: 0.0355, w: 0.86, h: 0.58 } as const;

/** The screen face of the spawn terminal that looks at `viewer`, as a dive target; null on a floor without a terminal. */
export function spawnScreenDive(layout: OfficeLayout, viewer: Point): { target: [number, number, number]; facing: number; size: [number, number] } | null {
  const terminal = layout.furniture.find((f) => f.kind === "spawnTerminal");
  if (!terminal) return null;
  const sin = Math.sin(terminal.rotationY), cos = Math.cos(terminal.rotationY);
  // The terminal is double-sided: take the face on the viewer's side.
  const side = (viewer.x - terminal.x) * sin + (viewer.z - terminal.z) * cos >= 0 ? 1 : -1;
  return {
    target: [terminal.x + sin * SPAWN_SCREEN.z * side, SPAWN_SCREEN.y, terminal.z + cos * SPAWN_SCREEN.z * side],
    facing: terminal.rotationY + (side === 1 ? 0 : Math.PI),
    size: [SPAWN_SCREEN.w, SPAWN_SCREEN.h],
  };
}

/** The middle of the break room's couches, where a coffee break gathers; the floor's entrance on a floor without any. */
export function loungeCentre(layout: OfficeLayout): Point {
  const couches = layout.spots.filter((spot) => spot.kind === "couch" && spot.room === "break");
  if (couches.length === 0) return layout.spawn;
  return { x: couches.reduce((sum, p) => sum + p.x, 0) / couches.length, z: couches.reduce((sum, p) => sum + p.z, 0) / couches.length };
}
