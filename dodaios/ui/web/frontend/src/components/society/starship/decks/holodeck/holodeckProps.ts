/**
 * The holodeck's fittings in the deck's merged batch: the emitter pedestal
 * under every game (prop kind "cabinet") and the holodeck arch. The hologram
 * itself is drawn live by the scene.
 */
import { arcadeGame } from "../../../arcade/arcadeGames";
import type { Frame } from "../../render/kit/geo";
import { SHIP } from "../../render/kit/palette";
import { PROP_BUILDERS, registerPropBuilders, type PropBuilder } from "../../render/deck/props";
import { WALL_H } from "../../render/deck/structure";
import { ARCH_W } from "./holodeckPlan";

/** Height of the emitter lens; the hologram hovers above it. */
export const LENS_Y = 0.25;

/** An emitter pedestal: an octagonal foot, a projector lens and four field nubs. Front (the player's side) is +z. */
const emitter: PropBuilder = (f, p) => {
  f.chamfer("structure", p.w, 0.08, p.d, 0.16, SHIP.charcoal, {});
  f.chamfer("structure", p.w - 0.18, 0.14, p.d - 0.16, 0.12, SHIP.graphite, { y: 0.08 });
  f.chamfer("metal", p.w - 0.26, 0.03, p.d - 0.24, 0.1, SHIP.steel, { y: 0.22 });
  // The lens: the light the hologram is made of.
  f.ring("metal", 0.25, 0.022, SHIP.steelLight, { y: LENS_Y }, Math.PI * 2, 32);
  f.cylinder("glow", 0.2, 0.2, 0.012, "#bfeaff", { y: LENS_Y - 0.006 }, 32);
  // Field nubs at the corners, each with a lit tip.
  for (const sx of [-1, 1]) for (const sz of [-1, 1]) {
    const x = sx * (p.w / 2 - 0.2), z = sz * (p.d / 2 - 0.17);
    f.cylinder("metal", 0.045, 0.055, 0.07, SHIP.steelLight, { x, z, y: 0.25 }, 12);
    f.cylinder("glow", 0.025, 0.025, 0.012, SHIP.cyan, { x, z, y: 0.32 }, 10);
  }
  // The player's edge: a gold inlay and the game's own colour as a ready light.
  f.box("metal", p.w - 0.5, 0.02, 0.03, SHIP.gold, { y: 0.2, z: (p.d - 0.16) / 2 + 0.005 });
  f.box("glow", 0.14, 0.022, 0.02, p.accent ?? SHIP.cyan, { y: 0.12, z: (p.d - 0.16) / 2 + 0.01 });
};

// "cabinet" is a shared prop kind; a pedestal is drawn only for a holodeck game, anything else keeps the builder it had.
const previous = PROP_BUILDERS.cabinet;
registerPropBuilders({
  cabinet: (f, p) => {
    if (p.ref && arcadeGame(p.ref)) emitter(f, p);
    else previous?.(f, p);
  },
});

/**
 * The holodeck arch round the chamber's doors, in the arch's own frame
 * (centred on the doorway, +z towards the vestibule): two pylons that rise
 * above the wall line, a lintel with a lit program lens, gold on the
 * vestibule face where the captain walks in.
 */
export function buildArch(f: Frame): void {
  const half = ARCH_W / 2;
  const top = WALL_H + 0.7;
  for (const s of [-1, 1]) {
    const x = s * (half + 0.42);
    f.chamfer("structure", 0.84, top, 0.9, 0.14, SHIP.graphite, { x });
    f.chamfer("structure", 0.96, 0.12, 1.0, 0.16, SHIP.charcoal, { x });
    // Gold edges on both faces, a cyan field line on the inner face.
    for (const face of [-1, 1]) f.box("metal", 0.05, top - 0.3, 0.03, SHIP.gold, { x: x - s * 0.36, y: 0.15, z: face * 0.46 });
    f.box("glow", 0.02, top - 0.6, 0.6, SHIP.cyan, { x: x - s * 0.43, y: 0.3 });
  }
  f.chamfer("structure", ARCH_W + 1.9, 0.5, 0.96, 0.18, SHIP.graphite, { y: top - 0.5 });
  f.box("metal", ARCH_W + 1.6, 0.04, 0.03, SHIP.gold, { y: top - 0.42, z: 0.49 });
  f.box("metal", ARCH_W + 1.6, 0.04, 0.03, SHIP.gold, { y: top - 0.42, z: -0.49 });
  // The program lens over the doorway, facing the vestibule.
  f.cylinder("metal", 0.22, 0.22, 0.06, SHIP.steelLight, { y: top - 0.25, z: 0.48, pitch: Math.PI / 2 }, 24);
  f.cylinder("glow", 0.15, 0.15, 0.02, SHIP.gold, { y: top - 0.25, z: 0.52, pitch: Math.PI / 2 }, 24);
}
