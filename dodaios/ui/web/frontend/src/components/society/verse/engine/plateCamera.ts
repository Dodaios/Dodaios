/**
 * Puts a three.js OrthographicCamera exactly where the plate's Cycles camera
 * was, framed on the current view: same pitch, same axes, the frustum in
 * plate metres. plateMath.test.ts checks the projection against the plate
 * maths to a thousandth of a pixel.
 */
import type { OrthographicCamera } from "three";
import { cameraBasis, type PlateCamera } from "./plateMath";
import { frustum, type View, type Viewport } from "./view";

/** How far behind the view centre the camera sits, metres: in front of everything on a deck. */
export const CAMERA_BACK = 300;
/** Where the plate quad sits, metres beyond the plate centre along the view direction. */
export const PLATE_DEPTH = 250;
export const CAMERA_FAR = CAMERA_BACK + PLATE_DEPTH + 50;

export function applyPlateCamera(camera: OrthographicCamera, plate: PlateCamera, view: View, vp: Viewport): void {
  const { right, up, dir } = cameraBasis(plate.pitchDeg);
  const [cx, cy, cz] = plate.center;
  camera.position.set(
    cx + right[0] * view.cu + up[0] * view.cv - dir[0] * CAMERA_BACK,
    cy + right[1] * view.cu + up[1] * view.cv - dir[1] * CAMERA_BACK,
    cz + right[2] * view.cu + up[2] * view.cv - dir[2] * CAMERA_BACK,
  );
  // Rotation about X by −pitch takes the camera's +Y to U and its −Z to D.
  camera.rotation.set(-(plate.pitchDeg * Math.PI) / 180, 0, 0, "XYZ");
  const f = frustum(view, vp);
  camera.left = f.left;
  camera.right = f.right;
  camera.top = f.top;
  camera.bottom = f.bottom;
  camera.zoom = 1;
  camera.near = 1;
  camera.far = CAMERA_FAR;
  camera.updateProjectionMatrix();
  camera.updateMatrixWorld(true);
}
