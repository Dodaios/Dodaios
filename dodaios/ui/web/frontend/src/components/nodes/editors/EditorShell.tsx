/**
 * The common frame of every node editor.
 *
 * A top bar (undo and redo, the type's own toolbar in the middle, the save
 * state and Done at the end), an optional strip that explains a conflict,
 * then the editor's body with an optional inspector panel beside it. The
 * frame also scopes the editor's keys: the hook's undo/redo shortcuts act
 * only while focus is inside this frame, and focus leaving it saves.
 *
 * Done saves first. If the save cannot go through (offline, refused, or the
 * node moved on), the frame says so and offers to leave anyway instead of
 * dropping the person's work without a word.
 */
import { useCallback, useState, type FocusEvent, type ReactNode } from "react";
import { AlertTriangle, Check, CloudOff, Loader2, Redo2, Undo2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { ToolbarButton, ToolbarGroup, ToolbarSeparator } from "./controls";
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
  onDone: () => void;
  /** The type's own toolbar controls. */
  toolbar?: ReactNode;
  /** An inspector panel beside the body. */
  side?: ReactNode;
  /** Classes for the body (the default scrolls). */
  bodyClassName?: string;
  children: ReactNode;
}

export function EditorShell({ editor, title, onDone, toolbar, side, bodyClassName, children }: EditorShellProps) {
  const t = useT();
  const [leaving, setLeaving] = useState<"idle" | "saving" | "stuck">("idle");

  const done = useCallback(async () => {
    setLeaving("saving");
    const saved = await editor.flush();
    if (saved) {
      setLeaving("idle");
      onDone();
    } else {
      setLeaving("stuck");
    }
  }, [editor, onDone]);

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

  const undoTip = editor.undoLabel ? `${t("nodes.editor.undo")}: ${editor.undoLabel}` : t("nodes.editor.undo");
  const redoTip = editor.redoLabel ? `${t("nodes.editor.redo")}: ${editor.redoLabel}` : t("nodes.editor.redo");

  return (
    <div
      role="region"
      aria-label={t("nodes.editor.region").replace("{0}", title)}
      className="flex h-full min-h-0 flex-col bg-background"
      onKeyDown={editor.onKeyDown}
      onBlur={onBlur}
      data-testid="node-editor"
    >
      <div
        role="toolbar"
        aria-label={t("nodes.editor.toolbar")}
        className="flex h-12 shrink-0 items-center gap-1 overflow-x-auto border-b border-border px-3"
      >
        <ToolbarGroup label={t("nodes.editor.history.group")}>
          <ToolbarButton
            label={undoTip}
            icon={<Undo2 aria-hidden />}
            shortcut={`${MOD}Z`}
            disabled={!editor.canUndo}
            onClick={editor.undo}
            data-testid="node-editor-undo"
          />
          <ToolbarButton
            label={redoTip}
            icon={<Redo2 aria-hidden />}
            shortcut={REDO_KEYS}
            disabled={!editor.canRedo}
            onClick={editor.redo}
            data-testid="node-editor-redo"
          />
        </ToolbarGroup>
        {toolbar && (
          <>
            <ToolbarSeparator />
            <div className="flex min-w-0 items-center gap-1">{toolbar}</div>
          </>
        )}
        <div className="flex-1" />
        <SaveStatus editor={editor} />
        <Button
          size="sm"
          onClick={() => void done()}
          disabled={leaving === "saving"}
          data-testid="node-editor-done"
          className="ml-2 shrink-0"
        >
          {leaving === "saving" && <Loader2 className="animate-spin" aria-hidden />}
          {t("nodes.editor.done")}
        </Button>
      </div>
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
          <Button size="sm" variant="destructive" onClick={onDone} data-testid="node-editor-leave-anyway">
            {t("nodes.editor.leave.anyway")}
          </Button>
        </div>
      )}
      <div className="flex min-h-0 flex-1">
        <div className={cn("min-h-0 min-w-0 flex-1 overflow-auto", bodyClassName)}>{children}</div>
        {side && (
          <aside
            aria-label={t("nodes.editor.inspector")}
            className="w-72 shrink-0 overflow-y-auto border-l border-border bg-sidebar p-4"
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

/** "Saving…", "Saved", "Not saved", with the reason and a retry where it helps. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function SaveStatus({ editor }: { editor: NodeSpecEditor<any> }) {
  const t = useT();
  const { saveState, error, dirty } = editor;
  return (
    <div
      className="flex min-w-0 shrink items-center gap-1.5 text-sm text-muted-foreground"
      aria-live="polite"
      data-testid="node-editor-save-state"
      data-state={saveState}
    >
      {saveState === "saving" && (
        <>
          <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" aria-hidden />
          <span>{t("nodes.editor.save.saving")}</span>
        </>
      )}
      {saveState === "saved" && (
        <>
          <Check className="h-3.5 w-3.5 shrink-0" aria-hidden />
          <span>{t("nodes.editor.save.saved")}</span>
        </>
      )}
      {saveState === "idle" && dirty && <span>{t("nodes.editor.save.pending")}</span>}
      {saveState === "held" && (
        <span className="truncate text-warning" title={error}>
          {error || t("nodes.editor.save.held")}
        </span>
      )}
      {saveState === "conflict" && <span className="text-warning">{t("nodes.editor.save.conflict")}</span>}
      {saveState === "failed" && (
        <>
          <CloudOff className="h-3.5 w-3.5 shrink-0 text-destructive" aria-hidden />
          <span className="max-w-[18rem] truncate text-destructive" title={error}>
            {error || t("nodes.editor.save.failed")}
          </span>
          <button
            type="button"
            onClick={editor.retry}
            className="shrink-0 rounded px-1 text-foreground underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {t("nodes.editor.save.retry")}
          </button>
        </>
      )}
    </div>
  );
}
