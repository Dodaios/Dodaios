import { useAgentChatStore } from "@/store/agentChat";
import { useEventStore, type SectionId } from "@/store/events";
import { openAgent, revealCard, type CardKind } from "@/views/society/agentNavigation";

import type { StatusRow } from "./statusLightStore";

/** The assistant's own id in the roster: its cards live in the conversation. */
const ASSISTANT_ID = "jarvis";
const CARD_KINDS: readonly string[] = ["question", "approval", "credential", "proposal"];

/**
 * Go to the place a status row stands for.
 *
 * A card of the assistant itself (a question, an approval) lives in its one
 * conversation, so the row opens the conversation and marks the card there.
 * Any other agent's card opens that agent; every other row names a section.
 */
export function goToStatusRow(row: StatusRow): void {
  const { link } = row;
  const kind = CARD_KINDS.includes(row.kind) ? (row.kind as CardKind) : undefined;
  if (link.agent_id === ASSISTANT_ID) {
    useEventStore.getState().setActiveSection("chats");
    // A `society:` id names the conversation itself, which is already the one on stage.
    if (link.session_id && !link.session_id.startsWith("society:")) {
      const chat = useAgentChatStore.getState();
      if (chat.activeSessionId !== link.session_id) chat.openSession(link.session_id);
    }
    void revealCard({ cardRef: link.ref_id || undefined, kind });
  } else if (link.agent_id) {
    openAgent(link.agent_id, { sessionId: link.session_id || undefined, cardRef: link.ref_id || undefined, kind });
  } else if (link.section) {
    useEventStore.getState().setActiveSection(link.section as SectionId);
  }
}

/** Open the API keys page, where a provider in trouble is set right. */
export function openKeys(): void {
  useEventStore.getState().setActiveSection("apikeys");
}
