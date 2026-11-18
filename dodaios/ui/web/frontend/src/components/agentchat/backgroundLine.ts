import type { InternalRunItem } from "./InternalMessageRun";
import type { NoticeItem, TimelineItem } from "./reduce";
import { isRoutineResult } from "./routineResult";

/**
 * Consecutive background notices, drawn as one quiet centred line.
 *
 * The assistant's chat is a conversation: what the assistant says, and what
 * the person says. Everything else that lands in it, a routine that started,
 * a memory it noted, an agent's report it reads before it answers, is
 * background. It stays in the log and one click away, but it reads as a
 * whisper ("2 updates from Nova"), never as a card between the messages.
 */
export interface BackgroundRunItem {
  type: "background_run";
  id: string;
  items: NoticeItem[];
}

/**
 * Notice kinds the timeline draws in a way of their own: a message, a card
 * with buttons, a line that must stay where it is, or nothing at all. They
 * never fold into a background line. Keep in step with the notice branch of
 * `AgentTimeline.renderItem`.
 */
export const OWN_NOTICE_KINDS: ReadonlySet<string> = new Set([
  "native_goal_verdict",
  "message_queued",
  "message_dequeued",
  "side_thread_started",
  "chain_result",
  "report",
  "coding_result",
  "seat_trouble",
  "browser_takeover",
  "approval_request",
  "action_blocked",
  "reminder_due",
  "memory_tidy",
  "event_trigger",
  "tasks_captured",
  "standing_proposal",
  "standing_paused",
  "context_reset",
  "seat_switched",
  "background_result_lost",
]);

/** A pause this long between two background notices starts a new line. */
const RUN_GAP_MS = 20 * 60 * 1000;

/**
 * Whether a timeline item is background: a notice no other part of the
 * timeline draws, and not a routine's result (that is the assistant
 * answering, `RoutineResultMessage`).
 */
export function isQuietBackground(item: TimelineItem | InternalRunItem | BackgroundRunItem): item is NoticeItem {
  if (item.type !== "notice") return false;
  if (OWN_NOTICE_KINDS.has(item.kind)) return false;
  return !isRoutineResult(item);
}

/**
 * Folds every stretch of back-to-back background notices into one run. A
 * pause of {@link RUN_GAP_MS} (the same gap that earns a time stamp) or any
 * other item in between starts a new run. Everything else passes through
 * unchanged and in order.
 */
export function groupBackgroundRuns(
  items: readonly (TimelineItem | InternalRunItem)[],
): (TimelineItem | InternalRunItem | BackgroundRunItem)[] {
  const out: (TimelineItem | InternalRunItem | BackgroundRunItem)[] = [];
  let run: BackgroundRunItem | null = null;
  for (const item of items) {
    if (isQuietBackground(item)) {
      const last = run?.items.at(-1);
      if (run && last && item.tsMs - last.tsMs < RUN_GAP_MS) {
        run.items.push(item);
        continue;
      }
      // The first notice's own id: the timeline keys its time stamps by item
      // id, so a stamp due above this notice stays above the run.
      run = { type: "background_run", id: item.id, items: [item] };
      out.push(run);
      continue;
    }
    run = null;
    out.push(item);
  }
  return out;
}
