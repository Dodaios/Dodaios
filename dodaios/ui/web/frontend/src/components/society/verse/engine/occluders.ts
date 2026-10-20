/**
 * The cook's occluder meshes (UCX_, world space, no materials), drawn into the
 * depth buffer only, after the plate and before anything live: an actor that
 * walks behind a console or a cut wall disappears exactly where the
 * photograph shows the console or wall in front of it.
 */
import { DoubleSide, Group, Mesh, MeshBasicMaterial, type Object3D } from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { BACKDROP_LAYER, RENDER_ORDER } from "./renderOrder";

export const depthOnly = new MeshBasicMaterial({ colorWrite: false, depthWrite: true, depthTest: true, side: DoubleSide });

export async function loadOccluders(url: string, signal: AbortSignal): Promise<Group> {
  const res = await fetch(url, { signal });
  if (!res.ok) throw new Error(`Occluders failed: HTTP ${res.status}`);
  const buffer = await res.arrayBuffer();
  const magic = new Uint8Array(buffer, 0, Math.min(4, buffer.byteLength));
  if (String.fromCharCode(...magic) !== "glTF") throw new Error("Occluders are not a binary glTF");
  const gltf = await new GLTFLoader().parseAsync(buffer, "");
  const group = new Group();
  group.name = "occluders";
  gltf.scene.updateMatrixWorld(true);
  const meshes: Mesh[] = [];
  gltf.scene.traverse((o: Object3D) => { if ((o as Mesh).isMesh) meshes.push(o as Mesh); });
  for (const mesh of meshes) {
    // Baked into world space so the group can sit at the scene root untransformed.
    const geometry = mesh.geometry.clone().applyMatrix4(mesh.matrixWorld);
    const occluder = new Mesh(geometry, depthOnly);
    occluder.name = mesh.name;
    occluder.renderOrder = RENDER_ORDER.occluder;
    occluder.layers.set(BACKDROP_LAYER);
    occluder.matrixAutoUpdate = false;
    group.add(occluder);
    mesh.geometry.dispose();
  }
  return group;
}

export function disposeOccluders(group: Group): void {
  group.traverse((o) => { if ((o as Mesh).isMesh) (o as Mesh).geometry.dispose(); });
}
