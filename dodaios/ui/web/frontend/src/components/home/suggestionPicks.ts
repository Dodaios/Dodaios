/**
 * The two or three things the empty front page offers under the greeting,
 * drawn from what the assistant already knows: what falls due soon (the
 * personal memory's `/upcoming`) and the person's agents that are working or
 * waiting. Pure, so the choice is testable without a page.
 *
 * A suggestion never sends anything: tapping it puts its sentence into the
 * composer, and the person decides.
 */
import { fill } from "@/i18n";

export const MAX_SUGGESTIONS = 3;

export type DueItem = { id: string; text: string; due_at: string | null };
export type AgentItem = { agentId: string; name: string; state: string };
export type Suggestion = { id: string; kind: "due" | "agent"; text: string };

/** Short enough to sit on one chip; the composer gets the same sentence. */
function clip(text: string, max = 80): string {
  const one = text.replace(/\s+/g, " ").trim();
  return one.length > max ? `${one.slice(0, max - 1).trimEnd()}…` : one;
}

export function buildSuggestions(
  due: readonly DueItem[],
  agents: readonly AgentItem[],
  t: (key: string) => string,
): Suggestion[] {
  const dueRows: Suggestion[] = due
    .filter((item) => item.due_at && item.text.trim())
    .sort((a, b) => String(a.due_at).localeCompare(String(b.due_at)))
    .map((item) => ({
      id: `due-${item.id}`,
      kind: "due",
      text: fill(t("design.greeting.due"), { text: clip(item.text) }),
    }));
  // Waiting on the person first: that is the one they can unblock.
  const agentRows: Suggestion[] = agents
    .filter((agent) => agent.state === "waiting" || agent.state === "working")
    .sort((a, b) => Number(b.state === "waiting") - Number(a.state === "waiting"))
    .map((agent) => ({
      id: `agent-${agent.agentId}`,
      kind: "agent",
      text: fill(t(agent.state === "waiting" ? "design.greeting.agent_waiting" : "design.greeting.agent_working"), {
        agent: agent.name,
      }),
    }));
  // Up to two due items and one agent; whichever side is short leaves its
  // place to the other.
  const agentSlots = Math.min(agentRows.length, Math.max(1, MAX_SUGGESTIONS - dueRows.length));
  const dueSlots = Math.min(dueRows.length, MAX_SUGGESTIONS - agentSlots);
  return [...dueRows.slice(0, dueSlots), ...agentRows.slice(0, agentSlots)];
}
