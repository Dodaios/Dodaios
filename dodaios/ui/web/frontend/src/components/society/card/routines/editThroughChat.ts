/**
 * "Edit in chat": put a ready sentence into the agent's own composer so the
 * agent rewrites its routine itself. Nothing is sent; the person finishes the
 * sentence and presses Send.
 */
import { writeComposerDraft } from "@/components/agentchat/composerDrafts";
import { useRoutineNavigation } from "../../chat/routineNavigation";

export interface ComposerTarget {
  tier: string;
  chatSessionId: string | null;
}

/** Focus the visible chat field and put the caret at the end. */
function focusComposer(): void {
  const fields = [...document.querySelectorAll<HTMLElement>("[data-jarvis-chat-input]")]
    .filter((field) => field.isContentEditable && field.offsetParent !== null && !field.closest("[data-testid='routine-chat']"));
  const field = fields[0];
  if (!field) return;
  field.focus();
  const selection = window.getSelection();
  if (!selection) return;
  const range = document.createRange();
  range.selectNodeContents(field);
  range.collapse(false);
  selection.removeAllRanges();
  selection.addRange(range);
}

/** Seed the agent's composer with `text`; resolves once the draft is written. */
export async function seedAgentComposer(agent: ComposerTarget, text: string): Promise<void> {
  // Loaded on click: the chat panel module is large and imports this card.
  const [{ useSocietyChatStore }, { useAgentChatStore }] = await Promise.all([
    import("../../chat/AgentChatPanel"),
    import("@/store/agentChat"),
  ]);
  const store = agent.tier === "lead" ? useAgentChatStore : useSocietyChatStore;
  const active = store.getState().activeSessionId;
  const sessionId = agent.tier === "lead" ? active : agent.chatSessionId ?? active;
  writeComposerDraft(store, sessionId, { text, choices: [] });
  // A run transcript may cover the chat lane; the composer lives behind it.
  useRoutineNavigation.getState().close();
  window.requestAnimationFrame(() => window.requestAnimationFrame(focusComposer));
}
