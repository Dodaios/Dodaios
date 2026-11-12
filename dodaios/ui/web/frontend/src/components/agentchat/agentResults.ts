import type { NoticeItem, TimelineItem } from "./reduce";
import { TURN_GRACE_MS } from "./turnMessages";

/**
 * The notice a delegated coding agent leaves in the assistant's chat when its
 * turn ends: finished, failed, stopped or waiting for an answer
 * (`dodaios/ui/web/server.py::_forward_delegation_to_chat`).
 */
export const AGENT_RESULT_KIND = "coding_result";

const STATUSES = new Set(["completed", "failed", "stopped", "needs_input", "exited"]);

function isAgentResult(item: TimelineItem): item is NoticeItem {
  return item.type === "notice" && item.kind === AGENT_RESULT_KIND;
}

/** One line for a result nobody answered: who, and how it ended. Never the report. */
export function agentResultLabel(t: (key: string) => string, item: NoticeItem): string {
  const status = STATUSES.has(item.status) ? item.status : "other";
  return t(`society.chat.agent_result_${status}`)
    .replace("{0}", item.agentName || t("agent_attention.fallback_agent"));
}

/**
 * `items` without the agent results the assistant takes up itself; the same
 * array when it drops none.
 *
 * The result is the assistant's material, not a message for the person: the
 * assistant reads it and answers in its own words (and its report card, when
 * it writes one, follows that answer). So the notice is not drawn when
 *
 * - it arrived while a turn of the assistant was working (the turn that waits
 *   for its agents receives the result and goes on with it), or
 * - a "result for your earlier request" turn follows it (the request's turn
 *   had closed, and its result comes back in a turn of its own).
 *
 * A result that neither happened to stays, drawn as one line
 * (`AgentResultLine`): the wait was stopped, or was lost in a restart, and
 * the person must still learn that the agent is done.
 */
export function withoutAnsweredResults(items: TimelineItem[]): TimelineItem[] {
  if (!items.some(isAgentResult)) return items;
  const answered = new Set<string>();
  let turnEndsMs: number | null = null;
  // An earlier request's result message whose turn has not started yet. The
  // agent's own notice is written a moment after its turn ended, so it can
  // land between that message and its turn.
  let continuing = false;
  // Results since the last turn or message of the person that nobody took up yet.
  let open: string[] = [];
  for (const item of items) {
    if (item.type === "turn") {
      turnEndsMs = item.status === "running" || item.durationMs === null
        ? Number.POSITIVE_INFINITY
        : item.startedMs + item.durationMs + TURN_GRACE_MS;
      continuing = false;
      open = [];
    } else if (item.type === "user") {
      turnEndsMs = null;
      continuing = item.origin === "background";
      if (continuing) for (const id of open) answered.add(id);
      open = [];
    } else if (isAgentResult(item)) {
      if (continuing || (turnEndsMs !== null && item.tsMs <= turnEndsMs)) answered.add(item.id);
      else open.push(item.id);
    }
  }
  return answered.size > 0 ? items.filter((item) => !answered.has(item.id)) : items;
}
