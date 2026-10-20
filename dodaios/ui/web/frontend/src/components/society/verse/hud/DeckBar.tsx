/**
 * The HUD's fixed parts: the deck title top left (number, name, who is on
 * duty) with the commander's rank card beside it, and the tool rail top right
 * (bird's-eye on or off, turbolift, bring the camera to the commander, help). Development builds
 * add a frame readout bottom right.
 */
import { useEffect, useRef, type ReactNode } from "react";
import { deckNumber, type DeckId } from "../decks";
import type { StageRuntime } from "../runtime";
import type { ControlMode } from "../life/control";

interface TitleProps {
  deck: DeckId;
  t: (key: string) => string;
  counts: { aboard: number; working: number; waiting: number };
  rankCard: ReactNode;
}

export function DeckTitle({ deck, t, counts, rankCard }: TitleProps) {
  return (
    <div className="verse-deck">
      <div className="verse-deck-head">
        <div className="verse-deck-number" aria-hidden>{String(deckNumber(deck)).padStart(2, "0")}</div>
        <div className="verse-deck-text">
          {/* Only the deck is announced when it changes; the crew counts below refresh too often to be read out. */}
          <div className="verse-deck-text" aria-live="polite" aria-atomic="true">
            <span className="verse-label">{t("verse.deck.label").replace("{n}", String(deckNumber(deck)))}</span>
            <span className="verse-deck-name">{t(`verse.deck.${deck}`)}</span>
          </div>
          <span className="verse-deck-sub">
            <span className="verse-label"><span className="verse-num">{counts.aboard}</span>{t("verse.crew.aboard").replace("{count}", "").trim()}</span>
            <span className="verse-label"><i className="verse-dot" data-state="working" /><span className="verse-num">{counts.working}</span>{t("verse.crew.working").replace("{count}", "").trim()}</span>
            {counts.waiting > 0 && (
              <span className="verse-label"><i className="verse-dot" data-state="waiting" /><span className="verse-num">{counts.waiting}</span>{t("verse.crew.waiting").replace("{count}", "").trim()}</span>
            )}
          </span>
        </div>
      </div>
      {/* Below the title, never beside it: the two never compete for width. */}
      {rankCard && <div className="verse-rank-slot">{rankCard}</div>}
    </div>
  );
}

interface ToolProps {
  t: (key: string) => string;
  /** Third person (the commander under the keys) or bird's-eye. */
  mode: ControlMode;
  onToggleView: () => void;
  onLift: () => void;
  onCommander: () => void;
  onHelp: () => void;
}

const icon = (d: string) => (
  <svg width="13" height="13" viewBox="0 0 13 13" aria-hidden fill="none" stroke="currentColor" strokeWidth="1.2"><path d={d} /></svg>
);

export function Toolbar({ t, mode, onToggleView, onLift, onCommander, onHelp }: ToolProps) {
  return (
    <nav className="verse-tools" aria-label={t("verse.stage.title")}>
      <button type="button" className="verse-tool" onClick={onToggleView} aria-pressed={mode === "overview"} title={`${t("verse.tools.overview")} (V)`}>
        {icon("M1 3.5l3.8-1.5 3.4 1.5L12 2v7.5L8.2 11 4.8 9.5 1 11zM4.8 2v7.5M8.2 3.5V11")}
        <span className="verse-tool-text">{t("verse.tools.overview")}</span>
        <kbd aria-hidden>V</kbd>
      </button>
      <button type="button" className="verse-tool" onClick={onLift} title={t("verse.tools.lift")}>
        {icon("M3.5 1.5v10M1 4l2.5-2.5L6 4M9.5 11.5v-10M7 9l2.5 2.5L12 9")}
        <span className="verse-tool-text">{t("verse.tools.lift")}</span>
      </button>
      <button type="button" className="verse-tool" onClick={onCommander} title={t("verse.tools.commander")}>
        {icon("M6.5 1v3M6.5 9v3M1 6.5h3M9 6.5h3M6.5 4.5a2 2 0 1 0 0 4a2 2 0 1 0 0-4")}
        <span className="verse-tool-text">{t("verse.tools.commander")}</span>
      </button>
      <button type="button" className="verse-tool" onClick={onHelp} title={t("verse.tools.help")}>
        {icon("M4.6 4.6a1.9 1.9 0 1 1 2.6 1.8c-.5.2-.7.6-.7 1.1v.6M6.5 10v.4")}
        <span className="verse-tool-text">{t("verse.tools.help")}</span>
      </button>
    </nav>
  );
}

/** Development readout: frame time, draw calls, triangles, tiles and the plate level streamed, actors. */
export function StatsReadout({ runtime }: { runtime: StageRuntime }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let last = 0;
    const show = () => {
      const now = performance.now();
      if (now - last < 500 || !ref.current) return;
      last = now;
      const s = runtime.stats;
      ref.current.textContent = `${s.frameMs.toFixed(1)} ms (${s.cpuMs.toFixed(1)} cpu)  ${s.drawCalls} calls  ${(s.triangles / 1000).toFixed(1)}k tris\n${s.tiles} tiles ${s.plateLevel} (${s.tilesLoading} loading)  ${s.actors} actors`;
    };
    runtime.afterFrame.add(show);
    return () => { runtime.afterFrame.delete(show); };
  }, [runtime]);
  return <div ref={ref} className="verse-panel verse-stats" aria-hidden />;
}
