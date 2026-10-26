import { memo, useEffect, useMemo, useRef, type ReactNode } from "react";
import { fill, useT } from "@/i18n";
import { BotStage, useTypingPresence } from "../botStage/BotStage";
import type { TurnItem } from "../reduce";
import { ToolChoiceIcon } from "../ToolChoiceChips";
import { toolIdentityStyle } from "../toolIdentity";
import type { ToolChoice } from "../toolChoices";
import { activityOf, activityPhrase, presenceForFamily, type Activity, type NameOf } from "./activityModel";
import { usePacedActivity } from "./usePacedActivity";
import "./runView.css";

/** The line shows how long the agent has been at it only past this. */
export const TIMER_AFTER_MS = 60_000;

/**
 * The one live line under a running turn: the agent's face playing what it
 * does, and a short phrase for the step it is on ("Editing app.ts",
 * "Working in Gmail"), with a slow light sweep while it works. A turn that
 * runs longer than a minute adds how long, in whole minutes, so short steps
 * never get a ticking counter.
 *
 * The phrase is paced (usePacedActivity): it changes at most once per
 * 800 ms and keeps its words while the step stays the same. The stage does
 * not announce itself; the transcript's own announcer says when the agent
 * starts, replies, finishes, stops or asks.
 */
export const ActivityLine = memo(function ActivityLine({ turn, avatar, color, nameOf, peerFace }: {
  turn: TurnItem;
  avatar: ReactNode;
  color: string;
  nameOf?: NameOf;
  /** The face of a teammate the agent writes to, shown beside the phrase. */
  peerFace?: (peer: string) => ReactNode;
}) {
  const t = useT();
  const raw = useMemo(() => activityOf(turn, nameOf), [turn, nameOf]);
  const textLength = useMemo(() => turn.blocks.reduce((n, block) => n + (block.kind === "text" ? block.text.length : 0), 0), [turn.blocks]);
  // Words that stopped arriving are thinking again, not typing.
  const typing = useTypingPresence(raw?.family === "composing" ? "typing" : null, textLength);
  const current = useMemo<Activity | null>(() => raw && raw.family === "composing" && typing !== "typing"
    ? { ...raw, family: "thinking", phrase: "thinking" }
    : raw, [raw, typing]);
  const shown = usePacedActivity(current);
  if (!shown) return null;
  const phrase = activityPhrase(shown, t);
  const words = <span className="run-activity-words">
    {shown.family === "connecting" && shown.brand ? <BrandDot brand={shown.brand} label={shown.target} /> : null}
    {shown.family === "messaging" && shown.peer && peerFace ? <span aria-hidden className="run-activity-peer">{peerFace(shown.peer)}</span> : null}
    <span className="run-activity-phrase" data-testid="activity-phrase" data-family={shown.family}>{phrase}</span>
    <ElapsedSince since={turn.startedMs} />
  </span>;
  return <div className="run-activity" data-testid="activity-line" data-family={shown.family}>
    <BotStage presence={presenceForFamily(shown.family)} seed={turn.id} avatar={avatar} color={color}
      words={words} wordsId={shown.family} announce={false} />
  </div>;
});

function BrandDot({ brand, label }: { brand: string; label: string }) {
  const row: ToolChoice = {
    id: `plugin:${brand}`, label, brand, group: "", skill: "", category: "plugins",
    description: "", available: true, tool_names: [],
  };
  return <span aria-hidden className="tool-identity run-activity-brand" style={toolIdentityStyle(row)}>
    <ToolChoiceIcon row={row} size={14} />
  </span>;
}

/** "3 min", "1 h 05 min": whole minutes, so the line never ticks every second. */
export function formatLongElapsed(ms: number, t: (key: string) => string): string {
  const minutes = Math.floor(Math.max(0, ms) / 60_000);
  if (minutes < 60) return fill(t("run_view.timer.min"), { count: minutes });
  return fill(t("run_view.timer.hour"), { hours: Math.floor(minutes / 60), minutes: String(minutes % 60).padStart(2, "0") });
}

/**
 * How long the turn has run, hidden for its first minute. It writes its own
 * text, so the line around it never re-renders to tick.
 */
function ElapsedSince({ since }: { since: number }) {
  const t = useT();
  const ref = useRef<HTMLSpanElement | null>(null);
  useEffect(() => {
    const paint = () => {
      const el = ref.current;
      if (!el) return;
      const elapsed = Date.now() - since;
      const show = since > 0 && elapsed >= TIMER_AFTER_MS;
      el.hidden = !show;
      if (show) el.textContent = `· ${formatLongElapsed(elapsed, t)}`;
    };
    paint();
    const timer = window.setInterval(paint, 5_000);
    return () => window.clearInterval(timer);
  }, [since, t]);
  return <span ref={ref} hidden className="run-activity-timer" data-testid="activity-timer" aria-hidden />;
}
