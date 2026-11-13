import { waitsInBackground, type TimelineItem, type TurnItem } from "@/components/agentchat/reduce";

/**
 * What the assistant is doing right now, for the line under its name.
 *
 * Read off the one conversation: a card
 * that waits for the person comes first, because nothing moves until they
 * answer; then a turn that is answering; then work handed off that still
 * runs, after its turn closed or while a turn that has already answered is
 * held open for the agents it sent out (`background_wait`). Pure, so the panel's header and its tests
 * agree on the order.
 */
export type AssistantNow =
  | { kind: "waiting" }
  /** A turn runs; the activity line's own phrase says what it is on. */
  | { kind: "working"; turn: TurnItem }
  /** Nobody answers, but `count` hand-offs still work on an earlier request. */
  | { kind: "background"; count: number }
  | { kind: "idle" };

function waitsOnPerson(turn: TurnItem): boolean {
  return turn.blocks.some(
    (block) => block.kind === "tool" && ((block.approval && !block.approval.decision) || (block.question && !block.question.closed)),
  );
}

export function assistantNow(items: readonly TimelineItem[]): AssistantNow {
  let running: TurnItem | null = null;
  let background = 0;
  for (const item of items) {
    if (item.type !== "turn") continue;
    if (waitsOnPerson(item)) return { kind: "waiting" };
    // A turn that said its piece and only waits on its agents is not answering.
    if (waitsInBackground(item)) background += (item.waitingOn ?? []).length;
    else if (item.status === "running") running = item;
    background += (item.background ?? []).length;
  }
  if (running) return { kind: "working", turn: running };
  if (background > 0) return { kind: "background", count: background };
  return { kind: "idle" };
}
