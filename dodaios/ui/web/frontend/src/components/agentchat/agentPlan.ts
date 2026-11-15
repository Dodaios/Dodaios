/**
 * The to-do list a coding agent keeps for itself, read from its tool calls.
 *
 * Agents track a longer job as a list of steps and tick them off as they go.
 * Each CLI has its own tool for it:
 *
 * - a whole-list tool sends the full list on every call: Claude Code's
 *   `TodoWrite` ({todos: [{content, status, activeForm}]}), Codex's
 *   `update_plan` ({plan: [{step, status}]}), Gemini's `write_todos`,
 *   OpenCode's `todowrite`, Cursor's todo tool (which may `merge` by id);
 * - Claude Code's task tools change one entry per call: `TaskCreate`
 *   ({subject, activeForm}) answers "Task #3 created successfully: …",
 *   `TaskUpdate` ({taskId, status, subject}) sets a status or deletes the
 *   task, and `TaskList` / `TaskGet` only read the list back.
 *
 * This module is the pure model behind the checklist a thread draws: which
 * calls are list calls, and for every such call the list as it stood right
 * after it and what the call changed. The task tools build on earlier calls
 * (also of earlier turns), so the list is folded over the whole conversation
 * in order.
 *
 * It never guesses a status the agent did not set: an entry is in progress
 * only when the agent said so.
 *
 * Each entry also keeps its times: when it came onto the list, when the agent
 * began it, and for a checked entry how long it took. Only working time
 * counts: the hours between two turns, while the agent waited for the person,
 * are left out.
 */

import type { TimelineItem, TurnBlock } from "./reduce";

export type PlanStatus = "pending" | "in_progress" | "completed";

export interface PlanItem {
  /** Stable within one list: the task's id, the entry's own id, else its place. */
  id: string;
  text: string;
  status: PlanStatus;
  /** The entry in its "doing" form ("Creating a.txt"), when the agent gave one. */
  active?: string;
  /** When the entry came onto the list. */
  addedMs?: number;
  /** When the agent began it (see `planViews` for an entry it checked off without beginning it). */
  startedMs?: number;
  /** How long a checked entry took, working time only; absent when that is not known. */
  tookMs?: number;
}

/** When a turn of the conversation ran; `endMs` is Infinity while it runs. */
export interface PlanSpan {
  startMs: number;
  endMs: number;
}

export type PlanChangeKind = "added" | "started" | "completed" | "removed";

export interface PlanChange {
  kind: PlanChangeKind;
  text: string;
}

/** The list right after one call, and what that call did to it. */
export interface PlanView {
  items: PlanItem[];
  changes: PlanChange[];
  /** The call began a new list: none stood before it, or the one before was finished or replaced. */
  fresh: boolean;
}

/** What a list call does: send the whole list, add one entry, change one entry, or only read. */
export type PlanCallKind = "list" | "create" | "update" | "read";

/** A tool's own name past the road it came by, lowercase, without "-", "_" or spaces. */
function bareKey(name: string): string {
  const raw = name.trim();
  const cut = Math.max(raw.lastIndexOf("__"), raw.lastIndexOf("/"), raw.lastIndexOf("."));
  const bare = cut >= 0 ? raw.slice(raw[cut] === "_" ? cut + 2 : cut + 1) : raw;
  return bare.toLowerCase().replace(/[-_\s]/g, "");
}

const WHOLE_LIST: ReadonlySet<string> = new Set([
  "todowrite", "updateplan", "writetodos", "updatetodos", "todolist", "settodos", "todoupdate", "updatetodolist",
]);
const READS: ReadonlySet<string> = new Set(["tasklist", "taskget", "todoread", "readtodos"]);

/** Which kind of list call a tool is, by its name; null for every other tool. */
export function planCallKind(name: string): PlanCallKind | null {
  const key = bareKey(name);
  if (WHOLE_LIST.has(key)) return "list";
  if (key === "taskcreate") return "create";
  if (key === "taskupdate") return "update";
  if (READS.has(key)) return "read";
  return null;
}

/** The agent only read its own list back: nothing a reader needs to see. */
export function isPlanRead(name: string): boolean {
  return planCallKind(name) === "read";
}

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

function text(value: unknown): string {
  return typeof value === "string" ? value.replace(/\s+/g, " ").trim() : "";
}

/** A status in any CLI's spelling ("in_progress", "TODO_STATUS_COMPLETED", "done"); null drops the entry. */
function statusOf(raw: unknown, done: unknown): PlanStatus | null {
  if (done === true) return "completed";
  const key = typeof raw === "string" ? raw.toLowerCase().replace(/[^a-z]/g, "").replace(/^todostatus/, "") : "";
  if (/^(completed?|done|finished|success)$/.test(key)) return "completed";
  if (/^(inprogress|active|running|doing|started|current)$/.test(key)) return "in_progress";
  if (/^(cancell?ed|deleted|removed|skipped|dropped)$/.test(key)) return null;
  return "pending";
}

const LIST_KEYS = ["todos", "plan", "items", "entries", "steps", "tasks"];
const TEXT_KEYS = ["content", "text", "step", "subject", "title", "task", "description", "name"];

/** The entries a whole-list call carries, or null when its input holds no list. */
function listEntries(input: unknown): PlanItem[] | null {
  const args = record(input);
  if (!args) return null;
  // A runtime's permission request nests the tool's own arguments.
  const source = LIST_KEYS.some((key) => Array.isArray(args[key])) ? args : record(args.arguments) ?? args;
  const raw = LIST_KEYS.map((key) => source[key]).find(Array.isArray) as unknown[] | undefined;
  if (!raw) return null;
  const items: PlanItem[] = [];
  raw.forEach((entry, index) => {
    const row = record(entry);
    const words = row ? TEXT_KEYS.map((key) => text(row[key])).find(Boolean) ?? "" : text(entry);
    if (!words) return;
    const status = row ? statusOf(row.status ?? row.state, row.completed ?? row.done) : "pending";
    if (status === null) return;
    const own = row && (typeof row.id === "string" || typeof row.id === "number") ? String(row.id) : "";
    const active = row ? text(row.activeForm ?? row.active_form) : "";
    items.push({ id: own || `#${index}`, text: words, status, ...(active ? { active } : {}) });
  });
  return items;
}

/** Whether a whole-list call only changes the entries it names (Cursor's `merge`). */
function merges(input: unknown): boolean {
  const args = record(input);
  return Boolean(args && (args.merge === true || record(args.arguments)?.merge === true));
}

/** One list call, as far as the fold needs it. */
export interface PlanOp {
  callId: string;
  kind: PlanCallKind;
  input: unknown;
  output: string | null;
  /** When the call was made. */
  atMs: number;
}

const OPS = new WeakMap<readonly TurnBlock[], PlanOp[]>();

/** A turn's own list calls, in order. A sub-agent keeps its own list: its calls stay with it. */
function opsOf(blocks: readonly TurnBlock[]): PlanOp[] {
  const known = OPS.get(blocks);
  if (known) return known;
  const ops: PlanOp[] = [];
  for (const block of blocks) {
    if (block.kind !== "tool" || block.isError) continue;
    const kind = planCallKind(block.name);
    if (kind) ops.push({ callId: block.callId, kind, input: block.input, output: block.output, atMs: block.startedMs });
  }
  OPS.set(blocks, ops);
  return ops;
}

/** Every list call of a conversation, oldest first. */
export function planOps(items: readonly TimelineItem[]): PlanOp[] {
  const ops: PlanOp[] = [];
  for (const item of items) if (item.type === "turn") ops.push(...opsOf(item.blocks));
  return ops;
}

/** When each turn of a conversation ran, oldest first. */
export function planSpans(items: readonly TimelineItem[]): PlanSpan[] {
  const spans: PlanSpan[] = [];
  for (const item of items) {
    if (item.type !== "turn") continue;
    const ended = item.status !== "running" && item.durationMs != null;
    spans.push({ startMs: item.startedMs, endMs: ended ? item.startedMs + item.durationMs! : Infinity });
  }
  return spans;
}

/**
 * The working time between two moments: the part of it that falls inside a
 * turn. Without turns, or when neither moment lies in one, the plain span.
 */
export function workedBetween(startMs: number, endMs: number, spans: readonly PlanSpan[]): number {
  if (!(endMs > startMs)) return 0;
  let worked = 0;
  for (const span of spans) {
    const from = Math.max(startMs, span.startMs);
    const to = Math.min(endMs, span.endMs);
    if (to > from) worked += to - from;
  }
  return worked > 0 ? worked : endMs - startMs;
}

/** Whether two runs of list calls are the same calls in the same state. */
export function samePlanOps(a: readonly PlanOp[], b: readonly PlanOp[]): boolean {
  return a.length === b.length && a.every((op, index) =>
    op.callId === b[index].callId && op.input === b[index].input && op.output === b[index].output);
}

function sameText(a: string, b: string): boolean {
  return a.trim().toLowerCase() === b.trim().toLowerCase();
}

/** What turned `before` into `after`, in the order a reader cares about. */
function diff(before: readonly PlanItem[], after: readonly PlanItem[], byId: boolean): PlanChange[] {
  const same = (a: PlanItem, b: PlanItem) => byId ? a.id === b.id : sameText(a.text, b.text);
  const completed: PlanChange[] = [];
  const started: PlanChange[] = [];
  const added: PlanChange[] = [];
  for (const item of after) {
    const old = before.find((entry) => same(entry, item));
    if (!old) {
      added.push({ kind: "added", text: item.text });
      continue;
    }
    if (item.status === old.status) continue;
    if (item.status === "completed") completed.push({ kind: "completed", text: item.text });
    else if (item.status === "in_progress") started.push({ kind: "started", text: item.text });
  }
  const removed = before.filter((entry) => !after.some((item) => same(entry, item)))
    .map((entry): PlanChange => ({ kind: "removed", text: entry.text }));
  return [...completed, ...started, ...added, ...removed];
}

function allDone(items: readonly PlanItem[]): boolean {
  return items.length > 0 && items.every((item) => item.status === "completed");
}

/** The fold's clock: when the current call was made, the turns, and when the last entry was checked off. */
interface Clock {
  atMs: number;
  spans: readonly PlanSpan[];
  /** When the agent last checked an entry off or made a new list: the next entry is current from then. */
  mark: number;
}

function withTimes(item: PlanItem, times: Pick<PlanItem, "addedMs" | "startedMs" | "tookMs">): PlanItem {
  const { addedMs: _added, startedMs: _started, tookMs: _took, ...rest } = item;
  return {
    ...rest,
    ...(times.addedMs != null ? { addedMs: times.addedMs } : {}),
    ...(times.startedMs != null ? { startedMs: times.startedMs } : {}),
    ...(times.tookMs != null ? { tookMs: times.tookMs } : {}),
  };
}

/**
 * `after` with each entry's times carried over from `before` and moved on by
 * what the call changed: an entry put in progress starts now, a checked one
 * gets its working time. An entry the agent checked off without having begun
 * it took the time since the entry before it was checked off (or since the
 * list was made, or since the entry came onto it), but only when it is the
 * one entry the call checked off: several ticked at once say nothing about
 * which took how long.
 */
function stamp(before: readonly PlanItem[], after: readonly PlanItem[], byId: boolean, clock: Clock): PlanItem[] {
  const same = (a: PlanItem, b: PlanItem) => byId ? a.id === b.id : sameText(a.text, b.text);
  const { atMs, spans } = clock;
  let checked = 0;
  let unbegun = -1;
  const out = after.map((item, index) => {
    const old = before.find((entry) => same(entry, item));
    if (!old) return withTimes(item, { addedMs: atMs, startedMs: item.status === "in_progress" ? atMs : undefined });
    const addedMs = old.addedMs;
    if (old.status === item.status) return withTimes(item, { addedMs, startedMs: old.startedMs, tookMs: old.tookMs });
    if (item.status === "in_progress") return withTimes(item, { addedMs, startedMs: atMs });
    if (item.status === "pending") return withTimes(item, { addedMs });
    checked += 1;
    if (old.status === "in_progress" && old.startedMs != null) {
      return withTimes(item, { addedMs, startedMs: old.startedMs, tookMs: workedBetween(old.startedMs, atMs, spans) });
    }
    if (old.status === "pending") unbegun = index;
    return withTimes(item, { addedMs });
  });
  if (checked === 1 && unbegun >= 0) {
    const item = out[unbegun];
    const startedMs = Math.max(clock.mark, item.addedMs ?? -Infinity);
    if (Number.isFinite(startedMs) && startedMs < atMs) out[unbegun] = withTimes(item, { addedMs: item.addedMs, startedMs, tookMs: workedBetween(startedMs, atMs, spans) });
  }
  if (checked > 0) clock.mark = atMs;
  return out;
}

/** "#2 [in_progress] Write the draft [blocked by #1]" — one line of `TaskList`. */
const TASK_LINE = /^#(\d+)\s+\[([\w -]+)\]\s+(.+?)(?:\s+\[blocked by [^\]]*\])?$/i;

/**
 * The list after every list call of a conversation, keyed by the call's id.
 * A call that only read the list has no entry.
 */
export function planViews(ops: readonly PlanOp[], spans: readonly PlanSpan[] = []): ReadonlyMap<string, PlanView> {
  const views = new Map<string, PlanView>();
  let items: PlanItem[] = [];
  const clock: Clock = { atMs: 0, spans, mark: -Infinity };
  // The highest task number seen, for a task whose own number never arrived.
  let highest = 0;
  const note = (id: string) => { if (/^\d+$/.test(id)) highest = Math.max(highest, Number(id)); };

  for (const op of ops) {
    clock.atMs = op.atMs;
    if (op.kind === "list") {
      const sent = listEntries(op.input);
      if (!sent) continue;
      let next = sent;
      const keyed = sent.length > 0 && sent.every((item) => !item.id.startsWith("#")) && items.some((item) => !item.id.startsWith("#"));
      if (merges(op.input) && keyed) {
        // Only the named entries change; the others stay as they were.
        next = items.map((item) => sent.find((entry) => entry.id === item.id) ?? item);
        next.push(...sent.filter((entry) => !items.some((item) => item.id === entry.id)));
      }
      // A list that shares no entry with the one before it is a new plan.
      const overlap = next.some((item) => items.some((old) => keyed ? old.id === item.id : sameText(old.text, item.text)));
      const fresh = items.length === 0 || !overlap;
      if (fresh) clock.mark = op.atMs;
      next = stamp(fresh ? [] : items, next, keyed, clock);
      views.set(op.callId, { items: next, changes: fresh ? [] : diff(items, next, keyed), fresh });
      items = next;
      continue;
    }

    const args = record(op.input) ?? {};
    if (op.kind === "create") {
      const subject = text(args.subject) || text(args.title) || text(args.description);
      if (!subject) continue;
      const answered = /#(\d+)/.exec(op.output ?? "")?.[1];
      const id = answered ?? String(highest + 1);
      note(id);
      const active = text(args.activeForm);
      // A finished list is done with: the next task starts a new one, as the CLI itself clears it.
      const fresh = items.length === 0 || allDone(items);
      if (fresh) clock.mark = op.atMs;
      const base = fresh ? [] : items.filter((item) => item.id !== id);
      const next = [...base, { id, text: subject, status: "pending" as const, addedMs: op.atMs, ...(active ? { active } : {}) }];
      views.set(op.callId, { items: next, changes: [{ kind: "added", text: subject }], fresh });
      items = next;
      continue;
    }

    if (op.kind === "update") {
      const id = text(args.taskId) || (typeof args.taskId === "number" ? String(args.taskId) : "") || text(args.id);
      if (!id) continue;
      note(id);
      const at = items.findIndex((item) => item.id === id);
      const status = "status" in args ? statusOf(args.status, undefined) : undefined;
      const subject = text(args.subject);
      const active = text(args.activeForm);
      let next: PlanItem[];
      if (status === null) {
        if (at < 0) continue;
        next = items.filter((item) => item.id !== id);
      } else if (at < 0) {
        // A task this conversation never saw created (another agent's): shown once it has a name.
        if (!subject) continue;
        next = [...items, { id, text: subject, status: status ?? "pending", ...(active ? { active } : {}) }];
        next = stamp(items, next, true, clock);
      } else {
        const old = items[at];
        const changed: PlanItem = {
          ...old,
          ...(subject ? { text: subject } : {}),
          ...(status ? { status } : {}),
          ...(active ? { active } : {}),
        };
        next = stamp(items, items.map((item, index) => index === at ? changed : item), true, clock);
      }
      views.set(op.callId, { items: next, changes: diff(items, next, true), fresh: false });
      items = next;
      continue;
    }

    // A read brings the list back in step with the CLI's own: what other
    // agents changed, and entries made before this conversation's history.
    const output = (op.output ?? "").trim();
    if (/^no tasks found\.?$/i.test(output)) {
      items = [];
      continue;
    }
    const lines = output.split(/\r?\n/).map((line) => TASK_LINE.exec(line.trim())).filter(Boolean) as RegExpExecArray[];
    if (lines.length === 0) continue;
    let next = items;
    for (const [, id, rawStatus, subject] of lines) {
      note(id);
      const status = statusOf(rawStatus, undefined);
      if (status === null) continue;
      const at = next.findIndex((item) => item.id === id);
      if (at >= 0) {
        const old = next[at];
        if (old.status === status && old.text === subject) continue;
        // A change made elsewhere, at a time this conversation does not know: no times for it.
        const changed = old.status === status ? { ...old, text: subject } : withTimes({ ...old, status, text: subject }, { addedMs: old.addedMs });
        next = next.map((item, index) => index === at ? changed : item);
      } else if (status !== "completed") {
        next = [...next, { id, text: subject, status, addedMs: op.atMs }];
      }
    }
    items = next;
  }
  return views;
}

/** The list after every list call of a conversation (see `planViews`). */
export function planViewsOf(items: readonly TimelineItem[]): ReadonlyMap<string, PlanView> {
  return planViews(planOps(items), planSpans(items));
}

/** How many entries are done, and how many there are. */
export function planProgress(items: readonly PlanItem[]): { done: number; total: number } {
  return { done: items.filter((item) => item.status === "completed").length, total: items.length };
}

/**
 * What a run of list calls did, taken together: the list after the last one
 * and every change since before the first. An agent that ticks one entry off
 * and starts the next with two calls reads as one step.
 */
export function joinPlanViews(views: readonly PlanView[]): PlanView {
  const last = views[views.length - 1];
  if (views.length === 1) return last;
  const fresh = views.some((view) => view.fresh);
  if (fresh) return { items: last.items, changes: [], fresh: true };
  // An entry added and finished within the run reads as finished; one started and finished, as finished.
  const kept = new Map<string, PlanChange>();
  const rank: Record<PlanChangeKind, number> = { added: 0, started: 1, completed: 2, removed: 3 };
  for (const view of views) {
    for (const change of view.changes) {
      const key = change.text.trim().toLowerCase();
      const old = kept.get(key);
      if (!old || rank[change.kind] >= rank[old.kind]) kept.set(key, change);
    }
  }
  const order: PlanChangeKind[] = ["completed", "started", "added", "removed"];
  const changes = order.flatMap((kind) => [...kept.values()].filter((change) => change.kind === kind));
  return { items: last.items, changes, fresh: false };
}
