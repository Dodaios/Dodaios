/**
 * Test support for the camera: projects a floor's corners through a camera
 * pose with three.js itself, independent of the fit maths under test.
 */
import { PerspectiveCamera, Vector3 } from "three";
import { CAMERA_FOV, cameraLimitsFor, type Bounds, type CameraPose } from "./officeCamera";

export interface ViewBox { minX: number; maxX: number; minY: number; maxY: number }

/**
 * Are all corners of `bounds` (on the floor and 3 m up) inside the view, how close to an edge does the floor
 * reach (0..1), and which box of the view (-1..1 on both axes) do they span?
 */
export function cornersInView(bounds: Bounds, pose: CameraPose, aspect: number): { inside: boolean; widest: number; box: ViewBox } {
  const camera = new PerspectiveCamera(CAMERA_FOV, aspect, 0.2, 5000);
  camera.position.set(...pose.position);
  camera.lookAt(new Vector3(...pose.target));
  camera.updateMatrixWorld(true);
  camera.updateProjectionMatrix();
  let widest = 0;
  let inside = true;
  const box: ViewBox = { minX: Infinity, maxX: -Infinity, minY: Infinity, maxY: -Infinity };
  for (const x of [bounds.minX, bounds.maxX]) {
    for (const z of [bounds.minZ, bounds.maxZ]) {
      for (const y of [0, 3]) {
        const p = new Vector3(x, y, z).project(camera);
        const reach = Math.max(Math.abs(p.x), Math.abs(p.y));
        if (reach > 1 || p.z > 1 || p.z < -1) inside = false;
        widest = Math.max(widest, reach);
        box.minX = Math.min(box.minX, p.x); box.maxX = Math.max(box.maxX, p.x);
        box.minY = Math.min(box.minY, p.y); box.maxY = Math.max(box.maxY, p.y);
      }
    }
  }
  return { inside, widest, box };
}

/** The limits for the most demanding common viewport (portrait side panel). */
export function campusLimits(bounds: Bounds) {
  return cameraLimitsFor(bounds, 0.62);
}
