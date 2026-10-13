/**
 * The rim a station's object wears while the person is near it or points at
 * it: a thin lit edge round the object's own silhouette. Every mesh under the
 * object gets a shell of the same geometry, pushed out along its normals and
 * drawn back faces only, so the object hides all of it but the edge. Nothing
 * is added to the room at rest.
 */
import { BackSide, Color, Mesh, ShaderMaterial, type InstancedMesh, type Object3D, type SkinnedMesh } from "three";

/**
 * One blue for "you can use this", the same family as a selected agent's ring. Mid-bright and saturated on
 * purpose: it has to read on the pale floor and light oak of the agents floor as well as on dark walnut and
 * the coding floor's night.
 */
export const STATION_RIM_COLOUR = "#3f8cff";
/** Edge width in metres up close; beyond `RIM_FAR_M` it grows with distance so it stays visible from the overview. */
const RIM_WIDTH_M = 0.016;
const RIM_FAR_M = 11;

/** Flat geometry has no silhouette to rim; its shell would only show as a stray sheet from behind. */
const FLAT_GEOMETRY = new Set(["PlaneGeometry", "CircleGeometry", "RingGeometry", "ShapeGeometry"]);

const RIM_FLAG = "stationRim";

export function createRimMaterial(): ShaderMaterial {
  return new ShaderMaterial({
    uniforms: {
      rimColour: { value: new Color(STATION_RIM_COLOUR) },
      rimOpacity: { value: 0 },
      rimWidth: { value: RIM_WIDTH_M },
      rimFar: { value: RIM_FAR_M },
    },
    vertexShader: /* glsl */ `
      uniform float rimWidth;
      uniform float rimFar;
      void main() {
        vec4 viewPosition = modelViewMatrix * vec4(position, 1.0);
        vec3 viewNormal = normalize(normalMatrix * normal);
        viewPosition.xyz += viewNormal * rimWidth * max(1.0, -viewPosition.z / rimFar);
        gl_Position = projectionMatrix * viewPosition;
      }
    `,
    fragmentShader: /* glsl */ `
      uniform vec3 rimColour;
      uniform float rimOpacity;
      void main() {
        gl_FragColor = vec4(rimColour, rimOpacity);
      }
    `,
    side: BackSide,
    transparent: true,
    depthWrite: false,
    toneMapped: false,
  });
}

/** Can this object carry a shell? Plain, visible meshes with normals only. */
function rimmable(object: Object3D): object is Mesh {
  const mesh = object as Mesh;
  if (!mesh.isMesh || mesh.userData[RIM_FLAG]) return false;
  if ((mesh as InstancedMesh).isInstancedMesh || (mesh as SkinnedMesh).isSkinnedMesh) return false;
  const geometry = mesh.geometry;
  if (!geometry?.attributes?.normal || !geometry.attributes.position) return false;
  // Text and other instanced-attribute geometry needs its own shader to make sense.
  if ((geometry as { isInstancedBufferGeometry?: boolean }).isInstancedBufferGeometry) return false;
  return !FLAT_GEOMETRY.has(geometry.type);
}

/** The visible meshes under `root` that get a shell. */
export function rimTargets(root: Object3D): Mesh[] {
  const targets: Mesh[] = [];
  root.traverseVisible((object) => { if (rimmable(object)) targets.push(object); });
  return targets;
}

/** Add a rim shell to every visible mesh under `root`; returns the shells so they can be taken off again. */
export function attachRim(root: Object3D, material: ShaderMaterial): Mesh[] {
  return rimTargets(root).map((mesh) => {
    const shell = new Mesh(mesh.geometry, material);
    shell.userData[RIM_FLAG] = true;
    shell.name = "station-rim";
    // The shell is light, not a thing: no clicks, no shadows.
    shell.raycast = () => undefined;
    shell.castShadow = false;
    shell.receiveShadow = false;
    shell.frustumCulled = mesh.frustumCulled;
    mesh.add(shell);
    return shell;
  });
}

/** Take the shells off again. Their geometry belongs to the meshes they copied, so nothing is disposed here. */
export function detachRim(shells: readonly Mesh[]): void {
  for (const shell of shells) shell.removeFromParent();
}

/** Is `object` still part of the scene under `scene`? A re-rendered prop leaves its old group detached. */
export function attachedTo(object: Object3D, scene: Object3D): boolean {
  for (let node: Object3D | null = object; node; node = node.parent) if (node === scene) return true;
  return false;
}
