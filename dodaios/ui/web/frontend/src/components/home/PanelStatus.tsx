import { useMemo } from "react";

import { activityOf, activityPhrase } from "@/components/agentchat/activity/activityModel";
import { usePacedActivity } from "@/components/agentchat/activity/usePacedActivity";
import { assistantNow, type AssistantNow } from "@/components/home/assistantNow";
import { useVoiceReadiness } from "@/hooks/useVoiceReadiness";
import { fill, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { useAgentChatStore } from "@/store/agentChat";

type Tone = "life" | "attention" | "quiet";

const IDLE: AssistantNow = { kind: "idle" };

const DOT: Record<Tone, string> = {
  life: "bg-success",
  attention: "bg-warning",
  quiet: "",
};

/**
 * The line under the assistant's name: what it is doing right now.
 *
 * While its conversation is on stage the line follows the running turn step
 * by step, in the activity line's own words ("Thinking", "Searching the
 * project"), paced the same way so it reads instead of flickering. While an
 * earlier chat is on stage instead, only the chat list's `running` flag is
 * known, so the line says "Working" and no more. A call and a card that
 * waits for the person come before both.
 */
export function PanelStatus({ leadId, onCall }: { leadId: string | null; onCall: boolean }) {
  const t = useT();
  const { connected, bootWarming } = useVoiceReadiness();
  // Until the conversation's id is known, the chat on stage is taken for it.
  const onStage = useAgentChatStore((s) => leadId === null || s.activeSessionId === leadId);
  const items = useAgentChatStore((s) => s.timeline.items);
  const listedRunning = useAgentChatStore(
    (s) => leadId !== null && s.sessions.some((row) => row.session_id === leadId && row.running === true),
  );
  const now = useMemo(() => (onStage ? assistantNow(items) : IDLE), [onStage, items]);
  const step = usePacedActivity(useMemo(() => (now.kind === "working" ? activityOf(now.turn) : null), [now]));

  let tone: Tone = "quiet";
  let text = t("sidebar.status_idle");
  let state: string = now.kind;
  if (!connected) {
    state = bootWarming ? "starting" : "offline";
    text = t(bootWarming ? "sidebar.status_starting" : "sidebar.status_offline");
  } else if (onCall) {
    state = "call";
    tone = "life";
    text = t("sidebar.status_call");
  } else if (now.kind === "waiting") {
    tone = "attention";
    text = t("sidebar.status_waiting");
  } else if (now.kind === "working") {
    tone = "life";
    text = step ? activityPhrase(step, t) : t("sidebar.status_working");
  } else if (now.kind === "background") {
    tone = "life";
    text = now.count === 1 ? t("sidebar.status_background_one") : fill(t("sidebar.status_background_many"), { count: now.count });
  } else if (!onStage && listedRunning) {
    state = "working";
    tone = "life";
    text = t("sidebar.status_working");
  }

  return (
    <span data-testid="assistant-panel-status" data-state={state} className="flex min-w-0 items-center gap-1.5 text-sm text-muted-foreground">
      {tone !== "quiet" && <span aria-hidden className={cn("h-1.5 w-1.5 shrink-0 rounded-full", DOT[tone], tone === "life" && "motion-safe:animate-pulse")} />}
      <span className="min-w-0 truncate">{text}</span>
    </span>
  );
}
