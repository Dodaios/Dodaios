/**
 * Furniture and fittings, built from primitives into the deck's merged
 * batch. Each builder draws one piece in its own frame: centred on its
 * footprint, its front (where a person uses it) towards +z, its foot on the
 * floor. Screens and holograms that change are drawn by their own
 * components; this only builds what never changes.
 */
import { Matrix4 } from "three";
import type { DeckPlan, Prop, PropKind } from "../../plan/types";
import type { CutLine, Frame, GeoBatch } from "../kit/geo";
import { SHIP } from "../kit/palette";

type Builder = (f: Frame, p: Prop) => void;

/** Where a console's screen sits in the console's own frame. */
export const CONSOLE_SCREEN = { y: 1.16, z: -0.2, w: 0.96, h: 0.52, tilt: -0.22 } as const;

const console: Builder = (f, p) => {
  const accent = p.accent ?? SHIP.cyan;
  // Pedestal and foot.
  f.chamfer("structure", 0.62, 0.08, 0.5, 0.08, SHIP.charcoal, { z: -0.06 });
  f.chamfer("structure", 0.44, 0.7, 0.32, 0.06, SHIP.graphite, { z: -0.1, y: 0.08 });
  // Desk: a dark top with a ceramic rim, sloping towards the user.
  f.rounded("panel", p.w, 0.07, 0.62, 0.08, SHIP.panelCool, { y: 0.74, z: 0.02 });
  f.rounded("structure", p.w - 0.08, 0.02, 0.5, 0.06, SHIP.panelDark, { y: 0.81, z: 0.04, pitch: 0.05 });
  // Input surface: a soft cyan pad and keys.
  f.box("glowSoft", 0.52, 0.006, 0.18, "#2a6c8f", { y: 0.835, z: 0.16 });
  f.box("glow", p.w - 0.1, 0.012, 0.012, accent, { y: 0.76, z: 0.33 });
  // Screen mount and bezel (the face itself is drawn live).
  f.box("structure", 0.08, 0.32, 0.06, SHIP.graphite, { y: 0.8, z: CONSOLE_SCREEN.z - 0.06 });
  const s = f.child({ y: CONSOLE_SCREEN.y, z: CONSOLE_SCREEN.z, pitch: CONSOLE_SCREEN.tilt });
  s.box("structure", CONSOLE_SCREEN.w + 0.06, CONSOLE_SCREEN.h + 0.06, 0.035, SHIP.charcoal, { y: -(CONSOLE_SCREEN.h + 0.06) / 2, z: -0.025 });
  s.box("glow", CONSOLE_SCREEN.w + 0.06, 0.01, 0.04, accent, { y: -(CONSOLE_SCREEN.h + 0.06) / 2 - 0.01, z: -0.025 });
  // A side wing with status lights.
  for (const side of [-1, 1]) {
    f.chamfer("panel", 0.1, 0.24, 0.44, 0.03, SHIP.panel, { x: side * (p.w / 2 - 0.05), y: 0.78, z: 0.0 });
  }
};

const consoleChair: Builder = (f, p) => {
  const accent = p.accent ?? SHIP.cyan;
  f.cylinder("metal", 0.26, 0.28, 0.04, SHIP.steel, {}, 20);
  f.cylinder("metal", 0.04, 0.05, 0.4, SHIP.steelLight, { y: 0.04 }, 12);
  f.rounded("fabric", 0.48, 0.08, 0.46, 0.1, SHIP.fabric, { y: 0.42 });
  // Back towards -z (the chair faces +z, towards the console).
  f.rounded("panel", 0.46, 0.5, 0.07, 0.08, SHIP.panel, { y: 0.52, z: -0.24, pitch: -0.12 });
  f.rounded("fabric", 0.38, 0.4, 0.04, 0.07, SHIP.fabric, { y: 0.56, z: -0.2, pitch: -0.12 });
  f.box("glow", 0.3, 0.015, 0.01, accent, { y: 0.98, z: -0.31 });
  for (const s of [-1, 1]) f.rounded("structure", 0.05, 0.04, 0.32, 0.02, SHIP.graphite, { x: s * 0.26, y: 0.62, z: 0.02 });
};

const holoTable: Builder = (f, p) => {
  const r = p.w / 2;
  const accent = p.accent ?? SHIP.cyan;
  f.cylinder("structure", r * 0.55, r * 0.7, 0.1, SHIP.charcoal, {}, 32);
  f.cylinder("structure", r * 0.4, r * 0.5, 0.72, SHIP.graphite, { y: 0.1 }, 32);
  f.cylinder("panel", r, r * 0.92, 0.1, SHIP.panelCool, { y: 0.82 }, 48);
  f.cylinder("structure", r * 0.86, r * 0.86, 0.02, SHIP.panelDark, { y: 0.92 }, 48);
  f.ring("glow", r * 0.98, 0.014, accent, { y: 0.9 }, Math.PI * 2, 64);
  f.ring("glowSoft", r * 0.62, 0.01, SHIP.cyan, { y: 0.935 }, Math.PI * 2, 48);
  f.ring("glow", r * 0.72, 0.012, accent, { y: 0.02 }, Math.PI * 2, 48);
};

const transporter: Builder = (f, p) => {
  const r = p.w / 2;
  f.cylinder("structure", r, r + 0.08, 0.08, SHIP.graphite, {}, 64);
  f.cylinder("metal", r - 0.18, r - 0.12, 0.1, SHIP.steel, { y: 0.0 }, 64);
  f.ring("glow", r - 0.05, 0.03, SHIP.gold, { y: 0.1 }, Math.PI * 2, 72);
  f.ring("glowSoft", r - 0.45, 0.02, SHIP.cyan, { y: 0.11 }, Math.PI * 2, 64);
  // Six emitter pads in a ring and one in the middle.
  for (let k = 0; k < 7; k += 1) {
    const a = (k / 6) * Math.PI * 2;
    const x = k === 6 ? 0 : Math.sin(a) * (r * 0.52), z = k === 6 ? 0 : Math.cos(a) * (r * 0.52);
    f.cylinder("metal", 0.36, 0.4, 0.04, SHIP.steelLight, { x, z, y: 0.1 }, 24);
    f.cylinder("glow", 0.26, 0.26, 0.012, "#bfeaff", { x, z, y: 0.14 }, 24);
  }
};

const transporterConsole: Builder = (f, p) => {
  f.chamfer("structure", 0.9, 0.9, 0.5, 0.1, SHIP.graphite, { z: -0.08 });
  f.rounded("panel", p.w, 0.08, p.d, 0.1, SHIP.panel, { y: 0.9, pitch: 0.28 });
  f.box("glowSoft", p.w - 0.2, 0.005, p.d - 0.24, "#1f5a7a", { y: 0.99, pitch: 0.28 });
  for (let k = 0; k < 3; k += 1) f.box("glow", 0.16, 0.01, 0.05, k === 1 ? SHIP.gold : SHIP.cyan, { x: (k - 1) * 0.36, y: 1.02, z: 0.12, pitch: 0.28 });
  f.box("glow", p.w, 0.012, 0.012, SHIP.gold, { y: 0.88, z: p.d / 2 });
};

const liftDoors: Builder = (f, p) => {
  f.box("structure", p.w + 0.6, 2.7, p.d, SHIP.graphite, { z: -0.05 });
  f.box("metal", p.w - 0.2, 2.25, 0.08, SHIP.steelLight, { z: p.d / 2 - 0.02 });
  f.box("structure", 0.03, 2.25, 0.1, SHIP.charcoal, { z: p.d / 2 });
  f.box("glow", p.w - 0.2, 0.03, 0.1, SHIP.gold, { y: 2.3, z: p.d / 2 });
  for (const s of [-1, 1]) f.box("glow", 0.03, 2.25, 0.1, SHIP.gold, { x: s * (p.w / 2 - 0.08), z: p.d / 2 });
};

const messTable: Builder = (f, p) => {
  f.cylinder("structure", 0.3, 0.34, 0.04, SHIP.charcoal, {}, 24);
  f.cylinder("metal", 0.06, 0.08, 0.66, SHIP.steelLight, { y: 0.04 }, 16);
  f.cylinder("ceramic", p.w / 2, p.w / 2 - 0.03, 0.05, "#f2f2f0", { y: 0.69 }, 40);
  f.ring("glowSoft", p.w / 2 - 0.12, 0.01, SHIP.lightWarm, { y: 0.685 }, Math.PI * 2, 40);
};

const messStool: Builder = (f) => {
  f.cylinder("metal", 0.03, 0.05, 0.42, SHIP.steelLight, {}, 12);
  f.cylinder("fabric", 0.2, 0.18, 0.06, SHIP.leather, { y: 0.42 }, 20);
};

const galley: Builder = (f, p) => {
  f.box("structure", p.w, 0.9, p.d, SHIP.graphite, {});
  f.rounded("ceramic", p.w + 0.06, 0.05, p.d + 0.08, 0.04, "#f0efec", { y: 0.9 });
  f.box("glowSoft", p.w - 0.2, 0.02, 0.02, SHIP.lightWarm, { y: 0.86, z: p.d / 2 + 0.02 });
  // The dispensers along the wall behind: lit alcoves.
  const n = Math.max(2, Math.floor(p.w / 1.3));
  for (let k = 0; k < n; k += 1) {
    const x = -p.w / 2 + (p.w * (k + 0.5)) / n;
    f.box("panel", 1.0, 1.0, 0.3, SHIP.panel, { x, y: 1.25, z: -p.d / 2 + 0.05 });
    f.box("glowSoft", 0.7, 0.55, 0.02, k % 2 ? "#ffd9a8" : "#b8e4ff", { x, y: 1.45, z: -p.d / 2 + 0.21 });
  }
};

const sofa: Builder = (f, p) => {
  const w = p.w, d = p.d;
  f.rounded("structure", w, 0.12, d, 0.08, SHIP.charcoal, { y: 0.04 });
  f.rounded("fabric", w - 0.1, 0.24, d - 0.22, 0.1, SHIP.fabric, { y: 0.16, z: 0.08 });
  f.rounded("fabric", w - 0.1, 0.42, 0.22, 0.1, SHIP.fabric, { y: 0.16, z: -d / 2 + 0.11 });
  for (const s of [-1, 1]) f.rounded("fabric", 0.18, 0.5, d, 0.08, "#343a47", { x: s * (w / 2 - 0.09), y: 0.12 });
  f.box("glowSoft", w - 0.2, 0.01, 0.01, SHIP.lightWarm, { y: 0.06, z: d / 2 });
};

const lowTable: Builder = (f, p) => {
  for (const sx of [-1, 1]) f.box("metal", 0.04, 0.34, p.d - 0.08, SHIP.steel, { x: sx * (p.w / 2 - 0.06) });
  f.rounded("glass", p.w, 0.03, p.d, 0.05, "#c8e8ff", { y: 0.34 });
  f.rounded("structure", p.w - 0.1, 0.02, p.d - 0.1, 0.04, SHIP.panelDark, { y: 0.12 });
};

const plant: Builder = (f, p) => {
  if (p.ref === "bed") {
    // A hydroponics bed: a long trough, rows of greens and grow lights on two posts.
    f.rounded("structure", p.w, 0.55, p.d, 0.06, SHIP.graphite, {});
    f.box("structure", p.w - 0.1, 0.02, p.d - 0.1, SHIP.soil, { y: 0.55 });
    for (let k = 0; k < Math.floor(p.d / 0.5); k += 1) {
      const z = -p.d / 2 + 0.3 + k * 0.5;
      for (const x of [-0.35, 0, 0.35]) f.sphere("fabric", 0.17 + ((k * 7 + x * 10) % 3) * 0.02, k % 2 ? SHIP.plant : SHIP.plantDark, { x, y: 0.66, z }, 8);
    }
    for (const s of [-1, 1]) f.box("metal", 0.05, 1.6, 0.05, SHIP.steel, { z: s * (p.d / 2 - 0.2), y: 0.55 });
    f.box("structure", 0.16, 0.06, p.d - 0.3, SHIP.graphite, { y: 2.12 });
    f.box("glow", 0.1, 0.012, p.d - 0.4, "#ff7ad0", { y: 2.11 });
    return;
  }
  f.chamfer("structure", p.w, 0.55, p.d, 0.1, SHIP.graphite, {});
  f.box("glowSoft", p.w * 0.8, 0.012, 0.012, SHIP.lightWarm, { y: 0.55, z: p.d / 2 - 0.05 });
  const h = p.h;
  f.sphere("fabric", p.w * 0.42, SHIP.plantDark, { y: 0.55 + h * 0.3 }, 10);
  f.sphere("fabric", p.w * 0.34, SHIP.plant, { y: 0.55 + h * 0.48, x: 0.08 }, 10);
  f.sphere("fabric", p.w * 0.26, SHIP.plant, { y: 0.55 + h * 0.62, x: -0.1, z: 0.05 }, 10);
};

const pod: Builder = (f, p) => {
  // Long along the pod's own x (w).
  f.rounded("panel", p.w, 0.5, p.d, 0.3, SHIP.panel, {});
  f.rounded("structure", p.w - 0.18, 0.08, p.d - 0.18, 0.24, SHIP.panelDark, { y: 0.5 });
  f.rounded("fabric", p.w - 0.4, 0.08, p.d - 0.32, 0.2, "#4b4f6a", { y: 0.55 });
  f.rounded("fabric", 0.35, 0.08, p.d - 0.42, 0.12, "#d9dbe8", { x: -p.w / 2 + 0.4, y: 0.62 });
  f.sphere("glass", 0.5, "#c9b8ff", { y: 0.58 }, 20);
  f.box("glowSoft", p.w - 0.3, 0.02, 0.02, "#a68cff", { y: 0.5, z: p.d / 2 - 0.02 });
};

const locker: Builder = (f, p) => {
  f.box("panel", p.w, p.h, p.d, SHIP.panelCool, {});
  f.box("structure", 0.02, p.h - 0.1, 0.02, SHIP.graphite, { y: 0.05, z: p.d / 2 });
  f.box("glow", 0.05, 0.05, 0.02, SHIP.gold, { x: p.w / 2 - 0.12, y: 1.25, z: p.d / 2 });
  f.box("structure", p.w, 0.06, p.d + 0.02, SHIP.graphite, { y: p.h - 0.06 });
};

const mirror: Builder = (f, p) => {
  f.box("structure", p.w, p.h, 0.12, SHIP.graphite, { z: -0.08 });
  f.box("metal", p.w - 0.16, p.h - 0.3, 0.02, "#d8e4ee", { y: 0.15, z: -0.01 });
  for (const s of [-1, 1]) f.box("glow", 0.02, p.h - 0.3, 0.03, SHIP.gold, { x: s * (p.w / 2 - 0.05), y: 0.15 });
  f.box("glow", p.w - 0.1, 0.02, 0.03, SHIP.gold, { y: p.h - 0.12 });
};

const divisionPlinth: Builder = (f, p) => {
  f.chamfer("structure", p.w, 0.08, p.d, 0.16, SHIP.charcoal, {});
  f.chamfer("panel", p.w * 0.66, p.h - 0.08, p.d * 0.66, 0.1, SHIP.panel, { y: 0.08 });
  f.chamfer("structure", p.w * 0.74, 0.04, p.d * 0.74, 0.1, SHIP.graphite, { y: p.h });
  f.ring("glow", p.w * 0.3, 0.012, SHIP.gold, { y: p.h + 0.04 }, Math.PI * 2, 32);
};

const pillar: Builder = (f, p) => {
  f.chamfer("structure", p.w, p.h, p.d, 0.18, SHIP.graphite, {});
  for (const s of [-1, 1]) f.box("glow", 0.025, p.h - 0.6, 0.025, SHIP.lightCool, { x: s * (p.w / 2 - 0.12), y: 0.3, z: p.d / 2 });
  f.chamfer("panel", p.w + 0.1, 0.12, p.d + 0.1, 0.2, SHIP.panel, { y: 0.0 });
};

const bench: Builder = (f, p) => {
  for (const s of [-1, 1]) f.box("structure", 0.08, 0.4, p.d - 0.06, SHIP.graphite, { x: s * (p.w / 2 - 0.2) });
  f.rounded("fabric", p.w, 0.07, p.d, 0.06, SHIP.leather, { y: 0.4 });
};

const crate: Builder = (f, p) => {
  f.chamfer("structure", p.w, p.h, p.d, 0.06, SHIP.steel, {});
  f.box("glow", p.w * 0.6, 0.02, 0.01, SHIP.gold, { y: p.h * 0.7, z: p.d / 2 });
};

export const PROP_BUILDERS: Partial<Record<PropKind, Builder>> = {
  console, consoleChair, holoTable, transporter, transporterConsole, liftDoors, messTable, messStool, galley, sofa,
  lowTable, plant, pod, locker, mirror, divisionPlinth, pillar, bench, crate,
};

/** Register builders for props that live on other decks. */
export function registerPropBuilders(builders: Partial<Record<PropKind, Builder>>): void {
  Object.assign(PROP_BUILDERS, builders);
}

export type PropBuilder = Builder;

/** Pieces that stand against a wall: they sink with it in the cut-away. */
const WALL_MOUNTED = new Set<PropKind>(["liftDoors", "locker", "mirror", "galley", "viewscreen", "rankWall", "cabinet"]);

function distToSegment(px: number, pz: number, ax: number, az: number, bx: number, bz: number): number {
  const dx = bx - ax, dz = bz - az, l2 = dx * dx + dz * dz || 1e-9;
  const t = Math.max(0, Math.min(1, ((px - ax) * dx + (pz - az) * dz) / l2));
  return Math.hypot(px - (ax + dx * t), pz - (az + dz * t));
}

/** The wall line nearest to a point, as a cut-away line (the hull's own edges first). */
export function nearestWallCut(plan: DeckPlan, x: number, z: number, reach = 1.2): CutLine | undefined {
  for (let i = 0; i < plan.hull.length; i += 1) {
    const a = plan.hull[i], c = plan.hull[(i + 1) % plan.hull.length];
    if (distToSegment(x, z, a.x, a.z, c.x, c.z) < Math.min(1.0, reach)) return { ax: a.x, az: a.z, bx: c.x, bz: c.z, kind: 1 };
  }
  let best: CutLine | undefined, bd = reach;
  for (const w of plan.walls) {
    const d = distToSegment(x, z, w.a.x, w.a.z, w.b.x, w.b.z);
    if (d < bd) { bd = d; best = { ax: w.a.x, az: w.a.z, bx: w.b.x, bz: w.b.z, kind: w.kind === "hull" ? 1 : 2 }; }
  }
  return best;
}

/** The wall a wall-mounted piece stands against, as a cut-away line. */
export function wallCutFor(plan: DeckPlan, p: Prop): CutLine | undefined {
  return WALL_MOUNTED.has(p.kind) ? nearestWallCut(plan, p.x, p.z) : undefined;
}

export function propFrame(batch: GeoBatch, p: Prop, cut?: CutLine): Frame {
  return batch.frame(new Matrix4().makeRotationY(p.yaw).setPosition(p.x, 0, p.z), cut);
}

/** Every prop of the plan with a builder, into `batch`. Props drawn elsewhere are skipped. */
export function buildProps(plan: DeckPlan, batch: GeoBatch): void {
  for (const p of plan.props) {
    const build = PROP_BUILDERS[p.kind];
    if (build) build(propFrame(batch, p, wallCutFor(plan, p)), p);
  }
}
