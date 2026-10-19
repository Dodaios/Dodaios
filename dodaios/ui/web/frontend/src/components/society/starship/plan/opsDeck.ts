/**
 * The operations deck: where the Jarvis agents live and work.
 *
 *            bow  ── observation lounge and mess, a panoramic window
 *   quartermaster │ transporter plaza │ rest pods
 *   division bays │       spine       │ division bays   (rows grow with the teams)
 *            stern ── turbolift lobby
 *
 * Every team (a society chat group) gets a division: a bay off the spine
 * with a horseshoe of consoles round a holo-table, its lead at the head
 * console. The crew without a team shares the first bay; one empty bay waits
 * for the next team. Seating is by arrival, so a refresh never re-seats
 * anyone; only a change of who belongs where rebuilds the plan.
 */
import {
  arcPoints, COMMAND_GOLD, DIVISION_COLOURS, hash, PlanBuilder, polygonBounds, POOL_COLOUR, slug, yawTowards,
} from "./builder";
import type { CrewInput, DeckPlan, Division, Place, TeamInput, Vec2 } from "./types";
import { rect } from "./types";

/** A bay is one cell of the division grid. */
export const BAY_W = 13.5;
export const BAY_D = 13;
/** The spine corridor between the two columns of bays. */
export const SPINE_W = 6;
export const HALF_W = SPINE_W / 2 + BAY_W;
export const LOUNGE_D = 15;
export const PLAZA_D = 12;
export const STERN_D = 10;
export const MIN_ROWS = 2;
export const MAX_ROWS = 6;
/** Consoles a division's horseshoe holds; later members of a larger team sit with the crew without a team. */
export const BAY_SEATS = 18;
/** Console spacing along the horseshoe. */
const CONSOLE_PITCH = 1.32;
/** The horseshoe's widest opening: everything but the side facing the door. */
const MAX_SPAN = (250 / 180) * Math.PI;
const MIN_RING = 3.1;
const MAX_RING = 5.3;
/** Where a seated agent sits, inside the console ring. */
const SEAT_INSET = 0.82;
const TABLE_R = 1.15;

const DOOR_W = 3.2;

export interface OpsInput {
  crew: readonly CrewInput[];
  teams: readonly TeamInput[];
}

function byArrival(a: CrewInput, b: CrewInput): number {
  return a.createdMs - b.createdMs || a.agentId.localeCompare(b.agentId);
}

interface DivisionPlan { id: string; teamId: string | null; name: string; leadId: string | null; members: CrewInput[] }

/**
 * Who sits in which division. Lead-tier agents are on the bridge (the lead
 * is the captain's pet), so they are not seated here. Teams are taken oldest
 * first; an agent in several sits with the oldest, unless it leads a younger
 * one. A team's lead sits first. The crew without a team comes first and
 * opens a second bay only when it outgrows one.
 */
export function planDivisions(crew: readonly CrewInput[], teams: readonly TeamInput[], maxBays: number): { divisions: DivisionPlan[]; unseated: string[] } {
  const staff = crew.filter((c) => c.tier !== "lead");
  const known = new Map(staff.map((c) => [c.agentId, c]));
  const ordered = [...teams].sort((a, b) => a.createdMs - b.createdMs || a.id.localeCompare(b.id));
  const home = new Map<string, string>();
  // Leading comes first: a lead sits with the team it leads (the oldest such team).
  for (const team of ordered) {
    if (team.leadId && known.has(team.leadId) && team.members.includes(team.leadId) && !home.has(team.leadId)) home.set(team.leadId, team.id);
  }
  for (const team of ordered) {
    for (const id of team.members) if (known.has(id) && !home.has(id)) home.set(id, team.id);
  }
  const teamBays = Math.max(0, maxBays - 1);
  const shown = ordered.slice(0, teamBays);
  const shownIds = new Set(shown.map((t) => t.id));
  const pool: CrewInput[] = [];
  const divisions: DivisionPlan[] = [];
  for (const team of shown) {
    const members = staff.filter((c) => home.get(c.agentId) === team.id).sort(byArrival);
    const lead = team.leadId && members.some((m) => m.agentId === team.leadId) ? team.leadId : null;
    if (lead) members.sort((a, b) => (a.agentId === lead ? -1 : b.agentId === lead ? 1 : 0));
    pool.push(...members.slice(BAY_SEATS));
    // The index keeps ids apart that slug alike ("a b" and "a_b").
    divisions.push({ id: `div-${divisions.length}-${slug(team.id)}`, teamId: team.id, name: team.name, leadId: lead, members: members.slice(0, BAY_SEATS) });
  }
  for (const c of staff) {
    const team = home.get(c.agentId);
    if (!team || !shownIds.has(team)) pool.push(c);
  }
  pool.sort(byArrival);
  const pools: DivisionPlan[] = [];
  const free = Math.max(1, maxBays - divisions.length);
  for (let i = 0; i === 0 || (i * BAY_SEATS < pool.length && pools.length < free); i += 1) {
    pools.push({ id: i === 0 ? "div-pool" : `div-pool-${i + 1}`, teamId: null, name: "", leadId: null, members: pool.slice(i * BAY_SEATS, (i + 1) * BAY_SEATS) });
  }
  const unseated = pool.slice(pools.length * BAY_SEATS).map((c) => c.agentId);
  return { divisions: [...pools, ...divisions], unseated };
}

/** The radius of a horseshoe that seats `n` consoles at the console pitch. */
export function ringRadius(n: number): number {
  return Math.min(MAX_RING, Math.max(MIN_RING, ((Math.max(1, n) - 1) * CONSOLE_PITCH) / MAX_SPAN));
}

export function rowsFor(bays: number): number {
  return Math.min(MAX_ROWS, Math.max(MIN_ROWS, Math.ceil(bays / 2)));
}

/** The hull outline of an operations deck with `rows` rows of bays. */
export function opsHull(rows: number): Vec2[] {
  const end = LOUNGE_D + PLAZA_D + rows * BAY_D + STERN_D;
  return [
    { x: -7, z: 0 }, { x: 7, z: 0 }, { x: HALF_W, z: 9 },
    { x: HALF_W, z: end - 3 }, { x: HALF_W - 3, z: end },
    { x: -HALF_W + 3, z: end }, { x: -HALF_W, z: end - 3 }, { x: -HALF_W, z: 9 },
  ];
}

export function buildOpsDeck({ crew, teams }: OpsInput): DeckPlan {
  const b = new PlanBuilder("ops");
  // How many bays: every team, the crew without a team, one free bay; at least two rows.
  const wanted = teams.length + 2;
  const rows = rowsFor(wanted);
  const bays = rows * 2;
  const { divisions: planned, unseated } = planDivisions(crew, teams, bays - 1);
  const hull = opsHull(rows);
  const bounds = polygonBounds(hull);
  const zPlaza = LOUNGE_D, zBays = LOUNGE_D + PLAZA_D, zStern = zBays + rows * BAY_D, zEnd = zStern + STERN_D;
  const spine = SPINE_W / 2;

  // ── hull ───────────────────────────────────────────────────────────
  hull.forEach((p, i) => {
    const q = hull[(i + 1) % hull.length];
    const stern = p.z === zEnd && q.z === zEnd;
    if (stern) {
      // The turbolift sits in the middle of the stern wall.
      b.wallWithDoors(`hull-${i}`, "hull", p, q, [{ at: Math.abs(q.x - p.x) / 2, width: 3, slides: true, id: "lift-door" }], 0.5);
    } else {
      b.wall(`hull-${i}`, "hull", p, q, 0.5, true);
    }
  });

  // ── bow: observation lounge and mess ───────────────────────────────
  b.room({ id: "lounge", kind: "lounge", rect: rect(-HALF_W, 0, HALF_W, zPlaza), floor: "carpet", accent: COMMAND_GOLD,
    sign: { key: "ship.room.lounge" }, signAt: { x: 0, z: zPlaza - 0.3, yaw: Math.PI } });
  b.wallWithDoors("lounge-s", "bulkhead", { x: -HALF_W, z: zPlaza }, { x: HALF_W, z: zPlaza }, [{ at: HALF_W, width: 8, slides: false, id: "lounge-arch" }]);
  // Mess tables, four stools each, in the port half.
  const mess: Vec2[] = [{ x: -12.2, z: 10.6 }, { x: -7.6, z: 10.6 }, { x: -9.4, z: 6.4 }];
  mess.forEach((m, i) => {
    b.prop({ id: `mess-${i}`, kind: "messTable", x: m.x, z: m.z, yaw: 0, w: 1.3, d: 1.3, h: 0.74, solid: true });
    for (let k = 0; k < 4; k += 1) {
      const a = (k / 4) * Math.PI * 2 + Math.PI / 4;
      const sx = m.x + Math.sin(a) * 1.05, sz = m.z + Math.cos(a) * 1.05;
      b.place({ id: `mess-${i}-${k}`, kind: "mess", x: sx, z: sz, yaw: yawTowards({ x: sx, z: sz }, m), pose: "sit", seatY: 0.48 });
      b.prop({ id: `stool-${i}-${k}`, kind: "messStool", x: sx, z: sz, yaw: 0, w: 0.42, d: 0.42, h: 0.46, solid: false });
    }
  });
  // The galley: a long counter on the lounge's aft wall, standing places in front.
  b.prop({ id: "galley", kind: "galley", x: -11.8, z: zPlaza - 0.75, yaw: Math.PI, w: 6.4, d: 0.9, h: 1.05, solid: true });
  for (let k = 0; k < 3; k += 1) b.place({ id: `galley-${k}`, kind: "galley", x: -14 + k * 2.2, z: zPlaza - 1.75, yaw: Math.PI, pose: "stand", seatY: 0 });
  b.station({ id: "mess", kind: "mess", x: -11.8, z: zPlaza - 1.9, radius: 1.6, propId: "galley" });
  // Sofas facing the bow window in the starboard half.
  const sofas: (Vec2 & { yaw: number })[] = [{ x: 4.6, z: 8.6, yaw: Math.PI }, { x: 9.6, z: 9.4, yaw: Math.PI * 0.82 }, { x: 13.2, z: 12.4, yaw: Math.PI * 0.72 }];
  sofas.forEach((s, i) => {
    b.prop({ id: `sofa-${i}`, kind: "sofa", x: s.x, z: s.z, yaw: s.yaw, w: 2.4, d: 0.95, h: 0.8, solid: true });
    const fx = Math.sin(s.yaw), fz = Math.cos(s.yaw);
    b.prop({ id: `lowtable-${i}`, kind: "lowTable", x: s.x + fx * 1.35, z: s.z + fz * 1.35, yaw: s.yaw, w: 1.3, d: 0.6, h: 0.38, solid: true });
    for (let k = -1; k <= 1; k += 2) {
      const lx = Math.cos(s.yaw) * 0.62 * k, lz = -Math.sin(s.yaw) * 0.62 * k;
      b.place({ id: `sofa-${i}-${k}`, kind: "lounge", x: s.x + lx + fx * 0.12, z: s.z + lz + fz * 0.12, yaw: s.yaw, pose: "sit", seatY: 0.44 });
    }
  });
  // Standing at the bow window.
  for (let k = 0; k < 5; k += 1) b.place({ id: `window-${k}`, kind: "window", x: -4.8 + k * 2.4, z: 1.25, yaw: Math.PI, pose: "stand", seatY: 0 });
  b.prop({ id: "plant-bow-w", kind: "plant", x: -6.2, z: 1.4, yaw: 0, w: 0.8, d: 0.8, h: 1.4, solid: true });
  b.prop({ id: "plant-bow-e", kind: "plant", x: 6.2, z: 1.4, yaw: 0, w: 0.8, d: 0.8, h: 1.4, solid: true });

  // ── plaza: transporter, quartermaster, rest pods ───────────────────
  const zMid = zPlaza + PLAZA_D / 2;
  b.room({ id: "plaza", kind: "plaza", rect: rect(-7, zPlaza, 7, zBays), floor: "deck", accent: "#5fd4ff", sign: null });
  b.prop({ id: "transporter", kind: "transporter", x: 0, z: zMid - 0.4, yaw: 0, w: 4.2, d: 4.2, h: 0.18, solid: false });
  b.prop({ id: "transporter-console", kind: "transporterConsole", x: 4.4, z: zMid - 0.4, yaw: -Math.PI / 2, w: 1.5, d: 0.75, h: 1.05, solid: true });
  b.station({ id: "transporter", kind: "transporter", x: 3.3, z: zMid - 0.4, radius: 1.5, propId: "transporter-console" });
  for (const [i, x] of [-6.2, 6.2].entries()) for (const [k, z] of [zPlaza + 1.0, zBays - 1.0].entries()) {
    b.prop({ id: `pillar-${i}-${k}`, kind: "pillar", x, z, yaw: 0, w: 0.9, d: 0.9, h: 2.6, solid: true });
  }

  b.room({ id: "quartermaster", kind: "quartermaster", rect: rect(-HALF_W, zPlaza, -7, zBays), floor: "ceramic", accent: COMMAND_GOLD,
    sign: { key: "ship.room.quartermaster" }, signAt: { x: -7.15, z: zMid - 2.4, yaw: Math.PI / 2 } });
  b.wallWithDoors("qm-e", "bulkhead", { x: -7, z: zPlaza }, { x: -7, z: zBays }, [{ at: PLAZA_D / 2, width: 2.2 }]);
  for (let k = 0; k < 5; k += 1) b.prop({ id: `locker-${k}`, kind: "locker", x: -HALF_W + 0.65, z: zPlaza + 2.2 + k * 1.05, yaw: Math.PI / 2, w: 0.95, d: 0.6, h: 2.1, solid: true });
  b.prop({ id: "mirror", kind: "mirror", x: -11.6, z: zBays - 0.55, yaw: Math.PI, w: 1.6, d: 0.3, h: 2.2, solid: true });
  b.station({ id: "quartermaster", kind: "quartermaster", x: -11.6, z: zBays - 1.7, radius: 1.5, propId: "mirror" });
  b.prop({ id: "qm-bench", kind: "bench", x: -11.6, z: zMid - 1.6, yaw: 0, w: 2.2, d: 0.5, h: 0.45, solid: true });

  b.room({ id: "pods", kind: "quarters", rect: rect(7, zPlaza, HALF_W, zBays), floor: "carpet", accent: "#a68cff",
    sign: { key: "ship.room.pods" }, signAt: { x: 7.15, z: zMid - 2.4, yaw: -Math.PI / 2 } });
  b.wallWithDoors("pods-w", "bulkhead", { x: 7, z: zPlaza }, { x: 7, z: zBays }, [{ at: PLAZA_D / 2, width: 2.2 }]);
  const podZ = [zPlaza + 2.0, zPlaza + 4.6, zPlaza + 7.2, zPlaza + 9.8];
  podZ.forEach((z, k) => {
    for (const [r, x] of [HALF_W - 0.95, HALF_W - 3.9].entries()) {
      b.prop({ id: `pod-${r}-${k}`, kind: "pod", x, z, yaw: Math.PI / 2, w: 2.3, d: 1.05, h: 1.0, solid: true });
      // Resting inside the pod: the place sits on the pod's own footprint, so it is reached from the aisle beside it.
      b.place({ id: `pod-${r}-${k}`, kind: "pod", x, z, yaw: 0, pose: "rest", seatY: 0.62 });
    }
  });

  // ── divisions ──────────────────────────────────────────────────────
  const seatOf = new Map<string, Place>();
  for (let r = 0; r <= rows; r += 1) {
    const z = zBays + r * BAY_D;
    // Row 0 is the plaza's aft edge, the last row the lobby's fore wall; the spine stays open.
    b.wall(`row-${r}-w`, "bulkhead", { x: -HALF_W, z }, { x: -spine, z });
    b.wall(`row-${r}-e`, "bulkhead", { x: spine, z }, { x: HALF_W, z });
  }
  b.room({ id: "spine", kind: "corridor", rect: rect(-spine, zBays, spine, zStern), floor: "deck", accent: "#5fd4ff", sign: null });
  let colour = 0;
  for (let i = 0; i < bays; i += 1) {
    const row = Math.floor(i / 2), west = i % 2 === 0;
    const z0 = zBays + row * BAY_D, z1 = z0 + BAY_D;
    const x0 = west ? -HALF_W : spine, x1 = west ? -spine : HALF_W;
    const centre = { x: (x0 + x1) / 2 + (west ? -0.4 : 0.4), z: (z0 + z1) / 2 };
    const doorX = west ? -spine : spine;
    const towardsDoor = west ? Math.PI / 2 : -Math.PI / 2;
    b.wallWithDoors(`bay-${i}-front`, "glass", { x: doorX, z: z0 }, { x: doorX, z: z1 }, [{ at: BAY_D / 2, width: DOOR_W, id: `bay-${i}-door` }]);
    const plan = planned[i];
    const roomId = plan ? plan.id : i === planned.length ? "div-free" : `garden-${i}`;
    if (plan) {
      const accent = plan.teamId ? DIVISION_COLOURS[colour++ % DIVISION_COLOURS.length] : POOL_COLOUR;
      b.room({ id: roomId, kind: "division", rect: rect(x0, z0, x1, z1), floor: "deck", accent,
        sign: plan.teamId ? { text: plan.name } : { key: "ship.division.pool" },
        signAt: { x: doorX + (west ? 0.2 : -0.2), z: z0 + BAY_D / 2, yaw: west ? Math.PI / 2 : -Math.PI / 2 } });
      const division = layDivision(b, plan, roomId, centre, towardsDoor, accent, seatOf);
      b.divisions.push(division);
      b.station({ id: `division:${roomId}`, kind: "division", x: centre.x + Math.sin(towardsDoor) * (TABLE_R + 0.75), z: centre.z + Math.cos(towardsDoor) * (TABLE_R + 0.75),
        radius: 1.6, propId: `table-${roomId}`, ref: plan.teamId ?? roomId });
    } else if (roomId === "div-free") {
      b.room({ id: roomId, kind: "division", rect: rect(x0, z0, x1, z1), floor: "deck", accent: COMMAND_GOLD,
        sign: { key: "ship.division.free" }, signAt: { x: doorX + (west ? 0.2 : -0.2), z: z0 + BAY_D / 2, yaw: west ? Math.PI / 2 : -Math.PI / 2 } });
      b.prop({ id: "free-plinth", kind: "divisionPlinth", x: centre.x, z: centre.z, yaw: towardsDoor, w: 1.2, d: 1.2, h: 1.1, solid: true });
      b.station({ id: "newDivision", kind: "newDivision", x: centre.x + Math.sin(towardsDoor) * 1.4, z: centre.z + Math.cos(towardsDoor) * 1.4, radius: 1.5, propId: "free-plinth" });
    } else {
      // A bay nobody needs yet is a hydroponics garden: a place to stroll.
      b.room({ id: roomId, kind: "bay", rect: rect(x0, z0, x1, z1), floor: "grate", accent: "#9bd65b", sign: { key: "ship.room.garden" },
        signAt: { x: doorX + (west ? 0.2 : -0.2), z: z0 + BAY_D / 2, yaw: west ? Math.PI / 2 : -Math.PI / 2 } });
      for (let k = 0; k < 3; k += 1) {
        const bx = centre.x + (west ? -1 : 1) * (k - 1) * 3.2;
        b.prop({ id: `${roomId}-bed-${k}`, kind: "plant", x: bx, z: centre.z, yaw: 0, w: 1.4, d: 7.5, h: 0.9, solid: true, ref: "bed" });
        b.place({ id: `${roomId}-stroll-${k}`, kind: "stroll", x: bx + 1.55 * (west ? 1 : -1), z: centre.z + (k - 1) * 2.1, yaw: west ? -Math.PI / 2 : Math.PI / 2, pose: "stand", seatY: 0 });
      }
    }
    // Side walls between neighbouring rows are the row lines; the bay's hull side is the hull.
  }

  // ── stern: turbolift lobby ─────────────────────────────────────────
  b.room({ id: "lobby", kind: "lift", rect: rect(-HALF_W, zStern, HALF_W, zEnd), floor: "deck", accent: COMMAND_GOLD,
    sign: { key: "ship.room.lift" }, signAt: { x: 0, z: zEnd - 0.35, yaw: Math.PI } });
  b.prop({ id: "lift-doors", kind: "liftDoors", x: 0, z: zEnd - 0.3, yaw: Math.PI, w: 3.4, d: 0.5, h: 2.7, solid: true });
  b.station({ id: "lift", kind: "lift", x: 0, z: zEnd - 1.4, radius: 1.6, propId: "lift-doors" });
  for (const [k, x] of [-8, 8].entries()) {
    b.prop({ id: `lobby-bench-${k}`, kind: "bench", x, z: zEnd - 4.2, yaw: 0, w: 2.6, d: 0.55, h: 0.45, solid: true });
    b.prop({ id: `lobby-plant-${k}`, kind: "plant", x: x + (k ? 2.2 : -2.2), z: zEnd - 4.2, yaw: 0, w: 0.8, d: 0.8, h: 1.4, solid: true });
    b.place({ id: `lobby-stroll-${k}`, kind: "stroll", x, z: zEnd - 5.4, yaw: Math.PI, pose: "stand", seatY: 0 });
  }
  for (let k = 0; k < rows; k += 1) {
    b.place({ id: `spine-stroll-${k}`, kind: "stroll", x: (k % 2 ? 1 : -1) * 1.6, z: zBays + k * BAY_D + 2.2, yaw: k % 2 ? -Math.PI / 2 : Math.PI / 2, pose: "stand", seatY: 0 });
  }

  return b.build({
    bounds, hull, seatOf, unseated,
    arrival: { x: 0, z: zMid - 0.4 },
    lift: { x: 0, z: zEnd - 1.6, yaw: Math.PI },
  });
}

function layDivision(b: PlanBuilder, plan: DivisionPlan, roomId: string, centre: Vec2, towardsDoor: number, accent: string, seatOf: Map<string, Place>): Division {
  // One spare console to grow into; at least six, so a new team's bay is a place to work.
  const consoles = Math.min(BAY_SEATS, Math.max(6, plan.members.length + 1));
  const radius = ringRadius(consoles);
  const span = Math.min(MAX_SPAN, consoles <= 1 ? 0 : ((consoles - 1) * CONSOLE_PITCH) / radius);
  const away = towardsDoor + Math.PI;
  const ring = arcPoints(centre, radius, consoles, away, span);
  // The head console (straight across from the door) first, then outwards alternately.
  const order = ring.map((p, i) => ({ p, i, off: Math.abs(i - (consoles - 1) / 2) })).sort((p, q) => p.off - q.off || p.i - q.i);
  b.prop({ id: `table-${roomId}`, kind: "holoTable", x: centre.x, z: centre.z, yaw: towardsDoor, w: TABLE_R * 2, d: TABLE_R * 2, h: 0.95, solid: true, ref: plan.teamId ?? roomId, accent });
  const members: string[] = [];
  order.forEach(({ p, i }, seatIndex) => {
    const owner = plan.members[seatIndex];
    const head = seatIndex === 0 && !!plan.leadId && owner?.agentId === plan.leadId;
    b.prop({ id: `console-${roomId}-${i}`, kind: "console", x: p.x, z: p.z, yaw: p.yaw + Math.PI, w: 1.15, d: 0.72, h: 1.02, solid: true,
      ref: owner?.agentId, accent: head ? COMMAND_GOLD : accent });
    const sx = p.x - Math.sin(p.yaw) * SEAT_INSET, sz = p.z - Math.cos(p.yaw) * SEAT_INSET;
    b.prop({ id: `chair-${roomId}-${i}`, kind: "consoleChair", x: sx, z: sz, yaw: p.yaw, w: 0.55, d: 0.55, h: 1.0, solid: false, ref: owner?.agentId, accent: head ? COMMAND_GOLD : accent });
    if (owner) {
      const seat = b.place({ id: `seat-${roomId}-${i}`, kind: "console", x: sx, z: sz, yaw: p.yaw, pose: "sit", seatY: 0.5, owner: owner.agentId, division: roomId });
      seatOf.set(owner.agentId, seat);
      members.push(owner.agentId);
    }
  });
  // Standing places round the table for a gathering: an arc on the door's side first.
  const gatherCount = Math.max(4, Math.min(10, plan.members.length));
  const gather = arcPoints(centre, TABLE_R + 0.62, gatherCount, towardsDoor, Math.min(Math.PI * 1.5, gatherCount * 0.62)).map((p, k) =>
    b.place({ id: `gather-${roomId}-${k}`, kind: "table", x: p.x, z: p.z, yaw: p.yaw + Math.PI, pose: "stand", seatY: 0, division: roomId }));
  // A quiet corner in every bay: two standing places by the hull window.
  const hullSide = towardsDoor + Math.PI;
  for (let k = 0; k < 2; k += 1) {
    const wx = centre.x + Math.sin(hullSide) * 4.9, wz = centre.z + (k ? 1 : -1) * 5.0;
    b.place({ id: `bay-window-${roomId}-${k}`, kind: hash(roomId + k) % 3 === 0 ? "window" : "stroll", x: wx, z: wz, yaw: hullSide, pose: "stand", seatY: 0, division: roomId });
  }
  return { id: roomId, teamId: plan.teamId, name: plan.name, colour: accent, leadId: plan.leadId, members, centre, room: roomId, gather };
}
