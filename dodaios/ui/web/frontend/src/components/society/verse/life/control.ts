/**
 * How the person steers on the deck. Two modes:
 *
 * - third person (`follow`, the default): the movement keys walk the
 *   commander directly, the camera stays on them at a close zoom and follows
 *   wherever they go, and the use key works the station they stand at;
 * - bird's-eye (`overview`): the camera pulls back over the whole deck and
 *   the movement keys pan it, as in a map.
 *
 * Clicking the floor sends the commander walking in both. The keys are read
 * screen-relative: the plate camera looks toward −Z, so "up" is −Z and
 * "right" is +X. Pure apart from the held-key state.
 */
import type { Station } from "../content/deck";
import type { PanKey } from "../engine/viewController";
import type { Point } from "../nav/pathfind";

export type ControlMode = "follow" | "overview";

/** How far from a station the commander can still work it with the use key, metres. */
export const STATION_REACH_M = 2.2;

export class CommanderControl {
  mode: ControlMode = "follow";
  /** Shift is held: the commander hurries. */
  run = false;
  /** The camera should frame the commander at the third-person zoom as soon as they stand on the deck. */
  reframe = true;
  /** The person dragged the view to look around: the camera leaves the commander until they walk again. */
  looking = false;
  private keys = new Set<PanKey>();

  setKey(key: PanKey, down: boolean, run = false): void {
    if (down) this.keys.add(key);
    else this.keys.delete(key);
    this.run = run;
  }

  clearKeys(): void {
    this.keys.clear();
    this.run = false;
  }

  /** The wanted walking direction on the floor, unit length, or null when no movement key is held (or they cancel out). */
  direction(): Point | null {
    const x = (this.keys.has("right") ? 1 : 0) - (this.keys.has("left") ? 1 : 0);
    const z = (this.keys.has("down") ? 1 : 0) - (this.keys.has("up") ? 1 : 0);
    if (x === 0 && z === 0) return null;
    const n = Math.hypot(x, z);
    return { x: x / n, z: z / n };
  }
}

/** The station nearest to (x, z) within reach, or null. */
export function stationWithin(stations: readonly Station[], x: number, z: number, reach = STATION_REACH_M): Station | null {
  let best: Station | null = null;
  let bestD = reach;
  for (const s of stations) {
    const d = Math.hypot(s.x - x, s.z - z);
    if (d <= bestD) { bestD = d; best = s; }
  }
  return best;
}
