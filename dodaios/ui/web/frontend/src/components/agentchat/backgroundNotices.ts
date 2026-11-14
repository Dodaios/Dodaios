import type { TimelineItem } from "./reduce";

/** Notice kinds that only record background work. */
const BACKGROUND_KINDS = new Set(["memory_learned", "watchdog"]);

/**
 * Whether a timeline item records work that went on in the background.
 *
 * The conversation's log keeps such a notice, but the assistant's chat does
 * not draw it. Each has a place of its own: what the assistant learned is on
 * the Memory page, a watchdog finding is in the status light, and an
 * unattended routine run that failed, was skipped or waits is in the
 * routine's run history. A routine's finished result is an answer the person
 * asked for and stays in the chat. The server applies the same rule to the
 * phone (`dodaios/agent_chat/events.py::is_background_notice`).
 */
export function isBackgroundNotice(item: TimelineItem): boolean {
  if (item.type !== "notice") return false;
  if (BACKGROUND_KINDS.has(item.kind)) return true;
  return item.kind === "society_result" && item.data.source === "routine"
    && item.status !== "" && item.status !== "done";
}

/**
 * Notice kinds the app draws beside the chat instead of in it. A reminder
 * that came due waits on the rail (`components/layout/dueReminders.ts`) until
 * it is ticked off or snoozed. The phone keeps it: it has no rail.
 */
const RAIL_KINDS = new Set(["reminder_due"]);

function notDrawnInChat(item: TimelineItem): boolean {
  return isBackgroundNotice(item) || (item.type === "notice" && RAIL_KINDS.has(item.kind));
}

/** `items` without the background notices and those drawn on the rail; the same array when it holds none. */
export function withoutBackgroundNotices(items: TimelineItem[]): TimelineItem[] {
  return items.some(notDrawnInChat) ? items.filter((item) => !notDrawnInChat(item)) : items;
}
