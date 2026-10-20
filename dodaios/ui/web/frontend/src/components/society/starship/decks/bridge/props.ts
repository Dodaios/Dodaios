/**
 * The bridge's furniture, registered into the shared prop builders: the
 * captain's chair, the command seats, the helm and operations consoles (and
 * the ready room's desk, which shares their screen mount), the horseshoe
 * rail's panels and its tactical console, the viewscreen's frame, the star
 * chart table and the ship model in the ready room. Each piece is drawn in
 * its own frame: centred on its footprint, its front (where a person uses
 * it) towards +z, its foot on the floor. `glow` is only ever a real light.
 */
import type { Prop } from "../../plan/types";
import type { Frame } from "../../render/kit/geo";
import { SHIP } from "../../render/kit/palette";
import { CONSOLE_SCREEN, registerPropBuilders, type PropBuilder } from "../../render/deck/props";

const TAU = Math.PI * 2;
/** A warm walnut-dark for the command furniture's tops. */
const WALNUT = "#43352c";
const GLASS_FIELD = "#1f5a7a";

/** The live screen's bezel, exactly where `ConsoleScreens` draws the face. */
function screenBezel(f: Frame, accent: string): void {
  const s = f.child({ y: CONSOLE_SCREEN.y, z: CONSOLE_SCREEN.z, pitch: CONSOLE_SCREEN.tilt });
  const bw = CONSOLE_SCREEN.w + 0.06, bh = CONSOLE_SCREEN.h + 0.06;
  s.box("structure", bw, bh, 0.035, SHIP.charcoal, { y: -bh / 2, z: -0.025 });
  s.box("structure", bw - 0.2, bh - 0.12, 0.05, SHIP.graphite, { y: -bh / 2 + 0.06, z: -0.07 });
  s.box("glow", bw, 0.01, 0.04, accent, { y: -bh / 2 - 0.01, z: -0.025 });
}

// ── seats ────────────────────────────────────────────────────────────

const captainChair: PropBuilder = (f) => {
  // A low round plinth, ringed with the command gold.
  f.cylinder("structure", 0.46, 0.5, 0.06, SHIP.charcoal, {}, 40);
  f.ring("glow", 0.475, 0.007, SHIP.gold, { y: 0.06 }, TAU, 56);
  f.cylinder("metal", 0.1, 0.15, 0.28, SHIP.steel, { y: 0.06 }, 20);
  // Seat shell and cushion.
  f.rounded("structure", 0.7, 0.1, 0.64, 0.12, SHIP.graphite, { y: 0.34 });
  f.rounded("fabric", 0.58, 0.09, 0.54, 0.1, SHIP.leather, { y: 0.43, z: 0.03 });
  // A tall back leaning back, its cushion, a headrest and the gold line along its crown.
  const back = f.child({ y: 0.42, z: -0.29, pitch: -0.14 });
  back.rounded("structure", 0.7, 0.86, 0.1, 0.12, SHIP.graphite, {});
  back.rounded("fabric", 0.54, 0.6, 0.06, 0.1, SHIP.leather, { y: 0.1, z: 0.07 });
  back.rounded("fabric", 0.38, 0.14, 0.08, 0.06, SHIP.leather, { y: 0.72, z: 0.07 });
  back.box("glow", 0.46, 0.012, 0.104, SHIP.gold, { y: 0.86 });
  // Armrests, each with a dark glass control pad and its lights.
  for (const s of [-1, 1]) {
    const arm = f.child({ x: s * 0.42, y: 0.4 });
    arm.rounded("structure", 0.1, 0.24, 0.46, 0.04, SHIP.graphite, { z: -0.04 });
    arm.rounded("panel", 0.15, 0.05, 0.62, 0.05, SHIP.panelCool, { y: 0.24, z: 0.02 });
    arm.box("structure", 0.1, 0.006, 0.24, SHIP.panelDark, { y: 0.29, z: 0.14 });
    arm.box("glowSoft", 0.07, 0.004, 0.1, GLASS_FIELD, { y: 0.296, z: 0.1 });
    arm.box("glow", 0.024, 0.006, 0.024, s > 0 ? SHIP.gold : SHIP.cyan, { y: 0.296, z: 0.21 });
  }
};

const commandSeat: PropBuilder = (f, p) => {
  if (p.ref === "desk") {
    // The ready room's desk chair: five feet on casters, a swivel column, a mid-height back.
    for (let k = 0; k < 5; k += 1) {
      const a = (k / 5) * TAU;
      f.box("metal", 0.05, 0.04, 0.3, SHIP.steel, { x: Math.sin(a) * 0.14, z: Math.cos(a) * 0.14, y: 0.04, yaw: a });
      f.sphere("structure", 0.03, SHIP.charcoal, { x: Math.sin(a) * 0.28, z: Math.cos(a) * 0.28, y: 0.03 }, 8);
    }
    f.cylinder("metal", 0.035, 0.045, 0.36, SHIP.steelLight, { y: 0.06 }, 12);
    f.rounded("fabric", 0.5, 0.08, 0.48, 0.1, SHIP.leather, { y: 0.42 });
    const back = f.child({ y: 0.5, z: -0.24, pitch: -0.12 });
    back.rounded("structure", 0.48, 0.5, 0.06, 0.1, SHIP.graphite, {});
    back.rounded("fabric", 0.4, 0.42, 0.04, 0.08, SHIP.leather, { y: 0.04, z: 0.04 });
    for (const s of [-1, 1]) f.rounded("structure", 0.05, 0.04, 0.3, 0.02, SHIP.graphite, { x: s * 0.26, y: 0.64, z: 0.02 });
    return;
  }
  // The first officer's and the port seat: the captain's chair's lines, lower and without the plinth's ring.
  f.cylinder("structure", 0.34, 0.38, 0.05, SHIP.charcoal, {}, 32);
  f.cylinder("metal", 0.08, 0.12, 0.3, SHIP.steel, { y: 0.05 }, 18);
  f.rounded("structure", 0.6, 0.09, 0.56, 0.1, SHIP.graphite, { y: 0.34 });
  f.rounded("fabric", 0.5, 0.08, 0.48, 0.09, SHIP.fabric, { y: 0.42, z: 0.03 });
  const back = f.child({ y: 0.42, z: -0.26, pitch: -0.12 });
  back.rounded("structure", 0.6, 0.62, 0.09, 0.1, SHIP.graphite, {});
  back.rounded("fabric", 0.46, 0.46, 0.05, 0.08, SHIP.fabric, { y: 0.08, z: 0.06 });
  back.box(p.ref === "firstOfficer" ? "glowSoft" : "structure", 0.36, 0.01, 0.094, p.ref === "firstOfficer" ? SHIP.gold : SHIP.steelLight, { y: 0.62 });
  for (const s of [-1, 1]) {
    const arm = f.child({ x: s * 0.36, y: 0.4 });
    arm.rounded("structure", 0.08, 0.2, 0.38, 0.03, SHIP.graphite, { z: -0.04 });
    arm.rounded("panel", 0.12, 0.04, 0.5, 0.04, SHIP.panelCool, { y: 0.2 });
  }
  // One small pad on the inner arm, towards the captain.
  const inner = p.ref === "firstOfficer" ? -1 : 1;
  f.box("glowSoft", 0.06, 0.004, 0.09, GLASS_FIELD, { x: inner * 0.36, y: 0.645, z: 0.12 });
};

// ── consoles ─────────────────────────────────────────────────────────

/** The helm and operations: a wedge desk with a sloped control surface and a live screen. */
function helmDesk(f: Frame, p: Prop): void {
  const accent = p.accent ?? SHIP.gold;
  const w = p.w, d = p.d;
  // A chamfered foot and a body that steps back from the knees.
  f.chamfer("structure", w - 0.3, 0.06, 0.62, 0.12, SHIP.charcoal, { z: -0.12 });
  f.chamfer("panel", w - 0.42, 0.62, 0.36, 0.1, SHIP.panelCool, { y: 0.06, z: -0.2 });
  f.box("structure", w - 0.4, 0.035, 0.37, SHIP.graphite, { y: 0.34, z: -0.2 });
  // Side wings carry the top.
  for (const side of [-1, 1]) f.chamfer("structure", 0.12, 0.72, d - 0.12, 0.04, SHIP.graphite, { x: side * (w / 2 - 0.08), z: -0.02 });
  // The sloped top: a ceramic rim round a dark glass control surface.
  const top = f.child({ y: 0.7, pitch: 0.2 });
  top.rounded("panel", w, 0.07, d, 0.12, SHIP.panel, {});
  top.rounded("structure", w - 0.14, 0.02, d - 0.16, 0.08, SHIP.panelDark, { y: 0.07 });
  // Two lit glass fields either side of the screen's foot, a row of keys at the front.
  for (const s of [-1, 1]) top.box("glowSoft", w * 0.3, 0.005, d * 0.34, GLASS_FIELD, { x: s * w * 0.27, y: 0.091, z: 0.02 });
  for (let k = 0; k < 7; k += 1) top.box("glow", 0.07, 0.006, 0.026, k === 3 ? accent : SHIP.cyan, { x: (k - 3) * 0.11, y: 0.092, z: d / 2 - 0.14 });
  top.box("glow", w - 0.18, 0.012, 0.012, accent, { y: 0.035, z: d / 2 + 0.002 });
  // The screen's neck and bezel.
  f.box("structure", 0.1, 0.36, 0.08, SHIP.graphite, { y: 0.74, z: CONSOLE_SCREEN.z - 0.08 });
  screenBezel(f, accent);
}

/** The ready room's desk: two pedestals, a walnut-dark top and a desk screen. */
function readyDesk(f: Frame, p: Prop): void {
  const w = p.w, d = p.d;
  for (const s of [-1, 1]) f.rounded("panel", 0.42, 0.68, d - 0.12, 0.05, SHIP.panel, { x: s * (w / 2 - 0.27) });
  f.box("structure", w - 0.96, 0.46, 0.04, SHIP.graphite, { y: 0.2, z: -d / 2 + 0.12 });
  f.rounded("structure", w, 0.06, d, 0.06, WALNUT, { y: 0.68 });
  f.rounded("fabric", w * 0.42, 0.006, d * 0.42, 0.04, SHIP.leather, { y: 0.74, z: 0.1 });
  f.box("glowSoft", w - 0.24, 0.012, 0.012, SHIP.lightWarm, { y: 0.67, z: d / 2 - 0.02 });
  // A data pad, a cup.
  f.rounded("structure", 0.18, 0.012, 0.26, 0.02, SHIP.panelDark, { x: w * 0.3, y: 0.742, z: 0.12, yaw: 0.25 });
  f.box("glowSoft", 0.14, 0.003, 0.2, GLASS_FIELD, { x: w * 0.3, y: 0.755, z: 0.12, yaw: 0.25 });
  f.cylinder("ceramic", 0.04, 0.035, 0.09, "#f2f2f0", { x: -w * 0.32, y: 0.74, z: 0.16 }, 16);
  // The screen on a slim neck.
  f.box("metal", 0.05, 0.22, 0.05, SHIP.steelLight, { y: 0.74, z: CONSOLE_SCREEN.z - 0.06 });
  f.rounded("metal", 0.26, 0.012, 0.16, 0.03, SHIP.steelLight, { y: 0.74, z: CONSOLE_SCREEN.z - 0.04 });
  screenBezel(f, p.accent ?? SHIP.gold);
}

const helmConsole: PropBuilder = (f, p) => (p.ref === "desk" ? readyDesk(f, p) : helmDesk(f, p));

// ── the rail ─────────────────────────────────────────────────────────

const tacticalRail: PropBuilder = (f, p) => {
  const w = p.w;
  if (p.ref === "console") {
    // Tactical: a long console set into the rail's apex, its officer standing behind it.
    const accent = p.accent ?? SHIP.gold;
    f.box("structure", w, 0.1, 0.5, SHIP.panelDark, { z: -0.04 });
    f.chamfer("panel", w - 0.06, 0.8, 0.4, 0.08, SHIP.panelCool, { y: 0.1, z: -0.08 });
    for (const s of [-1, 1]) f.chamfer("structure", 0.1, 0.9, 0.5, 0.03, SHIP.graphite, { x: s * (w / 2 - 0.05), z: -0.04 });
    const top = f.child({ y: 0.9, pitch: 0.26 });
    top.rounded("panel", w, 0.06, p.d, 0.08, SHIP.panel, {});
    top.rounded("structure", w - 0.12, 0.02, p.d - 0.12, 0.06, SHIP.panelDark, { y: 0.06 });
    top.box("glowSoft", w * 0.6, 0.005, p.d * 0.4, GLASS_FIELD, { y: 0.081, z: -0.06 });
    for (let k = 0; k < 9; k += 1) top.box("glow", 0.06, 0.006, 0.024, k === 4 ? accent : k % 2 ? SHIP.cyanDeep : SHIP.cyan, { x: (k - 4) * 0.13, y: 0.082, z: p.d / 2 - 0.12 });
    top.box("glow", w - 0.12, 0.012, 0.012, accent, { y: 0.03, z: p.d / 2 + 0.002 });
    return;
  }
  // A rail panel: the balustrade under the handrail, a warm wash on the floor inside the well.
  f.box("structure", w, 0.1, 0.2, SHIP.panelDark, {});
  f.box("panel", w, 0.8, 0.12, SHIP.panelCool, { y: 0.1 });
  f.box("structure", w, 0.05, 0.16, SHIP.graphite, { y: 0.88 });
  f.box("glowSoft", w - 0.08, 0.01, 0.01, SHIP.lightWarm, { y: 0.07, z: 0.105 });
};

// ── the viewscreen ───────────────────────────────────────────────────

/** One segment of the viewscreen's frame, standing against the bow window's inner face. */
const viewscreen: PropBuilder = (f, p) => {
  const w = p.w;
  // The header beam over the window, with the emitter strip that throws the picture.
  f.box("structure", w, 0.34, 0.3, SHIP.graphite, { y: 2.2, z: -0.02 });
  f.box("structure", w, 0.04, 0.34, SHIP.charcoal, { y: 2.18, z: -0.02 });
  f.box("glow", w - 0.04, 0.012, 0.02, SHIP.cyan, { y: 2.19, z: 0.14 });
  // The sill: a dark ledge with a quiet light line along its lip.
  f.box("structure", w, 0.12, 0.34, SHIP.panelDark, { y: 0.84 });
  f.box("glowSoft", w - 0.04, 0.01, 0.02, SHIP.cyan, { y: 0.9, z: 0.17 });
  // Posts at the joints (a neighbour's post overlaps, which reads as one).
  for (const s of [-1, 1]) f.chamfer("structure", 0.16, 1.42, 0.3, 0.05, SHIP.graphite, { x: (s * w) / 2, y: 0.84, z: -0.02 });
};

// ── the star chart and the model ─────────────────────────────────────

const starChart: PropBuilder = (f, p) => {
  if (p.ref === "model") {
    // The ready room's display: a plinth, a glass case and the Dodaios in miniature.
    f.chamfer("panel", 0.52, 1.0, 0.52, 0.08, SHIP.panel, {});
    f.chamfer("structure", 0.6, 0.05, 0.6, 0.09, SHIP.graphite, { y: 1.0 });
    f.box("glowSoft", 0.36, 0.006, 0.36, SHIP.lightWarm, { y: 1.05 });
    f.cylinder("metal", 0.008, 0.008, 0.14, SHIP.steel, { y: 1.05 }, 8);
    const m = f.child({ y: 1.22 });
    m.rounded("metal", 0.1, 0.045, 0.4, 0.04, SHIP.hullOuter, { z: -0.02 });
    m.box("structure", 0.34, 0.01, 0.06, SHIP.graphite, { y: 0.0, z: 0.06 });
    for (const s of [-1, 1]) {
      m.cylinder("metal", 0.024, 0.024, 0.3, SHIP.hullOuter, { x: s * 0.17, y: -0.01, z: -0.08, pitch: Math.PI / 2 }, 12);
      m.box("glow", 0.03, 0.01, 0.01, SHIP.cyan, { x: s * 0.17, y: 0.004, z: -0.085 });
    }
    f.box("glass", 0.46, 0.42, 0.46, "#cfe8ff", { y: 1.05 });
    return;
  }
  const r = p.w / 2;
  // An octagonal foot, a ribbed pedestal.
  f.chamfer("structure", r * 1.6, 0.08, r * 1.6, r * 0.46, SHIP.charcoal, {});
  f.cylinder("structure", r * 0.4, r * 0.56, 0.72, SHIP.graphite, { y: 0.08 }, 32);
  for (let k = 0; k < 8; k += 1) {
    const a = (k / 8) * TAU;
    f.box("structure", 0.06, 0.6, 0.2, SHIP.steel, { x: Math.sin(a) * r * 0.48, z: Math.cos(a) * r * 0.48, y: 0.12, yaw: a });
  }
  // The table: a ceramic ring round a dark glass disc with the projector's field in the middle.
  f.cylinder("panel", r, r * 0.9, 0.1, SHIP.panelCool, { y: 0.8 }, 64);
  f.cylinder("structure", r * 0.86, r * 0.86, 0.02, SHIP.panelDark, { y: 0.9 }, 64);
  f.ring("glow", r * 0.965, 0.012, SHIP.gold, { y: 0.9 }, TAU, 72);
  f.cylinder("glowSoft", r * 0.5, r * 0.5, 0.004, "#123a52", { y: 0.92 }, 48);
  f.ring("glow", r * 0.52, 0.007, p.accent ?? SHIP.cyan, { y: 0.922 }, TAU, 48);
  // A bearing scale round the rim: a gold mark every quarter.
  for (let k = 0; k < 36; k += 1) {
    const a = (k / 36) * TAU, major = k % 9 === 0;
    f.box(major ? "glow" : "glowSoft", 0.012, 0.004, major ? 0.09 : 0.04, major ? SHIP.gold : SHIP.cyanDeep,
      { x: Math.sin(a) * r * 0.76, z: Math.cos(a) * r * 0.76, y: 0.921, yaw: a });
  }
  f.ring("glowSoft", r * 0.62, 0.01, SHIP.cyan, { y: 0.02 }, TAU, 48);
};

registerPropBuilders({ captainChair, commandSeat, helmConsole, tacticalRail, viewscreen, starChart });
