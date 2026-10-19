/**
 * The bridge: where the captain commands the ship.
 *
 *              bow  ── a curved forward window, the viewscreen in its middle
 *           helm  ·  ops        (two consoles facing the window)
 *        ╭── command well ──╮   the captain's chair between two seats,
 *        │   ( chair )      │   inside a horseshoe rail open to the bow,
 *        ╰── tactical ──────╯   the tactical console at its aft apex
 *   science │  star chart   │ ready room (starboard: desk, sofa, window)
 *            stern ── aft stations either side of the turbolift
 *
 * Nobody is invented here: the deck's population is "none", so the only
 * people on it are the captain and the pet. The seats are real places the
 * captain uses; the screens show the ship's real state. The command well
 * reads as sunken (a lit step drawn by the scene) while the floor stays flat
 * for walking.
 */
import { arcPoints, COMMAND_GOLD, HOLO_CYAN, PlanBuilder, polygonBounds, yawTowards } from "../../plan/builder";
import type { DeckPlan, Vec2 } from "../../plan/types";
import { rect } from "../../plan/types";

/** Half the bridge's beam (x) and its length from the bow (z). */
export const BRIDGE_HALF_W = 15;
export const BRIDGE_END = 30;

/** The bow: an arc of short hull segments round `centre`, ±`span` from straight ahead. */
export const BOW = { centre: { x: 0, z: 15 } as Vec2, radius: 15, span: (60 / 180) * Math.PI, segments: 10 } as const;
/** The viewscreen fills the middle of the bow window, ±this angle. */
export const VIEWSCREEN_SPAN = (36 / 180) * Math.PI;
/** How far the viewscreen's frame stands in from the hull's centre line. */
export const VIEWSCREEN_INSET = 0.41;

/** The command well and the horseshoe rail round it. */
export const COMMAND: Vec2 = { x: 0, z: 13.5 };
export const RAIL_R = 4.6;
/** The rail's arc, centred on the stern side; the rest (towards the bow) is the way in. */
export const RAIL_SPAN = (236 / 180) * Math.PI;
const RAIL_SEGMENTS = 11;
/** The sunken-looking floor of the well (visual only). */
export const WELL_R = 3.45;

export const STAR_CHART = { x: 0, z: 23.4, r: 1.3 } as const;
/** The captain's ready room, off the starboard side. */
export const READY_ROOM = rect(9.5, 11.5, BRIDGE_HALF_W, 21.5);
const READY_DOOR_Z = 16.5;

const SIDE_Z = 11.5;

/** A point on the bow arc at angle `a` (0 = straight ahead, positive to starboard). */
export function bowPoint(a: number, radius: number = BOW.radius): Vec2 {
  return { x: BOW.centre.x + Math.sin(a) * radius, z: BOW.centre.z - Math.cos(a) * radius };
}

/** The bridge's hull, clockwise from the port end of the bow arc. Convex. */
export function bridgeHull(): Vec2[] {
  const out: Vec2[] = [];
  for (let k = 0; k <= BOW.segments; k += 1) out.push(bowPoint(-BOW.span + (2 * BOW.span * k) / BOW.segments));
  const W = BRIDGE_HALF_W, E = BRIDGE_END;
  out.push({ x: W, z: SIDE_Z }, { x: W, z: E - 3 }, { x: W - 3, z: E }, { x: -W + 3, z: E }, { x: -W, z: E - 3 }, { x: -W, z: SIDE_Z });
  return out;
}

export function buildBridgeDeck(): DeckPlan {
  const b = new PlanBuilder("bridge");
  const hull = bridgeHull();
  const bounds = polygonBounds(hull);
  const W = BRIDGE_HALF_W, E = BRIDGE_END;
  const C = COMMAND;

  // ── hull: the bow window, the side windows, the turbolift in the stern ──
  hull.forEach((p, i) => {
    const q = hull[(i + 1) % hull.length];
    if (p.z === E && q.z === E) {
      b.wallWithDoors(`hull-${i}`, "hull", p, q, [{ at: Math.abs(q.x - p.x) / 2, width: 3, slides: true, id: "lift-door" }], 0.5);
    } else {
      b.wall(`hull-${i}`, "hull", p, q, 0.5, true);
    }
  });

  // ── rooms ──────────────────────────────────────────────────────────
  // The open bridge is three rectangles round the ready room, so no floor is laid twice.
  b.room({ id: "bridge", kind: "bridge", rect: rect(-W, 0, READY_ROOM.x0, E), floor: "deck", accent: COMMAND_GOLD, sign: null });
  b.room({ id: "bridge-fore", kind: "bridge", rect: rect(READY_ROOM.x0, 0, W, READY_ROOM.z0), floor: "deck", accent: COMMAND_GOLD, sign: null });
  b.room({ id: "bridge-aft", kind: "bridge", rect: rect(READY_ROOM.x0, READY_ROOM.z1, W, E), floor: "deck", accent: COMMAND_GOLD, sign: null });

  // ── the viewscreen: a frame round the middle of the bow window ─────
  for (let k = 0; k < BOW.segments; k += 1) {
    const a0 = -BOW.span + (2 * BOW.span * k) / BOW.segments;
    const a1 = -BOW.span + (2 * BOW.span * (k + 1)) / BOW.segments;
    const mid = (a0 + a1) / 2;
    if (Math.abs(mid) > VIEWSCREEN_SPAN) continue;
    const p0 = bowPoint(a0), p1 = bowPoint(a1);
    const m = { x: (p0.x + p1.x) / 2, z: (p0.z + p1.z) / 2 };
    const len = Math.hypot(p1.x - p0.x, p1.z - p0.z);
    const inward = { x: C.x - m.x, z: BOW.centre.z - m.z };
    const n = Math.hypot(inward.x, inward.z);
    const at = { x: m.x + (inward.x / n) * VIEWSCREEN_INSET, z: m.z + (inward.z / n) * VIEWSCREEN_INSET };
    b.prop({ id: `viewscreen-${k}`, kind: "viewscreen", x: at.x, z: at.z, yaw: yawTowards(at, BOW.centre), w: len + 0.02, d: 0.34, h: 2.6, solid: true });
  }
  // Standing at the window, looking out.
  for (const [k, deg] of [-42, -21, 21, 42].entries()) {
    const a = (deg / 180) * Math.PI;
    const p = bowPoint(a, BOW.radius - 1.25);
    b.place({ id: `window-${k}`, kind: "window", x: p.x, z: p.z, yaw: yawTowards(p, bowPoint(a)), pose: "stand", seatY: 0 });
  }

  // ── helm and operations, facing the viewscreen ─────────────────────
  for (const [id, x] of [["helm", -2.5], ["ops", 2.5]] as const) {
    const z = 8.0;
    b.prop({ id: `${id}-console`, kind: "helmConsole", x, z, yaw: 0, w: 1.9, d: 0.85, h: 1.1, solid: true, ref: id, accent: COMMAND_GOLD });
    b.prop({ id: `${id}-chair`, kind: "consoleChair", x, z: z + 0.88, yaw: Math.PI, w: 0.55, d: 0.55, h: 1.0, solid: false, accent: COMMAND_GOLD });
    b.place({ id: `${id}-seat`, kind: "command", x, z: z + 0.88, yaw: Math.PI, pose: "sit", seatY: 0.5 });
    b.station({ id, kind: id, x, z: z + 1.3, radius: 1.3, propId: `${id}-console` });
  }

  // ── the command well: the captain's chair between two seats ────────
  const chair = { x: C.x, z: C.z + 0.4 };
  b.prop({ id: "captain-chair", kind: "captainChair", x: chair.x, z: chair.z, yaw: Math.PI, w: 0.92, d: 0.9, h: 1.32, solid: false });
  b.place({ id: "captain-seat", kind: "captain", x: chair.x, z: chair.z, yaw: Math.PI, pose: "sit", seatY: 0.5 });
  // The captain walks right up to the chair (it is not solid), so sitting down is a turn, not a jump.
  b.station({ id: "captain", kind: "captain", x: chair.x, z: chair.z - 0.3, radius: 1.4, propId: "captain-chair" });
  for (const [id, side] of [["first-officer", 1], ["port", -1]] as const) {
    const x = C.x + side * 2.05, z = C.z + 0.6;
    // Turned a little towards the captain.
    const yaw = Math.PI + side * 0.18;
    b.prop({ id: `${id}-seat`, kind: "commandSeat", x, z, yaw, w: 0.72, d: 0.72, h: 1.08, solid: false, ref: id === "port" ? "port" : "firstOfficer" });
    b.place({ id: `${id}-seat`, kind: "command", x, z, yaw, pose: "sit", seatY: 0.48 });
  }
  b.station({ id: "firstOfficer", kind: "firstOfficer", x: C.x + 2.05, z: C.z - 0.25, radius: 1.0, propId: "first-officer-seat" });

  // ── the horseshoe rail, open to the bow, tactical at its apex ──────
  const rail = arcPoints(C, RAIL_R, RAIL_SEGMENTS + 1, 0, RAIL_SPAN);
  const apex = (RAIL_SEGMENTS - 1) / 2;
  for (let i = 0; i < RAIL_SEGMENTS; i += 1) {
    const p = rail[i], q = rail[i + 1];
    const m = { x: (p.x + q.x) / 2, z: (p.z + q.z) / 2 };
    const len = Math.hypot(q.x - p.x, q.z - p.z);
    const inward = yawTowards(m, C);
    if (i === apex) {
      // The tactical console takes the apex; its officer stands outside the rail, looking forward over the well.
      b.prop({ id: "tactical", kind: "tacticalRail", x: m.x, z: m.z, yaw: inward + Math.PI, w: len + 0.08, d: 0.62, h: 1.08, solid: true, ref: "console", accent: COMMAND_GOLD });
      const out = { x: m.x + Math.sin(inward + Math.PI) * 0.95, z: m.z + Math.cos(inward + Math.PI) * 0.95 };
      b.place({ id: "tactical-stand", kind: "command", x: out.x, z: out.z, yaw: inward, pose: "stand", seatY: 0 });
      continue;
    }
    b.wall(`rail-${i}`, "rail", p, q);
    b.prop({ id: `rail-panel-${i}`, kind: "tacticalRail", x: m.x, z: m.z, yaw: inward, w: len, d: 0.16, h: 1.0, solid: false, ref: "panel" });
  }

  // ── science and navigation along the port side ─────────────────────
  for (const [id, z] of [["science", 15.0], ["navigation", 18.4]] as const) {
    const x = -W + 0.7;
    b.prop({ id: `${id}-console`, kind: "console", x, z, yaw: Math.PI / 2, w: 1.15, d: 0.72, h: 1.02, solid: true, accent: HOLO_CYAN });
    b.prop({ id: `${id}-chair`, kind: "consoleChair", x: x + 0.82, z, yaw: -Math.PI / 2, w: 0.55, d: 0.55, h: 1.0, solid: false, accent: HOLO_CYAN });
    b.place({ id: `${id}-seat`, kind: "command", x: x + 0.82, z, yaw: -Math.PI / 2, pose: "sit", seatY: 0.5 });
  }

  // ── the star chart, between the rail and the turbolift ─────────────
  const chart = STAR_CHART;
  b.prop({ id: "star-chart", kind: "starChart", x: chart.x, z: chart.z, yaw: 0, w: chart.r * 2, d: chart.r * 2, h: 0.95, solid: true, accent: HOLO_CYAN });
  arcPoints(chart, chart.r + 0.8, 6, 0, (Math.PI * 2 * 5) / 6).forEach((p, k) => {
    b.place({ id: `chart-${k}`, kind: "chart", x: p.x, z: p.z, yaw: p.yaw + Math.PI, pose: "stand", seatY: 0 });
  });
  // Course can be set from the chart too: it opens the helm's panel.
  b.station({ id: "chart", kind: "helm", x: chart.x, z: chart.z + chart.r + 0.65, radius: 1.1, propId: "star-chart" });

  // ── stern: the turbolift and an aft station either side ────────────
  b.room({ id: "lift-lobby", kind: "lift", rect: rect(-4, E - 3.5, 4, E), floor: "deck", accent: COMMAND_GOLD,
    sign: { key: "ship.room.lift" }, signAt: { x: 0, z: E - 0.35, yaw: Math.PI } });
  b.prop({ id: "lift-doors", kind: "liftDoors", x: 0, z: E - 0.3, yaw: Math.PI, w: 3.4, d: 0.5, h: 2.7, solid: true });
  b.station({ id: "lift", kind: "lift", x: 0, z: E - 1.4, radius: 1.6, propId: "lift-doors" });
  for (const [id, x] of [["personnel", -6.2], ["comms", 6.2]] as const) {
    const z = E - 0.7;
    b.prop({ id: `${id}-console`, kind: "console", x, z, yaw: Math.PI, w: 1.15, d: 0.72, h: 1.02, solid: true, accent: id === "comms" ? COMMAND_GOLD : HOLO_CYAN });
    b.prop({ id: `${id}-chair`, kind: "consoleChair", x, z: z - 0.82, yaw: 0, w: 0.55, d: 0.55, h: 1.0, solid: false, accent: id === "comms" ? COMMAND_GOLD : HOLO_CYAN });
    b.place({ id: `${id}-seat`, kind: "command", x, z: z - 0.82, yaw: 0, pose: "sit", seatY: 0.5 });
  }
  for (const [k, x] of [-10.2, 10.2].entries()) b.prop({ id: `aft-plant-${k}`, kind: "plant", x, z: E - 0.9, yaw: 0, w: 0.8, d: 0.8, h: 1.4, solid: true });
  for (const [k, x] of [-12.2, 12.2].entries()) b.prop({ id: `fore-plant-${k}`, kind: "plant", x, z: 10.4, yaw: 0, w: 0.8, d: 0.8, h: 1.4, solid: true });
  b.place({ id: "window-port", kind: "window", x: -W + 0.9, z: 23.2, yaw: -Math.PI / 2, pose: "stand", seatY: 0 });
  b.place({ id: "window-starboard", kind: "window", x: W - 0.9, z: 24.6, yaw: Math.PI / 2, pose: "stand", seatY: 0 });
  b.place({ id: "stroll-aft", kind: "stroll", x: -4.4, z: 25.6, yaw: Math.PI, pose: "stand", seatY: 0 });

  // ── the ready room ─────────────────────────────────────────────────
  const R = READY_ROOM;
  b.room({ id: "readyroom", kind: "readyroom", rect: R, floor: "carpet", accent: COMMAND_GOLD,
    sign: { key: "ship.bridge.room.readyroom" }, signAt: { x: R.x0 - 0.2, z: READY_DOOR_Z, yaw: -Math.PI / 2 } });
  b.wallWithDoors("ready-w", "bulkhead", { x: R.x0, z: R.z0 }, { x: R.x0, z: R.z1 }, [{ at: READY_DOOR_Z - R.z0, width: 1.8, id: "ready-door" }]);
  b.wall("ready-n", "bulkhead", { x: R.x0, z: R.z0 }, { x: R.x1, z: R.z0 });
  b.wall("ready-s", "bulkhead", { x: R.x0, z: R.z1 }, { x: R.x1, z: R.z1 });
  // The desk faces the door; the captain sits with the window behind.
  b.prop({ id: "ready-desk", kind: "helmConsole", x: 12.7, z: 14.6, yaw: Math.PI / 2, w: 1.8, d: 0.8, h: 1.1, solid: true, ref: "desk", accent: COMMAND_GOLD });
  b.prop({ id: "ready-chair", kind: "commandSeat", x: 13.65, z: 14.6, yaw: -Math.PI / 2, w: 0.7, d: 0.7, h: 1.1, solid: false, ref: "desk" });
  b.place({ id: "ready-chair", kind: "command", x: 13.65, z: 14.6, yaw: -Math.PI / 2, pose: "sit", seatY: 0.5 });
  const sofa = { x: 14.1, z: 19.4, yaw: -Math.PI / 2 };
  b.prop({ id: "ready-sofa", kind: "sofa", x: sofa.x, z: sofa.z, yaw: sofa.yaw, w: 2.2, d: 0.9, h: 0.8, solid: true });
  b.prop({ id: "ready-table", kind: "lowTable", x: sofa.x - 1.35, z: sofa.z, yaw: sofa.yaw, w: 1.2, d: 0.6, h: 0.38, solid: true });
  for (const k of [-1, 1]) {
    // Along the sofa (its own x runs along world z when turned to face port).
    b.place({ id: `ready-sofa-${k}`, kind: "lounge", x: sofa.x - 0.12, z: sofa.z + k * 0.6, yaw: sofa.yaw, pose: "sit", seatY: 0.44 });
  }
  b.place({ id: "ready-window", kind: "window", x: W - 0.85, z: 17.0, yaw: Math.PI / 2, pose: "stand", seatY: 0 });
  b.prop({ id: "ready-plant", kind: "plant", x: R.x0 + 0.7, z: R.z0 + 0.7, yaw: 0, w: 0.7, d: 0.7, h: 1.4, solid: true });
  b.prop({ id: "ready-model", kind: "starChart", x: R.x0 + 0.8, z: R.z1 - 0.8, yaw: Math.PI / 4, w: 0.7, d: 0.7, h: 1.5, solid: true, ref: "model" });

  return b.build({
    bounds, hull,
    arrival: { x: 0, z: E - 1.6 },
    lift: { x: 0, z: E - 1.6, yaw: Math.PI },
  });
}
