/**
 * Draws a set of static props as a few merged meshes instead of one per
 * part. A furnished room is hundreds of small meshes (every drawer, book and
 * cushion); each is a draw call, and a second one in the shadow pass. Merged,
 * a whole floor's furniture is a few dozen.
 *
 * The props are mounted as usual, so their components stay the single source
 * of their shape. Once they are in the scene, every plain mesh is baked into
 * a merged geometry and hidden; the merged meshes are drawn in its place.
 * Parts whose material is nothing but a colour (no texture, not transparent)
 * share one material per finish and carry their colour in the vertices, so a
 * shelf of twenty differently coloured books is still one mesh. Textured and
 * transparent parts merge per material.
 *
 * Hidden meshes still take pointer events and keep their place in the scene
 * graph, so clicks and lookups by name work as before. A part that glows
 * keeps its own material object, so whoever pulses that material still does.
 * Parts smaller than a hand's width (a cup, a book, a handle) stop casting a
 * shadow of their own: at the floor's scale it never shows, and it halves
 * what the shadow pass draws.
 *
 * Only for props that never change after they mount: no animated parts, no
 * material swapped on state. Instanced, skinned and multi-material meshes and
 * anything already hidden are left alone and keep drawing themselves.
 * `signature` names the content: the batch is rebuilt when it changes.
 */
import { useLayoutEffect, useRef, type ReactNode } from "react";
import {
  Box3, BufferAttribute, BufferGeometry, Group, Matrix4, Mesh, Vector3,
  type InstancedMesh, type Material, type MeshStandardMaterial, type Object3D, type SkinnedMesh,
} from "three";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";

const BAKED_FLAG = "staticBatched";
/** A part whose largest side is shorter than this casts no shadow of its own. */
const SHADOW_MIN_M = 0.22;
/** Sheets with no thickness; a batch that keeps them apart leaves them as their own meshes. */
const FLAT_GEOMETRY = new Set(["PlaneGeometry", "CircleGeometry", "RingGeometry", "ShapeGeometry"]);

export interface BakeOptions {
  /** Leave flat sheets (planes, discs, rings) as their own meshes: for props whose merged meshes get a silhouette rim. */
  keepFlat?: boolean;
  /**
   * Shadows as one: no part is dropped from the shadow for being small, and the parts of a finish share one merged
   * mesh, which casts if any of them did. For a jointed thing made of small parts (a figure's arm), where the
   * shadow of the whole must stay as it was.
   */
  castAsOne?: boolean;
}

/** A mesh that can be baked: one material, plain geometry with positions, visible all the way up to the batch. */
function bakeable(object: Object3D, root: Object3D, options: BakeOptions): object is Mesh<BufferGeometry, Material> {
  const mesh = object as Mesh;
  if (!mesh.isMesh || (mesh as unknown as InstancedMesh).isInstancedMesh || (mesh as unknown as SkinnedMesh).isSkinnedMesh) return false;
  if (Array.isArray(mesh.material) || !mesh.geometry?.getAttribute("position")) return false;
  if (options.keepFlat && FLAT_GEOMETRY.has(mesh.geometry.type)) return false;
  if ((mesh.material as Material & { vertexColors?: boolean }).vertexColors) return false;
  for (let node: Object3D | null = mesh; node && node !== root; node = node.parent) {
    // A part someone hid stays hidden; a part this batch hid earlier is baked again.
    if (!node.visible && !node.userData[BAKED_FLAG]) return false;
  }
  return true;
}

/**
 * The finish of a material that is only a colour: everything the shared material must match. Null for a material
 * with any texture, transparency or special rendering, which keeps a mesh of its own kind.
 */
function plainFinish(material: Material): string | null {
  const m = material as MeshStandardMaterial;
  if (!m.isMeshStandardMaterial || m.type !== "MeshStandardMaterial") return null;
  if (m.map || m.emissiveMap || m.normalMap || m.roughnessMap || m.metalnessMap || m.alphaMap || m.aoMap || m.bumpMap || m.envMap) return null;
  if (m.transparent || m.opacity < 1 || m.alphaTest > 0 || m.wireframe || !m.depthWrite || !m.depthTest || !m.visible) return null;
  // A part that glows keeps its own material: lights are pulsed through the material object.
  if (m.emissive.getHex() !== 0 && m.emissiveIntensity !== 0) return null;
  return [step(m.roughness, ROUGHNESS_STEP), step(m.metalness, METALNESS_STEP), m.flatShading ? 1 : 0, m.side, m.toneMapped ? 1 : 0, m.fog ? 1 : 0].join(":");
}

/**
 * Finishes are told apart in steps: furniture is authored with a dozen roughness values between "matt" and
 * "satin" that nobody can tell apart on a prop a hand wide, and each would be a draw call of its own.
 */
const ROUGHNESS_STEP = 0.25;
const METALNESS_STEP = 0.25;
const step = (value: number, size: number) => Math.round(value / size) * size;

/** One white, vertex-coloured material per finish, shared by every batch. */
const finishMaterials = new Map<string, MeshStandardMaterial>();
function finishMaterial(finish: string, like: MeshStandardMaterial): MeshStandardMaterial {
  let material = finishMaterials.get(finish);
  if (!material) {
    material = like.clone();
    material.color.set("#ffffff");
    material.vertexColors = true;
    material.roughness = step(like.roughness, ROUGHNESS_STEP);
    material.metalness = step(like.metalness, METALNESS_STEP);
    finishMaterials.set(finish, material);
  }
  return material;
}

/**
 * A copy of a mesh's geometry in the batch's own frame, reduced to position, normal and uv — and, for a plain
 * part, its material's colour in every vertex.
 */
function baked(mesh: Mesh<BufferGeometry, Material>, toBatch: Matrix4, tinted: boolean): BufferGeometry {
  const source = mesh.geometry;
  const flat = source.index ? source.toNonIndexed() : source.clone();
  for (const name of Object.keys(flat.attributes)) if (name !== "position" && name !== "normal" && name !== "uv") flat.deleteAttribute(name);
  if (!flat.getAttribute("normal")) flat.computeVertexNormals();
  const count = flat.getAttribute("position").count;
  if (!flat.getAttribute("uv")) flat.setAttribute("uv", new BufferAttribute(new Float32Array(count * 2), 2));
  if (tinted) {
    const { r, g, b } = (mesh.material as MeshStandardMaterial).color;
    const colours = new Float32Array(count * 3);
    for (let i = 0; i < count; i += 1) { colours[i * 3] = r; colours[i * 3 + 1] = g; colours[i * 3 + 2] = b; }
    flat.setAttribute("color", new BufferAttribute(colours, 3));
  }
  flat.morphAttributes = {};
  flat.clearGroups();
  return flat.applyMatrix4(new Matrix4().multiplyMatrices(toBatch, mesh.matrixWorld));
}

/**
 * Bake every bakeable mesh under `source` into merged meshes under `target` and hide the originals: one merged
 * mesh per finish for plain coloured parts, one per material for the rest, each split by its shadow flags.
 * Returns the merged meshes; the caller disposes their geometries.
 */
export function bakeStatic(source: Object3D, target: Object3D, options: BakeOptions = {}): Mesh[] {
  source.updateMatrixWorld(true);
  target.updateMatrixWorld(true);
  const toBatch = new Matrix4().copy(target.matrixWorld).invert();
  const buckets = new Map<string, { material: Material; cast: boolean; receive: boolean; order: number; pieces: BufferGeometry[]; meshes: Mesh[] }>();
  const box = new Box3(), extent = new Vector3();
  source.traverse((object) => {
    if (!bakeable(object, source, options)) return;
    const finish = plainFinish(object.material);
    const piece = baked(object, toBatch, finish !== null);
    piece.computeBoundingBox();
    box.copy(piece.boundingBox as Box3).getSize(extent);
    const cast = object.castShadow && (options.castAsOne || Math.max(extent.x, extent.y, extent.z) >= SHADOW_MIN_M);
    const key = `${finish === null ? object.material.uuid : `plain:${finish}`}:${options.castAsOne ? "" : cast ? 1 : 0}${object.receiveShadow ? 1 : 0}:${object.renderOrder}`;
    let bucket = buckets.get(key);
    if (!bucket) {
      bucket = {
        material: finish === null ? object.material : finishMaterial(finish, object.material as MeshStandardMaterial),
        cast, receive: object.receiveShadow, order: object.renderOrder, pieces: [], meshes: [],
      };
      buckets.set(key, bucket);
    }
    bucket.cast ||= cast;
    bucket.pieces.push(piece);
    bucket.meshes.push(object);
  });
  const out: Mesh[] = [];
  for (const bucket of buckets.values()) {
    const geometry = bucket.pieces.length === 1 ? bucket.pieces[0] : mergeGeometries(bucket.pieces, false);
    if (bucket.pieces.length > 1) for (const piece of bucket.pieces) piece.dispose();
    // A set that will not merge keeps drawing itself.
    if (!geometry) continue;
    const mesh = new Mesh(geometry, bucket.material);
    mesh.castShadow = bucket.cast;
    mesh.receiveShadow = bucket.receive;
    mesh.renderOrder = bucket.order;
    mesh.userData[BAKED_FLAG] = true;
    // The merged mesh is only drawn; pointer events stay with the parts it stands for.
    mesh.raycast = () => undefined;
    target.add(mesh);
    out.push(mesh);
    for (const original of bucket.meshes) {
      original.visible = false;
      original.userData[BAKED_FLAG] = true;
    }
  }
  return out;
}

export function StaticBatch({ signature, keepFlat = false, castAsOne = false, children }: {
  signature: string; keepFlat?: boolean; castAsOne?: boolean; children: ReactNode;
}) {
  const source = useRef<Group>(null);
  const target = useRef<Group>(null);
  useLayoutEffect(() => {
    const from = source.current, to = target.current;
    if (!from || !to) return;
    const meshes = bakeStatic(from, to, { keepFlat, castAsOne });
    return () => {
      for (const mesh of meshes) {
        to.remove(mesh);
        mesh.geometry.dispose();
      }
      // Whatever is still mounted draws itself again until the next bake.
      from.traverse((object) => {
        if (object.userData[BAKED_FLAG]) { object.visible = true; delete object.userData[BAKED_FLAG]; }
      });
    };
  }, [signature, keepFlat, castAsOne]);
  return (
    <>
      <group ref={source}>{children}</group>
      <group ref={target} />
    </>
  );
}
