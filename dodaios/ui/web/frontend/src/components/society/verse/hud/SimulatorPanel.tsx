/**
 * The simulator room: the ship's games. A list of programmes; choosing one
 * opens the existing arcade player (its code loads only then). The retro
 * player reports its own scored rounds to the level system; the 3D asteroid
 * run reports a new best when the commander leaves it.
 */
import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { useLocaleChunk } from "@/i18n";
import { ARCADE_GAMES, type ArcadeGameInfo, type RetroGameId } from "../../arcade/arcadeGames";
import { reportWorldAction } from "../../progression/progressionApi";
import { useReturnFocus, VerseDialog } from "./VerseDialog";

const RetroArcadeOverlay = lazy(() => import("../../arcade/RetroArcadeOverlay").then((m) => ({ default: m.RetroArcadeOverlay })));
const ArcadeCabinet = lazy(() => import("../../arcade/ArcadeCabinet").then((m) => ({ default: m.ArcadeCabinet })));

/** Where the 3D cabinet keeps its best score. */
const ASTEROID_BEST_KEY = "jarvis.office.arcade.asteroids.best";

function asteroidBest(): number {
  try {
    const n = Number(window.localStorage.getItem(ASTEROID_BEST_KEY));
    return Number.isFinite(n) && n > 0 ? n : 0;
  } catch {
    return 0;
  }
}

export function SimulatorPanel({ t, onClose }: { t: (key: string) => string; onClose: () => void }) {
  const ready = useLocaleChunk("society");
  const [game, setGame] = useState<ArcadeGameInfo | null>(null);
  const first = useRef<HTMLButtonElement>(null);
  // The panel outlives its list (a game takes the list's place), so the panel puts focus back when it closes.
  useReturnFocus();

  const asteroids = game?.kind === "asteroid3d";
  useEffect(() => {
    if (!asteroids) return;
    const before = asteroidBest();
    return () => { if (asteroidBest() > before) void reportWorldAction("simulator_record", "asteroid-run"); };
  }, [asteroids]);

  if (game) {
    const loading = <div className="verse-status" role="status">{t("verse.games.loading")}</div>;
    return (
      <Suspense fallback={loading}>
        {game.kind === "retro"
          ? <RetroArcadeOverlay gameId={game.id as RetroGameId} onClose={onClose} />
          : <ArcadeCabinet onClose={onClose} />}
      </Suspense>
    );
  }

  return (
    <VerseDialog title={t("verse.games.title")} closeLabel={t("verse.card.close")} onClose={onClose} initialFocus={first} returnFocus={false}>
      {ARCADE_GAMES.map((g, i) => (
        <button key={g.id} ref={i === 0 ? first : undefined} type="button" className="verse-lift-row" onClick={() => setGame(g)}>
          <b>{String(i + 1).padStart(2, "0")}</b>
          <span className="verse-lift-name">
            <span>{g.title}</span>
            {ready && <small>{t(`society.arcade.games.${g.key}.tagline`)}</small>}
          </span>
        </button>
      ))}
    </VerseDialog>
  );
}
