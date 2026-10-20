/**
 * The Hall of Honour: a long ceremonial hall where the captain's ranks are
 * kept.
 *
 *            bow  ── the rank wall, a dais in front of it
 *                    display cases down both sides (the officer and flag
 *                    ranks, higher ranks nearer the wall), benches between
 *                    them, a runner up the middle
 *            ───── an open arch
 *            stern ── the lobby with the turbolift
 *
 * Nobody lives here (population "none"). The plan depends on nothing but the
 * rank ladder, so it is built once.
 */
import { RANKS, type Rank } from "../../levels/ranks";
import { COMMAND_GOLD, PlanBuilder, polygonBounds } from "../../plan/builder";
import type { DeckPlan, Vec2 } from "../../plan/types";
import { rect } from "../../plan/types";

export const HALL_HALF_W = 9;
export const HALL_D = 38;
export const LOBBY_D = 8;
export const HALL_END = HALL_D + LOBBY_D;
export const HALL_ARCH_W = 5;
/** The rank wall stands this far from the bow. */
export const RANK_WALL = { z: 1.0, w: 10.4, d: 0.6, h: 3.4 } as const;
export const DAIS = { z: 3.4, w: 7, d: 2.2, h: 0.32 } as const;
/** The runner: from the dais steps to the lift. */
export const RUNNER_W = 2.2;
/** The display cases stand this far off the centre line. */
export const CASE_X = 7.0;
export const CASE = { w: 1.0, d: 0.8, h: 1.75 } as const;
/** The case pairs, stern first; the next rank up stands across the hall, the pair after one step nearer the wall. */
export const CASE_ROWS = [31, 26, 21, 16, 11] as const;
const BENCH_ROWS = [28.5, 23.5, 18.5, 13.5] as const;

/** The ranks that have a case: the officer and flag tiers, lowest first. */
export function caseRanks(): Rank[] {
  return RANKS.filter((r) => r.tier === "officer" || r.tier === "flag");
}

export function caseId(rankId: string): string { return `case-${rankId}`; }

export function hallHull(): Vec2[] {
  const w = HALL_HALF_W;
  return [
    { x: -6, z: 0 }, { x: 6, z: 0 }, { x: w, z: 4 },
    { x: w, z: HALL_END - 2 }, { x: w - 2, z: HALL_END },
    { x: -w + 2, z: HALL_END }, { x: -w, z: HALL_END - 2 }, { x: -w, z: 4 },
  ];
}

export function buildHonorsDeck(): DeckPlan {
  const b = new PlanBuilder("honors");
  const hull = hallHull();
  const bounds = polygonBounds(hull);
  const zEnd = HALL_END;

  // ── hull ───────────────────────────────────────────────────────────
  hull.forEach((p, i) => {
    const q = hull[(i + 1) % hull.length];
    if (p.z === zEnd && q.z === zEnd) {
      b.wallWithDoors(`hull-${i}`, "hull", p, q, [{ at: Math.abs(q.x - p.x) / 2, width: 3, slides: true, id: "lift-door" }], 0.5);
    } else {
      // Tall windows down the sides; the bow is the rank wall's back.
      b.wall(`hull-${i}`, "hull", p, q, 0.5, !(p.z === 0 && q.z === 0));
    }
  });

  // ── the hall ───────────────────────────────────────────────────────
  b.room({ id: "hall", kind: "hall", rect: rect(-HALL_HALF_W, 0, HALL_HALF_W, HALL_D), floor: "honor", accent: COMMAND_GOLD,
    sign: { key: "ship.honors.room" }, signAt: { x: 0, z: HALL_D + 0.24, yaw: 0 } });
  b.wallWithDoors("hall-arch", "bulkhead", { x: -HALL_HALF_W, z: HALL_D }, { x: HALL_HALF_W, z: HALL_D },
    [{ at: HALL_HALF_W, width: HALL_ARCH_W, slides: false, id: "hall-arch" }]);

  b.prop({ id: "rank-wall", kind: "rankWall", x: 0, z: RANK_WALL.z, yaw: 0, w: RANK_WALL.w, d: RANK_WALL.d, h: RANK_WALL.h, solid: true });
  b.prop({ id: "dais", kind: "dais", x: 0, z: DAIS.z, yaw: 0, w: DAIS.w, d: DAIS.d, h: DAIS.h, solid: true });
  b.station({ id: "rank-wall", kind: "rankWall", x: 0, z: DAIS.z + DAIS.d / 2 + 0.9, radius: 1.8, propId: "rank-wall" });
  b.place({ id: "dais-front", kind: "stroll", x: -2.2, z: DAIS.z + DAIS.d / 2 + 1.1, yaw: Math.PI, pose: "stand", seatY: 0 });

  // Display cases, alternating sides up the hall: port takes the first of each pair.
  caseRanks().forEach((rank, i) => {
    const row = Math.floor(i / 2), west = i % 2 === 0;
    const z = CASE_ROWS[Math.min(row, CASE_ROWS.length - 1)];
    const x = west ? -CASE_X : CASE_X;
    const yaw = west ? Math.PI / 2 : -Math.PI / 2;
    const id = caseId(rank.id);
    b.prop({ id, kind: "honorCase", x, z, yaw, w: CASE.w, d: CASE.d, h: CASE.h, solid: true, ref: rank.id, accent: COMMAND_GOLD });
    const sx = x + Math.sin(yaw) * (CASE.d / 2 + 0.9);
    b.station({ id, kind: "honorCase", x: sx, z, radius: 1.1, propId: id, ref: rank.id });
  });

  // Benches between the cases, facing the runner, and pillars against the windows.
  BENCH_ROWS.forEach((z, k) => {
    for (const west of [true, false]) {
      const side = west ? -1 : 1;
      const yaw = west ? Math.PI / 2 : -Math.PI / 2;
      b.prop({ id: `bench-${k}-${west ? "w" : "e"}`, kind: "bench", x: side * 3.4, z, yaw, w: 2.4, d: 0.5, h: 0.45, solid: true });
      for (const [s, dz] of [-0.6, 0.6].entries()) {
        b.place({ id: `bench-${k}-${west ? "w" : "e"}-${s}`, kind: "lounge", x: side * 3.4 - side * 0.05, z: z + dz, yaw, pose: "sit", seatY: 0.45 });
      }
      b.prop({ id: `pillar-${k}-${west ? "w" : "e"}`, kind: "pillar", x: side * 8.25, z, yaw, w: 0.7, d: 0.7, h: 2.6, solid: true });
    }
  });
  for (const [k, z] of [33.5, 8.2].entries()) {
    b.place({ id: `hall-stroll-${k}`, kind: "stroll", x: k ? 2.4 : -2.4, z, yaw: Math.PI, pose: "stand", seatY: 0 });
  }

  // ── the lobby ──────────────────────────────────────────────────────
  b.room({ id: "lobby", kind: "lift", rect: rect(-HALL_HALF_W, HALL_D, HALL_HALF_W, zEnd), floor: "deck", accent: COMMAND_GOLD,
    sign: { key: "ship.room.lift" }, signAt: { x: 0, z: zEnd - 0.35, yaw: Math.PI } });
  b.prop({ id: "lift-doors", kind: "liftDoors", x: 0, z: zEnd - 0.3, yaw: Math.PI, w: 3.4, d: 0.5, h: 2.7, solid: true });
  b.station({ id: "lift", kind: "lift", x: 0, z: zEnd - 1.4, radius: 1.6, propId: "lift-doors" });
  for (const [k, x] of [-5.4, 5.4].entries()) {
    b.prop({ id: `lobby-plant-${k}`, kind: "plant", x, z: HALL_D + 1.4, yaw: 0, w: 0.8, d: 0.8, h: 1.4, solid: true });
    b.prop({ id: `lobby-bench-${k}`, kind: "bench", x, z: zEnd - 3.6, yaw: 0, w: 2.4, d: 0.5, h: 0.45, solid: true });
    b.place({ id: `lobby-stroll-${k}`, kind: "stroll", x: x * 0.6, z: zEnd - 4.8, yaw: Math.PI, pose: "stand", seatY: 0 });
  }

  return b.build({
    bounds, hull,
    arrival: { x: 0, z: zEnd - 1.6 },
    lift: { x: 0, z: zEnd - 1.6, yaw: Math.PI },
  });
}
