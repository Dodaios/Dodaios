/**
 * A holo cabinet's program: the game's player, loaded the first time it is
 * needed. The retro games open RetroArcadeOverlay with a metered loader;
 * Asteroid Run opens its 3D cabinet. Closing the game closes the panel.
 */
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef } from "react";
import { useLocaleChunk } from "@/i18n";
import { arcadeGame, type RetroGameId } from "../../../arcade/arcadeGames";
import type { DeckPanelProps } from "../registry";
import { meteredLoader, readAsteroidBest } from "./holodeckMeter";
import "./holodeck.css";

const RetroArcadeOverlay = lazy(() => import("../../../arcade/RetroArcadeOverlay").then((m) => ({ default: m.RetroArcadeOverlay })));
const ArcadeCabinet = lazy(() => import("../../../arcade/ArcadeCabinet").then((m) => ({ default: m.ArcadeCabinet })));

export function HolodeckPanel({ station, actions }: DeckPanelProps) {
  // The players' own strings live in the society chunk.
  const ready = useLocaleChunk("society");
  const game = station.ref ? arcadeGame(station.ref) : null;
  // The stage's actions are rebuilt on every render; the game's callbacks must stay put.
  const actionsRef = useRef(actions);
  actionsRef.current = actions;
  const close = useCallback(() => actionsRef.current.closePanel(), []);
  const loader = useMemo(() => meteredLoader((action, ref) => actionsRef.current.reportAction(action, ref)), []);

  // Asteroid Run tells nobody about its rounds; a new best on leaving it counts as a record.
  const asteroids = game?.kind === "asteroid3d";
  useEffect(() => {
    if (!asteroids) return;
    const before = readAsteroidBest();
    return () => { if (readAsteroidBest() > before) actionsRef.current.reportAction("holodeck_record", "asteroid-run"); };
  }, [asteroids]);

  const t = actions.t;
  if (!game) {
    return (
      <div className="ship-scrim holo-scrim" onClick={close}>
        <section className="ship-panel holo-card" role="alertdialog" aria-modal="true" aria-label={t("ship.holodeck.room")} onClick={(e) => e.stopPropagation()}>
          <p>{t("ship.holodeck.missing")}</p>
          <button type="button" className="ship-btn" data-primary="true" autoFocus onClick={close}>{t("ship.close")}</button>
        </section>
      </div>
    );
  }
  const loading = (
    <div className="ship-scrim holo-scrim">
      <div className="ship-panel holo-card holo-loading" role="status" aria-live="polite">
        <span className="holo-loading-mark" aria-hidden />
        <span>
          <span className="ship-eyebrow">{t("ship.holodeck.program")}</span>
          <span className="holo-loading-title">{game.title}</span>
          <small>{t("ship.holodeck.loading")}</small>
        </span>
      </div>
    </div>
  );
  if (!ready) return loading;
  return (
    <Suspense fallback={loading}>
      {game.kind === "retro"
        ? <RetroArcadeOverlay gameId={game.id as RetroGameId} loadGame={loader} report={false} onClose={close} />
        : <ArcadeCabinet onClose={close} />}
    </Suspense>
  );
}
