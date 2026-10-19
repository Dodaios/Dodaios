/**
 * Static geometry is collected part by part and merged per finish, so a whole
 * deck's walls and furniture cost a handful of draw calls. Every part carries
 * its colour in its vertices; a finish (material) is shared by everything
 * made of it.
 */
import {
  BoxGeometry, BufferAttribute, BufferGeometry, Color, CylinderGeometry, ExtrudeGeometry, Matrix4, Quaternion,
  Shape, SphereGeometry, TorusGeometry, Vector3, type ColorRepresentation,
} from "three";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";

export type Finish =
  | "panel" | "structure" | "metal" | "deck" | "carpet" | "grate" | "ceramic" | "glass" | "glow" | "glowSoft" | "screen" | "fabric" | "holoFloor"
  /** A soft pool of light on the floor under a ceiling fitting (additive, radial). */
  | "pool";

const tmpColor = new Color();

/**
 * A wall line a part belongs to, for the cutaway (render/kit/cutaway.ts):
 * `kind` 1 = the hull (drops while the camera is outside it), 2 = an inner
 * wall (drops while it stands between the camera and the captain).
 */
export interface CutLine { ax: number; az: number; bx: number; bz: number; kind: 1 | 2 }

/** Bake a colour attribute into a non-indexed copy of `geo`. */
function prepared(geo: BufferGeometry, color: ColorRepresentation, cut?: CutLine): BufferGeometry {
  const g = geo.index ? geo.toNonIndexed() : geo.clone();
  geo.dispose();
  for (const name of Object.keys(g.attributes)) if (name !== "position" && name !== "normal" && name !== "uv") g.deleteAttribute(name);
  if (!g.attributes.uv) g.setAttribute("uv", new BufferAttribute(new Float32Array((g.attributes.position.count) * 2), 2));
  const n = g.attributes.position.count;
  const colors = new Float32Array(n * 3);
  tmpColor.set(color).convertSRGBToLinear();
  for (let i = 0; i < n; i += 1) { colors[i * 3] = tmpColor.r; colors[i * 3 + 1] = tmpColor.g; colors[i * 3 + 2] = tmpColor.b; }
  g.setAttribute("color", new BufferAttribute(colors, 3));
  // Every part carries the cutaway attributes (zero = never cut), so all of a finish merge together.
  const ab = new Float32Array(n * 4), kind = new Float32Array(n);
  if (cut) for (let i = 0; i < n; i += 1) { ab[i * 4] = cut.ax; ab[i * 4 + 1] = cut.az; ab[i * 4 + 2] = cut.bx; ab[i * 4 + 3] = cut.bz; kind[i] = cut.kind; }
  g.setAttribute("cutAB", new BufferAttribute(ab, 4));
  g.setAttribute("cutKind", new BufferAttribute(kind, 1));
  g.clearGroups();
  return g;
}

export interface Placement {
  x?: number; y?: number; z?: number;
  yaw?: number; pitch?: number; roll?: number;
}

const m4 = new Matrix4();
const q = new Quaternion();

/** Yaw about +y, then pitch about the turned x, then roll about the turned z. */
export function matrixOf(p: Placement, scale?: Vector3): Matrix4 {
  q.setFromAxisAngle(new Vector3(0, 1, 0), p.yaw ?? 0);
  if (p.pitch) q.multiply(new Quaternion().setFromAxisAngle(new Vector3(1, 0, 0), p.pitch));
  if (p.roll) q.multiply(new Quaternion().setFromAxisAngle(new Vector3(0, 0, 1), p.roll));
  return m4.clone().compose(new Vector3(p.x ?? 0, p.y ?? 0, p.z ?? 0), q, scale ?? new Vector3(1, 1, 1));
}

/**
 * A batch of parts, merged per finish. `frame` is the placement every part
 * added through `child()` is relative to.
 */
export class GeoBatch {
  private readonly parts = new Map<Finish, BufferGeometry[]>();
  private readonly castShadow = new Map<Finish, boolean>();

  add(finish: Finish, geo: BufferGeometry, color: ColorRepresentation, at: Matrix4, cut?: CutLine): this {
    const g = prepared(geo, color, cut);
    g.applyMatrix4(at);
    const list = this.parts.get(finish) ?? [];
    list.push(g);
    this.parts.set(finish, list);
    return this;
  }

  /** A frame to place parts in: `frame.box(...)` lands relative to `at`; `cut` ties them to a wall line. */
  frame(at: Matrix4, cut?: CutLine): Frame { return new Frame(this, at, cut); }

  merged(): { finish: Finish; geometry: BufferGeometry }[] {
    const out: { finish: Finish; geometry: BufferGeometry }[] = [];
    for (const [finish, list] of this.parts) {
      if (list.length === 0) continue;
      const geometry = mergeGeometries(list, false);
      for (const g of list) g.dispose();
      if (geometry) { geometry.computeBoundingSphere(); out.push({ finish, geometry }); }
    }
    this.parts.clear();
    return out;
  }

  noShadow(finish: Finish): this { this.castShadow.set(finish, false); return this; }
}

export class Frame {
  constructor(private readonly batch: GeoBatch, private readonly at: Matrix4, private readonly cut?: CutLine) {}

  private put(finish: Finish, geo: BufferGeometry, color: ColorRepresentation, p: Placement): this {
    this.batch.add(finish, geo, color, this.at.clone().multiply(matrixOf(p)), this.cut);
    return this;
  }

  /** A box whose bottom sits at `p.y` (default 0). */
  box(finish: Finish, w: number, h: number, d: number, color: ColorRepresentation, p: Placement = {}): this {
    const g = new BoxGeometry(w, h, d);
    g.translate(0, h / 2, 0);
    return this.put(finish, g, color, p);
  }

  /** A box with chamfered vertical edges (an extruded octagon), bottom at `p.y`. */
  chamfer(finish: Finish, w: number, h: number, d: number, c: number, color: ColorRepresentation, p: Placement = {}): this {
    const s = new Shape();
    const hw = w / 2, hd = d / 2, k = Math.min(c, hw * 0.9, hd * 0.9);
    s.moveTo(-hw + k, -hd); s.lineTo(hw - k, -hd); s.lineTo(hw, -hd + k); s.lineTo(hw, hd - k); s.lineTo(hw - k, hd);
    s.lineTo(-hw + k, hd); s.lineTo(-hw, hd - k); s.lineTo(-hw, -hd + k); s.closePath();
    const g = new ExtrudeGeometry(s, { depth: h, bevelEnabled: false });
    // Extrusion runs along +z; turned up, the shape's y lies along -z (the shapes are symmetric).
    g.rotateX(-Math.PI / 2);
    return this.put(finish, g, color, p);
  }

  /** A rounded slab: a box with rounded vertical edges and a small bevel on top. */
  rounded(finish: Finish, w: number, h: number, d: number, r: number, color: ColorRepresentation, p: Placement = {}): this {
    const s = new Shape();
    const hw = w / 2, hd = d / 2, k = Math.min(r, hw * 0.95, hd * 0.95);
    s.moveTo(-hw + k, -hd); s.lineTo(hw - k, -hd); s.quadraticCurveTo(hw, -hd, hw, -hd + k); s.lineTo(hw, hd - k);
    s.quadraticCurveTo(hw, hd, hw - k, hd); s.lineTo(-hw + k, hd); s.quadraticCurveTo(-hw, hd, -hw, hd - k);
    s.lineTo(-hw, -hd + k); s.quadraticCurveTo(-hw, -hd, -hw + k, -hd);
    const bevel = Math.min(0.02, h * 0.2);
    const g = new ExtrudeGeometry(s, { depth: Math.max(0.001, h - bevel * 2), bevelEnabled: true, bevelSize: bevel, bevelThickness: bevel, bevelSegments: 1, curveSegments: 4 });
    g.translate(0, 0, bevel);
    g.rotateX(-Math.PI / 2);
    return this.put(finish, g, color, p);
  }

  cylinder(finish: Finish, rTop: number, rBottom: number, h: number, color: ColorRepresentation, p: Placement = {}, segments = 24, open = false): this {
    const g = new CylinderGeometry(rTop, rBottom, h, segments, 1, open);
    g.translate(0, h / 2, 0);
    return this.put(finish, g, color, p);
  }

  ring(finish: Finish, radius: number, tube: number, color: ColorRepresentation, p: Placement = {}, arc = Math.PI * 2, segments = 48): this {
    const g = new TorusGeometry(radius, tube, 6, segments, arc);
    g.rotateX(Math.PI / 2);
    return this.put(finish, g, color, p);
  }

  sphere(finish: Finish, r: number, color: ColorRepresentation, p: Placement = {}, segments = 16): this {
    return this.put(finish, new SphereGeometry(r, segments, Math.max(6, segments / 2)), color, p);
  }

  /** Any prepared geometry. */
  geo(finish: Finish, geo: BufferGeometry, color: ColorRepresentation, p: Placement = {}): this {
    return this.put(finish, geo, color, p);
  }

  /** A child frame placed relative to this one. */
  child(p: Placement): Frame {
    return new Frame(this.batch, this.at.clone().multiply(matrixOf(p)), this.cut);
  }
}

/** A flat annulus sector lying on the floor (y up), for trims and floor lines. */
export function annulus(inner: number, outer: number, start = 0, length = Math.PI * 2, segments = 64): BufferGeometry {
  const positions: number[] = [], normals: number[] = [], uvs: number[] = [];
  for (let i = 0; i < segments; i += 1) {
    const a0 = start + (length * i) / segments, a1 = start + (length * (i + 1)) / segments;
    const p = (r: number, a: number) => [Math.sin(a) * r, 0, Math.cos(a) * r];
    const quad = [p(inner, a0), p(outer, a0), p(outer, a1), p(inner, a0), p(outer, a1), p(inner, a1)];
    for (const v of quad) { positions.push(...v); normals.push(0, 1, 0); uvs.push(0, 0); }
  }
  const g = new BufferGeometry();
  g.setAttribute("position", new BufferAttribute(new Float32Array(positions), 3));
  g.setAttribute("normal", new BufferAttribute(new Float32Array(normals), 3));
  g.setAttribute("uv", new BufferAttribute(new Float32Array(uvs), 2));
  return g;
}

/** A flat rectangle on the floor with uvs in metres (for tiling textures). */
export function floorQuad(w: number, d: number): BufferGeometry {
  const g = new BufferGeometry();
  const hw = w / 2, hd = d / 2;
  g.setAttribute("position", new BufferAttribute(new Float32Array([-hw, 0, -hd, -hw, 0, hd, hw, 0, hd, -hw, 0, -hd, hw, 0, hd, hw, 0, -hd]), 3));
  g.setAttribute("normal", new BufferAttribute(new Float32Array([0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0]), 3));
  g.setAttribute("uv", new BufferAttribute(new Float32Array([-hw, -hd, -hw, hd, hw, hd, -hw, -hd, hw, hd, hw, -hd]), 2));
  return g;
}
