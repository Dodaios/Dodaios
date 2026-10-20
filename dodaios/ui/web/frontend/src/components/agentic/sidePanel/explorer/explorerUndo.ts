/**
 * Undo and redo for the Folder tab's file actions, and the "ask first"
 * preferences that guard them.
 *
 * Every action runs as one or more {@link FileOp}s. Running an op returns its
 * inverse; an undo entry is the list of inverses, so undoing it runs them
 * backwards and collects THEIR inverses as the redo entry (and the other way
 * round). A delete is undone from the copy the server keeps for that purpose
 * (`undo_token`); without one (too large) Undo says to use the trash.
 */

import { create } from "zustand";

import { fill, translate } from "@/i18n";
import {
  copyEntry,
  createEntry,
  deleteEntry,
  moveEntry,
  restoreEntry,
  TrashUnavailableError,
} from "@/components/agentic/editor/editorApi";
import { checkDisk, moveModels } from "@/components/agentic/editor/editorModels";
import { forgetFileList } from "@/components/agentic/editor/QuickOpen";
import { isUnder, useCodeEditorStore } from "@/store/codeEditor";

export type FileOp =
  | { kind: "move"; from: string; to: string }
  /** `fallbackPermanent`: on a machine without trash, delete for good (a copy is kept for Undo). */
  | { kind: "delete"; path: string; permanent?: boolean; fallbackPermanent?: boolean }
  | { kind: "restore"; path: string; token: string | null }
  | { kind: "copy"; source: string; to: string; unique?: boolean }
  | { kind: "create"; path: string; entry: "file" | "directory" };

export interface FileOpResult {
  /** The op that takes this one back. */
  inverse: FileOp;
  /** Where the entry is now (moved, copied, created or restored); the old path for a delete. */
  path: string;
  /** Workspace paths whose folders need a re-read. */
  touched: string[];
}

export interface FileUndoEntry {
  /** What the user did, as shown in "Undo: …". */
  label: string;
  /** The inverses of the ops that ran, in the order they ran. */
  ops: FileOp[];
}

const MAX_ENTRIES = 50;

const baseName = (path: string) => path.split("/").filter(Boolean).pop() ?? path;

/** Run one file op against the server and keep the open editor tabs in step. */
export async function runFileOp(workspaceId: string, op: FileOp): Promise<FileOpResult> {
  const editor = useCodeEditorStore.getState();
  switch (op.kind) {
    case "move": {
      // A save in flight would land under the old name; wait for it.
      const saving = Object.values(editor.files).some(
        (file) => file.workspaceId === workspaceId && file.saving && isUnder(file.path, op.from),
      );
      if (saving) throw new Error(translate("ide_side_panel.explorer.busy_saving"));
      const moved = await moveEntry(workspaceId, op.from, op.to);
      forgetFileList(workspaceId);
      moveModels(workspaceId, op.from, moved.path);
      editor.renamePath(workspaceId, op.from, moved.path);
      return { inverse: { kind: "move", from: moved.path, to: op.from }, path: moved.path, touched: [op.from, moved.path] };
    }
    case "delete": {
      let answer;
      try {
        answer = await deleteEntry(workspaceId, op.path, op.permanent ?? false);
      } catch (err) {
        if (!(err instanceof TrashUnavailableError) || !op.fallbackPermanent) throw err;
        answer = await deleteEntry(workspaceId, op.path, true);
      }
      useCodeEditorStore.getState().markDeleted(workspaceId, op.path);
      forgetFileList(workspaceId);
      return { inverse: { kind: "restore", path: op.path, token: answer.undo_token }, path: op.path, touched: [op.path] };
    }
    case "restore": {
      if (!op.token) {
        throw new Error(fill(translate("ide_side_panel.explorer.undo_too_large"), { file: baseName(op.path) }));
      }
      const restored = await restoreEntry(workspaceId, op.token);
      forgetFileList(workspaceId);
      // Open tabs of the restored files leave their "deleted" state.
      for (const [fileKey, file] of Object.entries(useCodeEditorStore.getState().files)) {
        if (file.workspaceId === workspaceId && isUnder(file.path, restored.path)) void checkDisk(fileKey);
      }
      return {
        inverse: { kind: "delete", path: restored.path, fallbackPermanent: true },
        path: restored.path,
        touched: [restored.path],
      };
    }
    case "copy": {
      const copied = await copyEntry(workspaceId, op.source, op.to, op.unique ?? false);
      forgetFileList(workspaceId);
      return { inverse: { kind: "delete", path: copied.path, fallbackPermanent: true }, path: copied.path, touched: [copied.path] };
    }
    case "create": {
      const created = await createEntry(workspaceId, op.path, op.entry);
      forgetFileList(workspaceId);
      return { inverse: { kind: "delete", path: created.path, fallbackPermanent: true }, path: created.path, touched: [created.path] };
    }
  }
}

interface FileUndoState {
  undo: Record<string, FileUndoEntry[]>;
  redo: Record<string, FileUndoEntry[]>;
  /** True while an undo or redo runs; a second press waits for it. */
  busy: boolean;
  record: (workspaceId: string, entry: FileUndoEntry) => void;
}

export const useFileUndoStore = create<FileUndoState>((set) => ({
  undo: {},
  redo: {},
  busy: false,
  record: (workspaceId, entry) =>
    set((state) => {
      if (entry.ops.length === 0) return {};
      const stack = [...(state.undo[workspaceId] ?? []), entry].slice(-MAX_ENTRIES);
      // A new action ends the redo chain, as in every editor.
      return { undo: { ...state.undo, [workspaceId]: stack }, redo: { ...state.redo, [workspaceId]: [] } };
    }),
}));

/** Remember a finished action for Undo; `ops` are the inverses its ops returned. */
export function recordFileUndo(workspaceId: string, label: string, ops: FileOp[]): FileUndoEntry | null {
  if (ops.length === 0) return null;
  const entry = { label, ops };
  useFileUndoStore.getState().record(workspaceId, entry);
  return entry;
}

export type UndoDirection = "undo" | "redo";

/** The entry the next undo or redo would run, without running it. */
export function peekFileUndo(workspaceId: string, direction: UndoDirection): FileUndoEntry | null {
  const stack = useFileUndoStore.getState()[direction][workspaceId] ?? [];
  return stack[stack.length - 1] ?? null;
}

export interface ReplayResult {
  label: string;
  /** Where the entries are now. */
  paths: string[];
  touched: string[];
  error: Error | null;
}

/**
 * Undo or redo the newest action. One op failing (a file too large to keep,
 * a name taken meanwhile) does not stop the others; the ops that succeeded
 * move to the other stack, so what was done can still be redone.
 */
export async function replayFileUndo(workspaceId: string, direction: UndoDirection): Promise<ReplayResult | null> {
  const store = useFileUndoStore;
  if (store.getState().busy) return null;
  const entry = peekFileUndo(workspaceId, direction);
  if (!entry) return null;
  const other: UndoDirection = direction === "undo" ? "redo" : "undo";
  store.setState((state) => ({
    busy: true,
    [direction]: { ...state[direction], [workspaceId]: (state[direction][workspaceId] ?? []).slice(0, -1) },
  }));
  const inverses: FileOp[] = [];
  const paths: string[] = [];
  const touched: string[] = [];
  let error: Error | null = null;
  try {
    for (const op of [...entry.ops].reverse()) {
      try {
        const result = await runFileOp(workspaceId, op);
        inverses.push(result.inverse);
        paths.push(result.path);
        touched.push(...result.touched);
      } catch (err) {
        error ??= err instanceof Error ? err : new Error(String(err));
      }
    }
  } finally {
    store.setState((state) => ({
      busy: false,
      [other]:
        inverses.length > 0
          ? { ...state[other], [workspaceId]: [...(state[other][workspaceId] ?? []), { label: entry.label, ops: inverses }].slice(-MAX_ENTRIES) }
          : state[other],
    }));
  }
  return { label: entry.label, paths, touched, error };
}

/** Whether undoing (or redoing) this entry deletes something. */
export function entryDeletes(entry: FileUndoEntry): boolean {
  return entry.ops.some((op) => op.kind === "delete");
}

/** The questions the Folder tab can be told to stop asking. Permanent deletes always ask. */
export type ConfirmKind = "move" | "delete" | "undo";

const confirmKey = (kind: ConfirmKind) => `dodaios.explorer.confirm.${kind}`;

export function shouldConfirm(kind: ConfirmKind): boolean {
  try {
    return window.localStorage.getItem(confirmKey(kind)) !== "never";
  } catch {
    return true; // storage blocked: ask every time
  }
}

export function setConfirm(kind: ConfirmKind, ask: boolean): void {
  try {
    if (ask) window.localStorage.removeItem(confirmKey(kind));
    else window.localStorage.setItem(confirmKey(kind), "never");
  } catch {
    // storage blocked: the choice lasts until the page reloads at most
  }
}
