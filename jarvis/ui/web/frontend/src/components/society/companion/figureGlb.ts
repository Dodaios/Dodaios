/**
 * Reads the companion models (companions.glb, accessories.glb) without a 3D
 * library: binary glTF holding plain triangle meshes with positions, normals
 * and indices, no textures, no compression and no node transforms. The
 * profile faces draw these meshes on the CPU (figureRender.ts), so a roster
 * needs neither WebGL nor the map's renderer.
 */

/** Linear red, green and blue, 0 to 1. */
export type LinearRgb = [number, number, number];

export interface FigureMaterial {
  name: string;
  color: LinearRgb;
  roughness: number;
  /** Emits its own light (an ember, a lamp): drawn unlit and bright. */
  glow: boolean;
}

export interface FigureMesh {
  /** The node that carries the mesh, for example `squircle.Body` or `acc_cap`. */
  name: string;
  positions: Float32Array;
  normals: Float32Array;
  indices: Uint16Array | Uint32Array;
  material: FigureMaterial;
}

const GLB_MAGIC = 0x46546c67;
const CHUNK_JSON = 0x4e4f534a;
const CHUNK_BIN = 0x004e4942;
const FLOAT = 5126, UNSIGNED_SHORT = 5123, UNSIGNED_INT = 5125;

interface GltfAccessor { bufferView: number; byteOffset?: number; componentType: number; count: number; type: string }
interface GltfView { byteOffset?: number; byteLength: number; byteStride?: number }
interface GltfJson {
  accessors: GltfAccessor[];
  bufferViews: GltfView[];
  nodes: { name?: string; mesh?: number }[];
  meshes: { primitives: { attributes: Record<string, number>; indices?: number; material?: number; mode?: number }[] }[];
  materials?: { name?: string; emissiveFactor?: number[]; pbrMetallicRoughness?: { baseColorFactor?: number[]; roughnessFactor?: number } }[];
}

/** Every mesh of a binary glTF file, one entry per primitive, named after its node. */
export function readGlb(file: ArrayBuffer): FigureMesh[] {
  const view = new DataView(file);
  if (view.byteLength < 20 || view.getUint32(0, true) !== GLB_MAGIC) throw new Error("Not a binary glTF file");
  let json: GltfJson | undefined;
  let binStart = -1;
  for (let offset = 12; offset + 8 <= view.byteLength;) {
    const length = view.getUint32(offset, true), type = view.getUint32(offset + 4, true);
    if (type === CHUNK_JSON) json = JSON.parse(new TextDecoder().decode(new Uint8Array(file, offset + 8, length))) as GltfJson;
    if (type === CHUNK_BIN) binStart = offset + 8;
    offset += 8 + length;
  }
  if (!json || binStart < 0) throw new Error("Binary glTF without a mesh buffer");
  const gltf = json;

  const read = (index: number, parts: number): Float32Array | Uint16Array | Uint32Array => {
    const accessor = gltf.accessors[index];
    const span = accessor && gltf.bufferViews[accessor.bufferView];
    if (!accessor || !span || span.byteStride) throw new Error("Unsupported glTF accessor");
    const start = binStart + (span.byteOffset ?? 0) + (accessor.byteOffset ?? 0);
    const length = accessor.count * parts;
    const Kind = accessor.componentType === FLOAT ? Float32Array : accessor.componentType === UNSIGNED_SHORT ? Uint16Array
      : accessor.componentType === UNSIGNED_INT ? Uint32Array : undefined;
    if (!Kind) throw new Error("Unsupported glTF component type");
    // A typed array must start on a multiple of its element size; copy when the file does not.
    return start % Kind.BYTES_PER_ELEMENT === 0 ? new Kind(file, start, length)
      : new Kind(file.slice(start, start + length * Kind.BYTES_PER_ELEMENT));
  };

  const materials: FigureMaterial[] = (gltf.materials ?? []).map(material => {
    const base = material.pbrMetallicRoughness?.baseColorFactor ?? [1, 1, 1];
    return {
      name: material.name ?? "",
      color: [base[0] ?? 1, base[1] ?? 1, base[2] ?? 1],
      roughness: material.pbrMetallicRoughness?.roughnessFactor ?? 1,
      glow: (material.emissiveFactor ?? []).some(value => value > 0),
    };
  });
  const plain: FigureMaterial = { name: "", color: [1, 1, 1], roughness: 1, glow: false };

  const meshes: FigureMesh[] = [];
  for (const node of gltf.nodes) {
    const mesh = node.mesh === undefined ? undefined : gltf.meshes[node.mesh];
    if (!mesh) continue;
    for (const primitive of mesh.primitives) {
      const { POSITION, NORMAL } = primitive.attributes;
      if ((primitive.mode ?? 4) !== 4 || POSITION === undefined || NORMAL === undefined || primitive.indices === undefined) continue;
      meshes.push({
        name: node.name ?? "",
        positions: read(POSITION, 3) as Float32Array,
        normals: read(NORMAL, 3) as Float32Array,
        indices: read(primitive.indices, 1) as Uint16Array | Uint32Array,
        material: (primitive.material === undefined ? undefined : materials[primitive.material]) ?? plain,
      });
    }
  }
  return meshes;
}

/** The meshes of one file, by node name. */
export function meshesByName(meshes: readonly FigureMesh[]): Map<string, FigureMesh[]> {
  const byName = new Map<string, FigureMesh[]>();
  for (const mesh of meshes) {
    const list = byName.get(mesh.name);
    if (list) list.push(mesh); else byName.set(mesh.name, [mesh]);
  }
  return byName;
}
