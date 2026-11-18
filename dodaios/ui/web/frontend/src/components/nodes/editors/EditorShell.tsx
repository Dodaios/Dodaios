/**
 * The common frame of every node editor.
 *
 * A node opens straight in its editor: the body fills the stage, and the
 * type's tools float in one small bar at the bottom (`NodeBar`): the few
 * used most as icons, "⋯" for the rest (undo and redo with them), then the
 * stage's comment button and "Chat". There is no toolbar row on top and no
 * Done: the work is saved as it is made, and closing the node saves what is
 * left. An inspector panel beside the body shows only where the editor puts
 * one (each type opens it from its bar). Above the body, a strip explains a
 * conflict or a save that did not go through.
 *
 * The frame also scopes the editor's keys: the hook's undo/redo shortcuts act
 * only while focus is inside this frame, and focus leaving it saves.
 *
 * Closing the node saves first (`leaveGuard.ts`). If the save cannot go
 * through, the frame says so and offers to leave anyway instead of dropping
 * the person's work without a word.
 */
import { useCallback, useEffect, useRef, useState, type FocusEvent, type ReactNode } from "react";
import { AlertTriangle, CloudOff, Loader2, Redo2, Undo2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { QuickTooltip } from "@/components/ui/tooltip";
import { useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { NodeBar, NodeBarDivider, NodeBarEnd, NodeBarMore } from "../bar/NodeBar";
import { MenuDivider, MenuItem } from "./controls";
import { useLeaveGuard } from "./leaveGuard";
import type { NodeSpecEditor } from "./useNodeSpecEditor";

const IS_MAC = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
const MOD = IS_MAC ? "⌘" : "Ctrl+";
const REDO_KEYS = IS_MAC ? "⇧⌘Z" : "Ctrl+Y";

export interface EditorShellProps {
  // The shell reads only the editor's state and actions; the spec's type does not matter here.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  editor: NodeSpecEditor<any>;
  /** The node's title, the frame's accessible name. */
  title: string;
  /** Part of every editor's contract; the stage closes the node, the frame has no Done of its own. */
  onDone: () => void;
  /** The type's tools used most: icons in the node bar. */
  toolbar?: ReactNode;
  /** The type's tools used now and then: items of the bar's "⋯" menu, after undo and redo. */
  more?: ReactNode | ((close: () => void) => ReactNode);
  /** An inspector panel beside the body; absent while the editor keeps it closed. */
  side?: ReactNode;
  /** Classes for the body (the default scrolls). */
  bodyClassName?: string;
  /** Lifts the bar over something at the bottom of the body that has to stay in view (a sheet's tabs). */
  barInset?: number;
  children: ReactNode;
}

export function EditorShell({ editor, title, toolbar, more, side, bodyClassName, barInset = 0, children }: EditorShellProps) {
  const t = useT();
  const [leaving, setLeaving] = useState<"idle" | "saving" | "stuck">("idle");
  const leaveAnyway = useRef<(() => void) | null>(null);
  const flushRef = useRef(editor.flush);
  flushRef.current = editor.flush;

  /* Closing the node comes through here first: save, then close; stay and
   * say so when the save does not go through. */
  const guard = useLeaveGuard();
  useEffect(() => {
    if (!guard) return;
    return guard.hold((go) => {
      setLeaving("saving");
      void flushRef.current().then((saved) => {
        if (saved) {
          setLeaving("idle");
          go();
        } else {
          leaveAnyway.current = go;
          setLeaving("stuck");
        }
      });
    });
  }, [guard]);

  /* Focus moving between two fields of the editor ends a typing run (the
   * next field's typing is its own undo step); focus leaving the editor also
   * saves. */
  const onBlur = useCallback(
    (event: FocusEvent<HTMLDivElement>) => {
      const next = event.relatedTarget as Node | null;
      const inside = next !== null && (event.currentTarget.contains(next) || isEditorPopover(next));
      if (inside) editor.breakCoalesce();
      else editor.onBlur();
    },
    [editor],
  );

  const undoLabel = editor.undoLabel ? `${t("nodes.editor.undo")}: ${editor.undoLabel}` : t("nodes.editor.undo");
  const redoLabel = editor.redoLabel ? `${t("nodes.editor.redo")}: ${editor.redoLabel}` : t("nodes.editor.redo");

  return (
    <div
      role="region"
      aria-label={t("nodes.editor.region").replace("{0}", title)}
      className="flex h-full min-h-0 flex-col bg-background"
      onKeyDown={editor.onKeyDown}
      onBlur={onBlur}
      data-testid="node-editor"
    >
      {editor.conflict !== null && (
        <div
          role="alert"
          className="flex shrink-0 flex-wrap items-center gap-2 border-b border-border bg-warning/10 px-4 py-2 text-sm"
          data-testid="node-editor-conflict"
        >
          <AlertTriangle className="h-4 w-4 shrink-0 text-warning" aria-hidden />
          <span className="min-w-0 flex-1">{t("nodes.editor.conflict.message")}</span>
          <Button size="sm" variant="outline" onClick={editor.takeTheirs} data-testid="node-editor-take-theirs">
            {t("nodes.editor.conflict.theirs")}
          </Button>
          <Button size="sm" variant="secondary" onClick={editor.keepMine} data-testid="node-editor-keep-mine">
            {t("nodes.editor.conflict.mine")}
          </Button>
        </div>
      )}
      {leaving === "stuck" && (
        <div
          role="alert"
          className="flex shrink-0 flex-wrap items-center gap-2 border-b border-border bg-destructive/10 px-4 py-2 text-sm"
          data-testid="node-editor-unsaved"
        >
          <CloudOff className="h-4 w-4 shrink-0 text-destructive" aria-hidden />
          <span className="min-w-0 flex-1">{t("nodes.editor.leave.message")}</span>
          <Button size="sm" variant="outline" onClick={() => setLeaving("idle")}>
            {t("nodes.editor.leave.stay")}
          </Button>
          <Button
            size="sm"
            variant="destructive"
            onClick={() => {
              setLeaving("idle");
              leaveAnyway.current?.();
            }}
            data-testid="node-editor-leave-anyway"
          >
            {t("nodes.editor.leave.anyway")}
          </Button>
        </div>
      )}
      <div className="flex min-h-0 flex-1">
        <div className="relative flex min-h-0 min-w-0 flex-1 flex-col">
          <div className={cn("min-h-0 min-w-0 flex-1 overflow-auto", bodyClassName)}>{children}</div>
          <NodeBar label={t("nodes.editor.toolbar")} inset={barInset}>
            {toolbar}
            {toolbar && <NodeBarDivider />}
            <SaveStatus editor={editor} leaving={leaving === "saving"} />
            <NodeBarMore testId="node-editor-more">
              {(close) => (
                <>
                  <SaveLine editor={editor} />
                  <MenuItem
                    label={undoLabel}
                    aria-label={undoLabel}
                    icon={<Undo2 aria-hidden />}
                    shortcut={`${MOD}Z`}
                    disabled={!editor.canUndo}
                    onClick={editor.undo}
                    data-testid="node-editor-undo"
                  />
                  <MenuItem
                    label={redoLabel}
                    aria-label={redoLabel}
                    icon={<Redo2 aria-hidden />}
                    shortcut={REDO_KEYS}
                    disabled={!editor.canRedo}
                    onClick={editor.redo}
                    data-testid="node-editor-redo"
                  />
                  {more && <MenuDivider />}
                  {typeof more === "function" ? more(close) : more}
                </>
              )}
            </NodeBarMore>
            <NodeBarEnd divider={false} />
          </NodeBar>
        </div>
        {side && (
          <aside
            aria-label={t("nodes.editor.inspector")}
            className="w-72 shrink-0 overflow-y-auto border-l border-border bg-sidebar p-4 animate-in fade-in-0 slide-in-from-right-2 duration-150 motion-reduce:animate-none"
          >
            {side}
          </aside>
        )}
      </div>
    </div>
  );
}

/** A popover of the editor is portalled out of the frame but still part of it. */
function isEditorPopover(node: Node): boolean {
  return node instanceof Element && node.closest("[data-node-editor-popover], [data-combobox-panel]") !== null;
}

/**
 * Whether the work is safe. Saving is quiet: the words are there for screen
 * readers and at the top of "⋯", and the bar itself shows a mark only when
 * there is something to do about it: a warning that names the reason when a
 * save is held or the node changed elsewhere, a crossed-out cloud that tries
 * again on a click when a save was refused, and a turning circle while the
 * node waits for its last save to close.
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function SaveStatus({ editor, leaving = false }: { editor: NodeSpecEditor<any>; leaving?: boolean }) {
  const words = useSaveWords(editor);
  const { saveState } = editor;
  const state = leaving && saveState !== "failed" && saveState !== "conflict" ? "saving" : saveState;
  let mark: ReactNode = null;
  if (state === "saving" && leaving) {
    mark = (
      <span className="inline-flex h-8 w-8 items-center justify-center text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
      </span>
    );
  } else if (state === "held" || state === "conflict") {
    mark = (
      <span className="inline-flex h-8 w-8 items-center justify-center text-warning">
        <AlertTriangle className="h-4 w-4" aria-hidden />
      </span>
    );
  } else if (state === "failed") {
    mark = (
      <button
        type="button"
        onClick={editor.retry}
        aria-label={words}
        data-testid="node-editor-retry"
        className={cn(
          "inline-flex h-8 w-8 items-center justify-center rounded-md text-destructive transition-colors hover:bg-secondary",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        )}
      >
        <CloudOff className="h-4 w-4" aria-hidden />
      </button>
    );
  }
  return (
    <div
      className="flex shrink-0 items-center"
      aria-live="polite"
      data-testid="node-editor-save-state"
      data-state={state}
    >
      {mark !== null && (
        <QuickTooltip content={words} side="top" className="inline-flex">
          {mark}
        </QuickTooltip>
      )}
      <span className="sr-only">{words}</span>
    </div>
  );
}

/** The save state in words: "Saving…", "Saved", "Unsaved changes", or why it is not saved. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function useSaveWords(editor: NodeSpecEditor<any>): string {
  const t = useT();
  const { saveState, error, dirty } = editor;
  if (saveState === "saving") return t("nodes.editor.save.saving");
  if (saveState === "saved") return t("nodes.editor.save.saved");
  if (saveState === "held") return error || t("nodes.editor.save.held");
  if (saveState === "conflict") return t("nodes.editor.save.conflict");
  if (saveState === "failed") return `${error || t("nodes.editor.save.failed")} · ${t("nodes.editor.save.retry")}`;
  return dirty ? t("nodes.editor.save.pending") : "";
}

/** The first line of "⋯": the save state, quietly. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function SaveLine({ editor }: { editor: NodeSpecEditor<any> }) {
  const words = useSaveWords(editor);
  if (!words) return null;
  return (
    <p className="truncate px-2 pb-1 pt-1 text-xs text-muted-foreground" data-testid="node-editor-save-line">
      {words}
    </p>
  );
}
