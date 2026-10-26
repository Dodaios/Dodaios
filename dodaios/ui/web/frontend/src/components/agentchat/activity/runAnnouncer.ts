/**
 * What a screen reader hears about an agent's turn: that it started, replied,
 * finished without a reply, stopped, failed, or asks the person something.
 * One sentence per change of the turn's lifecycle, never one per step, so a
 * long run never floods the reader. Visual only otherwise: nothing here is
 * ever spoken aloud by the app's own voice.
 */

import { waitsOnCard, type TimelineItem, type TurnItem } from "../reduce";

export interface RunSnapshot {
  turnId: string;
  status: TurnItem["status"];
  /** The id of the card that waits for the person, or "". */
  waitingOn: string;
  answered: boolean;
}

/** The newest turn's lifecycle, or null before the first turn. */
export function runSnapshot(items: readonly TimelineItem[]): RunSnapshot | null {
  for (let i = items.length - 1; i >= 0; i--) {
    const item = items[i];
    if (item.type !== "turn") continue;
    const waiting = item.blocks.find((block) => block.kind === "tool"
      && (waitsOnCard(block) || Boolean(block.approval && block.approval.decision === null)));
    return {
      turnId: item.id,
      status: item.status,
      waitingOn: waiting && waiting.kind === "tool" ? waiting.callId : "",
      answered: item.blocks.some((block) => block.kind === "text" && block.text.trim().length > 0),
    };
  }
  return null;
}

export interface Announcement {
  key: string;
  /** The question's text, for "asks". */
  detail: string;
}

/** The sentence a change deserves, or null when nothing worth saying changed. */
export function announcementFor(prev: RunSnapshot | null, next: RunSnapshot | null, question = ""): Announcement | null {
  if (!next) return null;
  const sameTurn = prev?.turnId === next.turnId;
  if (next.waitingOn && (!sameTurn || prev?.waitingOn !== next.waitingOn)) {
    return question ? { key: "run_view.announce.asked", detail: question } : { key: "run_view.announce.needs_ok", detail: "" };
  }
  if (sameTurn && prev?.status === next.status) return null;
  if (next.status === "running") return sameTurn ? null : { key: "run_view.announce.started", detail: "" };
  // A turn seen for the first time already finished was never live here.
  if (!sameTurn) return null;
  if (next.status === "done") return { key: next.answered ? "run_view.announce.replied" : "run_view.announce.finished", detail: "" };
  if (next.status === "cancelled") return { key: "run_view.announce.stopped", detail: "" };
  return { key: "run_view.announce.failed", detail: "" };
}

/** The first open question's text on the newest turn, for "asks". */
export function openQuestionText(items: readonly TimelineItem[], snapshot: RunSnapshot | null): string {
  if (!snapshot?.waitingOn) return "";
  const turn = items.find((item): item is TurnItem => item.type === "turn" && item.id === snapshot.turnId);
  const block = turn?.blocks.find((b) => b.kind === "tool" && b.callId === snapshot.waitingOn);
  if (!block || block.kind !== "tool" || !block.question) return "";
  const index = block.question.answers.findIndex((answer) => answer === null);
  return block.question.questions[Math.max(0, index)]?.question ?? "";
}
