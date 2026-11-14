/**
 * The grid's floating panels: the context menu (a right click, the menu key,
 * Shift+F10, or a column head's menu button) and a column's filter.
 *
 * Both open at a point rather than under a trigger, which is why they are
 * not the shared `Popover`; they follow its conventions all the same: drawn
 * in a portal, marked `data-node-editor-popover` (so the editor frame treats
 * focus inside them as focus inside the editor), focus goes in on open and
 * back to the grid on close, Escape and a click outside close them, and the
 * arrow keys move through a menu.
 */
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { MenuItem } from "../controls";
import { useT } from "@/i18n";
import { cn } from "@/lib/utils";

export interface MenuEntry {
  id: string;
  label: string;
  icon?: ReactNode;
  shortcut?: string;
  disabled?: boolean;
  destructive?: boolean;
  checked?: boolean;
  run: () => void;
}

/** A separator between groups of entries. */
export const SEPARATOR = "-";

export type MenuLine = MenuEntry | typeof SEPARATOR;

function usePlacement(x: number, y: number, panel: React.RefObject<HTMLDivElement | null>) {
  const [place, setPlace] = useState({ left: -9999, top: -9999 });
  useLayoutEffect(() => {
    const width = panel.current?.offsetWidth ?? 0;
    const height = panel.current?.offsetHeight ?? 0;
    setPlace({
      left: Math.max(8, Math.min(x, window.innerWidth - width - 8)),
      top: Math.max(8, Math.min(y, window.innerHeight - height - 8)),
    });
  }, [x, y, panel]);
  return place;
}

function useDismiss(panel: React.RefObject<HTMLDivElement | null>, onClose: () => void) {
  useEffect(() => {
    const onPointer = (event: PointerEvent) => {
      if (!panel.current?.contains(event.target as Node)) onClose();
    };
    window.addEventListener("pointerdown", onPointer, true);
    return () => window.removeEventListener("pointerdown", onPointer, true);
  }, [panel, onClose]);
}

export function ContextMenu({
  x,
  y,
  label,
  lines,
  onClose,
}: {
  x: number;
  y: number;
  label: string;
  lines: readonly MenuLine[];
  onClose: () => void;
}) {
  const panel = useRef<HTMLDivElement | null>(null);
  const place = usePlacement(x, y, panel);
  useDismiss(panel, onClose);
  useEffect(() => {
    const frame = window.requestAnimationFrame(() =>
      panel.current?.querySelector<HTMLElement>('[role^="menuitem"]:not([disabled])')?.focus(),
    );
    return () => window.cancelAnimationFrame(frame);
  }, []);
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    event.stopPropagation();
    if (event.key === "Escape" || event.key === "Tab") {
      event.preventDefault();
      onClose();
      return;
    }
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const items = Array.from(panel.current?.querySelectorAll<HTMLElement>('[role^="menuitem"]:not([disabled])') ?? []);
    if (!items.length) return;
    const at = items.indexOf(document.activeElement as HTMLElement);
    const next =
      event.key === "Home"
        ? 0
        : event.key === "End"
          ? items.length - 1
          : event.key === "ArrowDown"
            ? (at + 1) % items.length
            : (at - 1 + items.length) % items.length;
    items[next]?.focus();
  };
  return createPortal(
    <div
      ref={panel}
      role="menu"
      aria-label={label}
      onKeyDown={onKeyDown}
      onContextMenu={(event) => event.preventDefault()}
      style={place}
      className="fixed z-[100] min-w-[14rem] rounded-lg border border-border bg-popover p-1 text-popover-foreground shadow-float"
      data-node-editor-popover=""
      data-testid="sheet-menu"
    >
      {lines.map((line, index) =>
        line === SEPARATOR ? (
          <div key={`sep-${index}`} role="separator" className="my-1 h-px bg-border" />
        ) : (
          <MenuItem
            key={line.id}
            label={line.label}
            icon={line.icon}
            shortcut={line.shortcut}
            disabled={line.disabled}
            destructive={line.destructive}
            checked={line.checked}
            data-testid={`sheet-menu-${line.id}`}
            onClick={() => {
              onClose();
              line.run();
            }}
          />
        ),
      )}
    </div>,
    document.body,
  );
}

/** The values a column's filter offers, with how many rows hold each. */
export interface FilterValue {
  value: string;
  count: number;
}

/**
 * A column's filter: the column's distinct values as checkboxes, a search
 * over them, select all or none. Filtering is a view of the grid while the
 * person works (the page has its own filter for readers); it is not saved.
 */
export function FilterPanel({
  x,
  y,
  column,
  values,
  allowed,
  onApply,
  onClose,
}: {
  x: number;
  y: number;
  column: string;
  values: readonly FilterValue[];
  /** The values let through now; null when the column is not filtered. */
  allowed: readonly string[] | null;
  onApply: (allowed: string[] | null) => void;
  onClose: () => void;
}) {
  const t = useT();
  const panel = useRef<HTMLDivElement | null>(null);
  const place = usePlacement(x, y, panel);
  useDismiss(panel, onClose);
  const [query, setQuery] = useState("");
  const [picked, setPicked] = useState<Set<string>>(() => new Set(allowed ?? values.map((v) => v.value)));
  const shown = useMemo(() => {
    const words = query.toLocaleLowerCase().split(/\s+/).filter(Boolean);
    return values.filter((entry) => words.every((word) => entry.value.toLocaleLowerCase().includes(word)));
  }, [query, values]);
  useEffect(() => {
    const frame = window.requestAnimationFrame(() => panel.current?.querySelector<HTMLElement>("input")?.focus());
    return () => window.cancelAnimationFrame(frame);
  }, []);
  const apply = () => {
    onApply(picked.size === values.length ? null : [...picked]);
    onClose();
  };
  const empty = t("nodes.editor.sheets.filter.empty");
  return createPortal(
    <div
      ref={panel}
      role="dialog"
      aria-label={t("nodes.editor.sheets.filter.title").replace("{0}", column)}
      onKeyDown={(event) => {
        event.stopPropagation();
        if (event.key === "Escape") {
          event.preventDefault();
          onClose();
        } else if (event.key === "Enter" && (event.target as HTMLElement).tagName === "INPUT" && (event.target as HTMLInputElement).type === "search") {
          event.preventDefault();
          apply();
        }
      }}
      style={place}
      className="fixed z-[100] flex w-64 flex-col gap-2 rounded-lg border border-border bg-popover p-2 text-sm text-popover-foreground shadow-float"
      data-node-editor-popover=""
      data-own-undo=""
      data-testid="sheet-filter"
    >
      <input
        type="search"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder={t("nodes.editor.sheets.filter.search")}
        aria-label={t("nodes.editor.sheets.filter.search")}
        className="h-8 rounded-md border border-border-strong bg-input px-2 text-sm focus:border-accent focus:outline-none focus:ring-2 focus:ring-ring"
      />
      <div className="flex gap-2 text-xs">
        <button type="button" className="text-accent hover:underline" onClick={() => setPicked(new Set(values.map((v) => v.value)))}>
          {t("nodes.editor.sheets.filter.all")}
        </button>
        <button type="button" className="text-accent hover:underline" onClick={() => setPicked(new Set())}>
          {t("nodes.editor.sheets.filter.none")}
        </button>
      </div>
      <div role="group" aria-label={t("nodes.editor.sheets.filter.values")} className="max-h-56 overflow-y-auto">
        {shown.map((entry) => (
          <label key={entry.value} className="flex h-7 cursor-pointer items-center gap-2 rounded px-1 hover:bg-secondary">
            <input
              type="checkbox"
              checked={picked.has(entry.value)}
              onChange={(event) => {
                const next = new Set(picked);
                if (event.target.checked) next.add(entry.value);
                else next.delete(entry.value);
                setPicked(next);
              }}
            />
            <span className={cn("min-w-0 flex-1 truncate", !entry.value && "italic text-muted-foreground")}>
              {entry.value || empty}
            </span>
            <span className="text-xs tabular-nums text-muted-foreground">{entry.count}</span>
          </label>
        ))}
      </div>
      <div className="flex justify-end gap-2">
        <button
          type="button"
          className="h-7 rounded-md px-2 hover:bg-secondary"
          onClick={() => {
            onApply(null);
            onClose();
          }}
        >
          {t("nodes.editor.sheets.filter.clear")}
        </button>
        <button type="button" className="h-7 rounded-md bg-primary px-3 text-primary-foreground" onClick={apply} data-testid="sheet-filter-apply">
          {t("nodes.editor.sheets.filter.apply")}
        </button>
      </div>
    </div>,
    document.body,
  );
}
