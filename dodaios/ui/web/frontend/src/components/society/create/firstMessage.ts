/**
 * A new agent's chat opens with a suggested first message already in the
 * composer — typed out, never sent. The person reads it, edits it or deletes
 * it; nothing runs (and nothing bills) until they press send.
 *
 * The draft is written into the society chat's own draft store under the
 * agent's canonical session, which the composer reads when the chat mounts.
 * Text the person already typed there is never replaced.
 */
import type { SocietyAgent } from "../data";

export async function seedFirstMessage(agent: SocietyAgent, text: string): Promise<boolean> {
  const message = text.trim() ? text : "";
  const sessionId = agent.chatSessionId ?? `society:${agent.agentId}`;
  if (!message) return false;
  const [{ useSocietyChatStore }, drafts] = await Promise.all([
    import("../chat/AgentChatPanel"),
    import("@/components/agentchat/composerDrafts"),
  ]);
  const current = drafts.readComposerDraft(useSocietyChatStore, sessionId);
  if (current.text.trim()) return false;
  drafts.writeComposerDraft(useSocietyChatStore, sessionId, { text: message, choices: current.choices });
  return true;
}
