import { useEventStore, type SectionId } from "@/store/events";
import { openAgent, type CardKind } from "@/views/society/agentNavigation";

import type { StatusRow } from "./statusLightStore";

const CARD_KINDS: readonly string[] = ["question", "approval", "credential", "proposal"];

/**
 * Go to the place a status row stands for.
 *
 * A card (a question, an approval) lives in the assistant's one conversation,
 * so the row opens the conversation and marks the card there; every other row
 * names a section.
 */
export function goToStatusRow(row: StatusRow): void {
  const { link } = row;
  const kind = CARD_KINDS.includes(row.kind) ? (row.kind as CardKind) : undefined;
  if (link.agent_id) {
    openAgent(link.agent_id, { sessionId: link.session_id || undefined, cardRef: link.ref_id || undefined, kind });
  } else if (link.section) {
    useEventStore.getState().setActiveSection(link.section as SectionId);
  }
}

/** Open the API keys page, where a provider in trouble is set right. */
export function openKeys(): void {
  useEventStore.getState().setActiveSection("apikeys");
}
