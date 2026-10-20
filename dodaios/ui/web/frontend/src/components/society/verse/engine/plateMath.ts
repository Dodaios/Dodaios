/**
 * The fixed plate camera (BRIEF §2, §4) as pure maths.
 *
 * A deck plate is a Cycles render through an orthographic camera pitched 60°
 * below the horizon with yaw 0: it looks toward −Z and down, screen right is
 * +X. A world point P lands on the plate at
 *
 *   u = (P − C)·R,   v = (P − C)·U
 *
 * metres from the plate centre C, with R = (1, 0, 0), U = (0, cos p, −sin p)
 * and the view direction D = (0, −sin p, −cos p). The plate's pixels are a
 * uniform grid over (u, v) at `pxPerMetre`, origin at the top-left corner.
 *
 * Everything the runtime draws into the photograph goes through these
 * functions, so plate, 3D world and screen stay aligned to the pixel.
 */

export type Vec3 = readonly [number, number, number];

export interface PlateCamera {
  /** Plate centre C, world metres (three.js axes). */
  center: Vec3;
  /** Pitch below the horizon, degrees (60 for every deck). */
  pitchDeg: number;
  /** Plate extent along u and v, metres. */
  frameW: number;
  frameH: number;
  /** Full-resolution (L0) density along u. */
  pxPerMetre: number;
}

export interface PlatePoint { u: number; v: number }

export interface CameraBasis {
  right: Vec3;
  up: Vec3;
  /** View direction D (from the camera into the scene). */
  dir: Vec3;
}

export function cameraBasis(pitchDeg: number): CameraBasis {
  const p = (pitchDeg * Math.PI) / 180;
  const s = Math.sin(p);
  const c = Math.cos(p);
  return { right: [1, 0, 0], up: [0, c, -s], dir: [0, -s, -c] };
}

export function worldToPlate(cam: PlateCamera, x: number, y: number, z: number): PlatePoint {
  const { up } = cameraBasis(cam.pitchDeg);
  const dx = x - cam.center[0];
  const dy = y - cam.center[1];
  const dz = z - cam.center[2];
  return { u: dx, v: dy * up[1] + dz * up[2] };
}

/** The world point at height `y` that the plate shows at (u, v): the view ray through it meets that plane. */
export function plateToWorldAtHeight(cam: PlateCamera, u: number, v: number, y = 0): [number, number, number] {
  const { up, dir } = cameraBasis(cam.pitchDeg);
  const qy = cam.center[1] + up[1] * v;
  const qz = cam.center[2] + up[2] * v;
  const t = (y - qy) / dir[1];
  return [cam.center[0] + u, y, qz + dir[2] * t];
}

/** Plate metres to L0 pixels (origin top-left, y down). */
export function plateToPixel(cam: PlateCamera, u: number, v: number): { x: number; y: number } {
  return { x: (u + cam.frameW / 2) * cam.pxPerMetre, y: (cam.frameH / 2 - v) * cam.pxPerMetre };
}

export function pixelToPlate(cam: PlateCamera, x: number, y: number): PlatePoint {
  return { u: x / cam.pxPerMetre - cam.frameW / 2, v: cam.frameH / 2 - y / cam.pxPerMetre };
}

/** Plate size in L0 pixels. */
export function platePixels(cam: PlateCamera): { width: number; height: number } {
  return { width: Math.round(cam.frameW * cam.pxPerMetre), height: Math.round(cam.frameH * cam.pxPerMetre) };
}

/** Plate metres a vertical segment of `heightM` spans on screen (it is foreshortened by cos p). */
export function verticalSpan(cam: PlateCamera, heightM: number): number {
  return heightM * Math.cos((cam.pitchDeg * Math.PI) / 180);
}
