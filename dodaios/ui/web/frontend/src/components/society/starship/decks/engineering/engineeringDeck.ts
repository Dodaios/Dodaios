/**
 * The engineering deck: where the coding agents of the Agentic IDE work.
 *
 *                 bow ── crew rest nook: galley, mess table, benches at the windows
 *   bays (port) ── reactor core in a railed ring ── bays (starboard)
 *                stern ── master systems display, turbolift
 *
 * One round chamber (a twelve-sided hull) round a vertical reactor core you
 * can walk round. Every IDE workspace gets a bay: a sector of the ring with
 * arcs of consoles facing the core, one pane's seat behind each console, a
 * holo-table at the bay's inner edge and a power feed running to it from the
 * core. Bays share their side of the ring by how many consoles they need, so
 * a busy workspace gets a wide bay. Four bays at least (the empty ones stand
 * by), six at most; later workspaces share the last bay. Lanes between the
 * bays lead from the walkway to every row.
 */
import { COMMAND_GOLD, DIVISION_COLOURS, HOLO_CYAN, PlanBuilder, POOL_COLOUR, arcPoints, polygonBounds, slug, yawTowards } from "../../plan/builder";
import type { DeckPlan, Place, Rect, Vec2 } from "../../plan/types";
import { rect } from "../../plan/types";

/** One coding pane as the plan sees it. */
export interface EngineeringPane {
  /** The pane projected into a crew member (`paneAgentId`). */
  agentId: string;
  workspaceId: string;
  /** The workspace's label (its department name on the old coding floor). */
  workspace: string;
}

export interface EngineeringInput {
  panes: readonly EngineeringPane[];
}

export const MIN_BAYS = 4;
export const MAX_BAYS = 6;
const SIDES = 12;
const STEP = (Math.PI * 2) / SIDES;
/** The reactor's footprint and the rail round it. */
export const CORE_R = 2.4;
export const RAIL_R = 3.6;
/** Console rows, inner first; a third only when a bay needs it. */
export const ROW_R = [10.5, 13.1, 15.7] as const;
const SEAT_INSET = 0.82;
/** Room behind the last row's seats to the hull. */
const AFT_AISLE = 2.0;
const PITCH = 1.32;
/** From a bay's edge to the centre of its end console: half a walking lane plus the console. */
const LANE = 1.3;
/** The sectors that are not bays: the rest nook at the bow, the turbolift approach at the stern. */
const NOOK_HALF = (40 / 180) * Math.PI;
const LOBBY_HALF = (24 / 180) * Math.PI;
const SIDE_SPAN = Math.PI - NOOK_HALF - LOBBY_HALF;
export const TABLE_AT = 8.3;
const TABLE_R = 0.65;
/** Consoles an empty bay keeps ready. */
const FREE_CONSOLES = 3;
/** Every console screen of a deck lives in one atlas of this many cells. */
export const MAX_CONSOLES = 64;

export type BayKind = "workspace" | "other" | "free";

export interface BayPlan {
  id: string;
  kind: BayKind;
  /** The workspace (or "other") this bay stands for; null for an empty bay. */
  teamId: string | null;
  name: string;
  members: string[];
}

/** Where a bay lies on the ring, for the deck's own scene. */
export interface BayArc {
  room: string;
  kind: BayKind;
  /** From and to (yaw round the core), and the middle. */
  a0: number;
  a1: number;
  mid: number;
  accent: string;
}

export interface EngineeringLayout {
  centre: Vec2;
  /** The hull's inner radius (to the middle of its flat sides). */
  hullR: number;
  bays: BayArc[];
}

const layouts = new WeakMap<DeckPlan, EngineeringLayout>();

/** The ring geometry a plan was built with (the scene draws the floor trims and feeds from it). */
export function engineeringLayout(plan: DeckPlan): EngineeringLayout | undefined {
  return layouts.get(plan);
}

function polar(c: Vec2, r: number, a: number): Vec2 {
  return { x: c.x + Math.sin(a) * r, z: c.z + Math.cos(a) * r };
}

/** Distance from the centre to the hull wall in direction `a` (the hull is a regular twelve-gon with flat bow and stern). */
function wallDistance(hullR: number, a: number): { r: number; normal: number } {
  const normal = Math.round(a / STEP) * STEP;
  return { r: hullR / Math.cos(a - normal), normal };
}

/** Consoles that fit in one row of a bay `span` radians wide at radius `r`. */
export function rowCapacity(r: number, span: number): number {
  const room = span * r - 2 * LANE;
  return room < 0 ? 0 : Math.floor(room / PITCH) + 1;
}

/**
 * Which panes go to which bay: one bay per workspace in the order the panes
 * come (by workspace, then arrival), the workspaces past the sixth bay
 * folded into "Other", empty bays up to four.
 */
export function planBays(panes: readonly EngineeringPane[]): BayPlan[] {
  const order: string[] = [];
  const byWorkspace = new Map<string, EngineeringPane[]>();
  for (const p of panes) {
    let list = byWorkspace.get(p.workspaceId);
    if (!list) { list = []; byWorkspace.set(p.workspaceId, list); order.push(p.workspaceId); }
    list.push(p);
  }
  const own = order.length > MAX_BAYS ? order.slice(0, MAX_BAYS - 1) : order;
  const folded = order.length > MAX_BAYS ? order.slice(MAX_BAYS - 1) : [];
  const used = new Set<string>();
  const bays: BayPlan[] = own.map((ws) => {
    let id = `bay-ws-${slug(ws)}`;
    for (let k = 2; used.has(id); k += 1) id = `bay-ws-${slug(ws)}-${k}`;
    used.add(id);
    const list = byWorkspace.get(ws) ?? [];
    return { id, kind: "workspace", teamId: ws, name: list[0]?.workspace || ws, members: list.map((p) => p.agentId) };
  });
  if (folded.length) {
    const names = folded.map((ws) => byWorkspace.get(ws)?.[0]?.workspace || ws);
    bays.push({
      id: "bay-other", kind: "other", teamId: "other",
      name: names.slice(0, 2).join(" · ") + (names.length > 2 ? ` +${names.length - 2}` : ""),
      members: folded.flatMap((ws) => (byWorkspace.get(ws) ?? []).map((p) => p.agentId)),
    });
  }
  while (bays.length < MIN_BAYS) bays.push({ id: `bay-free-${bays.length}`, kind: "free", teamId: null, name: "", members: [] });
  return bays;
}

function need(bay: BayPlan): number {
  return bay.kind === "free" ? FREE_CONSOLES : bay.members.length + 1;
}

interface Sector { bay: BayPlan; a0: number; a1: number; mid: number; span: number }

/**
 * Split the two sides of the ring between the bays: each bay goes to the
 * lighter side, then every side is shared by weight (consoles needed, four
 * at least). Starboard runs from the stern towards the bow, port likewise.
 */
function sectors(bays: readonly BayPlan[]): Sector[] {
  const weight = (b: BayPlan) => Math.max(4, need(b));
  const sides: BayPlan[][] = [[], []];
  const load = [0, 0];
  for (const bay of bays) {
    const s = load[0] <= load[1] ? 0 : 1;
    sides[s].push(bay);
    load[s] += weight(bay);
  }
  const out: Sector[] = [];
  sides.forEach((list, s) => {
    const start = s === 0 ? LOBBY_HALF : Math.PI * 2 - LOBBY_HALF;
    const dir = s === 0 ? 1 : -1;
    let acc = 0;
    for (const bay of list) {
      const span = (SIDE_SPAN * weight(bay)) / load[s];
      const from = start + dir * acc, to = start + dir * (acc + span);
      out.push({ bay, a0: Math.min(from, to), a1: Math.max(from, to), mid: (from + to) / 2, span });
      acc += span;
    }
  });
  // Back in bay order.
  return bays.map((b) => out.find((o) => o.bay === b) as Sector);
}

function capacity(span: number, rows: number): number[] {
  return ROW_R.slice(0, rows).map((r) => rowCapacity(r, span));
}

/** The hull outline: a regular twelve-gon round `centre`, flat at the bow (z = 0) and the stern, clockwise from the bow. */
export function engineeringHull(hullR: number): Vec2[] {
  const rv = hullR / Math.cos(STEP / 2);
  const c = { x: 0, z: hullR };
  return Array.from({ length: SIDES }, (_, j) => {
    const p = polar(c, rv, Math.PI + STEP / 2 - STEP * j);
    // Snap the flat edges exactly onto their lines.
    return { x: Math.abs(p.x) < 1e-9 ? 0 : p.x, z: Math.abs(p.z) < 1e-9 ? 0 : Math.abs(p.z - 2 * hullR) < 1e-9 ? 2 * hullR : p.z };
  });
}

export function buildEngineeringDeck({ panes }: EngineeringInput): DeckPlan {
  const b = new PlanBuilder("engineering");
  const bays = planBays(panes);
  const sect = sectors(bays);

  // Two rows unless a bay needs a third.
  let rows = 2;
  if (sect.some((s) => s.bay.members.length > capacity(s.span, 2).reduce((x, y) => x + y, 0))) rows = 3;
  const caps = sect.map((s) => capacity(s.span, rows));
  const capTotal = caps.map((c) => c.reduce((x, y) => x + y, 0));

  // Seat members first (within the bay and the screen atlas), then spare consoles while there is room.
  let budget = MAX_CONSOLES;
  const seated = sect.map((s, i) => {
    const n = Math.min(s.bay.members.length, capTotal[i], budget);
    budget -= n;
    return n;
  });
  const consoles = sect.map((s, i) => {
    const extra = Math.max(0, Math.min(need(s.bay) - seated[i], capTotal[i] - seated[i], budget));
    budget -= extra;
    return seated[i] + extra;
  });
  const unseated = sect.flatMap((s, i) => s.bay.members.slice(seated[i]));

  const hullR = ROW_R[rows - 1] + SEAT_INSET + AFT_AISLE;
  const c: Vec2 = { x: 0, z: hullR };
  const zEnd = 2 * hullR;
  const hull = engineeringHull(hullR);
  const bounds = polygonBounds(hull);
  const clampRect = (r: Rect): Rect => rect(Math.max(bounds.x0, r.x0), Math.max(bounds.z0, r.z0), Math.min(bounds.x1, r.x1), Math.min(bounds.z1, r.z1));

  // ── hull ───────────────────────────────────────────────────────────
  // Edge j runs from vertex j to j + 1; edge 0 is the bow, 6 the stern, 1 and 11 the nook's windows.
  hull.forEach((p, i) => {
    const q = hull[(i + 1) % hull.length];
    if (i === SIDES / 2) {
      b.wallWithDoors(`hull-${i}`, "hull", p, q, [{ at: Math.abs(q.x - p.x) / 2, width: 3, slides: true, id: "lift-door" }], 0.5);
    } else {
      b.wall(`hull-${i}`, "hull", p, q, 0.5, i === 1 || i === SIDES - 1);
    }
  });

  // ── the core ───────────────────────────────────────────────────────
  b.room({ id: "core", kind: "core", rect: rect(c.x - RAIL_R, c.z - RAIL_R, c.x + RAIL_R, c.z + RAIL_R), floor: "deck", accent: HOLO_CYAN, sign: null });
  b.room({ id: "chamber", kind: "engineering", rect: clampRect(rect(c.x - ROW_R[0], c.z - ROW_R[0], c.x + ROW_R[0], c.z + ROW_R[0])), floor: "deck", accent: HOLO_CYAN, sign: null });
  b.prop({ id: "reactor", kind: "reactor", x: c.x, z: c.z, yaw: 0, w: CORE_R * 2, d: CORE_R * 2, h: 5.2, solid: true });
  const railN = 16;
  for (let k = 0; k < railN; k += 1) {
    b.wall(`core-rail-${k}`, "rail", polar(c, RAIL_R, (k / railN) * Math.PI * 2), polar(c, RAIL_R, ((k + 1) / railN) * Math.PI * 2));
  }

  // ── master systems display, between the core and the turbolift ───
  b.prop({ id: "systems", kind: "systemsTable", x: c.x, z: c.z + 6.2, yaw: 0, w: 3.2, d: 1.5, h: 1.05, solid: true, accent: COMMAND_GOLD });
  b.station({ id: "systems", kind: "systems", x: c.x, z: c.z + 7.6, radius: 1.6, propId: "systems" });

  // ── bays ───────────────────────────────────────────────────────────
  const seatOf = new Map<string, Place>();
  const arcs: BayArc[] = [];
  let colour = 0;
  const boundaries = new Set<number>();
  sect.forEach((s, i) => {
    const bay = s.bay;
    const room = bay.id;
    const accent = bay.kind === "free" ? POOL_COLOUR : DIVISION_COLOURS[colour++ % DIVISION_COLOURS.length];
    arcs.push({ room, kind: bay.kind, a0: s.a0, a1: s.a1, mid: s.mid, accent });
    boundaries.add(Math.round(s.a0 * 1e6) / 1e6);
    boundaries.add(Math.round(s.a1 * 1e6) / 1e6);

    // The bay's floor area (for the sign and the minimap; the floor itself is the chamber's).
    const corners = [s.a0, s.mid, s.a1].flatMap((a) => [polar(c, TABLE_AT - 1, a), polar(c, wallDistance(hullR, a).r, a)]);
    const box = polygonBounds(corners);
    const wall = wallDistance(hullR, s.mid);
    const signAt = polar(c, wall.r - 0.3, s.mid);
    b.room({ id: room, kind: "bay", rect: clampRect(box), floor: "deck", accent,
      sign: bay.kind === "workspace" ? { text: bay.name } : { key: bay.kind === "other" ? "ship.engineering.other" : "ship.engineering.bay_free" },
      signAt: { ...signAt, yaw: wall.normal + Math.PI } });

    // Consoles, inner row first, each row centred on the bay; seats behind them face the core.
    const members: string[] = [];
    let left = consoles[i];
    let seatIndex = 0;
    let lastRow = 0;
    caps[i].forEach((cap, row) => {
      const n = Math.min(cap, left);
      left -= n;
      if (n <= 0) return;
      lastRow = row;
      const r = ROW_R[row];
      arcPoints(c, r, n, s.mid, ((n - 1) * PITCH) / r).forEach((p, k) => {
        const owner = seatIndex < seated[i] ? bay.members[seatIndex] : undefined;
        seatIndex += 1;
        const seat = polar(c, r + SEAT_INSET, p.yaw);
        b.prop({ id: `bayconsole-${room}-${row}-${k}`, kind: "bayConsole", x: p.x, z: p.z, yaw: p.yaw, w: 1.15, d: 0.72, h: 1.5, solid: true, ref: owner, accent });
        b.prop({ id: `chair-${room}-${row}-${k}`, kind: "consoleChair", x: seat.x, z: seat.z, yaw: p.yaw + Math.PI, w: 0.55, d: 0.55, h: 1.0, solid: false, ref: owner, accent });
        if (owner) {
          const place = b.place({ id: `seat-${room}-${row}-${k}`, kind: "console", x: seat.x, z: seat.z, yaw: p.yaw + Math.PI, pose: "sit", seatY: 0.5, owner, division: room });
          seatOf.set(owner, place);
          members.push(owner);
        }
      });
    });

    // The power feed from the core to the bay, under a floor plate.
    const feedFrom = RAIL_R + 0.25, feedTo = TABLE_AT - TABLE_R - 0.3;
    const feedAt = polar(c, (feedFrom + feedTo) / 2, s.mid);
    b.prop({ id: `feed-${room}`, kind: "conduit", x: feedAt.x, z: feedAt.z, yaw: s.mid, w: 0.46, d: feedTo - feedFrom, h: 0.05, solid: false, ref: `floor:${room}`, accent });

    // A quiet place in the aisle behind the consoles.
    const stroll = polar(c, Math.min(ROW_R[lastRow] + SEAT_INSET + 0.85, wall.r - 1.0), s.mid);

    const tableAt = polar(c, TABLE_AT, s.mid);
    if (bay.kind === "free") {
      b.prop({ id: `crate-${room}-0`, kind: "crate", x: tableAt.x, z: tableAt.z, yaw: s.mid, w: 1.0, d: 0.9, h: 0.8, solid: true });
      const side = polar(c, TABLE_AT, s.mid + 1.25 / TABLE_AT);
      b.prop({ id: `crate-${room}-1`, kind: "crate", x: side.x, z: side.z, yaw: s.mid + 0.3, w: 0.8, d: 0.7, h: 0.6, solid: true });
      return;
    }
    b.place({ id: `bay-stroll-${room}`, kind: "stroll", x: stroll.x, z: stroll.z, yaw: s.mid + Math.PI, pose: "stand", seatY: 0, division: room });
    // The bay's holo-table at the walkway, its people gather on the core's side of it.
    b.prop({ id: `table-${room}`, kind: "holoTable", x: tableAt.x, z: tableAt.z, yaw: s.mid + Math.PI, w: TABLE_R * 2, d: TABLE_R * 2, h: 0.95, solid: true, ref: room, accent });
    const towardsCore = yawTowards(tableAt, c);
    const gather = arcPoints(tableAt, TABLE_R + 0.62, 3, towardsCore, 1.5).map((p, k) =>
      b.place({ id: `gather-${room}-${k}`, kind: "table", x: p.x, z: p.z, yaw: p.yaw + Math.PI, pose: "stand", seatY: 0, division: room }));
    b.divisions.push({ id: room, teamId: bay.teamId, name: bay.name, colour: accent, leadId: null, members, centre: tableAt, room, gather });
  });

  // Pipe risers on the hull wall where the bays meet each other, the nook and the lobby.
  [...boundaries].sort((x, y) => x - y).forEach((a, k) => {
    const wall = wallDistance(hullR, a);
    const at = polar(c, wall.r - 0.25 - 0.3, a);
    b.prop({ id: `riser-${k}`, kind: "conduit", x: at.x, z: at.z, yaw: wall.normal + Math.PI, w: 1.0, d: 0.6, h: 2.7, solid: true, ref: "wall" });
  });

  // ── bow: the crew rest nook ────────────────────────────────────────
  const nookDepth = Math.min(7.6, c.z - 8.4);
  b.room({ id: "nook", kind: "mess", rect: rect(-5.5, 0, 5.5, nookDepth), floor: "carpet", accent: COMMAND_GOLD,
    sign: { key: "ship.engineering.nook" }, signAt: { x: 0, z: 0.3, yaw: 0 } });
  b.prop({ id: "galley", kind: "galley", x: 0, z: 0.75, yaw: 0, w: 4.4, d: 0.9, h: 1.05, solid: true });
  for (let k = 0; k < 3; k += 1) b.place({ id: `galley-${k}`, kind: "galley", x: -1.6 + k * 1.6, z: 1.8, yaw: 0, pose: "stand", seatY: 0 });
  b.station({ id: "mess", kind: "mess", x: 0, z: 2.0, radius: 1.6, propId: "galley" });
  for (const [k, x] of [-3.2, 3.2].entries()) b.prop({ id: `nook-plant-${k}`, kind: "plant", x, z: 0.8, yaw: 0, w: 0.8, d: 0.8, h: 1.4, solid: true });
  const mess = { x: 0, z: Math.min(4.8, nookDepth - 1.6) };
  b.prop({ id: "mess-0", kind: "messTable", x: mess.x, z: mess.z, yaw: 0, w: 1.3, d: 1.3, h: 0.74, solid: true });
  for (let k = 0; k < 4; k += 1) {
    const a = (k / 4) * Math.PI * 2 + Math.PI / 4;
    const sx = mess.x + Math.sin(a) * 1.05, sz = mess.z + Math.cos(a) * 1.05;
    b.place({ id: `mess-0-${k}`, kind: "mess", x: sx, z: sz, yaw: yawTowards({ x: sx, z: sz }, mess), pose: "sit", seatY: 0.48 });
    b.prop({ id: `stool-0-${k}`, kind: "messStool", x: sx, z: sz, yaw: 0, w: 0.42, d: 0.42, h: 0.46, solid: false });
  }
  // Benches facing the two windowed sides of the bow, standing places at the glass.
  for (const [k, side] of [-1, 1].entries()) {
    const a = Math.PI + side * (22 / 180) * Math.PI;
    const at = polar(c, hullR - 2.6, a);
    b.prop({ id: `nook-bench-${k}`, kind: "bench", x: at.x, z: at.z, yaw: a, w: 2.4, d: 0.55, h: 0.45, solid: true });
    for (const s of [-1, 1]) {
      const p = { x: at.x + Math.cos(a) * 0.55 * s, z: at.z - Math.sin(a) * 0.55 * s };
      b.place({ id: `nook-bench-${k}-${s}`, kind: "lounge", x: p.x, z: p.z, yaw: a, pose: "sit", seatY: 0.45 });
    }
    for (const [w, deg] of [18, 28].entries()) {
      const wa = Math.PI + side * (deg / 180) * Math.PI;
      const wp = polar(c, wallDistance(hullR, wa).r - 1.0, wa);
      b.place({ id: `nook-window-${k}-${w}`, kind: "window", x: wp.x, z: wp.z, yaw: wa, pose: "stand", seatY: 0 });
    }
  }

  // ── stern: the turbolift ───────────────────────────────────────────
  b.room({ id: "lobby", kind: "lift", rect: rect(-3.8, zEnd - 6, 3.8, zEnd), floor: "deck", accent: COMMAND_GOLD,
    sign: { key: "ship.room.lift" }, signAt: { x: 0, z: zEnd - 0.56, yaw: Math.PI } });
  b.prop({ id: "lift-doors", kind: "liftDoors", x: 0, z: zEnd - 0.3, yaw: Math.PI, w: 3.4, d: 0.5, h: 2.7, solid: true });
  b.station({ id: "lift", kind: "lift", x: 0, z: zEnd - 1.4, radius: 1.6, propId: "lift-doors" });
  for (const [k, x] of [-3.2, 3.2].entries()) {
    b.prop({ id: `lobby-locker-${k}`, kind: "locker", x, z: zEnd - 0.6, yaw: Math.PI, w: 1.0, d: 0.6, h: 2.1, solid: true });
    b.place({ id: `lobby-stroll-${k}`, kind: "stroll", x: x * 0.6, z: zEnd - 4.2, yaw: x < 0 ? Math.PI / 2 : -Math.PI / 2, pose: "stand", seatY: 0 });
  }

  const plan = b.build({
    bounds, hull, seatOf, unseated,
    arrival: { x: 0, z: zEnd - 2.4 },
    lift: { x: 0, z: zEnd - 1.6, yaw: Math.PI },
  });
  layouts.set(plan, { centre: c, hullR, bays: arcs });
  return plan;
}
