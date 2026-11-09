/**
 * The Unreal Verse's simulator room opens the web arcade (`simulator.open
 * {programme}`, bridge contract 11). `handleVerseOpen` brings the app to the
 * Agents section and dispatches `VERSE_OPEN_SIMULATOR_EVENT`; this host, mounted
 * once in the main view, shows the cabinet for that programme on top of the
 * app. The retro player reports its own scored rounds to the level system; the
 * 3D Asteroid Run reports `simulator_record` when the commander leaves it with
 * a higher best than it started with, the same rule the three.js room used.
 */
import { lazy, Suspense, useEffect, useState } from "react";
import { ARCADE_GAMES, type ArcadeGameInfo, type RetroGameId } from "@/components/society/arcade/arcadeGames";
import { reportWorldAction } from "@/components/society/progression/progressionApi";
import { VERSE_OPEN_SIMULATOR_EVENT } from "./openRequest";

const RetroArcadeOverlay = lazy(() =>
  import("@/components/society/arcade/RetroArcadeOverlay").then((m) => ({ default: m.RetroArcadeOverlay })));
const ArcadeCabinet = lazy(() =>
  import("@/components/society/arcade/ArcadeCabinet").then((m) => ({ default: m.ArcadeCabinet })));

/** Where the 3D cabinet keeps its best score (the Unreal side imports this key once). */
export const ASTEROID_BEST_KEY = "jarvis.office.arcade.asteroids.best";

export function readAsteroidBest(storage: Pick<Storage, "getItem"> = window.localStorage): number {
  try {
    const n = Number(storage.getItem(ASTEROID_BEST_KEY));
    return Number.isFinite(n) && n > 0 ? n : 0;
  } catch {
    return 0;
  }
}

/** The programme the Verse named, or null for an id this build does not have. */
export function programmeById(id: string): ArcadeGameInfo | null {
  return ARCADE_GAMES.find((g) => g.id === id) ?? null;
}

export function SimulatorHost() {
  const [game, setGame] = useState<ArcadeGameInfo | null>(null);

  useEffect(() => {
    const onOpen = (event: Event) => {
      const programme = (event as CustomEvent<{ programme?: string }>).detail?.programme ?? "";
      const found = programmeById(programme);
      if (found) setGame(found);
    };
    window.addEventListener(VERSE_OPEN_SIMULATOR_EVENT, onOpen);
    return () => window.removeEventListener(VERSE_OPEN_SIMULATOR_EVENT, onOpen);
  }, []);

  const asteroids = game?.kind === "asteroid3d";
  useEffect(() => {
    if (!asteroids) return;
    const before = readAsteroidBest();
    return () => {
      if (readAsteroidBest() > before) void reportWorldAction("simulator_record", "asteroid-run");
    };
  }, [asteroids]);

  if (!game) return null;
  const close = () => setGame(null);
  return (
    <Suspense fallback={null}>
      <div data-testid="verse-simulator-host">
        {game.kind === "retro"
          ? <RetroArcadeOverlay gameId={game.id as RetroGameId} onClose={close} />
          : <ArcadeCabinet onClose={close} />}
      </div>
    </Suspense>
  );
}
