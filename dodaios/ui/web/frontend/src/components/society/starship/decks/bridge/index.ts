/**
 * Deck 1, the bridge. Nobody is invented here (population "none"): the
 * captain and the pet walk it; the seats and consoles are the captain's.
 * The captain's chair seats the captain (any movement stands up again), the
 * first officer's seat opens the lead agent's chat, the helm (and the star
 * chart) sets a course, operations opens the crew directory.
 */
import { captain, useShip } from "../../shipStore";
import type { DeckPlan } from "../../plan/types";
import { registerDeck, type DeckModule } from "../registry";
import { buildBridgeDeck } from "./bridgeDeck";
import { bridgeRuntime } from "./bridgeRuntime";
import { BridgeScene } from "./BridgeScene";
import { BridgePanel } from "./HelmPanel";
import "./props";

// The plan never changes: one build per session keeps the navigation grid and the merged deck.
let plan: DeckPlan | null = null;

const handleStation: NonNullable<DeckModule["useStation"]> = (station, deck, actions, far) => {
  switch (station.kind) {
    case "captain": {
      const seat = deck.places.find((p) => p.kind === "captain");
      if (!seat) return false;
      if (captain.seated) { actions.sit(null); return true; }
      if (far) {
        bridgeRuntime.seatRequestedMs = performance.now();
        useShip.getState().requestWalk({ x: station.x, z: station.z });
        return true;
      }
      actions.sit({ x: seat.x, z: seat.z, yaw: seat.yaw, seatY: seat.seatY });
      return true;
    }
    case "firstOfficer":
      if (bridgeRuntime.leadId) actions.openAgent(bridgeRuntime.leadId);
      else actions.say(actions.t("ship.bridge.no_first_officer"));
      return true;
    case "helm":
      actions.openPanel(station.id);
      return true;
    case "ops":
      actions.openLedger();
      return true;
    default:
      return false;
  }
};

registerDeck({
  id: "bridge",
  population: "none",
  build: () => (plan ??= buildBridgeDeck()),
  Scene: BridgeScene,
  useStation: handleStation,
  Panel: BridgePanel,
});
