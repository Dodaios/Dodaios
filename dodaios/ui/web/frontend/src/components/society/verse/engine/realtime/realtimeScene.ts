/**
 * Loads a deck's eye-level scene (docs/verse/realtime.md): the meshopt glTF,
 * its lightmap pages and the rooms' reflection probes, and dresses every
 * chunk with its deck material. Also builds the collision structure the
 * camera and the pointer use (a BVH over the chunks whose material collides,
 * in world space).
 *
 * Images arrive as RGBA WebP in the "rgbm2" encoding and are decoded without
 * premultiplication or colour conversion. Lightmap pages stay encoded (the
 * deck shader decodes them); each probe panorama is decoded once on the GPU
 * into a half-float equirect and prefiltered with PMREM.
 */
import {
  BufferAttribute, BufferGeometry, Group, HalfFloatType, LinearFilter, LinearMipmapLinearFilter, Mesh, NoColorSpace,
  OrthographicCamera, PlaneGeometry, PMREMGenerator, RGBAFormat, Scene, ShaderMaterial, Texture, Vector3, WebGLRenderTarget,
  type Material, type WebGLRenderer,
} from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { MeshoptDecoder } from "three/examples/jsm/libs/meshopt_decoder.module.js";
import { MeshBVH } from "three-mesh-bvh";
import type { RealtimeContent, RealtimeProbe } from "../../content/deck";
import { fetchImageBitmap } from "../imageFetch";
import { REALTIME_LAYER } from "../renderOrder";
import { depthOrder, makeDeckMaterial, type ProbeBinding } from "./deckMaterial";

export interface RealtimeScene {
  group: Group;
  /** Every deck material (one per chunk key). */
  materials: readonly Material[];
  /** World-space collision of the solid chunks, or null when there are none. */
  collider: MeshBVH | null;
  /** Draw chunks and triangles, for the stats. */
  chunks: number;
  triangles: number;
  dispose(): void;
}

interface ChunkInfo { material: string; room: string; page: number }

function chunkInfo(extras: unknown): ChunkInfo | null {
  const e = extras as Partial<ChunkInfo> | undefined;
  if (!e || typeof e.material !== "string" || typeof e.room !== "string" || typeof e.page !== "number") return null;
  return { material: e.material, room: e.room, page: e.page };
}

async function pageTexture(url: string, anisotropy: number, signal: AbortSignal): Promise<Texture> {
  const bitmap = await fetchImageBitmap(url, signal, "none");
  const texture = new Texture(bitmap);
  texture.flipY = false; // glTF UVs: v = 0 is the top row
  texture.colorSpace = NoColorSpace;
  texture.premultiplyAlpha = false;
  texture.format = RGBAFormat;
  texture.generateMipmaps = true;
  texture.minFilter = LinearMipmapLinearFilter;
  texture.magFilter = LinearFilter;
  texture.anisotropy = anisotropy;
  texture.needsUpdate = true;
  return texture;
}

const DECODE_VERTEX = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = vec4( position.xy, 0.0, 1.0 );
}
`;

const DECODE_FRAGMENT = /* glsl */ `
uniform sampler2D source;
uniform float range;
varying vec2 vUv;
void main() {
  vec4 t = texture2D( source, vUv );
  gl_FragColor = vec4( t.rgb * t.rgb * ( t.a * t.a * range ), 1.0 );
}
`;

/** Decode an rgbm2 panorama into a half-float equirect and prefilter it (PMREM). */
async function probeTexture(gl: WebGLRenderer, probe: RealtimeProbe, signal: AbortSignal): Promise<Texture> {
  // Flipped at decode time: equirect textures have v = 1 at the top, as three expects.
  const bitmap = await fetchImageBitmap(probe.url, signal, "flipY");
  const source = new Texture(bitmap);
  source.flipY = false;
  source.colorSpace = NoColorSpace;
  source.premultiplyAlpha = false;
  source.generateMipmaps = false;
  source.minFilter = LinearFilter;
  source.magFilter = LinearFilter;
  source.needsUpdate = true;
  const target = new WebGLRenderTarget(probe.width, probe.height, { type: HalfFloatType, depthBuffer: false });
  const material = new ShaderMaterial({
    uniforms: { source: { value: source }, range: { value: probe.range } },
    vertexShader: DECODE_VERTEX,
    fragmentShader: DECODE_FRAGMENT,
    depthTest: false,
    depthWrite: false,
  });
  const quad = new Mesh(new PlaneGeometry(2, 2), material);
  const scene = new Scene();
  scene.add(quad);
  const camera = new OrthographicCamera(-1, 1, 1, -1, 0, 1);
  const previous = gl.getRenderTarget();
  const toneMapping = gl.toneMapping;
  try {
    gl.toneMapping = 0;
    gl.setRenderTarget(target);
    gl.render(scene, camera);
  } finally {
    gl.setRenderTarget(previous);
    gl.toneMapping = toneMapping;
  }
  const pmrem = new PMREMGenerator(gl);
  const env = pmrem.fromEquirectangular(target.texture).texture;
  pmrem.dispose();
  target.dispose();
  material.dispose();
  quad.geometry.dispose();
  source.dispose();
  bitmap.close();
  return env;
}

/** Everything solid, merged into one world-space geometry for the BVH. */
function buildCollider(meshes: readonly Mesh[]): MeshBVH | null {
  let vertexCount = 0;
  let indexCount = 0;
  for (const mesh of meshes) {
    vertexCount += mesh.geometry.getAttribute("position").count;
    indexCount += mesh.geometry.index?.count ?? mesh.geometry.getAttribute("position").count;
  }
  if (vertexCount === 0) return null;
  const positions = new Float32Array(vertexCount * 3);
  const indices = new Uint32Array(indexCount);
  const v = new Vector3();
  let vo = 0;
  let io = 0;
  for (const mesh of meshes) {
    mesh.updateWorldMatrix(true, false);
    const position = mesh.geometry.getAttribute("position");
    const base = vo / 3;
    for (let i = 0; i < position.count; i++) {
      v.fromBufferAttribute(position, i).applyMatrix4(mesh.matrixWorld);
      positions[vo++] = v.x;
      positions[vo++] = v.y;
      positions[vo++] = v.z;
    }
    const index = mesh.geometry.index;
    if (index) for (let i = 0; i < index.count; i++) indices[io++] = base + index.getX(i);
    else for (let i = 0; i < position.count; i++) indices[io++] = base + i;
  }
  const geometry = new BufferGeometry();
  geometry.setAttribute("position", new BufferAttribute(positions, 3));
  geometry.setIndex(new BufferAttribute(indices, 1));
  return new MeshBVH(geometry);
}

export async function loadRealtimeScene(gl: WebGLRenderer, content: RealtimeContent, signal: AbortSignal): Promise<RealtimeScene> {
  const loader = new GLTFLoader();
  loader.setMeshoptDecoder(MeshoptDecoder);
  const anisotropy = Math.min(8, gl.capabilities.getMaxAnisotropy());
  const [gltfBuffer, pages] = await Promise.all([
    fetch(content.sceneUrl, { signal }).then((res) => {
      if (!res.ok) throw new Error(`Realtime scene: HTTP ${res.status}`);
      return res.arrayBuffer();
    }),
    Promise.all(content.pages.map((p) => pageTexture(p.url, anisotropy, signal))),
  ]);
  signal.throwIfAborted();
  const gltf = await loader.parseAsync(gltfBuffer, "");
  signal.throwIfAborted();
  const probes = new Map<string, ProbeBinding>();
  const envs: Texture[] = [];
  for (const probe of content.probes) {
    try {
      const env = await probeTexture(gl, probe, signal);
      envs.push(env);
      probes.set(probe.room, { env, position: probe.position, boxMin: probe.boxMin, boxMax: probe.boxMax });
    } catch (error) {
      if (signal.aborted) throw error;
      // A room without its probe still draws its baked light; only its reflections go.
      console.warn("Verse realtime probe unavailable", probe.room, error);
    }
  }
  signal.throwIfAborted();
  const materials = new Map<string, Material>();
  const solid: Mesh[] = [];
  let triangles = 0;
  let chunks = 0;
  const group = gltf.scene;
  group.name = "verse-realtime";
  const unused: Material[] = [];
  const order = depthOrder(Object.keys(content.materials));
  group.traverse((object) => {
    const mesh = object as Mesh;
    if (!mesh.isMesh) return;
    const info = chunkInfo(mesh.userData) ?? chunkInfo(mesh.parent?.userData);
    const params = info ? content.materials[info.material] : undefined;
    const page = info ? pages[info.page] : undefined;
    if (!info || !params || !page) {
      mesh.visible = false;
      return;
    }
    const key = `${info.material}|${info.room}|${info.page}`;
    let material = materials.get(key);
    if (!material) {
      material = makeDeckMaterial({ name: key, params, page, range: content.range, probe: probes.get(info.room) ?? null, order: order.get(info.material) ?? 0 });
      materials.set(key, material);
    }
    for (const old of Array.isArray(mesh.material) ? mesh.material : [mesh.material]) unused.push(old);
    mesh.material = material;
    mesh.layers.set(REALTIME_LAYER);
    mesh.renderOrder = params.transparent ? 5 : 0;
    mesh.matrixAutoUpdate = false;
    chunks++;
    triangles += (mesh.geometry.index?.count ?? mesh.geometry.getAttribute("position").count) / 3;
    if (params.collide) solid.push(mesh);
  });
  for (const m of new Set(unused)) m.dispose();
  group.updateMatrixWorld(true);
  const collider = buildCollider(solid);
  return {
    group,
    materials: [...materials.values()],
    collider,
    chunks,
    triangles,
    dispose() {
      group.traverse((object) => {
        const mesh = object as Mesh;
        if (mesh.isMesh) mesh.geometry.dispose();
      });
      for (const m of materials.values()) m.dispose();
      for (const t of pages) t.dispose();
      for (const t of envs) t.dispose();
      collider?.geometry.dispose();
    },
  };
}
