/**
 * The world actions only the visit itself can see, reported to the level
 * system (which meters them; reporting twice is harmless):
 *
 * - `inspection` (ref: deck id): the commander has set foot in every room of
 *   the deck; once per deck per day from this window.
 * - `walk_together`: every 50 m the commander walks with the companion drone
 *   at heel.
 * - `team_briefing` (ref: team id): a team round gathers while the commander
 *   is on the bridge, where the briefing room is.
 */
import { useEffect, useRef } from "react";
import type { Deck } from "../content/deck";
import type { DeckId } from "../decks";
import type { StageRuntime } from "../runtime";
import { reportWorldAction } from "../../progression/progressionApi";
import { insidePolygon } from "../actors/roomLight";
import { COMMANDER_ID, COMPANION_ID } from "./cast";

const TICK_MS = 500;
const WALK_TOGETHER_M = 50;
/** The drone counts as at heel within this distance. */
const HEEL_M = 2.5;

/** The rooms of `deck` that contain (x, z). Pure. */
export function roomsAt(deck: Pick<Deck, "rooms">, x: number, y: number, z: number): string[] {
  return deck.rooms.filter((r) => Math.abs(r.floorY - y) < 1.2 && insidePolygon(x, z, r.polygon)).map((r) => r.id);
}

export function useWorldActions(runtime: StageRuntime, deck: Deck | null, deckId: DeckId, awake: boolean, runningTeams: ReadonlySet<string>): void {
  const inspected = useRef(new Set<string>());

  useEffect(() => {
    if (!awake || !deck || deck.rooms.length === 0) return;
    const visited = new Set<string>();
    let last: { x: number; z: number } | null = null;
    let together = 0;
    const timer = setInterval(() => {
      const me = runtime.poses.get(COMMANDER_ID);
      if (!me) return;
      for (const id of roomsAt(deck, me.x, me.y, me.z)) visited.add(id);
      const day = new Date().toDateString();
      const key = `${deck.id}:${day}`;
      if (!inspected.current.has(key) && deck.rooms.every((r) => visited.has(r.id))) {
        inspected.current.add(key);
        void reportWorldAction("inspection", deck.id);
      }
      const drone = runtime.poses.get(COMPANION_ID);
      if (last && drone && Math.hypot(drone.x - me.x, drone.z - me.z) < HEEL_M) {
        together += Math.hypot(me.x - last.x, me.z - last.z);
        if (together >= WALK_TOGETHER_M) {
          together -= WALK_TOGETHER_M;
          void reportWorldAction("walk_together");
        }
      }
      last = { x: me.x, z: me.z };
    }, TICK_MS);
    return () => clearInterval(timer);
  }, [runtime, deck, awake]);

  const briefed = useRef(new Set<string>());
  useEffect(() => {
    if (!awake || deckId !== "bridge") return;
    for (const team of runningTeams) {
      if (briefed.current.has(team)) continue;
      briefed.current.add(team);
      void reportWorldAction("team_briefing", team);
    }
    // A round that ended can gather again later.
    for (const team of briefed.current) if (!runningTeams.has(team)) briefed.current.delete(team);
  }, [runningTeams, deckId, awake]);
}
