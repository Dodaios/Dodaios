import { lazy, Suspense, useEffect } from "react";

import { useT } from "@/i18n";
import { useAgentChatStore } from "@/store/agentChat";
import { useEventStore } from "@/store/events";
import { useHomeStore } from "@/store/home";

const ChatStage = lazy(() =>
  import("@/components/home/ChatStage").then((module) => ({ default: module.ChatStage })),
);
// The call card is only needed once a call runs.
const CallCard = lazy(() =>
  import("@/components/home/CallCard").then((module) => ({ default: module.CallCard })),
);
// An agent's own chat, opened from the sidebar — society code, its own chunk.
const HomeAgentChat = lazy(() => import("@/components/home/HomeAgentChat"));

/**
 * The front page: ONE chat with the assistant (2026-10-01), and since
 * 2026-11-09 one endless conversation: there is no blank "new chat" page.
 *
 * Nothing but the conversation — no header row, no side card. An empty chat
 * is a short greeting over the composer in the middle of the page;
 * the composer itself carries every control,
 * including the round voice button. A call is not another page: the
 * conversation stays on screen, the call card (components/home/CallCard)
 * floats over its top right corner while the call runs, and what is said
 * lands in the conversation as ordinary messages.
 */
export function AssistantChat() {
  const t = useT();
  const agentChatId = useHomeStore((s) => s.agentChatId);
  const callLive = useEventStore((s) => s.voiceState !== "idle" && s.voiceState !== "error" && Boolean(s.voiceState));
  // An explicitly selected archived voice chat owns the lane.
  const voiceThreadOpen = useEventStore((s) => s.activeKind === "voice" && Boolean(s.activeThreadId));
  // The page always shows the one conversation (agent_chat/lead.py): with no
  // session on stage — first paint, a deleted chat — it opens it, unless an
  // archived voice chat was put on stage on purpose.
  const activeSessionId = useAgentChatStore((s) => s.activeSessionId);
  const continuedVoiceId = useHomeStore((s) => s.continuedVoiceId);
  useEffect(() => {
    if (agentChatId || activeSessionId !== null || continuedVoiceId || voiceThreadOpen) return;
    useAgentChatStore.getState().newChat();
  }, [activeSessionId, agentChatId, continuedVoiceId, voiceThreadOpen]);
  const loading = (
    <div role="status" className="flex min-h-0 flex-1 items-center justify-center text-sm text-muted-foreground">
      {t("common.loading")}
    </div>
  );

  if (agentChatId) {
    return (
      <div className="relative flex min-h-0 flex-1 flex-col" data-testid="assistant-chat" data-agent={agentChatId}>
        <Suspense fallback={loading}>
          <HomeAgentChat agentId={agentChatId} />
        </Suspense>
      </div>
    );
  }

  return (
    <div className="relative flex min-h-0 flex-1 flex-col" data-testid="assistant-chat">
      <Suspense fallback={loading}>
        <ChatStage />
      </Suspense>
      {callLive && (
        <Suspense fallback={null}>
          <CallCard />
        </Suspense>
      )}
    </div>
  );
}
