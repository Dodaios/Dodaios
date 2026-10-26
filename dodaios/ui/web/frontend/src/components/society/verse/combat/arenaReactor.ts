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
 *
 * One deliberate difference from the nav grid: the 2.4 m rim band around the
 * drop is cooked as mostly blocked (plate seams and bolt strips); here it is
 * floor up to the kerb, as it reads on screen, so the south passage between
 * the drop and the gallery wall stays open.
 *
 *            far wall (z 2): stacks and machinery
 *   x 33 +--------------------------------------------------+ x 82
 *        |  O     O    [##][###][##]     O     O     O       |
 *        |                 . . N . .                         |
 *        |             .              .              [=]  || |
 *        |          .         |         .                    |
 *   W  0 >  - - - - - - (  ( core )  ) - - - - - - < 1  [=]  || |  E
 *        |          .         |         .                    |
 *        |             .              .              [=]  || |
 *        |                 . . S . .                         |
 *        +-------- door ---------- door ---------- door -----+ z 38.1
 *   0, 1: spawns (sides swap each round)  [=] coolant (1 m)  || conduit
 */
import type { ArenaCollider, ArenaDef } from "./arena";

const SHAFT = { x: 54, z: 22 };
const STACK_X = [35.4, 41.4, 66.6, 72.6, 78.6];
const UNIT_Z = [12, 22, 32];

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
