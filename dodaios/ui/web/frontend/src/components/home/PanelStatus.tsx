import { useEffect, useMemo, useRef, useState } from "react";

import { activityOf, activityPhrase, type ActivityFamily } from "@/components/agentchat/activity/activityModel";
import { usePacedActivity } from "@/components/agentchat/activity/usePacedActivity";
import type { TimelineItem, TurnStatus } from "@/components/agentchat/reduce";
import { assistantNow, type AssistantNow } from "@/components/home/assistantNow";
import { petStateForVoice } from "@/components/pets/PetMark";
import { useVoiceReadiness } from "@/hooks/useVoiceReadiness";
import { fill, useT } from "@/i18n";
import { ONE_SHOT_MS, type PetState } from "@/lib/petStates";
import { cn } from "@/lib/utils";
import { useAgentChatStore } from "@/store/agentChat";
import { useEventStore } from "@/store/events";

type Tone = "life" | "attention" | "quiet";

const IDLE: AssistantNow = { kind: "idle" };

const DOT: Record<Tone, string> = {
  life: "bg-success",
  attention: "bg-warning",
  quiet: "",
};

/** What the panel's header shows: the line under the name and the pet's row beside it. */
export interface PanelNow {
  /** `data-state` of the line: idle, working, waiting, background, call, starting, offline. */
  state: string;
  tone: Tone;
  text: string;
  /** The animation row of the pet beside the name, read off the same state as the line. */
  pet: PetState;
}

/**
 * The pet row for one step of a running turn, in the activity line's verb
 * families: it thinks while the line says "Thinking", looks things up while
 * it searches, reads or browses, talks while the reply streams in, and works
 * for everything else it does with a tool.
 */
export function petForFamily(family: ActivityFamily): PetState {
  switch (family) {
    case "thinking":
      return "thinking";
    case "composing":
      return "talking";
    case "searching":
    case "reading":
    case "browsing":
    case "recalling":
      return "searching";
    case "waiting":
      return "listening";
    default:
      return "working";
  }
}

/** The newest turn of the chat on stage, as far as its outcome goes. */
function latestTurn(items: readonly TimelineItem[]): { id: string; status: TurnStatus } | null {
  for (let i = items.length - 1; i >= 0; i--) {
    const item = items[i];
    if (item.type === "turn") return { id: item.id, status: item.status };
  }
  return null;
}

/**
 * A short success or error row when the turn the person watched run ends:
 * only on the change from running to done or to error, seen live. A turn that
 * was already over when the chat came on stage, or one the person stopped,
 * plays nothing. The row holds for a pet's one-shot time.
 */
export function useOutcomeFlash(items: readonly TimelineItem[], live: boolean): PetState | null {
  const latest = live ? latestTurn(items) : null;
  const id = latest?.id ?? "";
  const status = latest?.status ?? null;
  const seen = useRef<{ id: string; status: TurnStatus | null }>({ id, status });
  const [flash, setFlash] = useState<"success" | "error" | null>(null);

  useEffect(() => {
    const before = seen.current;
    seen.current = { id, status };
    if (!id || before.id !== id || before.status !== "running") return;
    const outcome = status === "done" ? "success" : status === "error" ? "error" : null;
    if (!outcome) return;
    setFlash(outcome);
    const timer = window.setTimeout(() => setFlash(null), ONE_SHOT_MS[outcome]);
    return () => {
      window.clearTimeout(timer);
      setFlash(null);
    };
  }, [id, status]);

  return flash;
}

/**
 * What the assistant is doing right now: the line under its name and the
 * row its pet plays, from one reading so they never disagree.
 *
 * While its conversation is on stage the line follows the running turn step
 * by step, in the activity line's own words ("Thinking", "Searching the
 * project"), paced the same way so it reads instead of flickering, and the
 * pet plays the matching row. While an earlier chat is on stage instead,
 * only the chat list's `running` flag is known, so the line says "Working"
 * and the pet works. A call and a card that waits for the person come before
 * both. When nothing happens the pet rests; it sleeps while the app is
 * offline, and a turn that ends plays success or error once.
 */
export function usePanelNow(leadId: string | null, onCall: boolean): PanelNow {
  const t = useT();
  const { connected, bootWarming } = useVoiceReadiness();
  const voiceState = useEventStore((s) => s.voiceState);
  // Until the conversation's id is known, the chat on stage is taken for it.
  const onStage = useAgentChatStore((s) => leadId === null || s.activeSessionId === leadId);
  const items = useAgentChatStore((s) => s.timeline.items);
  const listedRunning = useAgentChatStore(
    (s) => leadId !== null && s.sessions.some((row) => row.session_id === leadId && row.running === true),
  );
  const now = useMemo(() => (onStage ? assistantNow(items) : IDLE), [onStage, items]);
  const step = usePacedActivity(useMemo(() => (now.kind === "working" ? activityOf(now.turn) : null), [now]));
  const flash = useOutcomeFlash(items, onStage);

  if (!connected) {
    return bootWarming
      ? { state: "starting", tone: "quiet", text: t("sidebar.status_starting"), pet: "idle" }
      : { state: "offline", tone: "quiet", text: t("sidebar.status_offline"), pet: "sleeping" };
  }
  if (onCall) return { state: "call", tone: "life", text: t("sidebar.status_call"), pet: petStateForVoice(voiceState) };
  if (now.kind === "waiting") return { state: "waiting", tone: "attention", text: t("sidebar.status_waiting"), pet: "listening" };
  if (now.kind === "working") {
    // Before the first step arrives the turn is thinking about its answer.
    return {
      state: "working",
      tone: "life",
      text: step ? activityPhrase(step, t) : t("sidebar.status_working"),
      pet: step ? petForFamily(step.family) : "thinking",
    };
  }
  if (now.kind === "background") {
    const text = now.count === 1 ? t("sidebar.status_background_one") : fill(t("sidebar.status_background_many"), { count: now.count });
    return { state: "background", tone: "life", text, pet: "working" };
  }
  if (!onStage && listedRunning) return { state: "working", tone: "life", text: t("sidebar.status_working"), pet: "working" };
  return { state: "idle", tone: "quiet", text: t("sidebar.status_idle"), pet: flash ?? "idle" };
}

/** The line under the assistant's name; `usePanelNow` says what it reads. */
export function PanelStatus({ now }: { now: PanelNow }) {
  return (
    <span data-testid="assistant-panel-status" data-state={now.state} className="flex min-w-0 items-center gap-1.5 text-sm text-muted-foreground">
      {now.tone !== "quiet" && (
        <span aria-hidden className={cn("h-1.5 w-1.5 shrink-0 rounded-full", DOT[now.tone], now.tone === "life" && "motion-safe:animate-pulse")} />
      )}
      <span className="min-w-0 truncate">{now.text}</span>
    </span>
  );
}
