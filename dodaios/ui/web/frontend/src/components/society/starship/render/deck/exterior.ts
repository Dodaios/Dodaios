/**
 * The ship around the deck: what the camera sees past the hull walls. Two
 * engine nacelles on swept pylons, the main engines at the stern, ribbed
 * plating and running lights on the sloping hull, a sensor array at the bow.
 * It frames every deck the same way, so a deck reads as a slice of one ship.
 */
import { CylinderGeometry, Matrix4, Quaternion, Vector3 } from "three";
import type { DeckPlan } from "../../plan/types";
import type { GeoBatch } from "../kit/geo";
import { SHIP } from "../kit/palette";

export function buildExterior(plan: DeckPlan, batch: GeoBatch): void {
  const { x0, x1, z0, z1 } = plan.bounds;
  const half = (x1 - x0) / 2, cx = (x0 + x1) / 2, len = z1 - z0;
  const root = batch.frame(new Matrix4());

  // ── nacelles ───────────────────────────────────────────────────────
  const nz0 = z0 + len * 0.32, nz1 = z1 + 8;
  const nlen = nz1 - nz0, nr = 2.3;
  for (const side of [-1, 1]) {
    const nx = cx + side * (half + 8.5), ny = -4.2;
    const along = (r0: number, r1: number, l: number, at: number, finish: "structure" | "panel" | "metal" | "glow" | "glowSoft", colour: string, seg = 28) => {
      const g = new CylinderGeometry(r0, r1, l, seg, 1);
      g.applyMatrix4(new Matrix4().compose(new Vector3(nx, ny, at), new Quaternion().setFromAxisAngle(new Vector3(1, 0, 0), Math.PI / 2), new Vector3(1, 1, 1)));
      root.geo(finish, g, colour);
    };
    along(nr, nr, nlen, nz0 + nlen / 2, "panel", SHIP.hullOuter);
    along(nr * 1.04, nr * 1.04, 1.2, nz0 + 3, "structure", SHIP.graphite);
    along(nr * 1.04, nr * 1.04, 1.2, nz1 - 6, "structure", SHIP.graphite);
    // The intake at the front glows cyan, the exhaust at the back gold.
    along(nr * 0.7, nr, 2.6, nz0 - 1.2, "structure", SHIP.charcoal);
    along(nr * 0.62, nr * 0.62, 0.4, nz0 - 2.5, "glow", "#7fd8ff");
    along(nr * 0.9, nr * 0.8, 0.5, nz1 + 0.2, "glow", "#ffb54a");
    // Lit coil strips along the top and the inner flank.
    root.box("glow", 0.22, 0.12, nlen - 10, "#3fa9ff", { x: nx, y: ny + nr - 0.02, z: nz0 + nlen / 2 });
    root.box("glowSoft", 0.12, 0.12, nlen - 12, "#3fa9ff", { x: nx - side * (nr - 0.05), y: ny, z: nz0 + nlen / 2 });
    // Swept pylons back to the hull.
    for (const pz of [nz0 + nlen * 0.35, nz0 + nlen * 0.72]) {
      const px = cx + side * (half + 3.4);
      root.box("structure", 9, 0.7, 3.2, SHIP.hullDark, { x: px + side * 0.6, y: ny + 0.6, z: pz, roll: side * 0.22 });
      root.box("glowSoft", 8, 0.05, 0.08, SHIP.lightWarm, { x: px + side * 0.6, y: ny + 1.32, z: pz - 1.62, roll: side * 0.22 });
    }
  }

  // ── main engines at the stern ──────────────────────────────────────
  for (const ex of [-half * 0.45, 0, half * 0.45]) {
    const r = ex === 0 ? 2.6 : 2.0;
    const g = new CylinderGeometry(r, r * 1.15, 3, 32, 1);
    g.applyMatrix4(new Matrix4().compose(new Vector3(cx + ex, -3.6, z1 + 1.8), new Quaternion().setFromAxisAngle(new Vector3(1, 0, 0), Math.PI / 2), new Vector3(1, 1, 1)));
    root.geo("structure", g, SHIP.graphite);
    const glow = new CylinderGeometry(r * 0.82, r * 0.82, 0.3, 32, 1);
    glow.applyMatrix4(new Matrix4().compose(new Vector3(cx + ex, -3.6, z1 + 3.4), new Quaternion().setFromAxisAngle(new Vector3(1, 0, 0), Math.PI / 2), new Vector3(1, 1, 1)));
    root.geo("glow", glow, "#ffc46b");
  }
  root.box("structure", half * 1.6, 2.4, 3.4, SHIP.hullDark, { x: cx, y: -5.2, z: z1 + 0.6 });

  // ── bow sensor array ───────────────────────────────────────────────
  root.box("structure", 9, 1.2, 3, SHIP.hullDark, { x: cx, y: -3.4, z: z0 - 1.6 });
  root.box("glow", 7.4, 0.1, 0.1, "#7fd8ff", { x: cx, y: -2.3, z: z0 - 3.1 });

  // ── greebles on the sloping plates ─────────────────────────────────
  for (const side of [-1, 1]) {
    for (let z = z0 + 10; z < z1 - 4; z += 4.8) {
      const w = 1.2 + ((z * 7) % 3) * 0.4;
      root.box("structure", 0.5, 0.35, w, SHIP.graphite, { x: cx + side * (half + 1.6), y: -0.9, z, roll: side * -0.55 });
    }
  }
}
