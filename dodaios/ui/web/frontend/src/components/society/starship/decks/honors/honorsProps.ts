/**
 * The Hall of Honour's fittings in the deck's merged batch: the rank wall's
 * frame (its plaques are drawn live by the scene), the dais before it and
 * the display cases (their insignia and lights are live too), plus the
 * runner up the middle of the hall.
 */
import { annulus, type Frame } from "../../render/kit/geo";
import { SHIP } from "../../render/kit/palette";
import { registerPropBuilders, type PropBuilder } from "../../render/deck/props";

/** Dark polished stone and bronze: the hall's own materials, in the ship's palette. */
export const HALL = {
  stone: "#1b1e24",
  stoneLight: "#2b2f37",
  bronze: "#6b5532",
  runner: "#252b3a",
} as const;

/** Where the plaques sit on the rank wall's face, in the wall's own frame. */
export const PLAQUE_FACE = { y0: 0.42, y1: 3.12, inset: 0.3, z: 0.012 } as const;
/** The display case's glass, in the case's own frame. */
export const VITRINE = { y0: 0.95, y1: 1.63 } as const;

const rankWall: PropBuilder = (f, p) => {
  const { w, h, d } = p;
  f.chamfer("structure", w + 0.3, 0.3, d + 0.24, 0.12, SHIP.charcoal, {});
  f.box("structure", w, h - 0.48, d, HALL.stone, { y: 0.3 });
  f.chamfer("structure", w + 0.44, 0.18, d + 0.3, 0.12, HALL.stoneLight, { y: h - 0.18 });
  // Bronze pilasters at both ends, a gold frame round the plaque field.
  for (const s of [-1, 1]) f.chamfer("metal", 0.32, h - 0.3, d + 0.12, 0.06, HALL.bronze, { x: s * (w / 2 - 0.1), y: 0.3 });
  const fz = d / 2 + 0.01;
  const fw = w - 2 * PLAQUE_FACE.inset + 0.12;
  f.box("metal", fw, 0.04, 0.03, SHIP.gold, { y: PLAQUE_FACE.y0 - 0.08, z: fz });
  f.box("metal", fw, 0.04, 0.03, SHIP.gold, { y: PLAQUE_FACE.y1 + 0.04, z: fz });
  for (const s of [-1, 1]) f.box("metal", 0.04, PLAQUE_FACE.y1 - PLAQUE_FACE.y0 + 0.16, 0.03, SHIP.gold, { x: s * (fw / 2), y: PLAQUE_FACE.y0 - 0.08, z: fz });
  // Warm uplights in the plinth wash the plaques from below.
  f.box("glowSoft", w - 0.6, 0.02, 0.02, SHIP.lightWarm, { y: 0.31, z: d / 2 + 0.1 });
};

const dais: PropBuilder = (f, p) => {
  const { w, d } = p;
  const step = p.h / 2;
  f.chamfer("structure", w, step, d, 0.14, HALL.stoneLight, {});
  f.chamfer("structure", w - 0.6, step, d - 0.5, 0.12, HALL.stone, { y: step, z: -0.1 });
  // Gold inlay round the upper step and an emblem ring in its middle.
  const tw = w - 0.75, td = d - 0.65;
  f.box("metal", tw, 0.006, 0.04, SHIP.gold, { y: p.h, z: -0.1 + td / 2 });
  f.box("metal", tw, 0.006, 0.04, SHIP.gold, { y: p.h, z: -0.1 - td / 2 });
  for (const s of [-1, 1]) f.box("metal", 0.04, 0.006, td, SHIP.gold, { x: s * tw / 2, y: p.h, z: -0.1 });
  f.geo("metal", annulus(0.5, 0.56, 0, Math.PI * 2, 48), SHIP.gold, { y: p.h + 0.004, z: -0.1 });
  f.geo("metal", annulus(0.3, 0.33, 0, Math.PI * 2, 48), SHIP.gold, { y: p.h + 0.004, z: -0.1 });
  f.box("metal", w - 0.1, 0.02, 0.03, HALL.bronze, { y: step - 0.02, z: d / 2 });
  // Two lanterns at the front corners: the dais's own light.
  for (const s of [-1, 1]) {
    const x = s * (w / 2 - 0.55), z = d / 2 - 0.5;
    f.cylinder("structure", 0.16, 0.2, 0.12, SHIP.charcoal, { x, z, y: p.h }, 16);
    f.cylinder("metal", 0.05, 0.06, 1.0, HALL.bronze, { x, z, y: p.h + 0.12 }, 12);
    f.cylinder("glow", 0.08, 0.08, 0.36, SHIP.lightWarm, { x, z, y: p.h + 1.12 }, 16);
    f.cylinder("metal", 0.11, 0.09, 0.05, HALL.bronze, { x, z, y: p.h + 1.48 }, 16);
  }
};

const honorCase: PropBuilder = (f, p) => {
  const { w, d } = p;
  f.chamfer("metal", w + 0.04, 0.08, d + 0.04, 0.06, HALL.bronze, {});
  f.chamfer("structure", w, VITRINE.y0 - 0.08, d, 0.06, HALL.stone, { y: 0.08 });
  f.box("metal", w - 0.1, 0.02, 0.02, SHIP.gold, { y: VITRINE.y0 - 0.1, z: d / 2 + 0.005 });
  f.box("structure", w * 0.5, 0.12, 0.012, HALL.stoneLight, { y: 0.62, z: d / 2 + 0.004 });
  // The glass, its corner posts and a small stand for the insignia.
  const gw = w - 0.1, gd = d - 0.1, gh = VITRINE.y1 - VITRINE.y0;
  f.box("glass", gw, gh, gd, "#d8ecff", { y: VITRINE.y0 });
  for (const sx of [-1, 1]) for (const sz of [-1, 1]) f.box("metal", 0.03, gh, 0.03, SHIP.steelLight, { x: sx * gw / 2, z: sz * gd / 2, y: VITRINE.y0 });
  f.cylinder("metal", 0.1, 0.13, 0.08, SHIP.steel, { y: VITRINE.y0 }, 20);
  f.chamfer("structure", w, 0.1, d, 0.06, HALL.stoneLight, { y: VITRINE.y1 });
  f.box("metal", w - 0.08, 0.02, 0.015, SHIP.gold, { y: VITRINE.y1 + 0.04, z: d / 2 + 0.002 });
};

registerPropBuilders({ rankWall, dais, honorCase });

/** The runner up the middle of the hall, from the dais steps to the arch, in world coordinates. */
export function buildRunner(f: Frame, z0: number, z1: number, width: number): void {
  const len = z1 - z0, z = (z0 + z1) / 2;
  f.box("fabric", width, 0.012, len, HALL.runner, { z, y: 0.006 });
  // Gold borders, a fine inner line, and a cross-bar every few metres.
  for (const s of [-1, 1]) {
    f.box("metal", 0.05, 0.004, len, SHIP.gold, { x: s * (width / 2 - 0.08), y: 0.018, z });
    f.box("metal", 0.015, 0.004, len, SHIP.goldDeep, { x: s * (width / 2 - 0.2), y: 0.018, z });
  }
  for (let k = z0 + 2.5; k < z1 - 1; k += 5) f.box("metal", width - 0.5, 0.004, 0.02, SHIP.goldDeep, { y: 0.018, z: k });
}
