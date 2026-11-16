/**
 * Portions adapted from pingdotgg/t3code @ e22c880 (apps/web MessagesTimeline,
 * packages/client-runtime work-log presentation), MIT License,
 * Copyright (c) 2026 T3 Tools Inc. Full text: third_party/t3code/LICENSE.
 *
 * The pure model behind a thread turn's work log. A turn reads as the
 * agent's own words — its answer and every thought it put into words — with
 * its work in between: ONE group per run of tool calls between two
 * paragraphs, named by what it did ("Edited files, ran commands", the call
 * itself when it ran alone). A thought with words is a paragraph of its own
 * and splits the work around it; wordless (redacted) thinking is no row,
 * except the thought the running turn is having, which shows as a live
 * "Thinking" step so the turn never looks idle. The group the running turn is
 * still in is live.
 *
 * The agent's own to-do list is no work: its list calls are told as what they
 * changed ("Completed the draft"), and the list as it stands after the newest
 * of them is one card in the flow, where the agent last touched it.
 */

import { joinPlanViews, type PlanView } from "@/components/agentchat/agentPlan";
import type { ReasoningBlock, TextBlock, ToolBlock, TurnBlock, TurnStatus } from "@/components/agentchat/reduce";
import { buildTimeline, summarize, type Call, type CallKind, type Translate } from "@/components/agentchat/traceEntries";
import { isSubagentCall } from "./subagents";
import { isCompaction } from "@/components/agentchat/compaction";

/**
 * One step of a group: a tool call, the wordless thought a running turn is
 * having, or a run of to-do list calls read as one step (what they changed,
 * and the list after them).
 */
export type WorkItem =
  | { kind: "call"; id: string; call: Call; startedMs: number }
  | { kind: "thought"; id: string; block: ReasoningBlock; startedMs: number }
  | { kind: "plan"; id: string; calls: Call[]; plan: PlanView; startedMs: number };

export interface WorkGroup {
  kind: "work";
  id: string;
  items: WorkItem[];
  /** "Edited files, ran commands", the command itself, "Thinking". */
  summary: string;
  /** The single kind of call the group made, "thought" when it only thinks, else null. */
  sole: CallKind | "thought" | null;
  added: number;
  removed: number;
  startedMs: number;
  /** The running turn's newest group: it stays open and follows its newest step. */
  live: boolean;
}

export type ThreadRow =
  | WorkGroup
  | { kind: "text"; id: string; text: string; block: TextBlock }
  /** A thought in the agent's own words, read as a paragraph between its work. */
  | { kind: "thought"; id: string; text: string; block: ReasoningBlock; live: boolean }
  /** A call that waits for the person: an approval or a question card. */
  | { kind: "pending"; id: string; block: ToolBlock }
  /** A sub-agent the turn spawned: a card of its own that opens its conversation. */
  | { kind: "agent"; id: string; block: ToolBlock }
  /** The agent's to-do list as it stands after the turn's newest list call. */
  | { kind: "plan"; id: string; plan: PlanView; calls: Call[] }
  /** The agent compacted its own conversation here: a line across the turn. */
  | { kind: "compaction"; id: string; block: ToolBlock };

/**
 * A row that is bookkeeping, not work: a thought, the to-do list, a
 * compaction, or a line whose only steps are list calls.
 */
export function isBookkeeping(row: ThreadRow): boolean {
  return row.kind === "thought" || row.kind === "plan" || row.kind === "compaction"
    || (row.kind === "work" && row.items.every((item) => item.kind === "plan"));
}

export function isFailed(call: Call): boolean {
  return call.status === "failed" || call.status === "blocked" || call.status === "declined";
}

/** How long a thought's gist may run before it is cut at a word. */
export const GIST_MAX = 140;

/**
 * A thought as one short line a reader takes in at a glance: its heading
 * when it opens with one ("**Checking the build**"), else its first
 * sentence, without Markdown marks and cut at a word past GIST_MAX.
 */
export function thoughtGist(text: string): string {
  const source = text.trim();
  const heading = /^(?:#{1,6}\s+(.+)|\*\*([^*\n]+)\*\*\s*(?:\n|$))/.exec(source);
  const raw = heading ? (heading[1] ?? heading[2]) : source.split(/\n\s*\n/)[0];
  const plain = raw
    .replace(/```[^\n]*\n?/g, " ")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/^\s{0,3}(>|[-*+]|\d+[.)])\s+/gm, "")
    .replace(/(\*\*|__|~~|`)/g, "")
    .replace(/\s+/g, " ")
    .trim();
  const sentence = /^.+?[.!?:](?=\s|$)/.exec(plain)?.[0] ?? plain;
  if (sentence.length <= GIST_MAX) return sentence;
  const cut = sentence.slice(0, GIST_MAX);
  const space = cut.lastIndexOf(" ");
  return `${(space > GIST_MAX / 2 ? cut.slice(0, space) : cut).replace(/[\s,;:]+$/, "")}…`;
}

function soleKind(items: WorkItem[]): WorkGroup["sole"] {
  const calls = items.flatMap((item) => item.kind === "call" ? [item.call] : []);
  if (calls.length === 0) return items.some((item) => item.kind === "thought") ? "thought" : null;
  const kinds = new Set(calls.map((call) => call.kind));
  return kinds.size === 1 ? calls[0].kind : null;
}

/**
 * Lay out a turn's blocks as text, thoughts, waiting cards and work groups.
 *
 * `plans` is the agent's to-do list after each of its list calls
 * (`planViewsOf`). With it, list calls leave the work: the newest run of them
 * becomes the list's card, earlier runs one step each. Without it a list call
 * is a call like any other.
 */
export function buildThreadRows(
  blocks: TurnBlock[],
  options: { t: Translate; lang: string; status: TurnStatus; plans?: ReadonlyMap<string, PlanView> },
): ThreadRow[] {
  const timeline = buildTimeline(blocks, { ...options, live: true });
  const plans = options.plans;
  // The turn's newest list call: the run it belongs to is drawn as the card.
  let newestPlan = "";
  if (plans?.size) {
    for (const entry of timeline.entries) {
      if (entry.kind !== "activity") continue;
      for (const call of entry.calls) if (plans.has(call.id)) newestPlan = call.id;
    }
  }
  const started = new Map<string, number>();
  for (const block of blocks) {
    if (block.kind === "tool") started.set(block.callId, block.startedMs);
    else if (block.kind === "reasoning") started.set(block.id, block.startedMs);
  }
  const running = options.status === "running";
  const rows: ThreadRow[] = [];
  let items: WorkItem[] = [];

  const flush = () => {
    if (!items.length) return;
    const calls = items.flatMap((item) => item.kind === "call" ? [item.call] : []);
    rows.push({
      kind: "work",
      id: `work:${items[0].id}`,
      items,
      summary: calls.length ? summarize(calls, options.t, options.lang, true) : items.some((item) => item.kind === "thought") ? "Thinking" : "",
      sole: soleKind(items),
      added: calls.reduce((sum, call) => sum + call.added, 0),
      removed: calls.reduce((sum, call) => sum + call.removed, 0),
      startedMs: items[0].startedMs,
      live: false,
    });
    items = [];
  };

  for (const entry of timeline.entries) {
    if (entry.kind === "activity") {
      for (let at = 0; at < entry.calls.length; at++) {
        const call = entry.calls[at];
        const view = plans?.get(call.id);
        if (plans && view) {
          // List calls right after one another are one step: what they changed together.
          const run = [call];
          const views = [view];
          while (at + 1 < entry.calls.length && plans.has(entry.calls[at + 1].id)) {
            at += 1;
            run.push(entry.calls[at]);
            views.push(plans.get(entry.calls[at].id)!);
          }
          const plan = joinPlanViews(views);
          if (plan.items.length > 0 && run.some((one) => one.id === newestPlan)) {
            flush();
            rows.push({ kind: "plan", id: `plan:${call.id}`, plan, calls: run });
          } else {
            items.push({ kind: "plan", id: `plan:${call.id}`, calls: run, plan, startedMs: started.get(call.id) ?? 0 });
          }
          continue;
        }
        if (isCompaction(call.block)) {
          flush();
          rows.push({ kind: "compaction", id: `compaction:${call.id}`, block: call.block });
        } else if (isSubagentCall(call.block)) {
          flush();
          rows.push({ kind: "agent", id: `agent:${call.id}`, block: call.block });
        } else {
          items.push({ kind: "call", id: call.id, call, startedMs: started.get(call.id) ?? 0 });
        }
      }
      continue;
    }
    const block = entry.block;
    if (block.kind === "reasoning") {
      const live = running && block.live;
      const text = block.text.trim();
      if (text) {
        flush();
        rows.push({ kind: "thought", id: block.id, text, block, live });
      } else if (live) {
        items.push({ kind: "thought", id: block.id, block, startedMs: started.get(block.id) ?? 0 });
      }
      continue;
    }
    flush();
    if (block.kind === "text") rows.push({ kind: "text", id: entry.id, text: block.text, block });
    // A sub-agent waiting on an approval keeps its card; the card says it waits.
    else if (isSubagentCall(block)) rows.push({ kind: "agent", id: `agent:${block.callId}`, block });
    else rows.push({ kind: "pending", id: entry.id, block });
  }
  flush();
  const last = rows[rows.length - 1];
  if (running && last?.kind === "work") last.live = true;
  return rows;
}

/** One step of a stretch: a call, the wordless thought of a running turn, or a thought in words. */
export type StretchItem =
  | WorkItem
  | { kind: "said"; id: string; text: string; live: boolean; startedMs: number };

/**
 * Everything the agent did between two things it said: its calls and its
 * thoughts, read as ONE quiet line that opens to the single steps.
 */
export interface Stretch {
  kind: "stretch";
  id: string;
  items: StretchItem[];
  /** What the calls did ("Ran 6 commands, edited a file"); "" for a stretch of thoughts only. */
  label: string;
  /** The runtime's own title for these calls ("Rewrote the parser and ran its tests"), when it sent one. */
  title?: string;
  added: number;
  removed: number;
  startedMs: number;
  /** The running turn's tail: its line carries the live shine. */
  live: boolean;
}

type StretchRow = WorkGroup | Extract<ThreadRow, { kind: "thought" }>;

/**
 * Rows with each run of work groups and thoughts drawn as one stretch. The
 * agent's words, cards and sub-agents stay rows of their own and end a
 * stretch. A thought that only repeats the one before it is told once. The
 * stretch the running turn ends on is live.
 *
 * `thoughtsApart`: a thought in words stays a row of its own between the
 * stretches (a thread reads it as one short sentence), so the work between
 * two thoughts is its own line.
 */
export function joinStretches<T extends { kind: string }>(
  rows: readonly T[],
  options: { t: Translate; lang: string; running: boolean; titles?: Readonly<Record<string, string>>; thoughtsApart?: boolean },
): (T | Stretch)[] {
  const out: (T | Stretch)[] = [];
  let run: StretchRow[] = [];
  let lastApart = "";
  const flush = () => {
    if (!run.length) return;
    const items: StretchItem[] = [];
    let lastSaid = "";
    for (const row of run) {
      if (row.kind === "work") { items.push(...row.items); continue; }
      const text = row.text.trim();
      if (text === lastSaid) continue;
      lastSaid = text;
      items.push({ kind: "said", id: row.id, text: row.text, live: row.live, startedMs: row.block.startedMs });
    }
    const calls = items.flatMap((item) => item.kind === "call" ? [item.call] : []);
    // A runtime titles each run of calls under the run's last call; the
    // newest title among these calls names the whole line. A title filed
    // under a list call ("Marked task 1 in progress") names no work.
    let title: string | undefined;
    for (let i = calls.length - 1; i >= 0 && !title; i--) title = options.titles?.[calls[i].id];
    out.push({
      kind: "stretch",
      id: `stretch:${run[0].id}`,
      items,
      label: calls.length ? summarize(calls, options.t, options.lang, true) : "",
      ...(title ? { title } : {}),
      added: calls.reduce((sum, call) => sum + call.added, 0),
      removed: calls.reduce((sum, call) => sum + call.removed, 0),
      startedMs: items[0]?.startedMs ?? 0,
      live: false,
    });
    run = [];
  };
  for (const row of rows) {
    if (row.kind === "thought" && options.thoughtsApart) {
      flush();
      const text = (row as unknown as { text: string }).text.trim();
      if (text !== lastApart) out.push(row);
      lastApart = text;
    } else if (row.kind === "work" || row.kind === "thought") run.push(row as unknown as StretchRow);
    else {
      flush();
      if (row.kind === "text") lastApart = "";
      out.push(row);
    }
  }
  flush();
  const last = out[out.length - 1];
  if (options.running && last?.kind === "stretch") (last as Stretch).live = true;
  return out;
}
