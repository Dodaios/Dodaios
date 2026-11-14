/**
 * The editing state machine every node editor is built on.
 *
 * It holds the spec being edited and its undo history (`specHistory.ts`),
 * saves the person's work by itself, and keeps that work safe from the one
 * other writer a node has: the assistant, which may revise the node while the
 * editor is open.
 *
 * Saving. Every change schedules a save `saveDelayMs` (700 ms) later; a burst
 * of typing is one save. The save is flushed at once when the editor loses
 * focus, when the window is hidden, when the person presses Done, and when
 * the editor unmounts. Each save names the version it was edited from
 * (`base_version`). What the server answers (the spec as the type's
 * `normalize` kept it) becomes the saved BASE, but is NOT put under the
 * person's hands: `normalize` drops an empty row or bullet the person just
 * added and is about to fill, and swapping it in would make that row vanish.
 * The page drawn after Done shows what was kept.
 *
 * "Unsaved" is an identity check: the present spec is not the object that was
 * last saved or received. Undoing back to the saved version is therefore
 * clean again, without a save.
 *
 * Conflicts. When the server refuses a save because the node moved on (409),
 * or the stage's watcher reports a revision while the person has unsaved
 * work, autosave stops and `conflict` holds the other version: `takeTheirs()`
 * puts it in place as an undoable step (so the person's own work is one undo
 * away), `keepMine()` saves the person's version over it. A revision that
 * arrives while nothing is unsaved is simply taken, also as an undoable step.
 *
 * Shortcuts. `onKeyDown` (wired by `EditorShell` on the editor's root, so
 * the keys only act while focus is inside the editor) maps Cmd/Ctrl+Z to
 * undo and Shift+Cmd/Ctrl+Z and Ctrl+Y to redo. It leaves text fields alone
 * (input, textarea, select, contentEditable): they keep their own undo, or
 * call `undo()`/`redo()` themselves. A field opts into the spec's undo with
 * `data-spec-undo` on itself or an ancestor; `data-own-undo` opts out.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";

import { useT } from "@/i18n";
import { useEventStore } from "@/store/events";
import { NodesApiError } from "../useNodes";
import { SpecConflictError, fetchNodeSpec, saveNodeSpec, type SavedSpec } from "./api";
import { useRevisionSource } from "./editorContext";
import {
  HISTORY_DEPTH,
  applyChange,
  breakRun,
  commit,
  createHistory,
  redo as redoHistory,
  undo as undoHistory,
  type ChangeOptions,
  type SpecHistory,
} from "./specHistory";
import type { NodeEditorInitial } from "./types";

export type SaveState = "idle" | "saving" | "saved" | "failed" | "conflict" | "held";

export type ApplyOptions = ChangeOptions;

export interface NodeSpecEditorOptions<S> {
  /**
   * Runs on the spec before each save. Return the spec to send (strip a
   * transient state the type's `normalize` would refuse), or `{ error }` to
   * hold the save with that sentence until the next change (`saveState`
   * "held"); the local spec is never touched.
   */
  prepare?: (spec: S) => S | { error: string };
  /** Quiet time after a change before it is saved. Default 700 ms. */
  saveDelayMs?: number;
  /** Undo steps kept. Default 200. */
  depth?: number;
}

export interface NodeSpecEditor<S> {
  nodeId: string;
  /** The spec as the person sees it now. */
  spec: S;
  /** The spec as the server last saved or sent it (normalized). */
  saved: S;
  /** The server version the editor works from. */
  version: number;
  updatedAt: number;
  /** Change the spec: mutate the draft, or return the next spec. One undo step (see `coalesce`). */
  apply: (change: (draft: S) => S | void, options?: ApplyOptions) => void;
  undo: () => void;
  redo: () => void;
  canUndo: boolean;
  canRedo: boolean;
  /** Step labels: `undo` oldest first (the last is undone next), `redo` next first. */
  history: { undo: readonly string[]; redo: readonly string[] };
  undoLabel: string | null;
  redoLabel: string | null;
  /** End the open run of coalesced changes: the next change is its own undo step. */
  breakCoalesce: () => void;
  /** The person has changes the server does not have yet. */
  dirty: boolean;
  saveState: SaveState;
  /** Why the last save failed or is held; "" otherwise. */
  error: string;
  /** The other version when the node moved on under unsaved work; null otherwise. */
  conflict: SavedSpec | null;
  takeTheirs: () => void;
  keepMine: () => void;
  /** Save now. Resolves true when everything is saved. */
  flush: () => Promise<boolean>;
  /** Try a failed save again now. */
  retry: () => void;
  /** The stage's watcher saw the node at `updatedAt` (wired by the stage's context too). */
  receiveRevision: (updatedAt: number) => void;
  /** The editor's shortcuts; put on the editor's root element (EditorShell does). */
  onKeyDown: (event: ReactKeyboardEvent | KeyboardEvent) => void;
  /** Focus left the editor: save now and close the run (EditorShell wires it). */
  onBlur: () => void;
}

export const DEFAULT_SAVE_DELAY_MS = 700;
/** Waits before saving again after a failure that may pass (network, server busy). */
const RETRY_DELAYS_MS = [2_000, 5_000, 10_000, 30_000];

/** Whether `target` is a text field with an undo of its own. */
export function hasOwnUndo(target: EventTarget | null): boolean {
  if (!(target instanceof Element)) return false;
  if (target.closest("[data-own-undo]")) return true;
  if (target.closest("[data-spec-undo]")) return false;
  if (target instanceof HTMLElement && target.isContentEditable) return true;
  if (target.closest('[contenteditable=""], [contenteditable="true"], [contenteditable="plaintext-only"]')) return true;
  const tag = target.tagName;
  if (tag === "TEXTAREA" || tag === "SELECT") return true;
  if (tag === "INPUT") {
    const type = (target as HTMLInputElement).type;
    return !["button", "checkbox", "radio", "range", "color", "submit", "reset", "file", "image"].includes(type);
  }
  return false;
}

/** The undo or redo a key press asks for, or null. */
export function shortcutOf(event: Pick<KeyboardEvent, "key" | "metaKey" | "ctrlKey" | "shiftKey" | "altKey">): "undo" | "redo" | null {
  if (event.altKey || !(event.metaKey || event.ctrlKey)) return null;
  const key = event.key.toLowerCase();
  if (key === "z") return event.shiftKey ? "redo" : "undo";
  if (key === "y" && !event.shiftKey) return "redo";
  return null;
}

function heldError(value: unknown): string | null {
  if (value !== null && typeof value === "object" && !Array.isArray(value)) {
    const error = (value as { error?: unknown }).error;
    if (typeof error === "string" && Object.keys(value).length === 1) return error;
  }
  return null;
}

export function useNodeSpecEditor<S>(
  nodeId: string,
  initial: NodeEditorInitial,
  options: NodeSpecEditorOptions<S> = {},
): NodeSpecEditor<S> {
  const t = useT();
  const assistant = useEventStore((s) => s.assistantName);
  const depth = options.depth ?? HISTORY_DEPTH;
  const delay = options.saveDelayMs ?? DEFAULT_SAVE_DELAY_MS;
  const prepareRef = useRef(options.prepare);
  prepareRef.current = options.prepare;
  const labels = useRef({ remote: "", theirs: "" });
  labels.current = {
    remote: t("nodes.editor.history.remote").replace("{assistant}", () => assistant || "Dodaios"),
    theirs: t("nodes.editor.history.theirs"),
  };

  /* The history and the server's side live in refs, so a burst of changes in
   * one event chains correctly and the save machinery always reads the
   * latest; `tick` re-renders after each. */
  const historyRef = useRef<SpecHistory<S>>(createHistory(initial.spec as S));
  const baseRef = useRef<SavedSpec>({ ...initial });
  /** The local spec object the server's version stands for (identity). */
  const savedPresentRef = useRef<S>(initial.spec as S);
  const ownRevisions = useRef(new Set<number>([initial.updated_at]));
  const conflictRef = useRef<SavedSpec | null>(null);
  const inFlight = useRef<Promise<void> | null>(null);
  const timer = useRef<number | null>(null);
  const retryCount = useRef(0);
  const heldRevision = useRef<number | null>(null);
  const alive = useRef(true);
  const [status, setStatus] = useState<{ state: SaveState; error: string }>({ state: "idle", error: "" });
  const [, setTick] = useState(0);
  const rerender = useCallback(() => setTick((n) => n + 1), []);

  const isDirty = () => !Object.is(historyRef.current.present, savedPresentRef.current);

  const clearTimer = () => {
    if (timer.current !== null) {
      window.clearTimeout(timer.current);
      timer.current = null;
    }
  };

  const setState = useCallback((state: SaveState, error = "") => {
    if (alive.current) setStatus((now) => (now.state === state && now.error === error ? now : { state, error }));
  }, []);

  // Declared below; the save loop and the revision check call each other.
  const checkRevision = useRef<(updatedAt: number) => void>(() => {});

  const saveOnce = useCallback(async (): Promise<void> => {
    if (conflictRef.current !== null || !isDirty()) return;
    const sent = historyRef.current.present;
    let body: unknown = sent;
    if (prepareRef.current) {
      const prepared = prepareRef.current(sent);
      const held = heldError(prepared);
      if (held !== null) {
        setState("held", held);
        return;
      }
      body = prepared;
    }
    setState("saving");
    try {
      const saved = await saveNodeSpec(nodeId, body, baseRef.current.version);
      ownRevisions.current.add(saved.updated_at);
      baseRef.current = saved;
      savedPresentRef.current = sent;
      retryCount.current = 0;
      setState(isDirty() ? "saving" : "saved");
    } catch (error) {
      if (error instanceof SpecConflictError) {
        conflictRef.current = error.current;
        setState("conflict", error.detail);
        return;
      }
      const refused = error instanceof NodesApiError && error.status >= 400 && error.status < 500;
      const reason = error instanceof NodesApiError && error.detail ? error.detail : "";
      setState("failed", reason || t("nodes.editor.save.failed"));
      // A refusal waits for the next change; anything else may pass by itself.
      if (!refused && alive.current) {
        const wait = RETRY_DELAYS_MS[Math.min(retryCount.current, RETRY_DELAYS_MS.length - 1)];
        retryCount.current += 1;
        clearTimer();
        timer.current = window.setTimeout(() => void runSave(), wait);
      }
      throw error;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodeId, setState, t]);

  /** Save until the server has the present spec, one request at a time. */
  const runSave = useCallback(async (): Promise<boolean> => {
    clearTimer();
    while (inFlight.current) await inFlight.current.catch(() => undefined);
    try {
      while (isDirty() && conflictRef.current === null) {
        const before = historyRef.current.present;
        inFlight.current = saveOnce();
        await inFlight.current;
        inFlight.current = null;
        // Held by `prepare`, or nothing new since: stop here.
        if (Object.is(historyRef.current.present, before) && isDirty()) break;
      }
    } catch {
      inFlight.current = null;
      return false;
    } finally {
      const held = heldRevision.current;
      if (held !== null && inFlight.current === null) {
        heldRevision.current = null;
        checkRevision.current(held);
      }
    }
    return !isDirty();
  }, [saveOnce]);

  const schedule = useCallback(() => {
    if (conflictRef.current !== null) return;
    clearTimer();
    timer.current = window.setTimeout(() => void runSave(), delay);
  }, [delay, runSave]);

  const afterChange = useCallback(
    (next: SpecHistory<S>) => {
      if (next === historyRef.current) return;
      historyRef.current = next;
      if (isDirty()) {
        if (conflictRef.current === null) schedule();
      } else {
        clearTimer();
        if (conflictRef.current === null) setState("saved");
      }
      rerender();
    },
    [rerender, schedule, setState],
  );

  const apply = useCallback(
    (change: (draft: S) => S | void, opts?: ApplyOptions) =>
      afterChange(applyChange(historyRef.current, change, opts, Date.now(), depth)),
    [afterChange, depth],
  );
  const undo = useCallback(() => afterChange(undoHistory(historyRef.current)), [afterChange]);
  const redo = useCallback(() => afterChange(redoHistory(historyRef.current)), [afterChange]);
  const breakCoalesce = useCallback(() => {
    historyRef.current = breakRun(historyRef.current);
  }, []);

  /** Put the server's version in place as an undoable step. */
  const takeVersion = useCallback(
    (theirs: SavedSpec, label: string) => {
      baseRef.current = theirs;
      ownRevisions.current.add(theirs.updated_at);
      const next = commit(breakRun(historyRef.current), theirs.spec as S, { label }, Date.now(), depth);
      savedPresentRef.current = next.present;
      historyRef.current = next;
      clearTimer();
      setState("saved");
      rerender();
    },
    [depth, rerender, setState],
  );

  checkRevision.current = (updatedAt: number) => {
    if (ownRevisions.current.has(updatedAt) || updatedAt <= baseRef.current.updated_at) return;
    // A save on its way may make exactly this revision: look after it lands.
    if (inFlight.current !== null) {
      heldRevision.current = updatedAt;
      return;
    }
    void fetchNodeSpec(nodeId)
      .then((theirs) => {
        if (!alive.current || theirs.version <= baseRef.current.version) return;
        if (ownRevisions.current.has(theirs.updated_at)) return;
        if (inFlight.current !== null) {
          heldRevision.current = theirs.updated_at;
          return;
        }
        if (isDirty() || conflictRef.current !== null) {
          conflictRef.current = theirs;
          clearTimer();
          setState("conflict");
          rerender();
          return;
        }
        takeVersion(theirs, labels.current.remote);
      })
      .catch(() => {
        // The next report from the watcher asks again.
      });
  };
  const receiveRevision = useCallback((updatedAt: number) => checkRevision.current(updatedAt), []);

  const takeTheirs = useCallback(() => {
    const theirs = conflictRef.current;
    if (theirs === null) return;
    conflictRef.current = null;
    takeVersion(theirs, labels.current.theirs);
  }, [takeVersion]);

  const keepMine = useCallback(() => {
    const theirs = conflictRef.current;
    if (theirs === null) return;
    conflictRef.current = null;
    // Saving over the version the person has now seen.
    baseRef.current = { ...baseRef.current, version: theirs.version, updated_at: theirs.updated_at };
    ownRevisions.current.add(theirs.updated_at);
    rerender();
    if (isDirty()) void runSave();
    else setState("saved");
  }, [rerender, runSave, setState]);

  const flush = useCallback(() => runSave(), [runSave]);
  const retry = useCallback(() => {
    retryCount.current = 0;
    void runSave();
  }, [runSave]);
  const onBlur = useCallback(() => {
    historyRef.current = breakRun(historyRef.current);
    if (isDirty()) void runSave();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runSave]);

  const onKeyDown = useCallback(
    (event: ReactKeyboardEvent | KeyboardEvent) => {
      const wanted = shortcutOf(event);
      if (wanted === null || event.defaultPrevented || hasOwnUndo(event.target)) return;
      event.preventDefault();
      event.stopPropagation();
      if (wanted === "undo") undo();
      else redo();
    },
    [undo, redo],
  );

  // The stage's watcher, when the editor sits in a stage.
  const source = useRevisionSource();
  useEffect(() => source?.subscribe(receiveRevision), [source, receiveRevision]);

  // A hidden window may be closed next: save what is there.
  useEffect(() => {
    const onVisibility = () => {
      if (document.visibilityState === "hidden" && isDirty()) void runSave();
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runSave]);

  // Leaving the editor saves what is still unsaved, even as the view goes away.
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      clearTimer();
      if (isDirty() && conflictRef.current === null && inFlight.current === null) {
        let body: unknown = historyRef.current.present;
        const prepared = prepareRef.current?.(historyRef.current.present as S);
        if (prepared !== undefined) {
          if (heldError(prepared) !== null) return;
          body = prepared;
        }
        void saveNodeSpec(nodeId, body, baseRef.current.version, { keepalive: true }).catch(() => {
          // Nothing is left on screen to tell; the next open shows the server's version.
        });
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodeId]);

  const history = historyRef.current;
  const dirty = isDirty();
  const undoLabels = useMemo(() => history.past.map((entry) => entry.label), [history.past]);
  const redoLabels = useMemo(() => history.future.map((entry) => entry.label), [history.future]);
  const conflict = conflictRef.current;
  const saveState: SaveState = conflict !== null ? "conflict" : status.state;
  return {
    nodeId,
    spec: history.present,
    saved: baseRef.current.spec as S,
    version: baseRef.current.version,
    updatedAt: baseRef.current.updated_at,
    apply,
    undo,
    redo,
    canUndo: history.past.length > 0,
    canRedo: history.future.length > 0,
    history: { undo: undoLabels, redo: redoLabels },
    undoLabel: history.past.length > 0 ? history.past[history.past.length - 1].label : null,
    redoLabel: history.future.length > 0 ? history.future[0].label : null,
    breakCoalesce,
    dirty,
    saveState: saveState === "saved" && dirty ? "idle" : saveState,
    error: status.error,
    conflict,
    takeTheirs,
    keepMine,
    flush,
    retry,
    receiveRevision,
    onKeyDown,
    onBlur,
  };
}
