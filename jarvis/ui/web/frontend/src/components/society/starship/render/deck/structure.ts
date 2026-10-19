/**
 * The deck's architecture as merged geometry: the slab and the outer hull
 * below it, the floors by room, the hull walls with their window band,
 * bulkheads, glass partitions, door frames and the light lines that trace
 * the cut-away top of every wall.
 */
import { BufferAttribute, BufferGeometry, Shape, ShapeGeometry, ExtrudeGeometry, Matrix4, BoxGeometry } from "three";
import type { DeckPlan, FloorFinish, Rect, Room, Vec2, Wall } from "../../plan/types";
import { GeoBatch, type CutLine, type Finish } from "../kit/geo";
import { SHIP } from "../kit/palette";

export const WALL_H = 2.7;
const BASE_H = 0.85;
const WINDOW_LO = 0.95;
const WINDOW_HI = 2.2;

/** Sutherland–Hodgman: clip a polygon to a convex clip polygon (both clockwise or both counter-clockwise). */
export function clipPolygon(subject: readonly Vec2[], clip: readonly Vec2[]): Vec2[] {
  let out = [...subject];
  const area = clip.reduce((s, p, i) => { const q = clip[(i + 1) % clip.length]; return s + (p.x * q.z - q.x * p.z); }, 0);
  const sign = area > 0 ? 1 : -1;
  for (let i = 0; i < clip.length && out.length > 0; i += 1) {
    const a = clip[i], b = clip[(i + 1) % clip.length];
    const inside = (p: Vec2) => sign * ((b.x - a.x) * (p.z - a.z) - (b.z - a.z) * (p.x - a.x)) >= -1e-9;
    const cross = (p: Vec2, q: Vec2): Vec2 => {
      const dx = q.x - p.x, dz = q.z - p.z;
      const ex = b.x - a.x, ez = b.z - a.z;
      const t = (ex * (p.z - a.z) - ez * (p.x - a.x)) / (ez * dx - ex * dz);
      return { x: p.x + dx * t, z: p.z + dz * t };
    };
    const input = out;
    out = [];
    for (let k = 0; k < input.length; k += 1) {
      const cur = input[k], prev = input[(k + input.length - 1) % input.length];
      if (inside(cur)) {
        if (!inside(prev)) out.push(cross(prev, cur));
        out.push(cur);
      } else if (inside(prev)) out.push(cross(prev, cur));
    }
  }
  return out;
}

function rectPoly(r: Rect): Vec2[] {
  return [{ x: r.x0, z: r.z0 }, { x: r.x1, z: r.z0 }, { x: r.x1, z: r.z1 }, { x: r.x0, z: r.z1 }];
}

/** A flat polygon at height y with uvs in world metres. */
function flatPolygon(points: readonly Vec2[], y: number): BufferGeometry {
  const shape = new Shape(points.map((p) => ({ x: p.x, y: -p.z }) as never));
  const g = new ShapeGeometry(shape);
  // Shape lies in xy with y = -z; turn it onto the floor.
  g.rotateX(-Math.PI / 2);
  g.translate(0, y, 0);
  const pos = g.attributes.position;
  const uv = new Float32Array(pos.count * 2);
  for (let i = 0; i < pos.count; i += 1) { uv[i * 2] = pos.getX(i); uv[i * 2 + 1] = pos.getZ(i); }
  g.setAttribute("uv", new BufferAttribute(uv, 2));
  return g;
}

const FLOOR_FINISH: Record<FloorFinish, { finish: Finish; color: string }> = {
  deck: { finish: "deck", color: "#c9ced6" },
  carpet: { finish: "carpet", color: "#d9d4e6" },
  grate: { finish: "grate", color: "#ffffff" },
  ceramic: { finish: "ceramic", color: "#9aa0a8" },
  holo: { finish: "holoFloor", color: "#ffffff" },
  honor: { finish: "metal", color: "#3a3226" },
};

/** How warm or cool the light under each kind of room is (additive, so dark = faint). */
const POOL_TONE: Partial<Record<Room["kind"], string>> = {
  lounge: "#6b5236", mess: "#6b5236", division: "#3a5374", plaza: "#2c5a6e", quarters: "#4e3f78", quartermaster: "#5e4c32",
  corridor: "#33465f", lift: "#5a4a2e", bay: "#36573a", bridge: "#4f4d5e", engineering: "#334f6c", holodeck: "#5a4620", hall: "#5a4a2c",
};

function flatQuad(size: number): BufferGeometry {
  const g = new BufferGeometry();
  const h = size / 2;
  g.setAttribute("position", new BufferAttribute(new Float32Array([-h, 0, -h, -h, 0, h, h, 0, h, -h, 0, -h, h, 0, h, h, 0, -h]), 3));
  g.setAttribute("normal", new BufferAttribute(new Float32Array([0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0]), 3));
  g.setAttribute("uv", new BufferAttribute(new Float32Array([0, 1, 0, 0, 1, 0, 0, 1, 1, 0, 1, 1]), 2));
  return g;
}

function insideConvex(poly: readonly Vec2[], p: Vec2, margin: number): boolean {
  const area = poly.reduce((s, a, i) => { const b = poly[(i + 1) % poly.length]; return s + (a.x * b.z - b.x * a.z); }, 0);
  const sign = area > 0 ? 1 : -1;
  for (let i = 0; i < poly.length; i += 1) {
    const a = poly[i], b = poly[(i + 1) % poly.length];
    const len = Math.hypot(b.x - a.x, b.z - a.z) || 1;
    if ((sign * ((b.x - a.x) * (p.z - a.z) - (b.z - a.z) * (p.x - a.x))) / len < margin) return false;
  }
  return true;
}

/** Offset a convex polygon outwards by `d` (vertex normals averaged). */
export function offsetPolygon(points: readonly Vec2[], d: number): Vec2[] {
  const n = points.length;
  const area = points.reduce((s, p, i) => { const q = points[(i + 1) % n]; return s + (p.x * q.z - q.x * p.z); }, 0);
  // (e.z, -e.x) points out of a polygon wound with positive area.
  const sign = area > 0 ? 1 : -1;
  return points.map((p, i) => {
    const prev = points[(i + n - 1) % n], next = points[(i + 1) % n];
    const e1 = { x: p.x - prev.x, z: p.z - prev.z }, e2 = { x: next.x - p.x, z: next.z - p.z };
    const l1 = Math.hypot(e1.x, e1.z) || 1, l2 = Math.hypot(e2.x, e2.z) || 1;
    const n1 = { x: (e1.z / l1) * sign, z: (-e1.x / l1) * sign }, n2 = { x: (e2.z / l2) * sign, z: (-e2.x / l2) * sign };
    const bx = n1.x + n2.x, bz = n1.z + n2.z;
    const bl = Math.hypot(bx, bz) || 1;
    const cos = (n1.x * bx + n1.z * bz) / bl;
    const k = d / Math.max(0.35, cos);
    return { x: p.x + (bx / bl) * k, z: p.z + (bz / bl) * k };
  });
}

/** A band between two polygon outlines at two heights (the hull's sloping plates). */
function band(top: readonly Vec2[], topY: number, bottom: readonly Vec2[], bottomY: number): BufferGeometry {
  const positions: number[] = [];
  const uvs: number[] = [];
  let run = 0;
  for (let i = 0; i < top.length; i += 1) {
    const j = (i + 1) % top.length;
    const a = top[i], b = top[j], c = bottom[j], d = bottom[i];
    const len = Math.hypot(b.x - a.x, b.z - a.z);
    const quad = [[a, topY, 0], [b, topY, len], [c, bottomY, len], [a, topY, 0], [c, bottomY, len], [d, bottomY, 0]] as const;
    for (const [p, y, u] of quad) { positions.push(p.x, y, p.z); uvs.push((run + u) / 2.4, y / 2.4); }
    run += len;
  }
  const g = new BufferGeometry();
  g.setAttribute("position", new BufferAttribute(new Float32Array(positions), 3));
  g.setAttribute("uv", new BufferAttribute(new Float32Array(uvs), 2));
  g.computeVertexNormals();
  return g;
}

/** A wall-like box from a to b with uvs in metres along its length. */
function wallBox(len: number, h: number, t: number): BufferGeometry {
  const g = new BoxGeometry(len, h, t);
  g.translate(0, h / 2, 0);
  const uv = g.attributes.uv as BufferAttribute;
  for (let i = 0; i < uv.count; i += 1) uv.setXY(i, uv.getX(i) * (len / 1.2), uv.getY(i) * (h / WALL_H));
  return g;
}

function along(batch: GeoBatch, wall: Wall) {
  const dx = wall.b.x - wall.a.x, dz = wall.b.z - wall.a.z;
  const len = Math.hypot(dx, dz);
  const yaw = Math.atan2(dz, dx);
  const at = new Matrix4().makeRotationY(-yaw).setPosition((wall.a.x + wall.b.x) / 2, 0, (wall.a.z + wall.b.z) / 2);
  const cut: CutLine = { ax: wall.a.x, az: wall.a.z, bx: wall.b.x, bz: wall.b.z, kind: wall.kind === "hull" ? 1 : 2 };
  return { frame: batch.frame(at, cut), len };
}

/** The wall line a doorway sits in: its hull edge (same direction as the hull), or a line along the door. */
function doorCut(plan: DeckPlan, door: DeckPlan["doors"][number]): CutLine {
  const hull = plan.hull;
  for (let i = 0; i < hull.length; i += 1) {
    const a = hull[i], b = hull[(i + 1) % hull.length];
    const dx = b.x - a.x, dz = b.z - a.z, len = Math.hypot(dx, dz) || 1;
    const dist = Math.abs((door.at.x - a.x) * dz - (door.at.z - a.z) * dx) / len;
    if (dist < 0.3) return { ax: a.x, az: a.z, bx: b.x, bz: b.z, kind: 1 };
  }
  const half = door.width / 2 + 0.4;
  return door.axis === "x"
    ? { ax: door.at.x - half, az: door.at.z, bx: door.at.x + half, bz: door.at.z, kind: 2 }
    : { ax: door.at.x, az: door.at.z - half, bx: door.at.x, bz: door.at.z + half, kind: 2 };
}

export function buildStructure(plan: DeckPlan): GeoBatch {
  const batch = new GeoBatch();
  const root = batch.frame(new Matrix4());

  // ── slab and outer hull ────────────────────────────────────────────
  const outline = plan.hull;
  const slabShape = new Shape(outline.map((p) => ({ x: p.x, y: -p.z }) as never));
  const slab = new ExtrudeGeometry(slabShape, { depth: 0.5, bevelEnabled: false });
  slab.rotateX(-Math.PI / 2);
  slab.translate(0, -0.5, 0);
  root.geo("structure", slab, SHIP.hullDark);
  const o1 = offsetPolygon(outline, 0.32), o2 = offsetPolygon(outline, 2.6), o3 = offsetPolygon(outline, 1.2), o4 = offsetPolygon(outline, -3.5);
  root.geo("panel", band(o1, 0.08, o2, -1.6), SHIP.hullOuter);
  root.geo("structure", band(o2, -1.6, o3, -4.8), SHIP.hullDark);
  root.geo("structure", band(o3, -4.8, o4, -6.4), SHIP.graphite);
  // A lip between the wall and the sloping plates, and running lights along it.
  root.geo("structure", band(offsetPolygon(outline, 0.25), 0.1, o1, 0.08), SHIP.graphite);
  o2.forEach((p, i) => {
    const q = o2[(i + 1) % o2.length];
    const len = Math.hypot(q.x - p.x, q.z - p.z);
    const n = Math.floor(len / 6);
    for (let k = 1; k < n; k += 1) {
      const t = k / n;
      root.box("glow", 0.22, 0.08, 0.22, i % 2 ? SHIP.cyan : SHIP.lightWarm, { x: p.x + (q.x - p.x) * t, y: -1.62, z: p.z + (q.z - p.z) * t });
    }
  });

  // ── floors ─────────────────────────────────────────────────────────
  root.geo("deck", flatPolygon(outline, 0.0), "#9aa0a9");
  for (const room of plan.rooms) {
    if (room.floor === "deck") continue;
    const poly = clipPolygon(rectPoly(room.rect), outline);
    if (poly.length < 3) continue;
    const f = FLOOR_FINISH[room.floor];
    root.geo(f.finish, flatPolygon(poly, 0.012), f.color);
  }

  // ── light pools under the (cut-away) ceiling fittings ──────────────
  for (const room of plan.rooms) {
    const tone = POOL_TONE[room.kind] ?? "#2a3444";
    const r = room.rect;
    const w = r.x1 - r.x0, d = r.z1 - r.z0;
    const nx = Math.max(1, Math.round(w / 4.4)), nz = Math.max(1, Math.round(d / 4.4));
    for (let i = 0; i < nx; i += 1) for (let k = 0; k < nz; k += 1) {
      const x = r.x0 + (w * (i + 0.5)) / nx, z = r.z0 + (d * (k + 0.5)) / nz;
      if (!insideConvex(outline, { x, z }, 1.6)) continue;
      root.geo("pool", flatQuad(3.6), tone, { x, y: 0.03, z });
    }
  }

  // ── walls ──────────────────────────────────────────────────────────
  const holoRooms = plan.rooms.filter((r) => r.kind === "holodeck");
  for (const wall of plan.walls) {
    const { frame, len } = along(batch, wall);
    if (len < 0.05) continue;
    const t = wall.t;
    const mx = (wall.a.x + wall.b.x) / 2, mz = (wall.a.z + wall.b.z) / 2;
    const holo = holoRooms.some((r) => mx >= r.rect.x0 - 0.5 && mx <= r.rect.x1 + 0.5 && mz >= r.rect.z0 - 0.5 && mz <= r.rect.z1 + 0.5);
    if (holo && (wall.kind === "hull" || wall.kind === "bulkhead")) {
      // The holodeck's chamber: black walls with the floor's gold grid running up them.
      frame.geo("structure", wallBox(len, WALL_H, t), "#08090b");
      for (let k = 1; k < 3; k += 1) frame.box("glowSoft", len, 0.02, t + 0.02, "#7a5f22", { y: k * 0.9 });
      const n = Math.max(1, Math.round(len));
      for (let k = 0; k <= n; k += 1) frame.box("glowSoft", 0.02, WALL_H, t + 0.02, "#7a5f22", { x: -len / 2 + (len * k) / n });
      frame.box("structure", len, 0.1, t + 0.06, SHIP.charcoal, { y: WALL_H });
      continue;
    }
    if (wall.kind === "hull" || wall.kind === "bulkhead") {
      const hull = wall.kind === "hull";
      // A dark base band, ceramic panels above it, and the cap.
      frame.geo("structure", wallBox(len, BASE_H, t + 0.03), SHIP.panelDark);
      if (hull && wall.windows && len > 2) {
        frame.geo("panel", wallBox(len, WINDOW_LO - BASE_H, t), SHIP.panelCool, { y: BASE_H });
        frame.geo("panel", wallBox(len, WALL_H - WINDOW_HI, t), SHIP.panelCool, { y: WINDOW_HI });
        frame.box("structure", len, 0.07, t + 0.12, SHIP.graphite, { y: WINDOW_LO - 0.07 });
        frame.box("structure", len, 0.06, t + 0.08, SHIP.graphite, { y: WINDOW_HI });
        frame.box("glass", len, WINDOW_HI - WINDOW_LO, 0.03, "#9fd6ff", { y: WINDOW_LO });
        frame.box("glowSoft", len, 0.02, 0.05, SHIP.lightCool, { y: WINDOW_LO, z: t / 2 - 0.04 });
      } else {
        frame.geo("panel", wallBox(len, WALL_H - BASE_H, t), SHIP.panelCool, { y: BASE_H });
      }
      frame.box("structure", len, 0.12, t + 0.08, SHIP.graphite, { y: WALL_H - 0.02 });
      frame.box("glowSoft", len, 0.018, t + 0.1, SHIP.lightCool, { y: WALL_H + 0.1 });
      // Ribs every 2.4 m: graphite pilasters with a light slit on both faces.
      const ribs = Math.max(1, Math.round(len / 2.4));
      for (let k = 0; k <= ribs; k += 1) {
        const x = -len / 2 + (len * k) / ribs;
        frame.box("structure", 0.24, WALL_H + 0.06, t + 0.14, SHIP.graphite, { x });
        for (const s of hull ? [1] : [-1, 1]) frame.box("glowSoft", 0.035, 1.25, 0.02, SHIP.cyan, { x, y: 1.0, z: s * (t / 2 + 0.075) });
      }
      // A light line in the floor along each inner face.
      for (const s of hull ? [1] : [-1, 1]) frame.box("glowSoft", len, 0.006, 0.035, s < 0 ? SHIP.lightCool : SHIP.lightWarm, { y: 0.004, z: s * (t / 2 + 0.28) });
    } else if (wall.kind === "glass") {
      const n = Math.max(1, Math.round(len / 1.6));
      for (let k = 0; k <= n; k += 1) frame.box("structure", 0.08, WALL_H, 0.14, SHIP.graphite, { x: -len / 2 + (len * k) / n });
      frame.box("structure", len, 0.12, 0.16, SHIP.charcoal, {});
      frame.box("structure", len, 0.1, 0.16, SHIP.graphite, { y: WALL_H - 0.1 });
      frame.box("glass", len, WALL_H - 0.22, 0.02, "#bfe4ff", { y: 0.12 });
      frame.box("glowSoft", len, 0.12, 0.03, "#7fb6d9", { y: 1.35 });
      frame.box("glow", len, 0.02, 0.05, SHIP.cyan, { y: WALL_H });
    } else {
      // A rail: posts and a lit handrail.
      const n = Math.max(1, Math.round(len / 1.4));
      for (let k = 0; k <= n; k += 1) frame.box("metal", 0.05, 1.0, 0.05, SHIP.steelLight, { x: -len / 2 + (len * k) / n });
      frame.box("metal", len, 0.06, 0.08, SHIP.steelLight, { y: 1.0 });
      frame.box("glow", len, 0.015, 0.03, SHIP.gold, { y: 1.06 });
    }
  }

  // ── door frames ────────────────────────────────────────────────────
  for (const door of plan.doors) {
    const yaw = door.axis === "x" ? 0 : Math.PI / 2;
    const f = batch.frame(new Matrix4().makeRotationY(yaw).setPosition(door.at.x, 0, door.at.z), doorCut(plan, door));
    const half = door.width / 2;
    for (const s of [-1, 1]) {
      f.box("structure", 0.16, WALL_H, 0.42, SHIP.graphite, { x: s * (half + 0.08) });
      f.box("glow", 0.03, 2.2, 0.44, door.slides ? SHIP.cyan : SHIP.lightWarm, { x: s * (half + 0.0), y: 0.1 });
    }
    f.box("structure", door.width + 0.32, WALL_H - 2.35, 0.46, SHIP.graphite, { y: 2.35 });
    f.box("glow", door.width, 0.03, 0.44, door.slides ? SHIP.cyan : SHIP.lightWarm, { y: 2.33 });
    // Threshold plate.
    f.box("metal", door.width, 0.015, 0.5, SHIP.steel, { y: 0.0 });
  }
  return batch;
}
