/**
 * Detail that makes a room read as part of a working ship without changing
 * where anyone can walk: wall consoles, conduit runs and service hatches on
 * the inner faces of the walls (inside the walls' own clearance), and inlays
 * in the floor (a lit runner down the corridors, an emblem in the turbolift
 * lobby, rings round the divisions' horseshoes, lines fanning out from the
 * transporter). Deterministic per wall, so a rebuilt plan dresses the same.
 */
import { Matrix4 } from "three";
import { hash } from "../../plan/builder";
import type { DeckPlan, Room, Wall } from "../../plan/types";
import { annulus, type GeoBatch, type CutLine } from "../kit/geo";
import { SHIP } from "../kit/palette";

const RIB = 2.4;

function wallFaces(wall: Wall): number[] {
  if (wall.kind === "hull") return [1];
  if (wall.kind === "bulkhead") return [-1, 1];
  return [];
}

/** Wall consoles, conduits and hatches between the ribs. */
function dressWalls(plan: DeckPlan, batch: GeoBatch): void {
  const bare = plan.rooms.filter((r) => r.kind === "holodeck");
  for (const wall of plan.walls) {
    const faces = wallFaces(wall);
    if (faces.length === 0) continue;
    const mx = (wall.a.x + wall.b.x) / 2, mz = (wall.a.z + wall.b.z) / 2;
    if (bare.some((r) => mx >= r.rect.x0 - 0.5 && mx <= r.rect.x1 + 0.5 && mz >= r.rect.z0 - 0.5 && mz <= r.rect.z1 + 0.5)) continue;
    const dx = wall.b.x - wall.a.x, dz = wall.b.z - wall.a.z;
    const len = Math.hypot(dx, dz);
    if (len < RIB * 1.5) continue;
    const yaw = Math.atan2(dz, dx);
    const cut: CutLine = { ax: wall.a.x, az: wall.a.z, bx: wall.b.x, bz: wall.b.z, kind: wall.kind === "hull" ? 1 : 2 };
    const f = batch.frame(new Matrix4().makeRotationY(-yaw).setPosition((wall.a.x + wall.b.x) / 2, 0, (wall.a.z + wall.b.z) / 2), cut);
    const bays = Math.max(1, Math.round(len / RIB));
    const pitch = len / bays;
    for (const side of faces) {
      // The window band of a hull wall leaves room only for low fittings.
      const windowed = wall.kind === "hull" && wall.windows;
      const z = side * (wall.t / 2 + 0.05);
      for (let k = 0; k < bays; k += 1) {
        const x = -len / 2 + pitch * (k + 0.5);
        const pick = hash(`${wall.id}:${side}:${k}`) % 7;
        if (pick === 0 && !windowed) {
          // A wall console: a dark panel with a lit screen and a row of keys.
          f.box("structure", 1.1, 0.75, 0.08, SHIP.panelDark, { x, y: 1.15, z });
          f.box("screen", 0.9, 0.45, 0.01, "#16405a", { x, y: 1.4, z: z + side * 0.045 });
          f.box("glow", 0.9, 0.012, 0.012, SHIP.cyan, { x, y: 1.37, z: z + side * 0.05 });
          for (let b = 0; b < 4; b += 1) f.box("glowSoft", 0.08, 0.04, 0.012, b === 1 ? SHIP.gold : "#3f7fa0", { x: x - 0.3 + b * 0.2, y: 1.23, z: z + side * 0.05 });
        } else if (pick === 1 || pick === 2) {
          // A service hatch in the base band, with a gold handle.
          f.box("structure", 0.9, 0.62, 0.04, SHIP.graphite, { x, y: 0.12, z });
          f.box("metal", 0.3, 0.035, 0.03, SHIP.gold, { x, y: 0.62, z: z + side * 0.03 });
        } else if (pick === 3 && !windowed) {
          // A status strip: three small lights stacked beside a vent.
          f.box("structure", 0.5, 0.5, 0.05, SHIP.graphite, { x, y: 1.6, z });
          for (let r = 0; r < 4; r += 1) f.box("structure", 0.42, 0.03, 0.02, SHIP.charcoal, { x, y: 1.66 + r * 0.09, z: z + side * 0.03 });
          for (let r = 0; r < 3; r += 1) f.box("glowSoft", 0.04, 0.04, 0.012, r === 0 ? "#3fd27f" : "#5fd4ff", { x: x + 0.34, y: 1.65 + r * 0.12, z: z + side * 0.03 });
        }
      }
      // A conduit run high on every inner wall, in two pipes.
      if (!windowed) {
        f.box("metal", len - 0.3, 0.07, 0.07, SHIP.steel, { y: 2.32, z: z + side * 0.02 });
        f.box("metal", len - 0.3, 0.05, 0.05, SHIP.steelLight, { y: 2.44, z: z + side * 0.015 });
      }
    }
  }
}

function dressFloor(plan: DeckPlan, batch: GeoBatch): void {
  const root = batch.frame(new Matrix4());
  for (const room of plan.rooms) {
    if (room.kind === "corridor") runner(root, room);
    if (room.kind === "lift") emblem(root, room);
  }
  // The horseshoe rings belong to the operations deck's divisions (engineering's bays draw their own).
  for (const d of plan.divisions) {
    if (plan.rooms.find((r) => r.id === d.room)?.kind !== "division") continue;
    const consoles = plan.props.filter((p) => p.kind === "console" && plan.places.some((pl) => pl.division === d.room && Math.hypot(pl.x - p.x, pl.z - p.z) < 1.2));
    const r = consoles.length ? Math.max(...consoles.map((p) => Math.hypot(p.x - d.centre.x, p.z - d.centre.z))) + 0.75 : 3.6;
    root.geo("structure", annulus(r - 0.06, r, 0, Math.PI * 2, 96), SHIP.charcoal, { x: d.centre.x, y: 0.008, z: d.centre.z });
    root.geo("glowSoft", annulus(r - 0.035, r - 0.015, 0, Math.PI * 2, 96), d.colour, { x: d.centre.x, y: 0.01, z: d.centre.z });
    root.geo("structure", annulus(0, r - 0.08, 0, Math.PI * 2, 64), "#1b1f25", { x: d.centre.x, y: 0.005, z: d.centre.z });
  }
  const pad = plan.props.find((p) => p.kind === "transporter");
  if (pad) {
    root.geo("glowSoft", annulus(2.6, 2.64, 0, Math.PI * 2, 96), SHIP.cyan, { x: pad.x, y: 0.01, z: pad.z });
    for (let k = 0; k < 12; k += 1) {
      const a = (k / 12) * Math.PI * 2;
      root.box("glowSoft", 0.025, 0.004, 2.2, k % 3 === 0 ? SHIP.gold : "#2a6c8f", { x: pad.x + Math.sin(a) * 3.85, y: 0.006, z: pad.z + Math.cos(a) * 3.85, yaw: a });
    }
  }
}

function runner(root: ReturnType<GeoBatch["frame"]>, room: Room): void {
  const r = room.rect;
  const cx = (r.x0 + r.x1) / 2, w = r.x1 - r.x0, d = r.z1 - r.z0;
  const along = d >= w;
  const length = along ? d : w;
  root.box("structure", along ? 1.3 : length, 0.006, along ? length : 1.3, "#15181d", { x: along ? cx : (r.x0 + r.x1) / 2, y: 0.004, z: (r.z0 + r.z1) / 2 });
  for (const s of [-1, 1]) root.box("glowSoft", along ? 0.02 : length, 0.006, along ? length : 0.02, "#2c6f93", { x: cx + (along ? s * 0.66 : 0), y: 0.007, z: (r.z0 + r.z1) / 2 + (along ? 0 : s * 0.66) });
  const n = Math.floor(length / 1.8);
  for (let k = 0; k < n; k += 1) {
    const t = -length / 2 + (k + 0.5) * (length / n);
    root.box("glow", along ? 0.3 : 0.06, 0.006, along ? 0.06 : 0.3, "#9fdcff", { x: along ? cx : cx + t, y: 0.008, z: (r.z0 + r.z1) / 2 + (along ? t : 0) });
  }
}

function emblem(root: ReturnType<GeoBatch["frame"]>, room: Room): void {
  const cx = (room.rect.x0 + room.rect.x1) / 2, cz = (room.rect.z0 + room.rect.z1) / 2 - 0.6;
  root.geo("structure", annulus(0, 3.2, 0, Math.PI * 2, 96), "#171a20", { x: cx, y: 0.005, z: cz });
  root.geo("metal", annulus(3.05, 3.2, 0, Math.PI * 2, 96), "#8a7550", { x: cx, y: 0.007, z: cz });
  root.geo("glowSoft", annulus(2.2, 2.24, 0, Math.PI * 2, 96), SHIP.gold, { x: cx, y: 0.008, z: cz });
  for (let k = 0; k < 8; k += 1) {
    const a = (k / 8) * Math.PI * 2;
    root.box("metal", 0.04, 0.004, 0.8, "#8a7550", { x: cx + Math.sin(a) * 2.65, y: 0.008, z: cz + Math.cos(a) * 2.65, yaw: a });
  }
  root.geo("metal", annulus(0.5, 0.62, 0, Math.PI * 2, 48), "#b89a5e", { x: cx, y: 0.008, z: cz });
}

export function buildDressing(plan: DeckPlan, batch: GeoBatch): void {
  dressWalls(plan, batch);
  dressFloor(plan, batch);
}
