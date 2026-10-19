/**
 * What the bridge's stations, its panel and its scene share outside React:
 * who the first officer is (the scene learns it from the roster), a seat the
 * captain is walking to, and the warp jump itself, whose timer must outlive
 * the helm's panel (the panel closes as the jump begins).
 */
import type { ShipActions } from "../registry";
import { useShip } from "../../shipStore";
import type { DestinationId } from "../../space/destinations";

export const bridgeRuntime = {
  /** The lead agent (the person's own assistant): the ship's first officer. */
  leadId: null as string | null,
  /** The captain was sent to the chair and sits down on arrival; the time it was asked. */
  seatRequestedMs: 0,
};

/** How long the streaks run before the ship drops out at the new destination. */
export const WARP_MS = 2600;

let timer: ReturnType<typeof setTimeout> | null = null;

/**
 * Jump to `id`: the streaks run for `WARP_MS`, then the sky changes under the
 * flash. With reduced motion the ship is there at once. A second order while
 * a jump runs is ignored.
 */
export function engageWarp(id: DestinationId, reduced: boolean, actions: Pick<ShipActions, "reportAction">): boolean {
  const ship = useShip.getState();
  if (ship.warpingTo || id === ship.destination) return false;
  if (reduced) {
    ship.setDestination(id);
    actions.reportAction("warp_jump", id);
    return true;
  }
  ship.setWarping(id);
  if (timer) clearTimeout(timer);
  timer = setTimeout(() => {
    timer = null;
    const s = useShip.getState();
    s.setDestination(id);
    s.setWarping(null);
    actions.reportAction("warp_jump", id);
  }, WARP_MS);
  return true;
}
