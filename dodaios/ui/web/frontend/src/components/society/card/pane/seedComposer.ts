/**
 * Put a ready message into this agent's chat composer without sending it.
 *
 * The society composer keeps its unsent text in the composer draft store of
 * its chat store, keyed by session; writing there is exactly what typing does,
 * so the person sees the text, can change it, and decides to send. Existing
 * unsent text is kept and the seed goes below it.
 */
import { readComposerDraft, writeComposerDraft } from "@/components/agentchat/composerDrafts";
import { useAgentChatStore } from "@/store/agentChat";

import { useSocietyChatStore } from "../../chat/AgentChatPanel";
import type { SocietyAgent } from "../../data";

export function seedAgentComposer(agent: SocietyAgent, text: string): boolean {
  const lead = agent.tier === "lead";
  const store = lead ? useAgentChatStore : useSocietyChatStore;
  const sessionId = lead ? store.getState().activeSessionId : agent.chatSessionId;
  if (!lead && !sessionId) return false;
  const current = readComposerDraft(store, sessionId);
  const joined = current.text.trim() ? `${current.text.trimEnd()}\n\n${text}` : text;
  writeComposerDraft(store, sessionId, { ...current, text: joined });
  // The field hydrates from the draft on its next layout; focus follows it.
  window.requestAnimationFrame(() => {
    const field = document.querySelector<HTMLElement>('[data-testid="agent-card-chat"] [data-testid="composer-chip-field"]');
    field?.focus();
  });
  return true;
}
