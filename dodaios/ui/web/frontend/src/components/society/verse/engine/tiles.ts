/**
 * Which plate images and tiles a view needs. Pure.
 *
 * A plate comes as a pyramid: the overview (the whole plate in one small
 * image, always resident and drawn under everything), optional tiled mips
 * (M4, M2: the plate downscaled by 4 and 2) and the full-density L0 tiles.
 * The view streams the coarsest level that is still sharp at its density
 * (plateLevelFor), and of that level only the tiles it touches, plus a
 * one-tile ring to prefetch while the budget allows, nearest to the view
 * centre first. A deck cooked without mips has just the overview and L0.
 */
import type { PlateImages } from "../content/deck";
import type { PlateCamera } from "./plateMath";

export interface TileKey {
  col: number;
  row: number;
  /** Index into PlateImages.levels; 0 (L0) when absent. */
  level?: number;
}

export interface TileRect {
  /** Pixel rectangle in the L0 plate (fractional for a mip whose size was rounded). */
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

/** Tile columns c0…c1 and rows r0…r1 of one level; empty when c1 < c0 or r1 < r0. */
export interface TileRange {
  level: number;
  c0: number;
  c1: number;
  r0: number;
  r1: number;
}

export interface PlateRect { u0: number; u1: number; v0: number; v1: number }

/** Any image of the plate (overview or tile level) may be magnified this much before a finer one streams in. */
export const OVERVIEW_MAGNIFY_LIMIT = 1.15;

/** plateLevelFor's answer when the overview alone is sharp enough. */
export const OVERVIEW_LEVEL = -1;

export function tileKey(col: number, row: number, level = 0): string {
  return level === 0 ? `${col}_${row}` : `${level}:${col}_${row}`;
}

/** L0 pixels per pixel of a level, along x (≈ its divisor, exact for a rounded size). */
function levelScaleX(plate: PlateImages, level: number): number {
  return plate.width / plate.levels[level].width;
}

function levelScaleY(plate: PlateImages, level: number): number {
  return plate.height / plate.levels[level].height;
}

export function tileRect(plate: PlateImages, cam: PlateCamera, col: number, row: number, level = 0): TileRect {
  const lv = plate.levels[level];
  const ts = lv.tileSize;
  const sx = levelScaleX(plate, level);
  const sy = levelScaleY(plate, level);
  const x = col * ts * sx;
  const y = row * ts * sy;
  const w = Math.min(ts, lv.width - col * ts) * sx;
  const h = Math.min(ts, lv.height - row * ts) * sy;
  const ppm = cam.pxPerMetre;
  return {
    x, y, w, h,
    u0: x / ppm - cam.frameW / 2,
    u1: (x + w) / ppm - cam.frameW / 2,
    v0: cam.frameH / 2 - (y + h) / ppm,
    v1: cam.frameH / 2 - y / ppm,
  };
}

/**
 * The image that shows the plate at this density (device px per L0 px): the
 * coarsest one that is magnified at most OVERVIEW_MAGNIFY_LIMIT. Returns
 * OVERVIEW_LEVEL for the overview, else an index into plate.levels (0 = L0,
 * also when even L0 is magnified, up to the zoom limit). Without mips this is
 * the overview until it would be magnified, then L0.
 */
export function plateLevelFor(plate: PlateImages, densityL0: number): number {
  if (densityL0 * (plate.width / plate.overview.width) <= OVERVIEW_MAGNIFY_LIMIT) return OVERVIEW_LEVEL;
  let best = 0;
  let bestScale = 1;
  for (let i = 1; i < plate.levels.length; i++) {
    const s = levelScaleX(plate, i);
    if (s > bestScale && densityL0 * s <= OVERVIEW_MAGNIFY_LIMIT) { best = i; bestScale = s; }
  }
  return best;
}

/** True when the view shows the plate denser than the overview can (device px per L0 px): tiles must stream. */
export function needsFullResolution(plate: PlateImages, densityL0: number): boolean {
  return plateLevelFor(plate, densityL0) !== OVERVIEW_LEVEL;
}

/** The tiles of `level` touching the plate rectangle, grown by `ring` tiles. Allocation-free with `out`. */
export function tileRange(
  plate: PlateImages, cam: PlateCamera, rect: PlateRect, ring = 0, level = 0,
  out: TileRange = { level, c0: 0, c1: -1, r0: 0, r1: -1 },
): TileRange {
  const lv = plate.levels[level];
  const ts = lv.tileSize;
  // Level pixels per plate metre.
  const kx = cam.pxPerMetre / levelScaleX(plate, level);
  const ky = cam.pxPerMetre / levelScaleY(plate, level);
  const px0 = (rect.u0 + cam.frameW / 2) * kx;
  const px1 = (rect.u1 + cam.frameW / 2) * kx;
  const py0 = (cam.frameH / 2 - rect.v1) * ky;
  const py1 = (cam.frameH / 2 - rect.v0) * ky;
  out.level = level;
  out.c0 = Math.max(0, Math.floor(px0 / ts) - ring);
  out.c1 = Math.min(lv.cols - 1, Math.ceil(px1 / ts) - 1 + ring);
  out.r0 = Math.max(0, Math.floor(py0 / ts) - ring);
  out.r1 = Math.min(lv.rows - 1, Math.ceil(py1 / ts) - 1 + ring);
  return out;
}

export function sameRange(a: TileRange, b: TileRange): boolean {
  return a.level === b.level && a.c0 === b.c0 && a.c1 === b.c1 && a.r0 === b.r0 && a.r1 === b.r1;
}

export function inRange(r: TileRange, col: number, row: number): boolean {
  return col >= r.c0 && col <= r.c1 && row >= r.r0 && row <= r.r1;
}

/**
 * Tiles of `level` touching the plate rectangle, grown by `ring` tiles,
 * ordered nearest to the rectangle's centre first.
 */
export function tilesInRect(plate: PlateImages, cam: PlateCamera, rect: PlateRect, ring = 0, level = 0): TileKey[] {
  const r = tileRange(plate, cam, rect, ring, level);
  const ts = plate.levels[level].tileSize;
  const kx = cam.pxPerMetre / levelScaleX(plate, level);
  const ky = cam.pxPerMetre / levelScaleY(plate, level);
  const cx = ((rect.u0 + rect.u1) / 2 + cam.frameW / 2) * kx;
  const cy = (cam.frameH / 2 - (rect.v0 + rect.v1) / 2) * ky;
  const out: { key: TileKey; d: number }[] = [];
  for (let row = r.r0; row <= r.r1; row++) {
    for (let col = r.c0; col <= r.c1; col++) {
      const d = Math.hypot((col + 0.5) * ts - cx, (row + 0.5) * ts - cy);
      out.push({ key: { col, row, level }, d });
    }
  }
  return out.sort((a, b) => a.d - b.d).map((o) => o.key);
}
