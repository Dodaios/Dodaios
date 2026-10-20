/**
 * Which floor point a click on the plate means. The view ray through a plate
 * point crosses several heights (a raised walkway, the deck, a sunken crew
 * pit); the floor the person sees is the first walkable surface the ray meets
 * coming from the camera. Pure.
 */
import type { NavGrid } from "../content/deck";
import type { PlateCamera } from "../engine/plateMath";
import { plateToWorldAtHeight } from "../engine/plateMath";
import { cellIndex, nearestWalkable, type Point } from "./pathfind";

const STEP_M = 0.025;

export function pickFloor(cam: PlateCamera, grid: NavGrid, u: number, v: number): (Point & { y: number }) | null {
  let top = -Infinity;
  let bottom = Infinity;
  for (let i = 0; i < grid.heights.length; i++) {
    if (!grid.walkable[i]) continue;
    const h = grid.heights[i];
    if (h > top) top = h;
    if (h < bottom) bottom = h;
  }
  if (top === -Infinity) return null;
  // March down the ray from above the highest floor; the first cell whose floor the ray has reached is the hit.
  for (let y = top + STEP_M; y >= bottom - STEP_M; y -= STEP_M) {
    const [x, , z] = plateToWorldAtHeight(cam, u, v, y);
    const i = cellIndex(grid, x, z);
    if (i < 0 || !grid.walkable[i]) continue;
    if (grid.heights[i] >= y - STEP_M) return { x, z, y: grid.heights[i] };
  }
  // Nothing walkable under the pointer (a wall, a console): the nearest floor to where the deck level would be.
  const [x, , z] = plateToWorldAtHeight(cam, u, v, 0);
  const near = nearestWalkable(grid, { x, z }, 3);
  return near ? { ...near, y: grid.heights[cellIndex(grid, near.x, near.z)] ?? 0 } : null;
}
