/**
 * Which plate tiles a view needs. Pure.
 *
 * The overview (L1) is always resident and drawn under everything. Full
 * resolution (L0) tiles are streamed only once the overview would be
 * magnified on screen, and only those the view touches (plus a one-tile ring
 * to prefetch while the budget allows), nearest to the view centre first.
 */
import type { PlateImages } from "../content/deck";
import type { PlateCamera } from "./plateMath";

export interface TileKey { col: number; row: number }

export interface TileRect {
  /** Pixel rectangle in the L0 plate. */
  x: number;
  y: number;
  w: number;
  h: number;
  /** The same rectangle in plate metres. */
  u0: number;
  u1: number;
  v0: number;
  v1: number;
}

/** The overview may be magnified this much before L0 tiles stream in. */
export const OVERVIEW_MAGNIFY_LIMIT = 1.15;

export function tileKey(col: number, row: number): string {
  return `${col}_${row}`;
}

export function tileRect(plate: PlateImages, cam: PlateCamera, col: number, row: number): TileRect {
  const x = col * plate.tileSize;
  const y = row * plate.tileSize;
  const w = Math.min(plate.tileSize, plate.width - x);
  const h = Math.min(plate.tileSize, plate.height - y);
  const ppm = cam.pxPerMetre;
  return {
    x, y, w, h,
    u0: x / ppm - cam.frameW / 2,
    u1: (x + w) / ppm - cam.frameW / 2,
    v0: cam.frameH / 2 - (y + h) / ppm,
    v1: cam.frameH / 2 - y / ppm,
  };
}

/** True when the view shows the plate denser than the overview can (device px per L0 px). */
export function needsFullResolution(plate: PlateImages, densityL0: number): boolean {
  const overviewDensity = plate.overview.width / plate.width;
  return densityL0 > overviewDensity * OVERVIEW_MAGNIFY_LIMIT;
}

/**
 * Tiles touching the plate rectangle, grown by `ring` tiles, ordered nearest
 * to the rectangle's centre first.
 */
export function tilesInRect(
  plate: PlateImages, cam: PlateCamera,
  rect: { u0: number; u1: number; v0: number; v1: number }, ring = 0,
): TileKey[] {
  const ppm = cam.pxPerMetre;
  const ts = plate.tileSize;
  const px0 = (rect.u0 + cam.frameW / 2) * ppm;
  const px1 = (rect.u1 + cam.frameW / 2) * ppm;
  const py0 = (cam.frameH / 2 - rect.v1) * ppm;
  const py1 = (cam.frameH / 2 - rect.v0) * ppm;
  const c0 = Math.max(0, Math.floor(px0 / ts) - ring);
  const c1 = Math.min(plate.cols - 1, Math.ceil(px1 / ts) - 1 + ring);
  const r0 = Math.max(0, Math.floor(py0 / ts) - ring);
  const r1 = Math.min(plate.rows - 1, Math.ceil(py1 / ts) - 1 + ring);
  const cx = (px0 + px1) / 2;
  const cy = (py0 + py1) / 2;
  const out: { key: TileKey; d: number }[] = [];
  for (let row = r0; row <= r1; row++) {
    for (let col = c0; col <= c1; col++) {
      const d = Math.hypot((col + 0.5) * ts - cx, (row + 0.5) * ts - cy);
      out.push({ key: { col, row }, d });
    }
  }
  return out.sort((a, b) => a.d - b.d).map((o) => o.key);
}
