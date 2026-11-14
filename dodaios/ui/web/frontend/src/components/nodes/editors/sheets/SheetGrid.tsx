/**
 * The spreadsheet grid: cells drawn from the spec, selected and typed into
 * with the keyboard first and the mouse as well.
 *
 * Rows are virtualized: a sheet holds up to 1,000 rows of 30 columns, and
 * only the rows in view (and a margin) are in the DOM, between two spacer
 * rows that keep the scroll height. Rows have one fixed height, so a row's
 * place is arithmetic, never a measurement.
 *
 * Keys go to ONE focused text field that sits over the active cell. When the
 * person just moves around it is invisible and empty; the first character
 * typed (or an input method's composition, which is why it is a real text
 * field and not a key handler) lands in it and turns it into the cell's
 * editor, replacing the value. F2, a double-click or the formula bar edit
 * the value as it is. Copy, cut and paste are the field's clipboard events,
 * so they carry tab-separated text to and from other spreadsheet apps. While
 * the person only moves around, the field carries `data-spec-undo`, so
 * Cmd/Ctrl+Z undoes the last grid step; while typing, the field's own undo
 * applies.
 *
 * Accessibility: the table is an ARIA grid (row and column counts, row and
 * column indices on what is drawn, the selection as `aria-selected`), and the
 * field is labelled with the active cell's address, column and value, so a
 * screen reader announces every move.
 */
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ClipboardEvent,
  type KeyboardEvent,
  type MouseEvent,
} from "react";
import { ArrowDown, ArrowUp, ChevronDown, Filter, Sigma } from "lucide-react";

import { cn } from "@/lib/utils";
import { COLOR_TOKENS, columnLetter, displayText, statusTone, type ColumnView, type Row, type Sheet } from "./model";
import { advance, inRange, jump, move, rangeOf, type GridSize, type Selection } from "./selection";

export const ROW_HEIGHT = 30;
export const HEAD_HEIGHT = 34;
export const ROW_NUMBER_WIDTH = 52;
/*
 * A selected cell's tint is laid over an opaque ground: frozen columns and
 * the sticky head scroll over other cells and must not let them show through.
 */
const SELECTED_CELL = "linear-gradient(hsl(var(--accent) / 0.12), hsl(var(--accent) / 0.12)), hsl(var(--background))";
const SELECTED_HEAD = "linear-gradient(hsl(var(--accent) / 0.14), hsl(var(--accent) / 0.14)), hsl(var(--secondary))";
/** Rows drawn beyond the visible ones on each side, so a fast scroll does not show blanks. */
const OVERSCAN = 10;

export function defaultWidth(kind: string): number {
  switch (kind) {
    case "number":
    case "currency":
    case "percent":
      return 112;
    case "date":
      return 132;
    case "check":
      return 72;
    case "status":
      return 120;
    case "link":
      return 180;
    default:
      return 160;
  }
}

export interface EditState {
  row: number;
  col: number;
  text: string;
  /** "replace": started by typing (arrows commit); "edit": F2 / double-click (arrows move the caret). */
  mode: "replace" | "edit";
}

export interface GridActions {
  /** Write what was typed into a cell (view row). */
  commit: (row: number, col: number, text: string) => void;
  clear: () => void;
  copyText: () => string;
  cut: () => void;
  paste: (text: string) => void;
  fill: (direction: "down" | "right") => void;
  toggleCheck: (row: number, col: number) => void;
  /** Whether a view cell holds something (Cmd/Ctrl+arrow jumps between blocks). */
  filled: (row: number, col: number) => boolean;
  /** The text an edit of a view cell starts from. */
  editText: (row: number, col: number) => string;
  /** Why a cell cannot be typed into ("" when it can). */
  readOnly: (col: number) => string;
  openMenu: (x: number, y: number) => void;
  openColumnMenu: (col: number, x: number, y: number) => void;
  openFilter: (col: number, x: number, y: number) => void;
  resizeColumn: (col: number, width: number) => void;
  moveColumn: (from: number, to: number) => void;
  selectColumns: (left: number, right: number) => void;
  selectRows: (top: number, bottom: number) => void;
  selectAll: () => void;
  toggleBold: () => void;
  openColumnSettings: (col: number) => void;
  announce: (text: string) => void;
}

export interface SheetGridProps {
  sheet: Sheet;
  /** The sheet's rows with formula cells computed, lined up with `sheet.rows`. */
  computed: readonly Row[];
  views: readonly ColumnView[];
  /** Stored row index for each view row that holds data (filtered). */
  viewRows: readonly number[];
  /** All rows the grid shows: `viewRows` plus empty rows below. */
  rowCount: number;
  selection: Selection;
  onSelect: (selection: Selection) => void;
  editing: EditState | null;
  setEditing: (edit: EditState | null) => void;
  actions: GridActions;
  /** Keys of the filtered columns. */
  filtered: ReadonlySet<string>;
  sorted: { key: string; dir: 1 | -1 } | null;
  /** Each column's total as display text (null: no totals row). */
  totals: readonly (string | null)[] | null;
  totalMarks: readonly string[];
  locale?: string;
  label: string;
  labels: {
    columnMenu: (column: string) => string;
    resize: (column: string) => string;
    rowNumber: (row: number) => string;
    cell: (address: string, column: string, value: string) => string;
    empty: string;
    selectAll: string;
    newRow: string;
  };
  /** Focus requests from outside (the toolbar, a closed menu): bump to focus the grid. */
  focusToken: number;
}

const IS_MAC = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);

export function SheetGrid(props: SheetGridProps) {
  const {
    sheet,
    computed,
    views,
    viewRows,
    rowCount,
    selection,
    onSelect,
    editing,
    setEditing,
    actions,
    filtered,
    sorted,
    totals,
    totalMarks,
    locale,
    label,
    labels,
    focusToken,
  } = props;
  const scroller = useRef<HTMLDivElement | null>(null);
  const field = useRef<HTMLTextAreaElement | null>(null);
  const [scroll, setScroll] = useState({ top: 0, left: 0, height: 600, width: 800 });
  const dragging = useRef<"cells" | "rows" | "columns" | null>(null);
  const composing = useRef(false);
  const cols = views.length;
  const size: GridSize = useMemo(() => ({ rows: Math.max(1, rowCount), cols: Math.max(1, cols) }), [rowCount, cols]);
  const freeze = Math.min(sheet.freeze ?? 1, cols);

  const widths = useMemo(() => views.map((view) => view.column.width ?? defaultWidth(view.kind)), [views]);
  const lefts = useMemo(() => {
    const out: number[] = [];
    let left = ROW_NUMBER_WIDTH;
    for (const width of widths) {
      out.push(left);
      left += width;
    }
    return out;
  }, [widths]);
  const tableWidth = ROW_NUMBER_WIDTH + widths.reduce((a, b) => a + b, 0);
  const frozenWidth = freeze > 0 ? lefts[freeze - 1] + widths[freeze - 1] : ROW_NUMBER_WIDTH;
  const footHeight = totals ? ROW_HEIGHT : 0;

  // What is in view: measured on scroll and resize, one state update per frame.
  useLayoutEffect(() => {
    const el = scroller.current;
    if (!el) return;
    let frame = 0;
    const read = () => {
      frame = 0;
      setScroll((now) => {
        const next = { top: el.scrollTop, left: el.scrollLeft, height: el.clientHeight || now.height, width: el.clientWidth || now.width };
        return next.top === now.top && next.left === now.left && next.height === now.height && next.width === now.width ? now : next;
      });
    };
    const onScroll = () => {
      if (!frame) frame = window.requestAnimationFrame(read);
    };
    read();
    el.addEventListener("scroll", onScroll, { passive: true });
    const observer = typeof ResizeObserver !== "undefined" ? new ResizeObserver(onScroll) : null;
    observer?.observe(el);
    return () => {
      el.removeEventListener("scroll", onScroll);
      observer?.disconnect();
      if (frame) window.cancelAnimationFrame(frame);
    };
  }, []);

  const first = Math.max(0, Math.floor(scroll.top / ROW_HEIGHT) - OVERSCAN);
  const last = Math.min(rowCount, Math.ceil((scroll.top + scroll.height) / ROW_HEIGHT) + OVERSCAN);
  const range = rangeOf(selection);
  const active = selection.active;

  // Keep the active cell in view, clear of the sticky head, totals and frozen columns.
  useLayoutEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const top = active.row * ROW_HEIGHT;
    const viewTop = el.scrollTop;
    const room = el.clientHeight - HEAD_HEIGHT - footHeight;
    if (top < viewTop) el.scrollTop = top;
    else if (room > ROW_HEIGHT && top + ROW_HEIGHT > viewTop + room) el.scrollTop = top + ROW_HEIGHT - room;
    if (active.col >= freeze && cols > 0) {
      const left = lefts[active.col] - frozenWidth;
      const right = lefts[active.col] + widths[active.col];
      if (left < el.scrollLeft) el.scrollLeft = Math.max(0, left);
      else if (right > el.scrollLeft + el.clientWidth) el.scrollLeft = right - el.clientWidth;
    }
  }, [active.row, active.col, freeze, frozenWidth, lefts, widths, cols, footHeight]);

  const focusField = useCallback(() => field.current?.focus({ preventScroll: true }), []);
  useEffect(() => {
    if (focusToken > 0) focusField();
  }, [focusToken, focusField]);

  const editingHere = editing !== null && editing.row === active.row && editing.col === active.col;
  // The field mirrors the edit; outside an edit it stays empty (its value is the clipboard's only briefly).
  useLayoutEffect(() => {
    const el = field.current;
    if (!el) return;
    const wanted = editingHere ? editing.text : "";
    if (el.value !== wanted) el.value = wanted;
  }, [editingHere, editing]);

  const startEdit = useCallback(
    (mode: EditState["mode"], text?: string) => {
      const why = actions.readOnly(active.col);
      if (why) {
        actions.announce(why);
        return false;
      }
      setEditing({ row: active.row, col: active.col, mode, text: text ?? actions.editText(active.row, active.col) });
      if (mode === "edit") {
        window.requestAnimationFrame(() => {
          const el = field.current;
          if (el) el.setSelectionRange(el.value.length, el.value.length);
        });
      }
      return true;
    },
    [actions, active.row, active.col, setEditing],
  );

  const finish = useCallback(
    (then?: Selection) => {
      if (editing) actions.commit(editing.row, editing.col, field.current?.value ?? editing.text);
      setEditing(null);
      if (then) onSelect(then);
    },
    [actions, editing, onSelect, setEditing],
  );

  const cancel = useCallback(() => setEditing(null), [setEditing]);

  const onFieldKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (composing.current || event.nativeEvent.isComposing) return;
    const mod = IS_MAC ? event.metaKey : event.ctrlKey;
    const key = event.key;
    if (editingHere) {
      if (key === "Enter" && !event.altKey) {
        event.preventDefault();
        finish(advance(selection, true, !event.shiftKey, size));
      } else if (key === "Tab") {
        event.preventDefault();
        finish(advance(selection, false, !event.shiftKey, size));
      } else if (key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        cancel();
      } else if (key === "F2") {
        event.preventDefault();
        setEditing({ ...editing, text: field.current?.value ?? editing.text, mode: editing.mode === "edit" ? "replace" : "edit" });
      } else if (editing.mode === "replace" && key.startsWith("Arrow") && !mod && !event.shiftKey) {
        event.preventDefault();
        const [dr, dc] = key === "ArrowUp" ? [-1, 0] : key === "ArrowDown" ? [1, 0] : key === "ArrowLeft" ? [0, -1] : [0, 1];
        finish(move(selection, dr, dc, size));
      }
      return;
    }
    const arrows: Record<string, [number, number]> = {
      ArrowUp: [-1, 0],
      ArrowDown: [1, 0],
      ArrowLeft: [0, -1],
      ArrowRight: [0, 1],
    };
    if (key in arrows) {
      event.preventDefault();
      const [dr, dc] = arrows[key];
      if (mod) onSelect(jump(selection, dr, dc, size, actions.filled, event.shiftKey));
      else onSelect(move(selection, dr, dc, size, event.shiftKey));
      return;
    }
    if (key === "PageDown" || key === "PageUp") {
      event.preventDefault();
      const page = Math.max(1, Math.floor((scroll.height - HEAD_HEIGHT - footHeight) / ROW_HEIGHT) - 1);
      onSelect(move(selection, key === "PageDown" ? page : -page, 0, size, event.shiftKey));
      return;
    }
    if (key === "Home" || key === "End") {
      event.preventDefault();
      const toRow = mod ? (key === "Home" ? 0 : Math.max(0, viewRows.length - 1)) : selection.active.row;
      const toCol = key === "Home" ? 0 : cols - 1;
      if (event.shiftKey) onSelect({ ...selection, focus: { row: toRow, col: toCol } });
      else onSelect({ anchor: { row: toRow, col: toCol }, focus: { row: toRow, col: toCol }, active: { row: toRow, col: toCol } });
      return;
    }
    if (key === "Enter" || key === "Tab") {
      event.preventDefault();
      onSelect(advance(selection, key === "Enter", !event.shiftKey, size));
      return;
    }
    if (key === "F2") {
      event.preventDefault();
      startEdit("edit");
      return;
    }
    if (key === "Delete" || key === "Backspace") {
      event.preventDefault();
      actions.clear();
      return;
    }
    if (key === "Escape") {
      if (range.top !== range.bottom || range.left !== range.right) {
        event.preventDefault();
        event.stopPropagation();
        onSelect({ anchor: active, focus: active, active });
      }
      return;
    }
    if (key === " " && event.shiftKey && !mod) {
      event.preventDefault();
      actions.selectRows(range.top, range.bottom);
      return;
    }
    if (key === " " && event.ctrlKey) {
      event.preventDefault();
      actions.selectColumns(range.left, range.right);
      return;
    }
    if (key === " " && views[active.col]?.kind === "check" && !mod) {
      event.preventDefault();
      actions.toggleCheck(active.row, active.col);
      return;
    }
    if (key === "ContextMenu" || (key === "F10" && event.shiftKey)) {
      event.preventDefault();
      const box = field.current?.getBoundingClientRect();
      actions.openMenu(box ? box.left + 8 : 0, box ? box.bottom : 0);
      return;
    }
    if (mod && !event.altKey) {
      const lower = key.toLowerCase();
      if (lower === "a") {
        event.preventDefault();
        actions.selectAll();
      } else if (lower === "c" || lower === "x") {
        // The field holds the selection's text, selected, so the system's own
        // copy takes it even where the clipboard event is not offered.
        const el = field.current;
        if (el) {
          el.value = actions.copyText();
          el.select();
          window.setTimeout(() => {
            if (field.current && !editing) field.current.value = "";
          }, 0);
        }
      } else if (lower === "d") {
        event.preventDefault();
        actions.fill("down");
      } else if (lower === "r") {
        event.preventDefault();
        actions.fill("right");
      } else if (lower === "b") {
        event.preventDefault();
        actions.toggleBold();
      }
    }
  };

  const onInput = () => {
    if (editingHere || composing.current) {
      if (editingHere && editing && field.current && field.current.value !== editing.text) {
        setEditing({ ...editing, text: field.current.value });
      }
      return;
    }
    const text = field.current?.value ?? "";
    if (!text) return;
    if (!startEdit("replace", text) && field.current) field.current.value = "";
  };

  const onCopy = (event: ClipboardEvent<HTMLTextAreaElement>) => {
    if (editingHere) return;
    event.preventDefault();
    event.clipboardData.setData("text/plain", actions.copyText());
    if (field.current) field.current.value = "";
  };
  const onCut = (event: ClipboardEvent<HTMLTextAreaElement>) => {
    if (editingHere) return;
    event.preventDefault();
    event.clipboardData.setData("text/plain", actions.copyText());
    if (field.current) field.current.value = "";
    actions.cut();
  };
  const onPaste = (event: ClipboardEvent<HTMLTextAreaElement>) => {
    if (editingHere) return;
    event.preventDefault();
    const text = event.clipboardData.getData("text/plain");
    if (text) actions.paste(text);
  };

  // A drag of the mouse extends the selection until the button is released.
  useEffect(() => {
    const up = () => {
      dragging.current = null;
    };
    window.addEventListener("mouseup", up);
    return () => window.removeEventListener("mouseup", up);
  }, []);

  const cellAt = (target: EventTarget | null): { row: number; col: number } | null => {
    const el = (target as HTMLElement | null)?.closest?.("[data-cell]") as HTMLElement | null;
    if (!el) return null;
    return { row: Number(el.dataset.row), col: Number(el.dataset.col) };
  };

  const onBodyMouseDown = (event: MouseEvent<HTMLTableSectionElement>) => {
    if (event.button !== 0 && event.button !== 2) return;
    const rowHead = (event.target as HTMLElement).closest("[data-rowhead]") as HTMLElement | null;
    if (editing) finish();
    if (rowHead) {
      event.preventDefault();
      const row = Number(rowHead.dataset.rowhead);
      if (event.button === 2 && inRange(range, row, 0) && range.left === 0 && range.right === cols - 1) return focusField();
      actions.selectRows(event.shiftKey ? Math.min(selection.anchor.row, row) : row, event.shiftKey ? Math.max(selection.anchor.row, row) : row);
      dragging.current = "rows";
      focusField();
      return;
    }
    const cell = cellAt(event.target);
    if (!cell) return;
    event.preventDefault();
    if ((event.target as HTMLElement).closest("[data-check]") && event.button === 0) {
      onSelect({ anchor: cell, focus: cell, active: cell });
      actions.toggleCheck(cell.row, cell.col);
      focusField();
      return;
    }
    // A right click inside the selection keeps it (the menu acts on it).
    if (event.button === 2 && inRange(range, cell.row, cell.col)) return focusField();
    if (event.shiftKey) onSelect({ ...selection, focus: cell });
    else onSelect({ anchor: cell, focus: cell, active: cell });
    dragging.current = "cells";
    focusField();
  };

  const onBodyMouseOver = (event: MouseEvent<HTMLTableSectionElement>) => {
    if (!dragging.current) return;
    if (dragging.current === "rows") {
      const rowHead = (event.target as HTMLElement).closest("[data-rowhead]") as HTMLElement | null;
      const cell = cellAt(event.target);
      const row = rowHead ? Number(rowHead.dataset.rowhead) : cell?.row;
      if (row === undefined) return;
      onSelect({ ...selection, focus: { row, col: cols - 1 } });
      return;
    }
    const cell = cellAt(event.target);
    if (cell && dragging.current === "cells" && (cell.row !== selection.focus.row || cell.col !== selection.focus.col)) {
      onSelect({ ...selection, focus: cell });
    }
  };

  const onContextMenu = (event: MouseEvent) => {
    event.preventDefault();
    actions.openMenu(event.clientX, event.clientY);
  };

  // Column widths: a drag on a head's right edge, one undo step when released.
  const [resizing, setResizing] = useState<{ col: number; width: number } | null>(null);
  const startResize = (event: MouseEvent, col: number) => {
    event.preventDefault();
    event.stopPropagation();
    const startX = event.clientX;
    const startWidth = widths[col];
    let width = startWidth;
    const onMove = (e: globalThis.MouseEvent) => {
      width = Math.max(48, Math.min(480, Math.round(startWidth + e.clientX - startX)));
      setResizing({ col, width });
    };
    const onUp = () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      setResizing(null);
      if (width !== startWidth) actions.resizeColumn(col, width);
      focusField();
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  };
  const shownWidths = resizing ? widths.map((w, i) => (i === resizing.col ? resizing.width : w)) : widths;
  const shownLefts = useMemo(() => {
    if (!resizing) return lefts;
    const out: number[] = [];
    let left = ROW_NUMBER_WIDTH;
    for (const width of shownWidths) {
      out.push(left);
      left += width;
    }
    return out;
  }, [resizing, lefts, shownWidths]);
  const shownTableWidth = resizing ? ROW_NUMBER_WIDTH + shownWidths.reduce((a, b) => a + b, 0) : tableWidth;

  const stickyLeft = (col: number) => (col < freeze ? shownLefts[col] : undefined);

  // Row numbers are the stored rows' (a filter leaves gaps); the empty rows below continue them.
  const rowNumber = (row: number) => (row < viewRows.length ? viewRows[row] + 1 : sheet.rows.length + (row - viewRows.length) + 1);
  const address = `${columnLetter(active.col)}${rowNumber(active.row)}`;
  const activeView = views[active.col];
  const activeStored = active.row < viewRows.length ? viewRows[active.row] : -1;
  const activeValue = activeView && activeStored >= 0 ? computed[activeStored]?.[activeView.column.key] : undefined;
  const activeText = activeView
    ? typeof activeValue === "boolean"
      ? activeValue
        ? "✓"
        : "–"
      : displayText(activeValue, activeView, locale) || labels.empty
    : "";

  // The field sits over the active cell (pinned with a frozen column as it scrolls).
  const fieldLeft = cols ? (active.col < freeze ? shownLefts[active.col] + scroll.left : shownLefts[active.col]) : 0;
  const fieldTop = HEAD_HEIGHT + active.row * ROW_HEIGHT;
  const fieldWidth = cols ? Math.max(shownWidths[active.col], editingHere ? Math.min(360, (editing?.text.length ?? 0) * 8 + 24) : 0) : 0;

  const rows: number[] = [];
  for (let row = first; row < last; row += 1) rows.push(row);

  return (
    <div
      ref={scroller}
      className="relative h-full min-h-0 overflow-auto overscroll-contain bg-background"
      data-testid="sheet-grid-scroll"
    >
      <div className="relative" style={{ width: shownTableWidth, height: HEAD_HEIGHT + rowCount * ROW_HEIGHT + footHeight }}>
        <table
          role="grid"
          aria-label={label}
          aria-rowcount={rowCount + 1 + (totals ? 1 : 0)}
          aria-colcount={cols + 1}
          aria-multiselectable="true"
          className="border-separate border-spacing-0 text-sm tabular-nums"
          style={{ tableLayout: "fixed", width: shownTableWidth }}
          data-testid="sheet-grid"
        >
          <colgroup>
            <col style={{ width: ROW_NUMBER_WIDTH }} />
            {shownWidths.map((width, col) => (
              <col key={views[col].column.key} style={{ width }} />
            ))}
          </colgroup>
          <thead>
            <tr role="row" aria-rowindex={1} style={{ height: HEAD_HEIGHT }}>
              <th
                role="columnheader"
                aria-label={labels.selectAll}
                className="sticky left-0 top-0 z-30 border-b border-r border-border bg-secondary"
                style={{ height: HEAD_HEIGHT }}
                onMouseDown={(event) => {
                  event.preventDefault();
                  if (editing) finish();
                  actions.selectAll();
                  focusField();
                }}
              />
              {views.map((view, col) => {
                const column = view.column;
                const selected = col >= range.left && col <= range.right;
                const isSorted = sorted?.key === column.key;
                const sticky = stickyLeft(col);
                return (
                  <th
                    key={column.key}
                    role="columnheader"
                    aria-colindex={col + 2}
                    aria-sort={isSorted ? (sorted?.dir === 1 ? "ascending" : "descending") : undefined}
                    title={column.formula ? `= ${column.formula}` : undefined}
                    className={cn(
                      "group sticky top-0 select-none border-b border-r border-border bg-secondary px-0 text-left font-medium",
                      selected ? "text-foreground" : "text-muted-foreground",
                      sticky !== undefined ? "z-30" : "z-20",
                    )}
                    style={{ height: HEAD_HEIGHT, left: sticky, background: selected ? SELECTED_HEAD : undefined }}
                    data-testid={`sheet-head-${col}`}
                    onMouseDown={(event) => {
                      if ((event.target as HTMLElement).closest("button,[data-resize]")) return;
                      event.preventDefault();
                      if (editing) finish();
                      const from = event.shiftKey ? selection.anchor.col : col;
                      actions.selectColumns(Math.min(from, col), Math.max(from, col));
                      focusField();
                    }}
                    onDoubleClick={() => actions.openColumnSettings(col)}
                    onContextMenu={(event) => {
                      event.preventDefault();
                      actions.openColumnMenu(col, event.clientX, event.clientY);
                    }}
                  >
                    <div className={cn("flex h-full items-center gap-1 pl-2 pr-1", view.numeric && column.align !== "left" && "flex-row-reverse pl-1 pr-2")}>
                      <span className="min-w-0 flex-1 truncate" style={{ textAlign: view.numeric && column.align !== "left" ? "right" : undefined }}>
                        {column.label}
                      </span>
                      {column.formula && <Sigma className="h-3 w-3 shrink-0 opacity-60" aria-hidden />}
                      {isSorted &&
                        (sorted?.dir === 1 ? (
                          <ArrowUp className="h-3 w-3 shrink-0" aria-hidden />
                        ) : (
                          <ArrowDown className="h-3 w-3 shrink-0" aria-hidden />
                        ))}
                      {filtered.has(column.key) && <Filter className="h-3 w-3 shrink-0 text-accent" aria-hidden />}
                      <button
                        type="button"
                        tabIndex={-1}
                        aria-label={labels.columnMenu(column.label)}
                        className="flex h-6 w-5 shrink-0 items-center justify-center rounded opacity-0 hover:bg-background focus:opacity-100 group-hover:opacity-100"
                        onMouseDown={(event) => event.preventDefault()}
                        onClick={(event) => {
                          const box = event.currentTarget.getBoundingClientRect();
                          actions.openColumnMenu(col, box.left, box.bottom + 4);
                        }}
                        data-testid={`sheet-head-menu-${col}`}
                      >
                        <ChevronDown className="h-3.5 w-3.5" aria-hidden />
                      </button>
                    </div>
                    <span
                      data-resize=""
                      role="separator"
                      aria-orientation="vertical"
                      aria-label={labels.resize(column.label)}
                      className="absolute right-[-3px] top-0 z-10 h-full w-[6px] cursor-col-resize hover:bg-accent/40"
                      onMouseDown={(event) => startResize(event, col)}
                    />
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody
            onMouseDown={onBodyMouseDown}
            onMouseOver={onBodyMouseOver}
            onContextMenu={onContextMenu}
            onDoubleClick={(event) => {
              if (cellAt(event.target) && !(event.target as HTMLElement).closest("[data-check]")) startEdit("edit");
            }}
          >
            {first > 0 && <tr aria-hidden style={{ height: first * ROW_HEIGHT }} />}
            {rows.map((row) => {
              const stored = row < viewRows.length ? viewRows[row] : -1;
              const values = stored >= 0 ? computed[stored] : undefined;
              const rowSelected = row >= range.top && row <= range.bottom;
              return (
                <tr key={row} role="row" aria-rowindex={row + 2} style={{ height: ROW_HEIGHT }}>
                  <th
                    role="rowheader"
                    scope="row"
                    data-rowhead={row}
                    aria-label={labels.rowNumber(row + 1)}
                    className={cn(
                      "sticky left-0 z-10 cursor-default select-none border-b border-r border-border bg-secondary px-1 text-center text-xs font-normal",
                      rowSelected ? "text-foreground" : "text-muted-foreground",
                    )}
                    style={{ height: ROW_HEIGHT }}
                  >
                    {rowNumber(row)}
                  </th>
                  {views.map((view, col) => {
                    const column = view.column;
                    const value = values?.[column.key];
                    const selected = inRange(range, row, col);
                    const isActive = row === active.row && col === active.col;
                    const sticky = stickyLeft(col);
                    const align = column.align ?? (view.numeric ? "right" : view.kind === "check" ? "center" : "left");
                    return (
                      <td
                        key={column.key}
                        role="gridcell"
                        aria-colindex={col + 2}
                        aria-selected={selected}
                        aria-readonly={column.formula ? true : undefined}
                        data-cell=""
                        data-row={row}
                        data-col={col}
                        id={isActive ? `sheet-cell-active` : undefined}
                        className={cn(
                          "overflow-hidden text-ellipsis whitespace-nowrap border-b border-r border-border px-2",
                          sticky !== undefined ? "sticky z-[5]" : "",
                          column.bold && "font-semibold",
                          column.formula && "text-muted-foreground",
                        )}
                        style={{
                          height: ROW_HEIGHT,
                          left: sticky,
                          textAlign: align,
                          color: column.color ? COLOR_TOKENS[column.color] : undefined,
                          background: selected && !isActive ? SELECTED_CELL : "hsl(var(--background))",
                          boxShadow: isActive ? "inset 0 0 0 2px hsl(var(--accent))" : undefined,
                        }}
                      >
                        <Cell value={value} view={view} locale={locale} />
                      </td>
                    );
                  })}
                </tr>
              );
            })}
            {last < rowCount && <tr aria-hidden style={{ height: (rowCount - last) * ROW_HEIGHT }} />}
          </tbody>
          {totals && (
            <tfoot>
              <tr role="row" aria-rowindex={rowCount + 2} style={{ height: ROW_HEIGHT }}>
                <td aria-hidden className="sticky bottom-0 left-0 z-30 border-r border-t border-border bg-secondary" />
                {views.map((view, col) => {
                  const sticky = stickyLeft(col);
                  return (
                    <td
                      key={view.column.key}
                      role="gridcell"
                      aria-colindex={col + 2}
                      aria-readonly
                      className={cn(
                        "sticky bottom-0 overflow-hidden whitespace-nowrap border-r border-t border-border bg-secondary px-2 font-semibold",
                        sticky !== undefined ? "z-30" : "z-20",
                      )}
                      style={{ left: sticky, textAlign: view.numeric ? "right" : undefined }}
                      data-testid={`sheet-total-${col}`}
                    >
                      {totals[col] !== null && (
                        <span className="inline-flex items-baseline gap-2">
                          <span className="text-xs font-medium text-muted-foreground">{totalMarks[col]}</span>
                          <span>{totals[col]}</span>
                        </span>
                      )}
                    </td>
                  );
                })}
              </tr>
            </tfoot>
          )}
        </table>
        <textarea
          ref={field}
          wrap="off"
          spellCheck={false}
          autoCapitalize="off"
          autoComplete="off"
          autoCorrect="off"
          rows={1}
          aria-label={labels.cell(address, activeView?.column.label ?? "", activeText)}
          data-spec-undo={editingHere ? undefined : ""}
          data-testid="sheet-cell-input"
          className={cn(
            "absolute z-40 m-0 resize-none overflow-hidden whitespace-pre border-0 px-2 text-sm outline-none",
            editingHere
              ? "bg-background text-foreground shadow-[0_0_0_2px_hsl(var(--accent)),0_4px_12px_rgba(0,0,0,0.12)]"
              : "pointer-events-none bg-transparent text-transparent caret-transparent",
          )}
          style={{
            top: fieldTop,
            left: fieldLeft,
            width: fieldWidth,
            height: ROW_HEIGHT,
            lineHeight: `${ROW_HEIGHT}px`,
            textAlign: editingHere ? "left" : undefined,
          }}
          onKeyDown={onFieldKeyDown}
          onInput={onInput}
          onCompositionStart={() => {
            composing.current = true;
            if (!editingHere) startEdit("replace", "");
          }}
          onCompositionEnd={() => {
            composing.current = false;
            onInput();
          }}
          onCopy={onCopy}
          onCut={onCut}
          onPaste={onPaste}
          onBlur={(event) => {
            // Leaving the grid (not for one of its own menus) ends the edit with what was typed.
            const next = event.relatedTarget as HTMLElement | null;
            if (editingHere && !next?.closest?.("[data-sheet-formula-bar]")) finish();
          }}
        />
      </div>
    </div>
  );
}

/** One cell's content, drawn as its type reads. */
function Cell({ value, view, locale }: { value: Row[string] | undefined; view: ColumnView; locale?: string }) {
  if (value === undefined) return null;
  if (typeof value === "boolean") {
    return (
      <span
        data-check=""
        role="img"
        aria-label={value ? "✓" : "–"}
        className={cn(
          "inline-flex h-4 w-4 cursor-pointer items-center justify-center rounded align-[-3px]",
          value ? "bg-foreground text-background" : "border-[1.5px] border-border-strong",
        )}
      >
        {value && (
          <svg viewBox="0 0 16 16" className="h-3 w-3" aria-hidden>
            <path d="M4 8.3l2.3 2.3 4.5-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        )}
      </span>
    );
  }
  const text = displayText(value, view, locale);
  if (view.kind === "status" || (typeof value === "object" && value.tone)) {
    const tone = statusTone(value);
    return (
      <span
        className={cn(
          "inline-block max-w-full truncate rounded-full px-2 text-xs leading-5",
          tone === "good" && "bg-success/15 text-success",
          tone === "info" && "bg-accent/15 text-accent",
          tone === "warn" && "bg-warning/15 text-warning",
          tone === "bad" && "bg-destructive/15 text-destructive",
          !tone && "bg-secondary text-foreground",
        )}
      >
        {text}
      </span>
    );
  }
  if (typeof value === "object" && value.href) return <span className="underline decoration-border-strong underline-offset-2">{text}</span>;
  if (typeof value === "string" && view.numeric) return <span className="text-muted-foreground">{text}</span>;
  return <>{text}</>;
}
