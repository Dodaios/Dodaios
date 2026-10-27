/**
 * The work inspector's rows: a turn's whole trace, one row per thing that
 * happened, in order. Where the conversation shows only messages and the
 * activity line, this is the full account: the request, every thought (with
 * its words when the provider shares them), every reply, every call with
 * what it ran and what came back, every card the agent showed the person,
 * and every helper it started (which opens that helper's own tab).
 *
 * Pure: blocks in, rows out. The same rows come from every runtime, because
 * every runtime writes the same event vocabulary. A runtime that streams
 * nothing (only finished blocks) simply has fewer, finished rows.
 */

import { isSubagentCall } from "@/components/agentic/threads/subagents";
import type { ReasoningBlock, TextBlock, ToolBlock, TurnBlock, TurnStatus } from "../reduce";
import { callOf, isPlumbing, outputGist, readableOutput, type Call, type Translate } from "../traceEntries";
import { stripInlineMarks } from "@/lib/plainMarks";

export type RowKind = "prompt" | "thought" | "reply" | "call" | "question" | "approval" | "credential" | "helper";
export type RowStatus = "running" | "done" | "failed" | "waiting" | "stopped" | "declined";

export interface InspectorRow {
  id: string;
  kind: RowKind;
  status: RowStatus;
  /** The row's words (translated or the call's own line). */
  label: string;
  /** A dimmed first line, at most PREVIEW_MAX characters. */
  preview: string;
  added: number;
  removed: number;
  durationMs: number | null;
  /** The call behind a call, card or helper row. */
  block?: ToolBlock;
  /** The trace model's view of a call row (its kind drives the mark). */
  call?: Call;
  /** The full text of a prompt, thought or reply. */
  text?: string;
}

export const PREVIEW_MAX = 80;

/** One line of plain text, capped; underscores and stars stay as written. */
export function plainPreview(text: string, max = PREVIEW_MAX): string {
  const clean = text.replace(/\s+/g, " ").trim();
  return clean.length > max ? `${clean.slice(0, max - 1).trimEnd()}…` : clean;
}

/** First meaningful line, markdown marks dropped (underscores in names stay), capped. */
export function previewOf(text: string, max = PREVIEW_MAX): string {
  const line = text
    .replace(/```[\s\S]*?```/g, " ")
    .split(/\r?\n/)
    .map((part) => stripInlineMarks(part.replace(/^[#>*\-\s]+/, "")).trim())
    .find(Boolean) ?? "";
  const clean = line.replace(/\s+/g, " ");
  return clean.length > max ? `${clean.slice(0, max - 1).trimEnd()}…` : clean;
}

export interface RowOptions {
  t: Translate;
  lang: string;
  status: TurnStatus;
  /** The person's message that started the turn, shown first. */
  prompt?: string;
  /** The first row's label key, when the trace starts with something else (a helper's task). */
  promptLabel?: string;
}

function thoughtRow(block: ReasoningBlock, turn: TurnStatus, t: Translate): InspectorRow {
  const text = block.text.trim();
  const running = turn === "running" && block.live;
  return {
    id: block.id, kind: "thought", status: running ? "running" : "done",
    label: t(text ? "run_view.row.thought" : "run_view.row.thought_hidden"),
    preview: previewOf(text), added: 0, removed: 0, durationMs: block.durationMs, text,
  };
}

function replyRow(block: TextBlock, t: Translate): InspectorRow {
  return {
    id: block.id, kind: "reply", status: "done", label: t("run_view.row.reply"),
    preview: previewOf(block.text), added: 0, removed: 0, durationMs: null, text: block.text,
  };
}

function cardRow(block: ToolBlock, turn: TurnStatus, t: Translate): InspectorRow {
  const base = { id: block.callId, added: 0, removed: 0, durationMs: block.durationMs, block };
  if (block.question) {
    const q = block.question;
    const first = q.questions[0]?.question ?? "";
    return { ...base, kind: "question", status: q.closed ? "done" : turn === "running" || q.deferred ? "waiting" : "stopped",
      label: t("run_view.row.question"), preview: previewOf(first) };
  }
  if (block.credential) {
    const c = block.credential;
    const status: RowStatus = c.status === null ? "waiting" : c.status === "saved" ? "done" : "declined";
    return { ...base, kind: "credential", status, label: t("run_view.row.credential"), preview: previewOf(c.label || c.env) };
  }
  const decision = block.approval?.decision ?? null;
  const status: RowStatus = decision === null ? "waiting" : decision === "deny" || decision === "cancel" || decision === "expired" ? "declined" : "done";
  return { ...base, kind: "approval", status, label: t("run_view.row.approval"), preview: previewOf(block.approval?.summary || block.name) };
}

function helperRow(block: ToolBlock, turn: TurnStatus, t: Translate): InspectorRow {
  const sub = block.subagent;
  const input = block.input && typeof block.input === "object" ? block.input as Record<string, unknown> : {};
  const title = sub?.description || (typeof input.description === "string" ? input.description : "")
    || previewOf(sub?.prompt || (typeof input.prompt === "string" ? input.prompt : ""));
  const reported = sub?.status;
  const status: RowStatus = reported === "running" ? "running" : reported === "failed" ? "failed" : reported === "stopped" ? "stopped"
    : reported === "done" ? "done"
    : block.output === null ? (turn === "running" ? "running" : "stopped") : block.isError ? "failed" : "done";
  return {
    id: block.callId, kind: "helper", status, label: t("run_view.row.helper"), preview: previewOf(title),
    added: 0, removed: 0, durationMs: sub?.durationMs ?? block.durationMs, block,
  };
}

const CALL_STATUS: Record<Call["status"], RowStatus> = {
  running: "running", done: "done", failed: "failed", blocked: "failed", declined: "declined", interrupted: "stopped",
};

function callRow(block: ToolBlock, turn: TurnStatus, t: Translate, lang: string): InspectorRow {
  const call = callOf(block, turn, t, lang);
  const tail = call.detail || call.result || (call.status === "failed" || call.status === "blocked" ? call.reason : "");
  return {
    id: block.callId, kind: "call", status: CALL_STATUS[call.status], label: call.text,
    // A call's own words are plain text (ids, paths, queries): only its output reads as markdown.
    preview: tail ? plainPreview(tail) : previewOf(call.kind === "command" ? "" : outputGist(readableOutput(block))),
    added: call.added, removed: call.removed, durationMs: block.durationMs, block, call,
  };
}

/** The rows of one trace (a turn's blocks, or a helper's). */
export function inspectorRows(blocks: readonly TurnBlock[], options: RowOptions): InspectorRow[] {
  const { t, lang, status, prompt, promptLabel = "run_view.row.prompt" } = options;
  const rows: InspectorRow[] = [];
  if (prompt && prompt.trim()) {
    rows.push({ id: "prompt", kind: "prompt", status: "done", label: t(promptLabel), preview: previewOf(prompt),
      added: 0, removed: 0, durationMs: null, text: prompt });
  }
  for (const block of blocks) {
    if (block.kind === "reasoning") {
      rows.push(thoughtRow(block, status, t));
      continue;
    }
    if (block.kind === "text") {
      if (block.text.trim()) rows.push(replyRow(block, t));
      continue;
    }
    if (isPlumbing(block)) continue;
    if (block.question || block.credential || block.approval) {
      // A decided approval reads as the call it guarded, with how it was decided.
      if (!block.question && !block.credential && block.approval && block.approval.decision !== null && block.output !== null) {
        rows.push(callRow(block, status, t, lang));
        continue;
      }
      rows.push(cardRow(block, status, t));
      continue;
    }
    if (isSubagentCall(block)) {
      rows.push(helperRow(block, status, t));
      continue;
    }
    rows.push(callRow(block, status, t, lang));
  }
  return rows;
}

/** Counts for the inspector's header line. */
export function rowCounts(rows: readonly InspectorRow[]): { steps: number; thoughts: number; failed: number } {
  let steps = 0;
  let thoughts = 0;
  let failed = 0;
  for (const row of rows) {
    if (row.kind === "thought") thoughts += 1;
    else if (row.kind !== "prompt" && row.kind !== "reply") steps += 1;
    if (row.status === "failed") failed += 1;
  }
  return { steps, thoughts, failed };
}
