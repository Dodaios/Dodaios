import type { NoticeItem, TimelineItem } from "./reduce";

/**
 * A notice {@link isRoutineResult} said yes to. Narrower than `NoticeItem`
 * on purpose: a caller that already holds a notice keeps it as a notice
 * after a "no" (a guard to `NoticeItem` itself would leave it `never`).
 */
export interface RoutineResultNotice extends NoticeItem {
  kind: "society_result";
}

/**
 * A routine's finished result in its owner's chat: a `society_result` notice
 * with `source: "routine"` and status `done` (or no status). The routine
 * runner (`dodaios/society/routine_runner.py`) and a standing task's run
 * (`dodaios/standing_tasks/service.py`) post it when a run ends with
 * something to say. It is the assistant answering, so the chat draws it as
 * the assistant's message (`RoutineResultMessage`), never as background.
 *
 * Payload fields a result may carry: `text` (the answer), `title` (the
 * routine's name) or `standing_title` (a standing task's) or `ritual_title`
 * (a ritual's), `task_id`, `session_id` (the run's own chat), `agent_id`,
 * `agent_name`.
 */
export function isRoutineResult(item: TimelineItem | { type: string }): item is RoutineResultNotice {
  if (item.type !== "notice") return false;
  const notice = item as NoticeItem;
  if (notice.kind !== "society_result") return false;
  // A ritual's card answers the phrase the person just said or typed, so it is
  // drawn the same way, whatever it says: that it started, what was gathered
  // for it, or that the gathering failed (`dodaios/rituals/service.py`).
  if (notice.data.source === "ritual") return true;
  return notice.data.source === "routine" && (notice.status === "" || notice.status === "done");
}

/** The routine's own name on a result, "" when the notice carries none. */
export function routineResultTitle(item: NoticeItem): string {
  const title = typeof item.data.title === "string" ? item.data.title : "";
  const standing = typeof item.data.standing_title === "string" ? item.data.standing_title : "";
  const ritual = typeof item.data.ritual_title === "string" ? item.data.ritual_title : "";
  return (title || standing || ritual).trim();
}

/**
 * `items` without the start line of a run whose result is in the chat: the
 * result's own header names the routine, so "Routine started" above it says
 * nothing new. Matched by the run's chat (`session_id`). The same array when
 * nothing is dropped.
 */
export function withoutReportedRoutineStarts(items: TimelineItem[]): TimelineItem[] {
  const reported = new Set<string>();
  for (const item of items) {
    if (!isRoutineResult(item)) continue;
    const session = typeof item.data.session_id === "string" ? item.data.session_id : "";
    if (session) reported.add(session);
  }
  if (reported.size === 0) return items;
  const kept = items.filter((item) => !(
    item.type === "notice"
    && item.kind === "routine_run"
    && reported.has(typeof item.data.session_id === "string" ? item.data.session_id : "")
  ));
  return kept.length === items.length ? items : kept;
}
