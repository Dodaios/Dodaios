/**
 * A turn's work in one line: how long, how many steps, which files changed.
 *
 * The specialist chat keeps tool calls and thoughts out of the conversation.
 * Under each turn that did any work, one quiet line says how much there was
 * ("Worked for 2m 05s · 14 steps · 3 files +40 −12") and opens the work
 * inspector. Pure, so the counts are testable and the same everywhere.
 */

import { isSubagentCall } from "@/components/agentic/threads/subagents";
import { isCredentialTool, isQuestionTool, type ToolBlock, type TurnBlock, type TurnItem } from "../reduce";
import { toolDiff } from "../toolDiff";
import { traceAction, traceToolName } from "../traceActivity";

export interface WorkSummary {
  /** Tool calls the agent made itself, without the polls behind a card. */
  steps: number;
  /** Thoughts, worded or not. */
  thoughts: number;
  /** Helpers (sub-agents) it started. */
  helpers: number;
  /** Distinct files its edits touched. */
  files: number;
  added: number;
  removed: number;
  /** Calls that failed. */
  failed: number;
}

/** A call that only waits on a card the person answers: never a step. */
export function isCardPoll(block: ToolBlock): boolean {
  return (isQuestionTool(block.name) && !block.question) || (isCredentialTool(block.name) && !block.credential);
}

/** Files, added and removed lines of one edit, from the diff the trace paints. */
export function editStat(block: ToolBlock): { paths: string[]; added: number; removed: number } {
  // Memory notes paint a diff too, but they are notes, not changed files.
  const action = traceAction(traceToolName(block.name));
  if (action !== "edit" && action !== "write") return { paths: [], added: 0, removed: 0 };
  const files = toolDiff(block.name, block.input, block.output) ?? [];
  let added = 0;
  let removed = 0;
  for (const file of files) {
    added += file.added;
    removed += file.removed;
  }
  return { paths: files.map((file) => file.path || "?"), added, removed };
}

export function workSummary(blocks: readonly TurnBlock[]): WorkSummary {
  const paths = new Set<string>();
  const out: WorkSummary = { steps: 0, thoughts: 0, helpers: 0, files: 0, added: 0, removed: 0, failed: 0 };
  for (const block of blocks) {
    if (block.kind === "reasoning") {
      out.thoughts += 1;
      continue;
    }
    if (block.kind !== "tool" || isCardPoll(block)) continue;
    out.steps += 1;
    if (block.isError) out.failed += 1;
    if (isSubagentCall(block)) {
      out.helpers += 1;
      continue;
    }
    // A denied edit changed nothing.
    if (block.isError || block.approval?.decision === "deny") continue;
    const stat = editStat(block);
    for (const path of stat.paths) paths.add(path);
    out.added += stat.added;
    out.removed += stat.removed;
  }
  out.files = paths.size;
  return out;
}

/** The turn did something worth opening: a call, a thought, a helper. */
export function hasWork(summary: WorkSummary): boolean {
  return summary.steps > 0 || summary.thoughts > 0;
}

/** How the line opens: still working, or how the turn ended. */
export function workHeadKey(turn: TurnItem): string {
  if (turn.status === "running") return "run_view.work.working";
  if (turn.status === "cancelled") return "run_view.work.stopped_after";
  if (turn.status === "error") return "run_view.work.failed_after";
  return "run_view.work.worked_for";
}
