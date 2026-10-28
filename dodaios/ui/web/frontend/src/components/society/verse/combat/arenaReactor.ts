/**
 * The Reactor Shaft hall of the engineering deck as a duel arena.
 *
 * Derived from the deck's sources (art/verse/decks/engineering/eng_common.py,
 * eng_reactor.py, eng_dressing.py and the kit's industrial reactor) and
 * checked against the cooked manifest and nav grid by arena.test.ts:
 *
 *   room "reactor"  x 33..82, z 2..38.1, ceiling 12 m
 *   shaft axis      (54, 22), drop r 13, control ring r 5..6.5 around a
 *                   core of r 3 (containment cage to r ~3.75, ~1.9 m tall)
 *   catwalks        N, E, S, W, 1.2 m wide, ring to rim
 *   far wall        heat-exchanger stacks (x 35.4/41.4/66.6/72.6/78.6) and
 *                   three machinery bays between them
 *   east floor      three power-conduit columns (x 78.6) behind three
 *                   waist-high coolant runs (x 70.8..75.6)
 *   arena fit-out   (eng_arena.py) the energy column on the core (r 2, 1.9 m
 *                   to the ceiling), coolant-tank pairs T flanking each
 *                   spawn in the core's sight shadow, chest-high blast
 *                   barriers B on the north and south walks
 *
 * One deliberate difference from the nav grid: the 2.4 m rim band around the
 * drop is cooked as mostly blocked (plate seams and bolt strips); here it is
 * floor up to the kerb, as it reads on screen, so the south passage between
 * the drop and the gallery wall stays open.
 *
 *            far wall (z 2): stacks and machinery
 *   x 33 +--------------------------------------------------+ x 82
 *        |  O     O    [##][###][##]     O     O     O       |
 *        |            B    . . N . .    B                    |
 *        |             .              .              [=]  || |
 *        |  T       .         |         .         T          |
 *   W  0 >  - - - - - - (  ( core )  ) - - - - - - < 1  [=]  || |  E
 *        |  T       .         |         .         T          |
 *        |             .              .              [=]  || |
 *        |            B    . . S . .    B                    |
 *        +-------- door ---------- door ---------- door -----+ z 38.1
 *   0, 1: spawns (sides swap each round)  [=] coolant (1 m)  || conduit
 *   T tank pair (2.7 m)  B blast barrier (1.2 m)
 */
import type { ArenaCollider, ArenaDef } from "./arena";

const SHAFT = { x: 54, z: 22 };
const STACK_X = [35.4, 41.4, 66.6, 72.6, 78.6];
const UNIT_Z = [12, 22, 32];
// Cover of the arena fit-out, plan centres as in art/verse/decks/engineering/eng_arena.py.
// Tank pairs flank each spawn in the core's sight shadow (from the far spawn the core hides them,
// so they are no pre-aimed hold on it); runs along z, 1.5 x 2.8 m.
const TANKS: [string, number, number][] = [
  ["tanks_nw", 35.6, 17.2], ["tanks_sw", 35.6, 26.8], ["tanks_ne", 72.4, 17.2], ["tanks_se", 72.4, 26.8],
];
const BARRIERS: [string, number, number][] = [
  ["barrier_nw", 46.8, 8.1], ["barrier_ne", 61.2, 8.1], ["barrier_sw", 46.8, 35.9], ["barrier_se", 61.2, 35.9],
];

const colliders: ArenaCollider[] = [
  // Core containment: blocks bolts up to its cap.
  { kind: "cyl", id: "core", x: SHAFT.x, z: SHAFT.z, r: 3.75, y0: -64, y1: 1.9 },
  // Heat-exchanger stacks on the far wall, on plinths.
  ...STACK_X.map((x, i): ArenaCollider => ({ kind: "cyl", id: `stack_${i}`, x, z: 3.35, r: 1.35, y0: 0, y1: 11.6 })),
  ...STACK_X.map((x, i): ArenaCollider => ({ kind: "box", id: `plinth_${i}`, x0: x - 1.5, x1: x + 1.5, z0: 2.0, z1: 4.8, y0: 0, y1: 0.5 })),
  // Coolant lines along the far wall at chest height (either side of the machinery bays).
  { kind: "box", id: "wall_pipes_w", x0: 33.0, x1: 45.4, z0: 2.0, z1: 2.75, y0: 0.9, y1: 2.3 },
  { kind: "box", id: "wall_pipes_e", x0: 62.6, x1: 82.0, z0: 2.0, z1: 2.75, y0: 0.9, y1: 2.3 },
  // Machinery bays between the stacks.
  { kind: "box", id: "machinery_0", x0: 45.6, x1: 50.8, z0: 2.0, z1: 3.1, y0: 0, y1: 7.2 },
  { kind: "box", id: "machinery_1", x0: 52.6, x1: 55.6, z0: 2.0, z1: 3.6, y0: 0, y1: 7.2 },
  { kind: "box", id: "machinery_2", x0: 57.2, x1: 62.4, z0: 2.0, z1: 3.1, y0: 0, y1: 7.2 },
  // East floor: power conduits to the ceiling, coolant runs at waist height.
  ...UNIT_Z.map((z, i): ArenaCollider => ({ kind: "box", id: `conduit_${i}`, x0: 78.0, x1: 79.4, z0: z - 1.15, z1: z + 1.15, y0: 0, y1: 12 })),
  ...UNIT_Z.map((z, i): ArenaCollider => ({ kind: "box", id: `coolant_${i}`, x0: 70.8, x1: 75.6, z0: z - 0.7, z1: z + 0.7, y0: 0, y1: 1.0 })),
  // The arena fit-out (eng_arena.py). The energy column rises from the core's cap to the ceiling.
  { kind: "cyl", id: "core_column", x: SHAFT.x, z: SHAFT.z, r: 2.0, y0: 1.9, y1: 12 },
  // Coolant-tank pairs beside the spawns: tall cover, mirrored about both axes.
  ...TANKS.map(([id, x, z]): ArenaCollider => ({ kind: "box", id, x0: x - 0.75, x1: x + 0.75, z0: z - 1.4, z1: z + 1.4, y0: 0, y1: 2.7 })),
  // Chest-high blast barriers on the north and south walks, mirrored about both axes.
  ...BARRIERS.map(([id, x, z]): ArenaCollider => ({ kind: "box", id, x0: x - 1.2, x1: x + 1.2, z0: z - 0.3, z1: z + 0.3, y0: 0, y1: 1.2 })),
];

export const REACTOR_ARENA: ArenaDef = {
  id: "engineering.reactor",
  name: "Reactor Shaft",
  deck: "engineering",
  room: "reactor",
  bounds: { x0: 33.0, x1: 82.0, z0: 2.0, z1: 38.1, ceiling: 12 },
  colliders,
  voids: [{ x: SHAFT.x, z: SHAFT.z, r: 13.0 }],
  bridges: [
    { kind: "annulus", x: SHAFT.x, z: SHAFT.z, r0: 5.0, r1: 6.5 },
    { kind: "spoke", x: SHAFT.x, z: SHAFT.z, yawDeg: 180, r0: 6.3, r1: 13.4, halfWidth: 0.6 },
    { kind: "spoke", x: SHAFT.x, z: SHAFT.z, yawDeg: 90, r0: 6.3, r1: 13.4, halfWidth: 0.6 },
    { kind: "spoke", x: SHAFT.x, z: SHAFT.z, yawDeg: 0, r0: 6.3, r1: 13.4, halfWidth: 0.6 },
    { kind: "spoke", x: SHAFT.x, z: SHAFT.z, yawDeg: 270, r0: 6.3, r1: 13.4, halfWidth: 0.6 },
  ],
  openings: [
    // Gallery doorways in the south wall and the glass door to the control room.
    { x0: 38.4, x1: 40.8, z0: 38.1, z1: 38.1, y1: 3 },
    { x0: 52.8, x1: 55.2, z0: 38.1, z1: 38.1, y1: 3 },
    { x0: 70.8, x1: 73.2, z0: 38.1, z1: 38.1, y1: 3 },
    { x0: 33.0, x1: 33.0, z0: 20.8, z1: 23.2, y1: 3 },
  ],
  spawns: [
    { x: 38.8, z: 22, yaw: Math.PI / 2 },
    { x: 69.2, z: 22, yaw: -Math.PI / 2 },
  ],
  // The four consoles hung on the control ring (manifest sockets reactor_ring__ring_N, kind "stand").
  terminals: [
    { id: "reactor_ring__ring_1", x: 58.2356, z: 17.7644, yaw: (135 * Math.PI) / 180 },
    { id: "reactor_ring__ring_2", x: 49.7644, z: 17.7644, yaw: (-135 * Math.PI) / 180 },
    { id: "reactor_ring__ring_3", x: 49.7644, z: 26.2356, yaw: (-45 * Math.PI) / 180 },
    { id: "reactor_ring__ring_4", x: 58.2356, z: 26.2356, yaw: (45 * Math.PI) / 180 },
  ],
  centre: SHAFT,
};
