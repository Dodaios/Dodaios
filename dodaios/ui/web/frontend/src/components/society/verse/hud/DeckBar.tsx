/**
 * The HUD's fixed parts: the deck title top left (number, name, who is on
 * duty) with the commander's rank card beside it, and the tool rail top right
 * (the view: bird's-eye, third or first person; turbolift; bring the camera to the
 * commander; the eye-level view's settings; help). Development builds add a
 * frame readout under the rail.
 */
import { useEffect, useRef, type ReactNode } from "react";
import { deckNumber, type DeckId } from "../decks";
import type { FrameStats, StageRuntime } from "../runtime";
import { VIEW_ORDER, keyForView, type VerseView } from "../engine/realtime/viewMode";

interface TitleProps {
  deck: DeckId;
  t: (key: string) => string;
  counts: { aboard: number; working: number; waiting: number };
  rankCard: ReactNode;
  /** Opens the turbolift. The title is where people look for the other decks, so the switch sits right on it. */
  onLift: () => void;
}

/** The duel's mark (a sight): the tool rail's Duel button and the arena icon on the bird's-eye view. */
export const DUEL_ICON = "M6.5 1v2.6M6.5 9.4V12M1 6.5h2.6M9.4 6.5H12M6.5 3.6a2.9 2.9 0 1 0 0 5.8a2.9 2.9 0 1 0 0-5.8";

const LIFT_ICON ="M3.5 1.5v10M1 4l2.5-2.5L6 4M9.5 11.5v-10M7 9l2.5 2.5L12 9";

export function DeckTitle({ deck, t, counts, rankCard, onLift }: TitleProps) {
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
        <button type="button" className="verse-deck-switch" onClick={onLift} title={t("verse.tools.lift")}>
          {icon(LIFT_ICON)}
          <span>{t("verse.lift.switch")}</span>
        </button>
      </div>
      {/* Below the title, never beside it: the two never compete for width. */}
      {rankCard && <div className="verse-rank-slot">{rankCard}</div>}
    </div>
  );
}

interface ToolProps {
  t: (key: string) => string;
  /** The view on screen: bird's-eye, third or first person. */
  view: VerseView;
  /** First person needs the deck's eye-level scene on the full-size stage or a roomy enough side panel. */
  firstAvailable: boolean;
  /** Why first person is off, when it is not the default reason (a side panel too small). */
  firstUnavailable?: string;
  onView: (view: VerseView) => void;
  onLift: () => void;
  /** The hoverboard is out (B). */
  board?: boolean;
  /** Fold the hoverboard out or away (absent: no board button). */
  onBoard?: () => void;
  onCommander: () => void;
  /** The eye-level view's settings; absent where the deck has no eye-level view on this stage. */
  onSettings?: () => void;
  /** Start a duel (absent where duels cannot run: the compact panel). */
  onDuel?: () => void;
  onHelp: () => void;
}

const icon = (d: string) => (
  <svg width="13" height="13" viewBox="0 0 13 13" aria-hidden fill="none" stroke="currentColor" strokeWidth="1.2"><path d={d} /></svg>
);

const VIEW_LOOKS: Readonly<Record<VerseView, { label: string; path: string }>> = {
  overview: { label: "verse.tools.overview", path: "M1 3.5l3.8-1.5 3.4 1.5L12 2v7.5L8.2 11 4.8 9.5 1 11zM4.8 2v7.5M8.2 3.5V11" },
  third: { label: "verse.tools.follow", path: "M6.5 1.5a2 2 0 1 0 0 4a2 2 0 1 0 0-4M2.5 11.5c0-2.4 1.8-4.2 4-4.2s4 1.8 4 4.2" },
  first: { label: "verse.tools.first", path: "M1 6.5c1.6-2.6 3.4-3.9 5.5-3.9s3.9 1.3 5.5 3.9c-1.6 2.6-3.4 3.9-5.5 3.9S2.6 9.1 1 6.5zM6.5 5a1.5 1.5 0 1 0 0 3a1.5 1.5 0 1 0 0-3" },
};

export function Toolbar({ t, view, firstAvailable, firstUnavailable, onView, onLift, board, onBoard, onCommander, onSettings, onDuel, onHelp }: ToolProps) {
  return (
    <nav className="verse-tools" aria-label={t("verse.stage.title")}>
      {/* The three views side by side, the one on screen pressed; 1, 2 and 3 pick one, V cycles them. */}
      <div className="verse-view-switch" role="group" aria-label={t("verse.tools.view")}>
        {VIEW_ORDER.map((v) => {
          const look = VIEW_LOOKS[v];
          const key = keyForView(v);
          const off = v === "first" && !firstAvailable;
          return (
            <button
              key={v}
              type="button"
              className="verse-tool"
              data-view={v}
              aria-pressed={view === v}
              disabled={off}
              onClick={() => onView(v)}
              title={off ? firstUnavailable ?? t("verse.tools.first_unavailable") :`${t(look.label)} (${key}, V)`}
            >
              {icon(look.path)}
              <span className="verse-tool-text">{t(look.label)}</span>
              <kbd aria-hidden>{key}</kbd>
            </button>
          );
        })}
      </div>
      <button type="button" className="verse-tool" onClick={onLift} title={t("verse.tools.lift")}>
        {icon(LIFT_ICON)}
        <span className="verse-tool-text">{t("verse.tools.lift")}</span>
      </button>
      {onBoard && (
        <button type="button" className="verse-tool" data-tool="board" aria-pressed={!!board} onClick={onBoard} title={`${t("verse.tools.board")} (B)`}>
          {icon("M1.5 7.5h10a1 1 0 0 1 0 1.6h-10a1 1 0 0 1 0-1.6M3.5 9.1v1.6M9.5 9.1v1.6M5 5.5h3M6.5 2v3.5")}
          <span className="verse-tool-text">{t("verse.tools.board")}</span>
          <kbd aria-hidden>B</kbd>
        </button>
      )}
      <button type="button" className="verse-tool" onClick={onCommander} title={t("verse.tools.commander")}>
        {icon("M6.5 1v3M6.5 9v3M1 6.5h3M9 6.5h3M6.5 4.5a2 2 0 1 0 0 4a2 2 0 1 0 0-4")}
        <span className="verse-tool-text">{t("verse.tools.commander")}</span>
      </button>
      {onDuel && (
        <button type="button" className="verse-tool" data-tool="duel" onClick={onDuel} title={t("verse.tools.duel_hint")} aria-label={`${t("verse.tools.duel")}: ${t("verse.tools.duel_hint")}`}>
          {icon(DUEL_ICON)}
          <span className="verse-tool-text">{t("verse.tools.duel")}</span>
        </button>
      )}
      {onSettings && (
        <button type="button" className="verse-tool" onClick={onSettings} title={t("verse.tools.settings")} aria-label={t("verse.tools.settings")}>
          {icon("M1 3.5h6.5M10.5 3.5H12M7.5 2v3M10.5 2v3M1 9.5h1.5M5.5 9.5H12M2.5 8v3M5.5 8v3")}
        </button>
      )}
      <button type="button" className="verse-tool" onClick={onHelp} title={t("verse.tools.help")}>
        {icon("M4.6 4.6a1.9 1.9 0 1 1 2.6 1.8c-.5.2-.7.6-.7 1.1v.6M6.5 10v.4")}
        <span className="verse-tool-text">{t("verse.tools.help")}</span>
      </button>
    </nav>
  );
}

/**
 * The development readout's text: frame rate and time, render cost, then
 * the view (the eye level's quality tier, or the plate's tiles and level)
 * and the actors. Pure.
 */
export function statsText(s: FrameStats): string {
  const fps = s.frameMs > 0 ? Math.round(1000 / s.frameMs) : 0;
  const view = s.plateLevel === "3D"
    ? `eye level, ${s.tier || "?"} tier`
    : `${s.tiles} tiles ${s.plateLevel} (${s.tilesLoading} loading)`;
  return `${fps} fps  ${s.frameMs.toFixed(1)} ms (${s.cpuMs.toFixed(1)} cpu)  ${s.drawCalls} calls  ${(s.triangles / 1000).toFixed(1)}k tris\n${view}  ${s.actors} actors`;
}

/** Development readout under the tool rail (`statsText`), refreshed twice a second. */
export function StatsReadout({ runtime }: { runtime: StageRuntime }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let last = 0;
    const show = () => {
      const now = performance.now();
      if (now - last < 500 || !ref.current) return;
      last = now;
      ref.current.textContent = statsText(runtime.stats);
    };
    runtime.afterFrame.add(show);
    return () => { runtime.afterFrame.delete(show); };
  }, [runtime]);
  return <div ref={ref} className="verse-panel verse-stats" aria-hidden />;
}
