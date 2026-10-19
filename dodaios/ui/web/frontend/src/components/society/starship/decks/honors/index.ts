/**
 * Deck 5, the Hall of Honour: the rank wall, the dais and the display cases.
 * Its stations (the rank wall and the cases) open the captain's service
 * record, which the stage owns; this module draws the hall and leaves them be.
 */
import { registerDeck } from "../registry";
import { buildHonorsDeck } from "./honorsPlan";
import { HonorsScene } from "./HonorsScene";
import "./honorsProps";

// The plan depends on nothing but the rank ladder: build it once.
let plan: ReturnType<typeof buildHonorsDeck> | null = null;

registerDeck({
  id: "honors",
  population: "none",
  build: () => (plan ??= buildHonorsDeck()),
  Scene: HonorsScene,
});
