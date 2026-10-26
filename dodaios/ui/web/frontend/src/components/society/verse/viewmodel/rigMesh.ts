/**
 * The viewmodel drawn as one mesh: every rigid part of the arms and the
 * blaster is baked into a single skinned geometry (each vertex bound with
 * full weight to the bone it moves with), and every surface is one slot of a
 * tiny palette (albedo, roughness, metalness and emission in three float
 * textures, one texel per slot) under one material. So both arms, their
 * fingers and the blaster cost one draw call, whatever the number of parts.
 *
 * Bones are plain Object3Ds in the rig's graph, posed as before; the mesh
 * sits at the scene's origin with identity bind matrices, so a vertex lands
 * at `bone.matrixWorld × (its position in the bone's frame)`.
 */
import {
  BufferAttribute, Color, DataTexture, DoubleSide, FloatType, Matrix4, MeshStandardMaterial, NearestFilter, RGBAFormat, Skeleton,
  SkinnedMesh, Vector3, type Bone, type BufferGeometry, type Object3D,
} from "three";
import { ConvexGeometry } from "three/examples/jsm/geometries/ConvexGeometry.js";
import { mergeGeometries, mergeVertices } from "three/examples/jsm/utils/BufferGeometryUtils.js";

/** A surface of the palette (an index into its textures). */
export type Slot = number;

const SIZE = 16;

function paletteTexture(): DataTexture {
  const t = new DataTexture(new Float32Array(SIZE * 4), SIZE, 1, RGBAFormat, FloatType);
  t.magFilter = NearestFilter;
  t.minFilter = NearestFilter;
  t.generateMipmaps = false;
  t.needsUpdate = true;
  return t;
}

/** The rig's surfaces: one material, one texel per surface. */
export class RigPalette {
  readonly material: MeshStandardMaterial;
  private readonly albedo = paletteTexture();
  /** Roughness in green, metalness in blue (three's channel convention). */
  private readonly rm = paletteTexture();
  private readonly glow = paletteTexture();
  private readonly names = new Map<string, Slot>();

  constructor(name: string) {
    this.material = new MeshStandardMaterial({
      name, map: this.albedo, roughnessMap: this.rm, metalnessMap: this.rm, emissiveMap: this.glow,
      color: 0xffffff, emissive: 0xffffff, roughness: 1, metalness: 1, side: DoubleSide,
    });
  }

  /** The slot named `name` (allocated on first use). */
  slot(name: string): Slot {
    let s = this.names.get(name);
    if (s === undefined) {
      s = this.names.size;
      if (s >= SIZE) throw new Error(`rig palette full (${SIZE} surfaces)`);
      this.names.set(name, s);
    }
    return s;
  }

  /** The texture coordinate that reads `slot`. */
  static u(slot: Slot): number {
    return (slot + 0.5) / SIZE;
  }

  /** A surface's colour (linear), roughness and metalness. */
  surface(slot: Slot, color: Color, roughness: number, metalness: number): void {
    const a = this.albedo.image.data as Float32Array;
    a[slot * 4] = color.r;
    a[slot * 4 + 1] = color.g;
    a[slot * 4 + 2] = color.b;
    a[slot * 4 + 3] = 1;
    const r = this.rm.image.data as Float32Array;
    r[slot * 4 + 1] = roughness;
    r[slot * 4 + 2] = metalness;
    r[slot * 4 + 3] = 1;
    this.albedo.needsUpdate = true;
    this.rm.needsUpdate = true;
  }

  /** A surface's emission: colour (linear) times intensity. Only uploads when it changed. */
  emit(slot: Slot, color: Color, intensity: number): void {
    const g = this.glow.image.data as Float32Array;
    const r = color.r * intensity;
    const gg = color.g * intensity;
    const b = color.b * intensity;
    const i = slot * 4;
    if (g[i] === r && g[i + 1] === gg && g[i + 2] === b) return;
    g[i] = r;
    g[i + 1] = gg;
    g[i + 2] = b;
    g[i + 3] = 1;
    this.glow.needsUpdate = true;
  }

  /** The emission written for `slot` (its strongest channel). */
  emission(slot: Slot): number {
    const g = this.glow.image.data as Float32Array;
    return Math.max(g[slot * 4], g[slot * 4 + 1], g[slot * 4 + 2]);
  }

  dispose(): void {
    this.material.dispose();
    this.albedo.dispose();
    this.rm.dispose();
    this.glow.dispose();
  }
}

interface Part {
  geometry: BufferGeometry;
  bone: number;
  slot: Slot;
  matrix: Matrix4 | null;
  mirror: boolean;
}

const MIRROR_X = new Matrix4().makeScale(-1, 1, 1);

/** Collects the rig's parts per bone and bakes them into one skinned mesh. */
export class RigBuilder {
  readonly bones: Object3D[] = [];
  private readonly parts: Part[] = [];

  /**
   * Add a part: `geometry` (taken over: it is disposed once baked) placed by `matrix` in `bone`'s frame, painted with
   * `slot`. `mirror` reflects it across the bone frame's YZ plane after placing (the left hand is the right one mirrored).
   */
  add(geometry: BufferGeometry, bone: Object3D, slot: Slot, matrix: Matrix4 | null = null, mirror = false): void {
    let b = this.bones.indexOf(bone);
    if (b < 0) {
      b = this.bones.length;
      this.bones.push(bone);
    }
    this.parts.push({ geometry, bone: b, slot, matrix, mirror });
  }

  /** Bake every part into one geometry (position, normal, uv into the palette, skin index and weight). */
  bake(): BufferGeometry {
    const baked: BufferGeometry[] = [];
    for (const p of this.parts) {
      const src = p.geometry.index ? p.geometry.toNonIndexed() : p.geometry.clone();
      if (!src.getAttribute("normal")) src.computeVertexNormals();
      for (const name of Object.keys(src.attributes)) if (name !== "position" && name !== "normal") src.deleteAttribute(name);
      src.morphAttributes = {};
      src.clearGroups();
      if (p.matrix) src.applyMatrix4(p.matrix);
      if (p.mirror) {
        src.applyMatrix4(MIRROR_X);
        flipWinding(src);
      }
      const n = src.getAttribute("position").count;
      const uv = new Float32Array(n * 2);
      const u = RigPalette.u(p.slot);
      for (let i = 0; i < n; i++) {
        uv[i * 2] = u;
        uv[i * 2 + 1] = 0.5;
      }
      const index = new Uint16Array(n * 4);
      const weight = new Float32Array(n * 4);
      for (let i = 0; i < n; i++) {
        index[i * 4] = p.bone;
        weight[i * 4] = 1;
      }
      src.setAttribute("uv", new BufferAttribute(uv, 2));
      src.setAttribute("skinIndex", new BufferAttribute(index, 4));
      src.setAttribute("skinWeight", new BufferAttribute(weight, 4));
      baked.push(src);
      if (src !== p.geometry) p.geometry.dispose();
    }
    const merged = mergeGeometries(baked, false);
    for (const g of baked) g.dispose();
    if (!merged) throw new Error("viewmodel rig: parts could not be merged");
    merged.name = "ViewmodelRig";
    return merged;
  }

  /** Bake and bind: one skinned mesh over the collected bones (identity bind pose). */
  build(material: MeshStandardMaterial): SkinnedMesh {
    const mesh = new SkinnedMesh(this.bake(), material);
    mesh.name = "ViewmodelRig";
    mesh.frustumCulled = false;
    const skeleton = new Skeleton(this.bones as Bone[], this.bones.map(() => new Matrix4()));
    mesh.bind(skeleton, new Matrix4());
    return mesh;
  }
}

/** Reverse each triangle's winding (non-indexed geometry), after a mirror. */
function flipWinding(g: BufferGeometry): void {
  for (const name of ["position", "normal"]) {
    const a = g.getAttribute(name);
    if (!a) continue;
    const arr = a.array as Float32Array;
    const s = a.itemSize;
    for (let t = 0; t + 2 < a.count; t += 3) {
      for (let k = 0; k < s; k++) {
        const i1 = (t + 1) * s + k;
        const i2 = (t + 2) * s + k;
        const tmp = arr[i1];
        arr[i1] = arr[i2];
        arr[i2] = tmp;
      }
    }
    a.needsUpdate = true;
  }
}

/**
 * A box with its edges chamfered at `c` (flat faces, a narrow facet on every edge, a triangle on every corner):
 * 44 triangles, where a rounded box with one segment costs 108. Centred on the origin. `smooth` shades it soft
 * (normals shared across the facets: a padded glove rather than machined metal).
 */
export function chamferBox(w: number, h: number, d: number, c: number, smooth = false): BufferGeometry {
  const x = w / 2;
  const y = h / 2;
  const z = d / 2;
  const k = Math.min(c, x * 0.9, y * 0.9, z * 0.9);
  const pts: Vector3[] = [];
  for (const sx of [-1, 1]) {
    for (const sy of [-1, 1]) {
      for (const sz of [-1, 1]) {
        pts.push(
          new Vector3(sx * x, sy * (y - k), sz * (z - k)),
          new Vector3(sx * (x - k), sy * y, sz * (z - k)),
          new Vector3(sx * (x - k), sy * (y - k), sz * z),
        );
      }
    }
  }
  const hull = new ConvexGeometry(pts);
  if (!smooth) return hull;
  hull.deleteAttribute("normal");
  const soft = mergeVertices(hull);
  hull.dispose();
  soft.computeVertexNormals();
  return soft;
}
