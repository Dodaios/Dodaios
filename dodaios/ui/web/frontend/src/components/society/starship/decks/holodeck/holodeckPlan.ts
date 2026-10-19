/**
 * The holodeck: a black chamber with a gold grid, where the ship's ten retro
 * games stand as holographic cabinets.
 *
 *            bow  ── the chamber: ten emitters on an arc round the program spot
 *                    (every emitter faces the spot, its player stands in front)
 *            ───── the holodeck arch (sliding doors)
 *            stern ── the vestibule with the turbolift
 *
 * Nobody lives here (population "none"): the places are for the captain's
 * companion and for standing about. The plan depends on nothing but the game
 * list, so it is built once.
 */
import { ARCADE_GAMES } from "../../../arcade/arcadeGames";
import { arcPoints, COMMAND_GOLD, HOLO_CYAN, PlanBuilder, polygonBounds, yawTowards } from "../../plan/builder";
import type { DeckPlan, Vec2 } from "../../plan/types";
import { rect } from "../../plan/types";

/** Half the deck's width. */
export const HOLO_HALF_W = 15;
/** The chamber runs from the bow to the arch. */
export const CHAMBER_D = 30;
export const VESTIBULE_D = 8;
export const HOLO_END = CHAMBER_D + VESTIBULE_D;
/** The open spot the emitters face: where a program is "set". */
export const PROGRAM_SPOT: Vec2 = { x: 0, z: 17 };
/** The arc the emitters stand on. */
export const CABINET_RING = 10.5;
const CABINET_SPAN = (200 / 180) * Math.PI;
/** The emitter pedestal's footprint. */
export const EMITTER_W = 1.1;
export const EMITTER_D = 0.9;
/** The player stands this far in front of the emitter's front edge. */
export const PLAY_GAP = 0.9;
export const ARCH_W = 3.6;

/** The prop id of a game's emitter and the id of its station. */
export function emitterId(gameId: string): string { return `cabinet-${gameId}`; }
export function cabinetStationId(gameId: string): string { return `holo:${gameId}`; }

export function holodeckHull(): Vec2[] {
  const w = HOLO_HALF_W;
  return [
    { x: -9, z: 0 }, { x: 9, z: 0 }, { x: w, z: 6 },
    { x: w, z: HOLO_END - 2 }, { x: w - 2, z: HOLO_END },
    { x: -w + 2, z: HOLO_END }, { x: -w, z: HOLO_END - 2 }, { x: -w, z: 6 },
  ];
}

export function buildHolodeck(): DeckPlan {
  const b = new PlanBuilder("holodeck");
  const hull = holodeckHull();
  const bounds = polygonBounds(hull);
  const zEnd = HOLO_END;

  // ── hull ───────────────────────────────────────────────────────────
  hull.forEach((p, i) => {
    const q = hull[(i + 1) % hull.length];
    if (p.z === zEnd && q.z === zEnd) {
      // The turbolift sits in the middle of the stern wall.
      b.wallWithDoors(`hull-${i}`, "hull", p, q, [{ at: Math.abs(q.x - p.x) / 2, width: 3, slides: true, id: "lift-door" }], 0.5);
    } else {
      // A holodeck has no windows: the chamber is a closed black room.
      b.wall(`hull-${i}`, "hull", p, q, 0.5, false);
    }
  });

  // ── the chamber ────────────────────────────────────────────────────
  b.room({ id: "holodeck", kind: "holodeck", rect: rect(-HOLO_HALF_W, 0, HOLO_HALF_W, CHAMBER_D), floor: "holo", accent: COMMAND_GOLD,
    sign: { key: "ship.holodeck.room" }, signAt: { x: 0, z: CHAMBER_D + 0.24, yaw: 0 } });
  b.wallWithDoors("arch", "bulkhead", { x: -HOLO_HALF_W, z: CHAMBER_D }, { x: HOLO_HALF_W, z: CHAMBER_D },
    [{ at: HOLO_HALF_W, width: ARCH_W, slides: true, id: "holo-arch" }]);

  // Ten emitters on an arc round the program spot, the first game on the port end.
  const ring = arcPoints(PROGRAM_SPOT, CABINET_RING, ARCADE_GAMES.length, Math.PI, CABINET_SPAN);
  ARCADE_GAMES.forEach((game, i) => {
    // With mid = π the arc starts at its starboard end; reversed, the list reads port to starboard.
    const p = ring[ARCADE_GAMES.length - 1 - i];
    const yaw = yawTowards(p, PROGRAM_SPOT);
    const fx = Math.sin(yaw), fz = Math.cos(yaw);
    const id = emitterId(game.id);
    b.prop({ id, kind: "cabinet", x: p.x, z: p.z, yaw, w: EMITTER_W, d: EMITTER_D, h: 2.2, solid: true, ref: game.id, accent: game.look.accent });
    const reach = EMITTER_D / 2 + PLAY_GAP;
    const sx = p.x + fx * reach, sz = p.z + fz * reach;
    b.station({ id: cabinetStationId(game.id), kind: "holoCabinet", x: sx, z: sz, radius: 1.1, propId: id, ref: game.id });
    b.place({ id: `play-${game.id}`, kind: "stroll", x: sx, z: sz, yaw: yaw + Math.PI, pose: "stand", seatY: 0 });
  });
  // A few places to stand and watch: the program spot and the chamber's aft corners.
  b.place({ id: "program-spot", kind: "stroll", x: PROGRAM_SPOT.x, z: PROGRAM_SPOT.z + 1.2, yaw: Math.PI, pose: "stand", seatY: 0 });
  for (const [k, x] of [-9.5, 9.5].entries()) {
    b.place({ id: `chamber-stroll-${k}`, kind: "stroll", x, z: CHAMBER_D - 3.5, yaw: yawTowards({ x, z: CHAMBER_D - 3.5 }, PROGRAM_SPOT), pose: "stand", seatY: 0 });
  }

  // ── the vestibule ──────────────────────────────────────────────────
  b.room({ id: "vestibule", kind: "lift", rect: rect(-HOLO_HALF_W, CHAMBER_D, HOLO_HALF_W, zEnd), floor: "deck", accent: HOLO_CYAN,
    sign: { key: "ship.room.lift" }, signAt: { x: 0, z: zEnd - 0.35, yaw: Math.PI } });
  b.prop({ id: "lift-doors", kind: "liftDoors", x: 0, z: zEnd - 0.3, yaw: Math.PI, w: 3.4, d: 0.5, h: 2.7, solid: true });
  b.station({ id: "lift", kind: "lift", x: 0, z: zEnd - 1.4, radius: 1.6, propId: "lift-doors" });
  for (const [k, x] of [-8, 8].entries()) {
    b.prop({ id: `vestibule-bench-${k}`, kind: "bench", x, z: zEnd - 4.2, yaw: 0, w: 2.6, d: 0.55, h: 0.45, solid: true });
    b.prop({ id: `vestibule-plant-${k}`, kind: "plant", x: x + (k ? 2.2 : -2.2), z: zEnd - 4.2, yaw: 0, w: 0.8, d: 0.8, h: 1.4, solid: true });
    b.place({ id: `vestibule-stroll-${k}`, kind: "stroll", x, z: zEnd - 5.4, yaw: Math.PI, pose: "stand", seatY: 0 });
  }

  return b.build({
    bounds, hull,
    arrival: { x: 0, z: zEnd - 1.6 },
    lift: { x: 0, z: zEnd - 1.6, yaw: Math.PI },
  });
}
