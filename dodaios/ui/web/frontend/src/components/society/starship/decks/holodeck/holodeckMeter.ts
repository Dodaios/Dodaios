/**
 * Metering the holodeck's games for the level system. The retro overlay has
 * no round callback, but it takes the loader of its game, so the holodeck
 * hands it the same game with a watched `status`: the first time a run reads
 * as over, a scored round is reported, as a record when it beats the stored
 * best. The overlay checks `status` right after the step that ends a run and
 * only then stores the new best, so the best read here is still the old one.
 */
import { loadRetroGame, type RetroGameId } from "../../../arcade/arcadeGames";
import type { RetroGame, RetroStatus } from "../../../arcade/retroGame";
import { readBest } from "../../../arcade/retroScores";

export type HolodeckAction = "holodeck_round" | "holodeck_record";
export type Report = (action: HolodeckAction, gameId: string) => void;

/** The same game, reporting each finished, scored run once. */
export function meteredGame<S>(game: RetroGame<S>, gameId: string, report: Report): RetroGame<S> {
  const finished = new WeakSet<object>();
  let finishedValue: unknown = undefined;
  const status = (state: S): RetroStatus => {
    const s = game.status(state);
    if (!s.over) return s;
    // States are objects in every game; a primitive state is remembered by value instead.
    const isObject = typeof state === "object" && state !== null;
    if (isObject ? finished.has(state as object) : finishedValue === state) return s;
    if (isObject) finished.add(state as object); else finishedValue = state;
    const score = Math.max(0, Math.floor(s.score));
    if (score > 0) report(score > readBest(gameId) ? "holodeck_record" : "holodeck_round", gameId);
    return s;
  };
  return Object.assign(Object.create(game) as RetroGame<S>, { status });
}

/** A loader for RetroArcadeOverlay that meters every game it loads. */
export function meteredLoader(report: Report): (id: RetroGameId) => Promise<RetroGame<unknown>> {
  return (id) => loadRetroGame(id).then((game) => meteredGame(game as RetroGame<unknown>, id, report));
}

/** Asteroid Run keeps its best score here (office/ArcadeCabinet.tsx); it has no loader to watch. */
export const ASTEROID_BEST_KEY = "jarvis.office.arcade.asteroids.best";

export function readAsteroidBest(): number {
  try {
    const n = Number(window.localStorage.getItem(ASTEROID_BEST_KEY));
    return Number.isFinite(n) && n > 0 ? Math.floor(n) : 0;
  } catch {
    return 0;
  }
}
