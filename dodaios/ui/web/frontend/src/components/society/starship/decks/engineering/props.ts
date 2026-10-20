/**
 * Engineering's machinery, built into the deck's merged batch: the bay
 * workstations, the master systems display, the reactor's housing and cage,
 * and the conduits (floor feeds and wall risers). Same conventions as the
 * shared builders: centred on the footprint, the front (where a person uses
 * it) towards +z, foot on the floor. The reactor's plasma and the screens
 * are drawn live by the deck's scene; `glow` is kept for real light sources.
 */
import { CONSOLE_SCREEN, registerPropBuilders, type PropBuilder } from "../../render/deck/props";
import { SHIP } from "../../render/kit/palette";

/** Where the plasma column runs inside the reactor (its own frame). */
export const PLASMA = { y0: 1.3, y1: 4.55, r: 0.62, sleeve: 0.92 } as const;

/** A bay workstation: a heavy pedestal, a sloped desk, the live screen and an equipment spine behind it. */
const bayConsole: PropBuilder = (f, p) => {
  const accent = p.accent ?? SHIP.cyan;
  f.chamfer("structure", p.w - 0.05, 0.1, 0.66, 0.1, SHIP.charcoal, { z: -0.03 });
  f.chamfer("structure", 0.84, 0.64, 0.44, 0.08, SHIP.graphite, { y: 0.1, z: -0.1 });
  // Vent slats on the pedestal's front and the kick light under them.
  for (let k = 0; k < 4; k += 1) f.box("structure", 0.56, 0.025, 0.02, SHIP.panelDark, { y: 0.26 + k * 0.08, z: 0.13 });
  f.box("glow", 0.6, 0.012, 0.012, accent, { y: 0.12, z: 0.13 });
  // Desk: ceramic rim round a dark sloped work surface.
  f.rounded("panel", p.w, 0.06, 0.6, 0.07, SHIP.panelCool, { y: 0.74, z: 0.04 });
  f.rounded("structure", p.w - 0.1, 0.02, 0.48, 0.05, SHIP.panelDark, { y: 0.8, z: 0.05, pitch: 0.06 });
  f.box("glowSoft", 0.5, 0.006, 0.15, "#24607f", { y: 0.825, z: 0.17 });
  for (const s of [-1, 1]) f.box("glowSoft", 0.12, 0.006, 0.1, s < 0 ? "#3a5a2c" : "#5c4a22", { x: s * 0.4, y: 0.825, z: 0.17 });
  f.box("glow", p.w - 0.12, 0.012, 0.012, accent, { y: 0.75, z: 0.34 });
  // Screen post and bezel (the face is drawn live in the same place as every console's).
  f.box("structure", 0.1, 0.34, 0.07, SHIP.graphite, { y: 0.8, z: CONSOLE_SCREEN.z - 0.07 });
  const s = f.child({ y: CONSOLE_SCREEN.y, z: CONSOLE_SCREEN.z, pitch: CONSOLE_SCREEN.tilt });
  s.box("structure", CONSOLE_SCREEN.w + 0.07, CONSOLE_SCREEN.h + 0.07, 0.04, SHIP.charcoal, { y: -(CONSOLE_SCREEN.h + 0.07) / 2, z: -0.028 });
  s.box("structure", CONSOLE_SCREEN.w + 0.07, 0.05, 0.08, SHIP.graphite, { y: (CONSOLE_SCREEN.h + 0.07) / 2 - 0.05, z: -0.05 });
  s.box("glow", CONSOLE_SCREEN.w + 0.06, 0.01, 0.045, accent, { y: -(CONSOLE_SCREEN.h + 0.07) / 2 - 0.01, z: -0.028 });
  // Equipment spine behind the screen: a dark box with module seams and two pilot lights.
  f.box("structure", p.w - 0.25, 0.5, 0.14, SHIP.graphite, { y: 0.8, z: -0.29 });
  for (let k = 0; k < 3; k += 1) f.box("structure", 0.012, 0.44, 0.15, SHIP.charcoal, { x: -0.3 + k * 0.3, y: 0.83, z: -0.29 });
  f.box("glow", 0.04, 0.04, 0.01, SHIP.cyan, { x: -(p.w - 0.25) / 2 + 0.1, y: 1.18, z: -0.36 });
  f.box("glow", 0.04, 0.04, 0.01, accent, { x: -(p.w - 0.25) / 2 + 0.18, y: 1.18, z: -0.36 });
  // Side cheeks.
  for (const side of [-1, 1]) f.chamfer("panel", 0.09, 0.26, 0.46, 0.03, SHIP.panel, { x: side * (p.w / 2 - 0.045), y: 0.77, z: 0.02 });
};

/** The master systems display: a long sloped table on two pedestals, framed by two uprights for the hologram above it. */
const systemsTable: PropBuilder = (f, p) => {
  const accent = p.accent ?? SHIP.gold;
  f.chamfer("structure", p.w - 0.2, 0.1, p.d - 0.2, 0.14, SHIP.charcoal, {});
  for (const s of [-1, 1]) {
    f.chamfer("structure", 0.7, 0.72, p.d - 0.5, 0.1, SHIP.graphite, { x: s * (p.w / 2 - 0.65), y: 0.1 });
    f.box("glow", 0.5, 0.012, 0.012, SHIP.cyan, { x: s * (p.w / 2 - 0.65), y: 0.14, z: (p.d - 0.5) / 2 + 0.005 });
  }
  f.box("structure", p.w - 1.6, 0.3, 0.3, SHIP.panelDark, { y: 0.5 });
  const top = f.child({ y: 0.84, pitch: 0.1 });
  top.rounded("panel", p.w, 0.08, p.d, 0.12, SHIP.panelCool, {});
  top.rounded("structure", p.w - 0.18, 0.02, p.d - 0.2, 0.08, SHIP.panelDark, { y: 0.08 });
  top.box("glowSoft", p.w - 0.36, 0.006, p.d - 0.42, "#12405c", { y: 0.1 });
  // A grid of status cells across the display.
  for (let k = 0; k < 8; k += 1) top.box("glowSoft", 0.24, 0.006, 0.08, k % 3 === 0 ? "#2f7fa8" : "#1c5574", { x: -1.05 + k * 0.3, y: 0.107, z: p.d / 2 - 0.36 });
  top.box("glow", p.w - 0.1, 0.014, 0.014, accent, { y: 0.02, z: p.d / 2 + 0.005 });
  // Uprights at the back with an emitter bar between them.
  for (const s of [-1, 1]) f.box("metal", 0.08, 1.1, 0.08, SHIP.steelLight, { x: s * (p.w / 2 - 0.12), y: 0.9, z: -p.d / 2 + 0.12 });
  f.box("structure", p.w - 0.2, 0.08, 0.12, SHIP.graphite, { y: 1.98, z: -p.d / 2 + 0.12 });
  f.box("glow", p.w - 0.4, 0.015, 0.03, SHIP.cyan, { y: 1.97, z: -p.d / 2 + 0.19 });
};

/** The reactor's fixed parts: plinth, housing, the glass sleeve, the cage with its constrictor coils, and the cap. */
const reactor: PropBuilder = (f, p) => {
  const r = p.w / 2;
  f.cylinder("structure", r, r + 0.05, 0.14, SHIP.charcoal, {}, 48);
  f.cylinder("structure", r - 0.55, r - 0.3, 0.95, SHIP.graphite, { y: 0.14 }, 12);
  // Housing panels: twelve inset faces with a seam light under each.
  for (let k = 0; k < 12; k += 1) {
    const a = (k / 12) * Math.PI * 2 + Math.PI / 12;
    f.box("panel", 0.62, 0.5, 0.05, SHIP.panelCool, { x: Math.sin(a) * (r - 0.42), z: Math.cos(a) * (r - 0.42), y: 0.36, yaw: a, pitch: -0.12 });
    if (k % 3 === 0) f.box("glowSoft", 0.4, 0.02, 0.02, SHIP.cyan, { x: Math.sin(a) * (r - 0.4), z: Math.cos(a) * (r - 0.4), y: 0.24, yaw: a });
  }
  // Feed pipes from the housing down into the deck.
  for (let k = 0; k < 8; k += 1) {
    const a = (k / 8) * Math.PI * 2;
    f.cylinder("metal", 0.08, 0.1, 0.62, SHIP.steel, { x: Math.sin(a) * (r - 0.18), z: Math.cos(a) * (r - 0.18), y: 0.14 }, 10);
    f.cylinder("structure", 0.13, 0.13, 0.06, SHIP.graphite, { x: Math.sin(a) * (r - 0.18), z: Math.cos(a) * (r - 0.18), y: 0.72 }, 10);
  }
  f.cylinder("panel", 1.55, 1.75, 0.2, SHIP.panel, { y: 1.09 }, 36);
  f.ring("glow", 1.58, 0.022, SHIP.cyan, { y: 1.3 }, Math.PI * 2, 64);
  // The sleeve the plasma runs in.
  f.cylinder("glass", PLASMA.sleeve, PLASMA.sleeve, PLASMA.y1 - PLASMA.y0, "#bfe8ff", { y: PLASMA.y0 }, 36, true);
  // Cage: six struts and the constrictor coils round the sleeve.
  for (let k = 0; k < 6; k += 1) {
    const a = (k / 6) * Math.PI * 2;
    f.box("metal", 0.09, PLASMA.y1 - PLASMA.y0, 0.16, SHIP.steelLight, { x: Math.sin(a) * 1.12, z: Math.cos(a) * 1.12, y: PLASMA.y0, yaw: a });
  }
  for (const y of [1.95, 2.85, 3.75]) {
    f.ring("structure", 1.06, 0.1, SHIP.graphite, { y }, Math.PI * 2, 40);
    f.ring("metal", 1.06, 0.035, SHIP.steelLight, { y: y + 0.11 }, Math.PI * 2, 40);
  }
  // Cap with its own collar and a ring of status lights.
  f.cylinder("panel", 1.7, 1.5, 0.18, SHIP.panel, { y: PLASMA.y1 }, 36);
  f.cylinder("structure", 1.2, 1.55, 0.42, SHIP.graphite, { y: PLASMA.y1 + 0.18 }, 12);
  f.ring("glow", 1.52, 0.02, SHIP.cyan, { y: PLASMA.y1 + 0.2 }, Math.PI * 2, 64);
  f.cylinder("metal", 0.5, 0.7, 0.05, SHIP.steel, { y: PLASMA.y1 + 0.6 }, 24);
};

/** A floor feed (`ref` "floor:…"): a ribbed duct under a plate. Otherwise a wall riser: a pipe bundle with brackets and a valve. */
const conduit: PropBuilder = (f, p) => {
  const accent = p.accent ?? SHIP.cyan;
  if (p.ref?.startsWith("floor")) {
    f.rounded("structure", p.w, 0.03, p.d, 0.08, SHIP.charcoal, {});
    f.box("metal", p.w - 0.12, 0.012, p.d - 0.12, SHIP.steel, { y: 0.03 });
    const n = Math.max(2, Math.floor(p.d / 0.6));
    for (let k = 0; k <= n; k += 1) f.box("structure", p.w - 0.06, 0.02, 0.05, SHIP.graphite, { y: 0.03, z: -p.d / 2 + 0.06 + ((p.d - 0.12) * k) / n });
    f.box("glowSoft", 0.05, 0.006, p.d - 0.2, accent, { y: 0.045 });
    return;
  }
  const h = p.h;
  f.chamfer("structure", p.w, 0.14, p.d, 0.08, SHIP.charcoal, {});
  f.box("structure", p.w, h - 0.1, 0.08, SHIP.graphite, { z: -p.d / 2 + 0.04, y: 0.1 });
  const xs = [-p.w / 2 + 0.2, 0, p.w / 2 - 0.2];
  xs.forEach((x, k) => f.cylinder("metal", k === 1 ? 0.11 : 0.075, k === 1 ? 0.11 : 0.075, h - 0.16, k === 1 ? SHIP.steelLight : SHIP.steel, { x, y: 0.14, z: 0.02 }, 14));
  for (const y of [0.55, 1.45, 2.3]) f.box("structure", p.w - 0.04, 0.07, p.d - 0.1, SHIP.panelDark, { y, z: 0.0 });
  // A lit band round the main pipe, and a hand valve on its front.
  f.ring("glow", 0.12, 0.012, SHIP.cyan, { y: 1.0, z: 0.02 }, Math.PI * 2, 20);
  f.ring("metal", 0.12, 0.018, SHIP.steelLight, { y: 1.2, z: 0.2, pitch: Math.PI / 2 }, Math.PI * 2, 20);
  f.box("metal", 0.03, 0.03, 0.1, SHIP.steel, { y: 1.185, z: 0.13 });
  f.box("glowSoft", 0.06, 0.12, 0.01, accent, { x: p.w / 2 - 0.08, y: 1.7, z: p.d / 2 - 0.02 });
};

registerPropBuilders({ bayConsole, systemsTable, reactor, conduit });
