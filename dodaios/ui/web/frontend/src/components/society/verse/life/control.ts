/**
 * How the person steers on the deck. Two modes:
 *
 * - third person (`follow`, the default): the movement keys walk the
 *   commander directly, the camera stays on them at a close zoom and follows
 *   wherever they go, and the use key works the station they stand at;
 * - bird's-eye (`overview`): the camera pulls back over the whole deck and
 *   the movement keys pan it, as in a map.
 *
 * Clicking the floor sends the commander walking in both. On the plate the
 * keys are read screen-relative: the plate camera looks toward −Z, so "up"
 * is −Z and "right" is +X; in the eye-level view they are read relative to
 * the camera behind the commander (`directionFrom`). Pure apart from the
 * held-key state.
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
  /** The commander rides the hoverboard (B): the keys glide much faster than a walk. */
  board = false;
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

  /** The held keys as screen axes: x right (+1) / left (−1), z down or toward the camera (+1) / up or away (−1). */
  axes(): { x: number; z: number } {
    return { x: this.axisX(), z: this.axisZ() };
  }

  private axisX(): number {
    return (this.keys.has("right") ? 1 : 0) - (this.keys.has("left") ? 1 : 0);
  }

  private axisZ(): number {
    return (this.keys.has("down") ? 1 : 0) - (this.keys.has("up") ? 1 : 0);
  }

  /**
   * The wanted walking direction on the floor, unit length, or null when no
   * movement key is held (or they cancel out); written into `out` when given.
   */
  direction(out?: Point): Point | null {
    const x = this.axisX();
    const z = this.axisZ();
    if (x === 0 && z === 0) return null;
    const n = Math.hypot(x, z);
    const o = out ?? { x: 0, z: 0 };
    o.x = x / n;
    o.z = z / n;
    return o;
  }

  /**
   * The eye-level view: the held keys relative to the camera (W walks away
   * from it), unit length or null; written into `out` when given (the frame
   * loop allocates nothing).
   */
  directionFrom(camera: CameraFrame, out?: Point): Point | null {
    return camera.walkDirection(this.axisX(), this.axisZ(), out);
  }
}

/** A camera that turns screen keys into a floor direction (the eye-level view's shoulder rig). */
export interface CameraFrame {
  walkDirection(ix: number, iz: number, out?: Point): Point | null;
}

/**
 * The station within reach of (x, z), or null: the nearest one, or, given
 * the direction the person looks along (`facing`, unit, on the floor), the
 * one most in front of them, so the use key works what they see when two
 * are in reach. A station straight behind counts as twice as far. Pure.
 */
export function stationWithin(
  stations: readonly Station[], x: number, z: number, reach = STATION_REACH_M, facing?: Point | null,
): Station | null {
  let best: Station | null = null;
  let bestScore = Infinity;
  for (const s of stations) {
    const dx = s.x - x;
    const dz = s.z - z;
    const d = Math.hypot(dx, dz);
    if (d > reach) continue;
    // One under the commander's feet counts as in front.
    const cos = facing && d > 0.3 ? (dx * facing.x + dz * facing.z) / d : 1;
    const score = d * (1.5 - 0.5 * cos);
    if (score < bestScore) { bestScore = score; best = s; }
  }
  return best;
}
