import { useCallback } from "react";

import { useVoiceCall } from "@/components/agentic/useVoiceCall";
import type { TimelineItem } from "@/components/agentchat/reduce";
import { useVoiceReadiness } from "@/hooks/useVoiceReadiness";
import { bindVoiceChat } from "@/lib/agentChatApi";
import { transcriptFromMessages, type TranscriptLine } from "@/lib/homeTranscript";
import { useAgentChatStore } from "@/store/agentChat";
import { useEventStore } from "@/store/events";
import { useHomeStore } from "@/store/home";

/**
 * The chat on stage as the voice lane's lines: what was typed or said, and
 * the answers' prose. Tool rows, notices and errors stay in the chat view.
 */
export function transcriptFromTimeline(items: readonly TimelineItem[]): TranscriptLine[] {
  const messages: { role: string; content: string; ts: number }[] = [];
  for (const item of items) {
    if (item.type === "user") {
      messages.push({ role: "user", content: item.text, ts: item.tsMs });
    } else if (item.type === "turn") {
      const text = item.blocks
        .flatMap((block) => (block.kind === "text" ? [block.text] : []))
        .join("\n");
      messages.push({ role: "assistant", content: text, ts: item.startedMs });
    }
  }
  return transcriptFromMessages(messages);
}

/**
 * Starting and ending a call from the front-page chat — the ONE path the
 * composer's round voice button and the call card use.
 *
 * A call never leaves the conversation: the chat stays on screen, a small
 * call card (components/home/CallCard) shows the call and its controls, and
 * what is said lands in the conversation as ordinary messages. Before the
 * call starts, the chat on stage is bound on the backend (`bindVoiceChat`):
 * the call starts with its history and its turns are filed into it. An
 * archived voice chat opened from the history is continued as itself.
 */
export function useVoiceModeSwitch() {
  const setActiveSection = useEventStore((s) => s.setActiveSection);
  const { active, busy, connecting, toggleCall } = useVoiceCall();
  const { connected } = useVoiceReadiness();
  const live = active || connecting;

  const enter = useCallback(() => {
    const chat = useAgentChatStore.getState();
    const events = useEventStore.getState();
    const home = useHomeStore.getState();
    // An archived voice chat on stage is continued as itself.
    const voiceThread = !chat.activeSessionId && events.activeKind === "voice" ? events.activeThreadId : null;
    if (voiceThread) home.setContinuedVoiceId(voiceThread);
    if (home.surface !== "chat") home.setSurface("chat");
    setActiveSection("chats");
    if (active || busy || connecting || !connected) return;
    home.resetTranscript();
    void bindVoiceChat(chat.activeSessionId, voiceThread)
      .catch((err: unknown) => {
        // The call still starts; it just lands in the one conversation.
        console.info("Voice chat binding failed.", err);
      })
      .finally(() => void toggleCall());
  }, [active, busy, connected, connecting, setActiveSection, toggleCall]);

  const exit = useCallback(() => {
    if (active && !busy) void toggleCall();
  }, [active, busy, toggleCall]);

  return { on: live, live, busy, enter, exit, toggle: live ? exit : enter };
}
