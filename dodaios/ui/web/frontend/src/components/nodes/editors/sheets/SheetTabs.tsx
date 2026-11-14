/**
 * The sheet tabs under the grid: pick, add, rename (double-click or F2),
 * reorder (drag, or Alt+Shift+arrow), duplicate and delete (the tab's menu).
 * Arrow keys move between tabs as in any tab list.
 */
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { Plus } from "lucide-react";

import { useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { MAX_NAME_CHARS, MAX_SHEETS } from "./model";

export interface SheetTabsProps {
  names: readonly string[];
  active: number;
  onPick: (index: number) => void;
  onAdd: () => void;
  onRename: (index: number, name: string) => void;
  onMove: (from: number, to: number) => void;
  onMenu: (index: number, x: number, y: number) => void;
  /** Bump to start renaming the active tab (from its menu). */
  renameToken: number;
}

export function SheetTabs({ names, active, onPick, onAdd, onRename, onMove, onMenu, renameToken }: SheetTabsProps) {
  const t = useT();
  const [renaming, setRenaming] = useState<number | null>(null);
  const [dragged, setDragged] = useState<number | null>(null);
  const tabs = useRef<Array<HTMLButtonElement | null>>([]);

  useEffect(() => {
    if (renameToken > 0) setRenaming(active);
    // Only a new request starts a rename, not a change of the active tab.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [renameToken]);

  const focusTab = (index: number) => window.requestAnimationFrame(() => tabs.current[index]?.focus());

  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    if (event.altKey && event.shiftKey && (event.key === "ArrowLeft" || event.key === "ArrowRight")) {
      event.preventDefault();
      const to = index + (event.key === "ArrowLeft" ? -1 : 1);
      if (to >= 0 && to < names.length) {
        onMove(index, to);
        focusTab(to);
      }
      return;
    }
    const to =
      event.key === "ArrowRight"
        ? index + 1
        : event.key === "ArrowLeft"
          ? index - 1
          : event.key === "Home"
            ? 0
            : event.key === "End"
              ? names.length - 1
              : -1;
    if (to >= 0 && to < names.length && to !== index) {
      event.preventDefault();
      onPick(to);
      focusTab(to);
    } else if (event.key === "F2") {
      event.preventDefault();
      setRenaming(index);
    } else if (event.key === "ContextMenu" || (event.key === "F10" && event.shiftKey)) {
      event.preventDefault();
      const box = event.currentTarget.getBoundingClientRect();
      onMenu(index, box.left, box.top - 4);
    }
  };

  return (
    <div className="flex h-10 shrink-0 items-stretch gap-0.5 overflow-x-auto border-t border-border bg-background px-2">
      <div role="tablist" aria-label={t("nodes.editor.sheets.tabs.label")} className="flex items-stretch gap-0.5">
        {names.map((name, index) =>
          renaming === index ? (
            <input
              key={`rename-${index}`}
              autoFocus
              defaultValue={name}
              maxLength={MAX_NAME_CHARS}
              aria-label={t("nodes.editor.sheets.tabs.rename")}
              data-own-undo=""
              className="my-1 w-40 rounded-md border border-accent bg-input px-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
              onFocus={(event) => event.currentTarget.select()}
              onBlur={(event) => {
                onRename(index, event.currentTarget.value);
                setRenaming(null);
              }}
              onKeyDown={(event) => {
                event.stopPropagation();
                if (event.key === "Enter") {
                  event.preventDefault();
                  event.currentTarget.blur();
                  focusTab(index);
                } else if (event.key === "Escape") {
                  event.preventDefault();
                  setRenaming(null);
                  focusTab(index);
                }
              }}
            />
          ) : (
            <button
              key={`tab-${index}`}
              ref={(el) => {
                tabs.current[index] = el;
              }}
              type="button"
              role="tab"
              aria-selected={index === active}
              tabIndex={index === active ? 0 : -1}
              draggable
              className={cn(
                "relative max-w-[220px] shrink-0 truncate px-3 text-sm font-medium transition-colors",
                index === active ? "text-foreground" : "text-muted-foreground hover:text-foreground",
                dragged !== null && dragged !== index && "data-[drop=true]:bg-secondary",
              )}
              onClick={() => onPick(index)}
              onDoubleClick={() => setRenaming(index)}
              onKeyDown={(event) => onKeyDown(event, index)}
              onContextMenu={(event) => {
                event.preventDefault();
                onPick(index);
                onMenu(index, event.clientX, event.clientY);
              }}
              onDragStart={(event) => {
                setDragged(index);
                event.dataTransfer.effectAllowed = "move";
                event.dataTransfer.setData("text/x-sheet-tab", String(index));
              }}
              onDragOver={(event) => {
                if (dragged === null) return;
                event.preventDefault();
                event.currentTarget.dataset.drop = "true";
              }}
              onDragLeave={(event) => delete event.currentTarget.dataset.drop}
              onDrop={(event) => {
                event.preventDefault();
                delete event.currentTarget.dataset.drop;
                if (dragged !== null && dragged !== index) onMove(dragged, index);
                setDragged(null);
              }}
              onDragEnd={() => setDragged(null)}
              data-testid={`sheet-tab-${index}`}
            >
              {index === active && <span aria-hidden className="absolute inset-x-3 top-0 h-0.5 bg-foreground" />}
              {name}
            </button>
          ),
        )}
      </div>
      <button
        type="button"
        aria-label={t("nodes.editor.sheets.tabs.add")}
        title={t("nodes.editor.sheets.tabs.add")}
        disabled={names.length >= MAX_SHEETS}
        onClick={onAdd}
        className="my-1 flex w-8 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-secondary hover:text-foreground disabled:opacity-40"
        data-testid="sheet-tab-add"
      >
        <Plus className="h-4 w-4" aria-hidden />
      </button>
    </div>
  );
}
