/**
 * Deck 4, the holodeck: the ship's ten retro games as holographic cabinets.
 * Using a cabinet opens its program in the deck's panel.
 */
import { arcadeGame } from "../../../arcade/arcadeGames";
import { registerDeck } from "../registry";
import { buildHolodeck } from "./holodeckPlan";
import { HolodeckPanel } from "./HolodeckPanel";
import { HolodeckScene } from "./HolodeckScene";
import "./holodeckProps";

// The plan depends on nothing but the game list: build it once.
let plan: ReturnType<typeof buildHolodeck> | null = null;

registerDeck({
  id: "holodeck",
  population: "none",
  build: () => (plan ??= buildHolodeck()),
  Scene: HolodeckScene,
  useStation: (station, _plan, actions) => {
    if (station.kind !== "holoCabinet") return false;
    actions.openPanel(station.id);
    return true;
  },
  Panel: HolodeckPanel,
  // The prompt names the game: "E · Play · Neon Snake".
  stationName: (station) => (station.kind === "holoCabinet" && station.ref ? arcadeGame(station.ref)?.title : undefined),
});
