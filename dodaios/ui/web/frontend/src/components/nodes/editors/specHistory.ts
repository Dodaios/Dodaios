/**
 * The undo history of an editor, as pure functions over immutable snapshots.
 *
 * Every version of the spec is kept whole, but cheaply: changes are made with
 * `produce`, so consecutive versions share everything that did not change.
 * That makes undo and redo trivially correct (no inverse patches to get
 * wrong, whatever the type's spec looks like) and lets "is this the version
 * on the server?" be a plain identity check.
 *
 * Three rules shape the history:
 *
 * * A RUN of changes with the same `coalesce` key (the keystrokes typed into
 *   one field) is one step, as long as the changes follow each other within
 *   `COALESCE_MS`. Another key, a pause, an undo, or `breakCoalesce` ends it.
 * * A new change clears what could be redone: redo only replays a branch
 *   that is still the one the person is on.
 * * The history keeps at most `depth` steps; the oldest fall off.
 */
import { produce } from "./produce";

/** Changes in one run further apart than this start a new undo step. */
export const COALESCE_MS = 2_000;
/** Undo steps kept by default. */
export const HISTORY_DEPTH = 200;

export interface HistoryEntry<S> {
  /** The spec on the other side of the step (before it for undo, after it for redo). */
  spec: S;
  /** What the step did, for the undo and redo buttons' tooltips. */
  label: string;
}

export interface SpecHistory<S> {
  past: readonly HistoryEntry<S>[];
  present: S;
  future: readonly HistoryEntry<S>[];
  /** The open run of coalesced changes, or null. */
  run: { key: string; at: number } | null;
}

export function createHistory<S>(present: S): SpecHistory<S> {
  return { past: [], present, future: [], run: null };
}

export interface ChangeOptions {
  label?: string;
  coalesce?: string;
}

/** The history after `change`; the same object when the change changed nothing. */
export function applyChange<S>(
  history: SpecHistory<S>,
  change: (draft: S) => S | void,
  options: ChangeOptions = {},
  now: number = Date.now(),
  depth: number = HISTORY_DEPTH,
): SpecHistory<S> {
  const next = produce(history.present, change);
  if (Object.is(next, history.present)) return history;
  return commit(history, next, options, now, depth);
}

/** The history with `next` as the present, as one step (or merged into the open run). */
export function commit<S>(
  history: SpecHistory<S>,
  next: S,
  options: ChangeOptions = {},
  now: number = Date.now(),
  depth: number = HISTORY_DEPTH,
): SpecHistory<S> {
  const key = options.coalesce ?? null;
  const run = history.run;
  if (key !== null && run !== null && run.key === key && now - run.at < COALESCE_MS && history.past.length > 0) {
    return { past: history.past, present: next, future: [], run: { key, at: now } };
  }
  const past = [...history.past, { spec: history.present, label: options.label ?? "" }];
  if (past.length > depth) past.splice(0, past.length - depth);
  return { past, present: next, future: [], run: key !== null ? { key, at: now } : null };
}

export function undo<S>(history: SpecHistory<S>): SpecHistory<S> {
  const last = history.past[history.past.length - 1];
  if (last === undefined) return history.run === null ? history : { ...history, run: null };
  return {
    past: history.past.slice(0, -1),
    present: last.spec,
    future: [{ spec: history.present, label: last.label }, ...history.future],
    run: null,
  };
}

export function redo<S>(history: SpecHistory<S>): SpecHistory<S> {
  const [next, ...rest] = history.future;
  if (next === undefined) return history.run === null ? history : { ...history, run: null };
  return {
    past: [...history.past, { spec: history.present, label: next.label }],
    present: next.spec,
    future: rest,
    run: null,
  };
}

/** The history with its open run closed: the next change is a step of its own. */
export function breakRun<S>(history: SpecHistory<S>): SpecHistory<S> {
  return history.run === null ? history : { ...history, run: null };
}
