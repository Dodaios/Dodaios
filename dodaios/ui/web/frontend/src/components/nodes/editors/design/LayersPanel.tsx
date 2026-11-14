/**
 * The design's blocks as a tree: what is on the page, in order, nested the
 * way the markup nests it.
 *
 * It is a real tree widget (`role="tree"`): one row holds the focus at a time
 * and the arrow keys travel (Up/Down through the visible rows, Right opens or
 * goes in, Left closes or goes out, Home/End). The editor's own keys work on
 * the focused row too: Alt+Up/Down moves the block, Cmd/Ctrl+D duplicates,
 * Delete removes, Enter edits its text. A row can also be dragged: onto the
 * upper or lower edge of another row to go before or after it, onto the
 * middle of a box to go inside it.
 */
import { useEffect, useMemo, useRef, useState, type DragEvent, type KeyboardEvent } from "react";
import {
  AlignLeft,
  Box,
  ChevronRight,
  Heading,
  Image as ImageIcon,
  Link2,
  List,
  Minus,
  MousePointerClick,
  Shapes,
  Table2,
  type LucideIcon,
} from "lucide-react";

import { useT } from "@/i18n";
import { cn } from "@/lib/utils";
import {
  OPEN_DEPTH,
  flattenLayers,
  isWithin,
  samePath,
  type DesignLayer,
  type ElementPath,
  type LayerKind,
} from "./designDoc";

export const KIND_ICONS: Record<LayerKind, LucideIcon> = {
  heading: Heading,
  text: AlignLeft,
  link: Link2,
  button: MousePointerClick,
  image: ImageIcon,
  graphic: Shapes,
  list: List,
  divider: Minus,
  table: Table2,
  box: Box,
};

const key = (path: ElementPath) => path.join(".");

export interface LayersPanelProps {
  layers: DesignLayer[];
  selected: number[] | null;
  onSelect: (path: number[] | null) => void;
  /** The editor's keys on a row (move, duplicate, delete, edit); return true when handled. */
  onRowKey: (event: KeyboardEvent<HTMLElement>, path: number[]) => boolean;
  onDrop: (from: number[], to: number[], where: "before" | "after" | "inside") => void;
}

export function LayersPanel({ layers, selected, onSelect, onRowKey, onDrop }: LayersPanelProps) {
  const t = useT();
  // Rows opened or closed by the person; the rest follow OPEN_DEPTH.
  const [toggled, setToggled] = useState<Map<string, boolean>>(() => new Map());
  const isOpen = (path: number[]) => toggled.get(key(path)) ?? path.length <= OPEN_DEPTH;
  const setOpen = (path: number[], open: boolean) =>
    setToggled((now) => new Map(now).set(key(path), open));

  // A block selected in the preview is shown: every row above it opens.
  useEffect(() => {
    if (!selected || selected.length < 2) return;
    setToggled((now) => {
      let next: Map<string, boolean> | null = null;
      for (let depth = 1; depth < selected.length; depth++) {
        const above = selected.slice(0, depth);
        if ((now.get(key(above)) ?? above.length <= OPEN_DEPTH) === false) {
          next = next ?? new Map(now);
          next.set(key(above), true);
        }
      }
      return next ?? now;
    });
  }, [selected]);

  const rows = useMemo(() => flattenLayers(layers, isOpen), [layers, toggled]); // eslint-disable-line react-hooks/exhaustive-deps
  const focusKey = selected && rows.some((row) => samePath(row.path, selected)) ? key(selected) : rows[0] ? key(rows[0].path) : "";
  const tree = useRef<HTMLDivElement>(null);
  const focusRow = (path: number[]) => {
    onSelect(path);
    window.requestAnimationFrame(() => {
      tree.current?.querySelector<HTMLElement>(`[data-layer="${key(path)}"]`)?.focus();
    });
  };

  // Keep the focused row in view when the selection comes from elsewhere.
  useEffect(() => {
    if (!selected) return;
    tree.current
      ?.querySelector<HTMLElement>(`[data-layer="${key(selected)}"]`)
      ?.scrollIntoView({ block: "nearest" });
  }, [selected]);

  const [drag, setDrag] = useState<{ from: number[]; over: string; where: "before" | "after" | "inside" } | null>(null);

  const onKeyDown = (event: KeyboardEvent<HTMLElement>, row: DesignLayer) => {
    if (onRowKey(event, row.path)) return;
    // With a modifier the arrows are the editor's (Alt+Up/Down moves the
    // block): leave the key to bubble up to it.
    if (event.altKey || event.metaKey || event.ctrlKey) return;
    const index = rows.findIndex((item) => samePath(item.path, row.path));
    const go = (target: DesignLayer | undefined) => {
      if (!target) return;
      event.preventDefault();
      focusRow(target.path);
    };
    switch (event.key) {
      case "ArrowDown":
        go(rows[index + 1]);
        break;
      case "ArrowUp":
        go(rows[index - 1]);
        break;
      case "Home":
        go(rows[0]);
        break;
      case "End":
        go(rows[rows.length - 1]);
        break;
      case "ArrowRight":
        if (row.children.length) {
          event.preventDefault();
          if (!isOpen(row.path)) setOpen(row.path, true);
          else focusRow(row.children[0]!.path);
        }
        break;
      case "ArrowLeft":
        event.preventDefault();
        if (row.children.length && isOpen(row.path)) setOpen(row.path, false);
        else if (row.path.length > 1) focusRow(row.path.slice(0, -1));
        break;
      default:
    }
  };

  const whereOf = (event: DragEvent<HTMLElement>, row: DesignLayer): "before" | "after" | "inside" => {
    const box = event.currentTarget.getBoundingClientRect();
    const y = (event.clientY - box.top) / Math.max(1, box.height);
    const canHold = row.kind === "box" || row.kind === "list";
    if (canHold && y > 0.3 && y < 0.7) return "inside";
    return y < 0.5 ? "before" : "after";
  };

  if (rows.length === 0) {
    return <p className="px-3 py-4 text-sm text-muted-foreground">{t("nodes.editor.design.layers.empty")}</p>;
  }

  return (
    <div
      ref={tree}
      role="tree"
      aria-label={t("nodes.editor.design.layers.label")}
      className="flex flex-col gap-px p-1.5"
      data-testid="design-layers"
    >
      {rows.map((row) => {
        const Icon = KIND_ICONS[row.kind];
        const rowKey = key(row.path);
        const active = samePath(row.path, selected);
        const open = row.children.length ? isOpen(row.path) : undefined;
        const target = drag && drag.over === rowKey ? drag.where : null;
        return (
          <div
            key={rowKey}
            role="treeitem"
            aria-level={row.path.length}
            aria-selected={active}
            aria-expanded={open}
            tabIndex={rowKey === focusKey ? 0 : -1}
            data-layer={rowKey}
            data-testid="design-layer"
            draggable
            onClick={() => onSelect(row.path)}
            onKeyDown={(event) => onKeyDown(event, row)}
            onDragStart={(event) => {
              event.dataTransfer.effectAllowed = "move";
              event.dataTransfer.setData("text/plain", rowKey);
              setDrag({ from: row.path, over: rowKey, where: "before" });
            }}
            onDragOver={(event) => {
              if (!drag || isWithin(row.path, drag.from)) return;
              event.preventDefault();
              const where = whereOf(event, row);
              if (drag.over !== rowKey || drag.where !== where) setDrag({ ...drag, over: rowKey, where });
            }}
            onDrop={(event) => {
              event.preventDefault();
              if (drag && !isWithin(row.path, drag.from)) onDrop(drag.from, row.path, whereOf(event, row));
              setDrag(null);
            }}
            onDragEnd={() => setDrag(null)}
            className={cn(
              "group relative flex h-8 cursor-default select-none items-center gap-1.5 rounded-md pr-2 text-sm outline-none",
              "hover:bg-secondary focus-visible:ring-2 focus-visible:ring-ring",
              active && "bg-secondary font-medium text-foreground",
              target === "inside" && "ring-2 ring-accent",
            )}
            style={{ paddingLeft: `${(row.path.length - 1) * 14 + 4}px` }}
          >
            {target === "before" && <span aria-hidden className="absolute inset-x-1 top-0 h-0.5 rounded bg-accent" />}
            {target === "after" && <span aria-hidden className="absolute inset-x-1 bottom-0 h-0.5 rounded bg-accent" />}
            {row.children.length ? (
              <button
                type="button"
                tabIndex={-1}
                aria-hidden
                onClick={(event) => {
                  event.stopPropagation();
                  setOpen(row.path, !open);
                }}
                className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-muted-foreground hover:text-foreground"
              >
                <ChevronRight className={cn("h-3.5 w-3.5 transition-transform", open && "rotate-90")} />
              </button>
            ) : (
              <span aria-hidden className="w-5 shrink-0" />
            )}
            <Icon aria-hidden className="h-4 w-4 shrink-0 text-muted-foreground" />
            <span className="min-w-0 flex-1 truncate" data-part="label">
              {row.label || t(`nodes.editor.design.kind.${row.kind}`)}
            </span>
            <span className="shrink-0 font-mono text-xs text-muted-foreground opacity-0 group-hover:opacity-100 group-aria-selected:opacity-100">
              {row.tag}
            </span>
          </div>
        );
      })}
    </div>
  );
}
