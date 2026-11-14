/**
 * The sheets editor: a spreadsheet over a "sheets" node's spec.
 *
 * The grid (`SheetGrid`) is where the person works: select, type, move with
 * the keys, copy and paste with other spreadsheet apps, fill, insert and
 * delete rows and columns, sort and filter. Around it: a toolbar for the
 * active column's type and number format, its look, sorting, inserting and
 * charts; a formula bar showing the active cell (or the column's formula);
 * an inspector for everything a column and the sheet can hold; the sheet
 * tabs; and the sheet's charts under the grid, made from a selection with
 * the shared chart editor and stored bound to the columns, so they follow
 * the cells.
 *
 * Every change goes through `useNodeSpecEditor`: one grid action is one
 * labelled undo step, a typed cell is one step when it is committed, and the
 * work is saved by itself. Selection, filters and open panels are view state
 * of this editor and never part of the spec.
 *
 * The rules a stored value has to follow (so the server's `normalize`
 * keeps it as it is) live in `model.ts`; the changes themselves in `ops.ts`.
 */
import { useCallback, useMemo, useRef, useState } from "react";
import {
  ArrowDownAZ,
  ArrowUpZA,
  BarChart3,
  Bold,
  ChevronDown,
  ClipboardPaste,
  Columns3,
  Copy,
  Eraser,
  Filter,
  FilterX,
  Minus,
  PanelRight,
  Plus,
  Rows3,
  Scissors,
  Trash2,
} from "lucide-react";

import { useT } from "@/i18n";
import { ChartEditor } from "../charts/ChartEditor";
import type { ChartBinding, ChartJson, ChartSource } from "../charts/chartModel";
import { ChartPreview } from "../charts/ChartPreview";
import { validateChart } from "../charts/chartModel";
import { EditorShell } from "../EditorShell";
import { MenuItem, Popover, Select, ToolbarButton, ToolbarGroup, ToolbarSeparator } from "../controls";
import type { NodeEditorProps } from "../types";
import { useNodeSpecEditor } from "../useNodeSpecEditor";
import { bindingOf, chartSource, drawnChart, storedChart } from "./charts";
import { clipboardText, parseTsv, toTsv } from "./clipboard";
import { ColumnPanel } from "./ColumnPanel";
import { columnTotal, computeRows, formulaPlan, totalAllowed } from "./formula";
import { ContextMenu, FilterPanel, SEPARATOR, type FilterValue, type MenuLine } from "./menus";
import {
  COLUMN_TYPES,
  MAX_CHARTS,
  MAX_COLUMNS,
  MAX_DECIMALS,
  MAX_ROWS,
  MAX_SHEETS,
  columnLetter,
  columnViews,
  convertCell,
  displayText,
  editText,
  parseInput,
  readSpec,
  type CellValue,
  type ColumnType,
  type Sheet,
  type SheetChart,
  type SheetsSpec,
} from "./model";
import * as ops from "./ops";
import { SheetGrid, type EditState, type GridActions } from "./SheetGrid";
import { SheetTabs } from "./SheetTabs";
import { at, clampSelection, rangeOf, selectAll, selectColumns, selectRows, type Selection } from "./selection";

/** Empty rows offered below the data, so the person can type on without inserting rows first. */
const SPARE_ROWS = 30;
const TOTAL_MARKS: Record<string, string> = { sum: "Σ", avg: "Ø", min: "min", max: "max", count: "#" };
const IS_MAC = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
const MOD = IS_MAC ? "⌘" : "Ctrl+";

type Menu =
  | { kind: "cells"; x: number; y: number }
  | { kind: "column"; col: number; x: number; y: number }
  | { kind: "tab"; index: number; x: number; y: number }
  | { kind: "filter"; col: number; x: number; y: number };

type ChartDialog = { index: number | null; value: ChartJson | null; source: ChartSource; binding: ChartBinding | null; range: [number, number] | null };

export default function SheetsEditor({ node, initial, onDone }: NodeEditorProps) {
  const t = useT();
  const locale = typeof navigator !== "undefined" ? navigator.language : undefined;
  const [start] = useState(() => ({ ...initial, spec: readSpec(initial.spec) }));

  const prepare = useCallback(
    (spec: SheetsSpec) => {
      // A formula the server would refuse holds the save with a sentence, never the whole spec.
      for (const sheet of spec.sheets) {
        const problem = formulaPlan(sheet.columns).problems[0];
        if (problem) {
          const label = sheet.columns.find((c) => c.key === problem.key)?.label ?? problem.key;
          return { error: t("nodes.editor.sheets.formula.held").replace("{0}", label) };
        }
      }
      return spec;
    },
    [t],
  );
  const editor = useNodeSpecEditor<SheetsSpec>(node.id ?? "", start, { prepare });
  const spec = editor.spec;
  const [activeSheet, setActiveSheet] = useState(0);
  const sheetIndex = Math.min(activeSheet, spec.sheets.length - 1);
  const sheet = spec.sheets[sheetIndex];

  const [selection, setSelection] = useState<Selection>(() => at(0, 0));
  const [editing, setEditing] = useState<EditState | null>(null);
  const [filters, setFilters] = useState<Record<string, Record<string, string[]>>>({});
  const [sorted, setSorted] = useState<{ sheet: number; key: string; dir: 1 | -1 } | null>(null);
  const [menu, setMenu] = useState<Menu | null>(null);
  const [panelOpen, setPanelOpen] = useState(false);
  const [panelFocus, setPanelFocus] = useState(0);
  const [focusToken, setFocusToken] = useState(0);
  const [renameToken, setRenameToken] = useState(0);
  const [chartDialog, setChartDialog] = useState<ChartDialog | null>(null);
  const [message, setMessage] = useState("");
  const messageTimer = useRef<number | null>(null);

  const announce = useCallback((text: string) => {
    setMessage(text);
    if (messageTimer.current) window.clearTimeout(messageTimer.current);
    messageTimer.current = window.setTimeout(() => setMessage(""), 5_000);
  }, []);
  const refocus = useCallback(() => setFocusToken((n) => n + 1), []);
  const step = useCallback((name: string) => t(`nodes.editor.sheets.step.${name}`), [t]);

  // ------------------------------------------------------------ derived view
  const plan = useMemo(() => formulaPlan(sheet.columns), [sheet.columns]);
  const computed = useMemo(() => computeRows(sheet.rows, plan), [sheet.rows, plan]);
  const views = useMemo(() => columnViews(sheet.columns, computed, locale), [sheet.columns, computed, locale]);
  const filterKey = `${sheetIndex}:${sheet.name}`;
  const sheetFilters = useMemo(() => filters[filterKey] ?? {}, [filters, filterKey]);
  const filteredKeys = useMemo(
    () => new Set(Object.keys(sheetFilters).filter((key) => sheet.columns.some((c) => c.key === key))),
    [sheetFilters, sheet.columns],
  );
  const viewRows = useMemo(() => {
    const out: number[] = [];
    const active = [...filteredKeys].map((key) => ({
      allowed: new Set(sheetFilters[key]),
      view: views.find((v) => v.column.key === key),
    }));
    computed.forEach((row, index) => {
      const ok = active.every(({ allowed, view }) => !view || allowed.has(cellToken(row[view.column.key], view, locale)));
      if (ok) out.push(index);
    });
    return out;
  }, [computed, filteredKeys, sheetFilters, views, locale]);
  const filtering = filteredKeys.size > 0;
  const spare = filtering ? 0 : Math.max(0, Math.min(MAX_ROWS - sheet.rows.length, Math.max(SPARE_ROWS, selection.active.row - viewRows.length + 10)));
  const rowCount = Math.max(1, viewRows.length + spare);
  const size = useMemo(() => ({ rows: rowCount, cols: Math.max(1, sheet.columns.length) }), [rowCount, sheet.columns.length]);
  const sel = useMemo(() => clampSelection(selection, size), [selection, size]);
  const range = rangeOf(sel);

  /** The stored row of a view row (an empty row below the data continues the stored rows). */
  const storedRow = useCallback(
    (row: number) => (row < viewRows.length ? viewRows[row] : sheet.rows.length + (row - viewRows.length)),
    [viewRows, sheet.rows.length],
  );
  /** The stored rows under the selection that hold data. */
  const selectedStoredRows = useCallback(() => {
    const out: number[] = [];
    for (let row = range.top; row <= range.bottom && row < viewRows.length; row += 1) out.push(viewRows[row]);
    return out;
  }, [range.top, range.bottom, viewRows]);
  const selectedKeys = useCallback(
    () => sheet.columns.slice(range.left, range.right + 1).map((c) => c.key),
    [sheet.columns, range.left, range.right],
  );

  const totals = useMemo(() => {
    if (!computed.length || !views.some((v) => v.column.total)) return null;
    const shown = viewRows.map((index) => computed[index]);
    return views.map((view) => {
      const total = view.column.total;
      if (!total || !totalAllowed(total, view.kind)) return null;
      const value = columnTotal(total, view.kind, view.column.key, shown);
      if (value === null) return "";
      if (total === "count") return new Intl.NumberFormat(locale).format(value);
      if (!view.numeric) return new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(value);
      return view.format(value);
    });
  }, [computed, views, viewRows, locale]);
  const totalMarks = useMemo(() => views.map((v) => (v.column.total ? TOTAL_MARKS[v.column.total] : "")), [views]);

  // ------------------------------------------------------------- changing
  const change = useCallback(
    (label: string, mutate: (draft: Sheet, spec: SheetsSpec) => void, coalesce?: string) =>
      editor.apply(
        (draft) => {
          mutate(draft.sheets[sheetIndex], draft);
        },
        { label, coalesce },
      ),
    [editor, sheetIndex],
  );

  const readOnly = useCallback(
    (col: number) => (sheet.columns[col]?.formula ? t("nodes.editor.sheets.message.formula_cell") : ""),
    [sheet.columns, t],
  );

  const commit = useCallback(
    (row: number, col: number, text: string) => {
      const view = views[col];
      if (!view || view.column.formula) return;
      const stored = storedRow(row);
      const previous = sheet.rows[stored]?.[view.column.key];
      const value = parseInput(text, view, locale, previous);
      if ((value ?? undefined) === previous) return;
      change(step("edit_cell"), (draft) => ops.writeCells(draft, [{ row: stored, key: view.column.key, value }]));
    },
    [views, storedRow, sheet.rows, locale, change, step],
  );

  const copyText = useCallback(() => {
    const lines: string[][] = [];
    for (let row = range.top; row <= range.bottom; row += 1) {
      const values = row < viewRows.length ? computed[viewRows[row]] : undefined;
      const line: string[] = [];
      for (let col = range.left; col <= range.right; col += 1) {
        line.push(clipboardText(values?.[sheet.columns[col].key], locale));
      }
      lines.push(line);
    }
    return toTsv(lines);
  }, [range, viewRows, computed, sheet.columns, locale]);

  const clear = useCallback(
    (label = step("clear")) => {
      const rows = selectedStoredRows();
      if (!rows.length) return;
      change(label, (draft) => ops.clearCells(draft, rows, selectedKeys()));
    },
    [selectedStoredRows, selectedKeys, change, step],
  );

  const paste = useCallback(
    (text: string) => {
      const block = parseTsv(text);
      if (!block.length) return;
      const width = Math.max(...block.map((line) => line.length));
      const single = block.length === 1 && width === 1;
      const multi = range.top !== range.bottom || range.left !== range.right;
      const top = range.top;
      const left = range.left;
      let added = 0;
      editor.apply(
        (draft) => {
          const target = draft.sheets[sheetIndex];
          if (!single) added = ops.ensureColumns(target, left + width);
          // The columns' types as they are now; a column the paste adds has none and takes numbers as numbers.
          const kinds = columnViews(target.columns, computed, locale);
          const writes: ops.CellWrite[] = [];
          const put = (row: number, col: number, raw: string) => {
            const view = kinds[col];
            if (!view || view.column.formula) return;
            const stored = storedRow(row);
            if (stored >= MAX_ROWS) return;
            writes.push({ row: stored, key: view.column.key, value: parseInput(raw, view, locale, target.rows[stored]?.[view.column.key]) });
          };
          if (single && multi) {
            for (let row = range.top; row <= range.bottom; row += 1)
              for (let col = range.left; col <= range.right; col += 1) put(row, col, block[0][0]);
          } else {
            block.forEach((line, i) => line.forEach((raw, j) => put(top + i, left + j, raw)));
          }
          ops.writeCells(target, writes);
        },
        { label: step("paste") },
      );
      if (!single || !multi) {
        const bottom = top + block.length - 1;
        const right = Math.min(left + width - 1, MAX_COLUMNS - 1);
        setSelection({ anchor: { row: top, col: left }, focus: { row: bottom, col: right }, active: { row: top, col: left } });
      }
      if (added) announce(t("nodes.editor.sheets.message.columns_added").replace("{0}", String(added)));
    },
    [range, editor, sheetIndex, computed, locale, storedRow, step, announce, t],
  );

  const fill = useCallback(
    (direction: "down" | "right") => {
      let rows = [];
      for (let row = range.top; row <= range.bottom; row += 1) rows.push(storedRow(row));
      let keys = selectedKeys();
      if (direction === "down" && rows.length === 1) {
        if (range.top === 0) return;
        rows = [storedRow(range.top - 1), ...rows];
      }
      if (direction === "right" && keys.length === 1) {
        if (range.left === 0) return;
        keys = [sheet.columns[range.left - 1].key, ...keys];
      }
      change(step(direction === "down" ? "fill_down" : "fill_right"), (draft) =>
        ops.fill(draft, rows, keys, direction, (value, key) => {
          const view = views.find((v) => v.column.key === key);
          return view ? convertCell(value, view.kind, view.column.unit ?? "", locale) : value;
        }),
      );
    },
    [range, storedRow, selectedKeys, sheet.columns, change, step, views, locale],
  );

  const toggleCheck = useCallback(
    (row: number, col: number) => {
      const view = views[col];
      if (!view || view.kind !== "check" || view.column.formula) return;
      const stored = storedRow(row);
      const value = sheet.rows[stored]?.[view.column.key];
      change(step("edit_cell"), (draft) => ops.writeCells(draft, [{ row: stored, key: view.column.key, value: value !== true }]));
    },
    [views, storedRow, sheet.rows, change, step],
  );

  const insertRows = useCallback(
    (where: "above" | "below") => {
      const count = range.bottom - range.top + 1;
      const atRow = where === "above" ? storedRow(range.top) : storedRow(range.bottom) + 1;
      if (atRow >= sheet.rows.length) {
        // Below the data the grid already offers empty rows: go there.
        if (where === "below") setSelection(at(Math.min(size.rows - 1, range.bottom + 1), sel.active.col));
        return;
      }
      if (sheet.rows.length + count > MAX_ROWS) return announce(t("nodes.editor.sheets.message.row_limit"));
      change(step("insert_rows"), (draft) => ops.insertRows(draft, atRow, count));
      if (where === "below") setSelection(at(range.bottom + 1, sel.active.col));
    },
    [range, storedRow, sheet.rows.length, size.rows, sel.active.col, change, step, announce, t],
  );

  const deleteRows = useCallback(() => {
    const rows = selectedStoredRows();
    if (!rows.length) return;
    change(step("delete_rows"), (draft) => ops.deleteRows(draft, rows));
    setSelection(at(range.top, sel.active.col));
  }, [selectedStoredRows, change, step, range.top, sel.active.col]);

  const insertColumns = useCallback(
    (where: "left" | "right") => {
      const count = range.right - range.left + 1;
      if (sheet.columns.length + count > MAX_COLUMNS) return announce(t("nodes.editor.sheets.message.column_limit"));
      const atCol = where === "left" ? range.left : range.right + 1;
      change(step("insert_columns"), (draft) => {
        ops.insertColumns(draft, atCol, count);
      });
      setSelection(at(sel.active.row, atCol));
    },
    [range, sheet.columns.length, change, step, sel.active.row, announce, t],
  );

  const deleteColumns = useCallback(() => {
    const keys = selectedKeys();
    if (keys.length >= sheet.columns.length) return announce(t("nodes.editor.sheets.message.last_column"));
    const users = ops.formulaUsers(sheet, keys);
    if (users.length) {
      return announce(t("nodes.editor.sheets.message.used_by_formula").replace("{0}", users.map((c) => c.label).join(", ")));
    }
    change(step("delete_columns"), (draft) => {
      ops.deleteColumns(draft, keys);
    });
    setSelection(at(sel.active.row, Math.min(range.left, sheet.columns.length - keys.length - 1)));
  }, [selectedKeys, sheet, change, step, sel.active.row, range.left, announce, t]);

  const sortBy = useCallback(
    (col: number, dir: 1 | -1) => {
      const view = views[col];
      if (!view) return;
      change(t("nodes.editor.sheets.step.sort").replace("{0}", view.column.label), (draft) =>
        ops.sortRows(draft, view.column.key, dir, view.numeric || view.kind === "check", computed),
      );
      setSorted({ sheet: sheetIndex, key: view.column.key, dir });
      refocus();
    },
    [views, change, t, computed, sheetIndex, refocus],
  );

  const patchColumn = useCallback(
    (col: number, patch: ops.ColumnPatch, label: string) => change(label, (draft) => ops.patchColumn(draft, col, patch, locale)),
    [change, locale],
  );
  /** The same change to every selected column (type, format, look). */
  const patchSelected = useCallback(
    (patch: ops.ColumnPatch, label: string) => {
      change(label, (draft) => {
        for (let col = range.left; col <= range.right; col += 1) ops.patchColumn(draft, col, patch, locale);
      });
      // A toolbar button acts on the selection; the keys go on in the grid.
      refocus();
    },
    [change, range.left, range.right, locale, refocus],
  );

  const activeView = views[sel.active.col];
  const activeColumn = activeView?.column;

  const changeDecimals = useCallback(
    (delta: number) => {
      if (!activeView?.numeric) return;
      const next = Math.max(0, Math.min(MAX_DECIMALS, activeView.decimals + delta));
      patchSelected({ decimals: next }, step("number_format"));
    },
    [activeView, patchSelected, step],
  );

  // ------------------------------------------------------------- charts
  const openChart = useCallback(
    (index: number | null) => {
      if (index !== null) {
        const chart = sheet.charts?.[index];
        if (!chart) return;
        const binding = bindingOf(chart);
        const rows = chart.rows
          ? Array.from({ length: Math.max(0, Math.min(sheet.rows.length, chart.rows[1]) - chart.rows[0] + 1) }, (_, i) => chart.rows![0] - 1 + i)
          : sheet.rows.map((_, i) => i);
        setChartDialog({
          index,
          value: drawnChart(chart, sheet, computed),
          source: chartSource(sheet, computed, sheet.columns.map((_, i) => i), rows),
          binding,
          range: chart.rows ?? null,
        });
        return;
      }
      if ((sheet.charts?.length ?? 0) >= MAX_CHARTS) return announce(t("nodes.editor.sheets.message.chart_limit"));
      const singleCell = range.top === range.bottom && range.left === range.right;
      const columns = singleCell
        ? sheet.columns.map((_, i) => i)
        : Array.from({ length: range.right - range.left + 1 }, (_, i) => range.left + i);
      // Numbers selected without their names: the sheet's first text column labels them.
      if (columns.every((col) => views[col]?.numeric)) {
        const names = views.findIndex((view) => !view.numeric && view.kind !== "check");
        if (names >= 0) columns.unshift(names);
      }
      let rows = range.bottom > range.top ? selectedStoredRows() : sheet.rows.map((_, i) => i);
      if (!rows.length) rows = sheet.rows.map((_, i) => i);
      const whole = rows.length === sheet.rows.length;
      setChartDialog({
        index: null,
        value: null,
        source: chartSource(sheet, computed, columns, rows),
        binding: null,
        range: whole ? null : [Math.min(...rows) + 1, Math.max(...rows) + 1],
      });
    },
    [sheet, computed, views, range, selectedStoredRows, announce, t],
  );

  const saveChart = useCallback(
    (chart: ChartJson, binding: ChartBinding | null) => {
      const dialog = chartDialog;
      setChartDialog(null);
      if (!dialog) return;
      const stored = storedChart(chart, binding, sheet, dialog.range);
      if (dialog.index === null) change(step("insert_chart"), (draft) => void ops.addChart(draft, stored));
      else change(step("edit_chart"), (draft) => ops.replaceChart(draft, dialog.index as number, stored));
      refocus();
    },
    [chartDialog, sheet, change, step, refocus],
  );

  // ------------------------------------------------------------- sheets
  const addSheet = useCallback(() => {
    if (spec.sheets.length >= MAX_SHEETS) return;
    let made = -1;
    editor.apply(
      (draft) => {
        made = ops.addSheet(draft, t("nodes.editor.sheets.tabs.default"));
      },
      { label: step("add_sheet") },
    );
    if (made >= 0) {
      setActiveSheet(made);
      setSelection(at(0, 0));
    }
  }, [spec.sheets.length, editor, t, step]);

  const pickSheet = useCallback(
    (index: number) => {
      if (editing) setEditing(null);
      setActiveSheet(index);
      setSelection(at(0, 0));
    },
    [editing],
  );

  // ------------------------------------------------------------- menus
  const menuClipboard = useCallback(
    (what: "cut" | "copy" | "paste") => {
      const clipboard = typeof navigator !== "undefined" ? navigator.clipboard : undefined;
      if (what === "paste") {
        void clipboard?.readText?.().then((text) => text && paste(text)).catch(() => announce(t("nodes.editor.sheets.message.paste_keys").replace("{0}", MOD)));
      } else {
        const text = copyText();
        void clipboard?.writeText?.(text).catch(() => undefined);
        if (what === "cut") clear(step("cut"));
      }
      refocus();
    },
    [paste, copyText, clear, step, refocus, announce, t],
  );

  const cellLines = useCallback((): MenuLine[] => {
    const wholeRows = range.left === 0 && range.right === sheet.columns.length - 1;
    const rowCountSel = range.bottom - range.top + 1;
    const colCountSel = range.right - range.left + 1;
    const rowsWord = (key: string) => t(key).replace("{0}", String(rowCountSel));
    const colsWord = (key: string) => t(key).replace("{0}", String(colCountSel));
    return [
      { id: "cut", label: t("nodes.editor.sheets.menu.cut"), icon: <Scissors aria-hidden />, shortcut: `${MOD}X`, run: () => menuClipboard("cut") },
      { id: "copy", label: t("nodes.editor.sheets.menu.copy"), icon: <Copy aria-hidden />, shortcut: `${MOD}C`, run: () => menuClipboard("copy") },
      {
        id: "paste",
        label: t("nodes.editor.sheets.menu.paste"),
        icon: <ClipboardPaste aria-hidden />,
        shortcut: `${MOD}V`,
        disabled: typeof navigator === "undefined" || !navigator.clipboard?.readText,
        run: () => menuClipboard("paste"),
      },
      SEPARATOR,
      { id: "insert-above", label: rowsWord("nodes.editor.sheets.menu.insert_above"), icon: <Rows3 aria-hidden />, run: () => insertRows("above") },
      { id: "insert-below", label: rowsWord("nodes.editor.sheets.menu.insert_below"), icon: <Rows3 aria-hidden />, run: () => insertRows("below") },
      { id: "insert-left", label: colsWord("nodes.editor.sheets.menu.insert_left"), icon: <Columns3 aria-hidden />, run: () => insertColumns("left") },
      { id: "insert-right", label: colsWord("nodes.editor.sheets.menu.insert_right"), icon: <Columns3 aria-hidden />, run: () => insertColumns("right") },
      SEPARATOR,
      { id: "delete-rows", label: rowsWord("nodes.editor.sheets.menu.delete_rows"), icon: <Trash2 aria-hidden />, destructive: true, disabled: range.top >= viewRows.length, run: deleteRows },
      { id: "delete-columns", label: colsWord("nodes.editor.sheets.menu.delete_columns"), icon: <Trash2 aria-hidden />, destructive: true, disabled: wholeRows && rowCountSel > 0 && colCountSel === sheet.columns.length, run: deleteColumns },
      { id: "clear", label: t("nodes.editor.sheets.menu.clear"), icon: <Eraser aria-hidden />, shortcut: "⌫", run: () => clear() },
      SEPARATOR,
      { id: "fill-down", label: t("nodes.editor.sheets.menu.fill_down"), shortcut: `${MOD}D`, run: () => fill("down") },
      { id: "fill-right", label: t("nodes.editor.sheets.menu.fill_right"), shortcut: `${MOD}R`, run: () => fill("right") },
      SEPARATOR,
      { id: "sort-asc", label: t("nodes.editor.sheets.menu.sort_asc"), icon: <ArrowDownAZ aria-hidden />, run: () => sortBy(sel.active.col, 1) },
      { id: "sort-desc", label: t("nodes.editor.sheets.menu.sort_desc"), icon: <ArrowUpZA aria-hidden />, run: () => sortBy(sel.active.col, -1) },
      { id: "chart", label: t("nodes.editor.sheets.menu.chart"), icon: <BarChart3 aria-hidden />, run: () => openChart(null) },
    ];
  }, [range, sheet.columns.length, viewRows.length, t, menuClipboard, insertRows, insertColumns, deleteRows, deleteColumns, clear, fill, sortBy, sel.active.col, openChart]);

  const columnLines = useCallback(
    (col: number): MenuLine[] => {
      const column = sheet.columns[col];
      const select = () => setSelection(selectColumns(col, col, viewRows.length));
      return [
        { id: "sort-asc", label: t("nodes.editor.sheets.menu.sort_asc"), icon: <ArrowDownAZ aria-hidden />, run: () => sortBy(col, 1) },
        { id: "sort-desc", label: t("nodes.editor.sheets.menu.sort_desc"), icon: <ArrowUpZA aria-hidden />, run: () => sortBy(col, -1) },
        {
          id: "filter",
          label: t("nodes.editor.sheets.menu.filter"),
          icon: <Filter aria-hidden />,
          run: () => setMenu({ kind: "filter", col, x: menu?.x ?? 0, y: menu?.y ?? 0 }),
        },
        SEPARATOR,
        {
          id: "insert-left",
          label: t("nodes.editor.sheets.menu.insert_left").replace("{0}", "1"),
          icon: <Columns3 aria-hidden />,
          disabled: sheet.columns.length >= MAX_COLUMNS,
          run: () => {
            change(step("insert_columns"), (draft) => void ops.insertColumns(draft, col, 1));
            setSelection(at(sel.active.row, col));
          },
        },
        {
          id: "insert-right",
          label: t("nodes.editor.sheets.menu.insert_right").replace("{0}", "1"),
          icon: <Columns3 aria-hidden />,
          disabled: sheet.columns.length >= MAX_COLUMNS,
          run: () => {
            change(step("insert_columns"), (draft) => void ops.insertColumns(draft, col + 1, 1));
            setSelection(at(sel.active.row, col + 1));
          },
        },
        {
          id: "move-left",
          label: t("nodes.editor.sheets.menu.move_left"),
          disabled: col === 0,
          run: () => {
            change(step("move_column"), (draft) => ops.moveColumn(draft, col, col - 1));
            setSelection(at(sel.active.row, col - 1));
          },
        },
        {
          id: "move-right",
          label: t("nodes.editor.sheets.menu.move_right"),
          disabled: col >= sheet.columns.length - 1,
          run: () => {
            change(step("move_column"), (draft) => ops.moveColumn(draft, col, col + 1));
            setSelection(at(sel.active.row, col + 1));
          },
        },
        SEPARATOR,
        {
          id: "settings",
          label: t("nodes.editor.sheets.menu.settings"),
          icon: <PanelRight aria-hidden />,
          run: () => {
            setSelection(at(sel.active.row, col));
            setPanelOpen(true);
            setPanelFocus((n) => n + 1);
          },
        },
        {
          id: "delete",
          label: t("nodes.editor.sheets.menu.delete_columns").replace("{0}", "1"),
          icon: <Trash2 aria-hidden />,
          destructive: true,
          disabled: sheet.columns.length <= 1,
          run: () => {
            const users = ops.formulaUsers(sheet, [column.key]);
            if (users.length) {
              select();
              return announce(t("nodes.editor.sheets.message.used_by_formula").replace("{0}", users.map((c) => c.label).join(", ")));
            }
            change(step("delete_columns"), (draft) => void ops.deleteColumns(draft, [column.key]));
            setSelection(at(sel.active.row, Math.max(0, Math.min(col, sheet.columns.length - 2))));
          },
        },
      ];
    },
    [sheet, viewRows.length, t, sortBy, menu, change, step, sel.active.row, announce],
  );

  const tabLines = useCallback(
    (index: number): MenuLine[] => [
      { id: "rename", label: t("nodes.editor.sheets.tabs.rename"), run: () => setRenameToken((n) => n + 1) },
      {
        id: "duplicate",
        label: t("nodes.editor.sheets.tabs.duplicate"),
        disabled: spec.sheets.length >= MAX_SHEETS,
        run: () => {
          let made = -1;
          editor.apply(
            (draft) => {
              made = ops.duplicateSheet(draft, index, t("nodes.editor.sheets.tabs.copy_word"));
            },
            { label: step("duplicate_sheet") },
          );
          if (made >= 0) pickSheet(made);
        },
      },
      {
        id: "move-left",
        label: t("nodes.editor.sheets.tabs.move_left"),
        disabled: index === 0,
        run: () => {
          editor.apply((draft) => ops.moveSheet(draft, index, index - 1), { label: step("move_sheet") });
          setActiveSheet(index - 1);
        },
      },
      {
        id: "move-right",
        label: t("nodes.editor.sheets.tabs.move_right"),
        disabled: index >= spec.sheets.length - 1,
        run: () => {
          editor.apply((draft) => ops.moveSheet(draft, index, index + 1), { label: step("move_sheet") });
          setActiveSheet(index + 1);
        },
      },
      SEPARATOR,
      {
        id: "delete",
        label: t("nodes.editor.sheets.tabs.delete"),
        icon: <Trash2 aria-hidden />,
        destructive: true,
        disabled: spec.sheets.length <= 1,
        run: () => {
          editor.apply((draft) => ops.deleteSheet(draft, index), { label: step("delete_sheet") });
          pickSheet(Math.max(0, Math.min(index, spec.sheets.length - 2)));
          announce(t("nodes.editor.sheets.message.sheet_deleted").replace("{0}", spec.sheets[index]?.name ?? ""));
        },
      },
    ],
    [spec.sheets, editor, t, step, pickSheet, announce],
  );

  const filterValues = useCallback(
    (col: number): FilterValue[] => {
      const view = views[col];
      if (!view) return [];
      const counts = new Map<string, number>();
      for (const row of computed) {
        const token = cellToken(row[view.column.key], view, locale);
        counts.set(token, (counts.get(token) ?? 0) + 1);
      }
      const collator = new Intl.Collator(locale, { numeric: true, sensitivity: "base" });
      return [...counts.entries()]
        .map(([value, count]) => ({ value, count }))
        .sort((a, b) => (a.value === "" ? 1 : b.value === "" ? -1 : collator.compare(a.value, b.value)))
        .slice(0, 500);
    },
    [views, computed, locale],
  );

  // ------------------------------------------------------------- grid wiring
  const actions: GridActions = useMemo(
    () => ({
      commit,
      clear: () => clear(),
      copyText,
      cut: () => clear(step("cut")),
      paste,
      fill,
      toggleCheck,
      filled: (row, col) => {
        if (row >= viewRows.length) return false;
        const value = computed[viewRows[row]]?.[sheet.columns[col]?.key];
        return value !== undefined && value !== "";
      },
      editText: (row, col) => {
        const key = sheet.columns[col]?.key;
        return key ? editText(sheet.rows[storedRow(row)]?.[key], locale) : "";
      },
      readOnly,
      openMenu: (x, y) => setMenu({ kind: "cells", x, y }),
      openColumnMenu: (col, x, y) => setMenu({ kind: "column", col, x, y }),
      openFilter: (col, x, y) => setMenu({ kind: "filter", col, x, y }),
      resizeColumn: (col, width) => patchColumn(col, { width }, step("resize_column")),
      moveColumn: (from, to) => {
        change(step("move_column"), (draft) => ops.moveColumn(draft, from, to));
        setSelection(at(sel.active.row, to));
      },
      selectColumns: (left, right) => setSelection(selectColumns(left, right, viewRows.length)),
      selectRows: (top, bottom) => setSelection(selectRows(top, bottom, size)),
      selectAll: () => setSelection(selectAll(size, viewRows.length)),
      toggleBold: () => patchSelected({ bold: !activeColumn?.bold || undefined }, step("bold")),
      openColumnSettings: (col) => {
        setSelection(at(sel.active.row, col));
        setPanelOpen(true);
        setPanelFocus((n) => n + 1);
      },
      announce,
    }),
    [commit, clear, copyText, step, paste, fill, toggleCheck, viewRows, computed, sheet.columns, sheet.rows, storedRow, locale, readOnly, patchColumn, change, sel.active.row, size, patchSelected, activeColumn, announce],
  );

  const closeMenu = useCallback(() => {
    setMenu(null);
    refocus();
  }, [refocus]);

  const typeOptions = COLUMN_TYPES.map((type) => ({ value: type, label: t(`nodes.editor.sheets.types.${type}`) }));

  // ------------------------------------------------------------- toolbar
  const toolbar = (
    <>
      <ToolbarGroup label={t("nodes.editor.sheets.toolbar.format")}>
        <Select
          label={t("nodes.editor.sheets.panel.type")}
          value={activeColumn?.formula ? activeView.kind : (activeColumn?.type ?? activeView?.kind ?? "text")}
          options={activeColumn?.formula ? typeOptions.filter((o) => ["number", "currency", "percent"].includes(o.value)) : typeOptions}
          onChange={(value) => patchSelected({ type: value as ColumnType }, step("column_type"))}
          className="w-32"
          testId="sheet-type"
        />
        <ToolbarButton
          label={t("nodes.editor.sheets.toolbar.fewer_decimals")}
          icon={<Minus aria-hidden />}
          disabled={!activeView?.numeric || activeView.decimals <= 0}
          onClick={() => changeDecimals(-1)}
          data-testid="sheet-decimals-down"
        />
        <span className="w-12 text-center text-xs tabular-nums text-muted-foreground" aria-live="polite">
          {activeView?.numeric ? `.${"0".repeat(activeView.decimals) || "–"}` : ""}
        </span>
        <ToolbarButton
          label={t("nodes.editor.sheets.toolbar.more_decimals")}
          icon={<Plus aria-hidden />}
          disabled={!activeView?.numeric || activeView.decimals >= MAX_DECIMALS}
          onClick={() => changeDecimals(1)}
          data-testid="sheet-decimals-up"
        />
        <ToolbarButton
          label={t("nodes.editor.sheets.toolbar.bold")}
          icon={<Bold aria-hidden />}
          shortcut={`${MOD}B`}
          active={Boolean(activeColumn?.bold)}
          onClick={() => patchSelected({ bold: !activeColumn?.bold || undefined }, step("bold"))}
        />
      </ToolbarGroup>
      <ToolbarSeparator />
      <ToolbarGroup label={t("nodes.editor.sheets.toolbar.data")}>
        <ToolbarButton label={t("nodes.editor.sheets.menu.sort_asc")} icon={<ArrowDownAZ aria-hidden />} onClick={() => sortBy(sel.active.col, 1)} data-testid="sheet-sort-asc" />
        <ToolbarButton label={t("nodes.editor.sheets.menu.sort_desc")} icon={<ArrowUpZA aria-hidden />} onClick={() => sortBy(sel.active.col, -1)} data-testid="sheet-sort-desc" />
        <ToolbarButton
          label={t("nodes.editor.sheets.menu.filter")}
          icon={<Filter aria-hidden />}
          active={activeColumn ? filteredKeys.has(activeColumn.key) : false}
          onClick={(event) => {
            const box = event.currentTarget.getBoundingClientRect();
            setMenu({ kind: "filter", col: sel.active.col, x: box.left, y: box.bottom + 4 });
          }}
          data-testid="sheet-filter-button"
        />
        {filtering && (
          <ToolbarButton
            label={t("nodes.editor.sheets.filter.clear_all")}
            icon={<FilterX aria-hidden />}
            onClick={() => setFilters((all) => ({ ...all, [filterKey]: {} }))}
            data-testid="sheet-filter-clear"
          />
        )}
      </ToolbarGroup>
      <ToolbarSeparator />
      <ToolbarGroup label={t("nodes.editor.sheets.toolbar.insert")}>
        <Popover
          label={t("nodes.editor.sheets.toolbar.insert")}
          role="menu"
          trigger={
            <ToolbarButton
              label={t("nodes.editor.sheets.toolbar.insert")}
              icon={<Plus aria-hidden />}
              showLabel
              trailing={<ChevronDown className="h-3 w-3" aria-hidden />}
              data-testid="sheet-insert"
            />
          }
        >
          <MenuItem label={t("nodes.editor.sheets.menu.insert_above").replace("{0}", String(range.bottom - range.top + 1))} icon={<Rows3 aria-hidden />} onClick={() => {
            insertRows("above");
            refocus();
          }} data-testid="sheet-insert-above" />
          <MenuItem label={t("nodes.editor.sheets.menu.insert_below").replace("{0}", String(range.bottom - range.top + 1))} icon={<Rows3 aria-hidden />} onClick={() => {
            insertRows("below");
            refocus();
          }} />
          <MenuItem label={t("nodes.editor.sheets.menu.insert_left").replace("{0}", String(range.right - range.left + 1))} icon={<Columns3 aria-hidden />} onClick={() => {
            insertColumns("left");
            refocus();
          }} />
          <MenuItem label={t("nodes.editor.sheets.menu.insert_right").replace("{0}", String(range.right - range.left + 1))} icon={<Columns3 aria-hidden />} onClick={() => {
            insertColumns("right");
            refocus();
          }} data-testid="sheet-insert-right" />
        </Popover>
        <ToolbarButton
          label={t("nodes.editor.sheets.menu.chart")}
          icon={<BarChart3 aria-hidden />}
          showLabel
          disabled={(sheet.charts?.length ?? 0) >= MAX_CHARTS}
          onClick={() => openChart(null)}
          data-testid="sheet-insert-chart"
        />
      </ToolbarGroup>
      <ToolbarSeparator />
      <ToolbarButton
        label={t("nodes.editor.sheets.toolbar.settings")}
        icon={<PanelRight aria-hidden />}
        active={panelOpen}
        onClick={() => setPanelOpen((open) => !open)}
        data-testid="sheet-panel-toggle"
      />
    </>
  );

  const side = panelOpen ? (
    <ColumnPanel
      sheet={sheet}
      col={sel.active.col}
      view={activeView}
      note={spec.note ?? ""}
      focusToken={panelFocus}
      onPatch={(patch, label) => patchColumn(sel.active.col, patch, label)}
      onFreeze={(count) => change(step("freeze"), (draft) => void (draft.freeze = count))}
      onNote={(text) =>
        editor.apply(
          (draft) => {
            const note = text.split(/\s+/).filter(Boolean).join(" ").slice(0, 200);
            if (note) draft.note = note;
            else delete draft.note;
          },
          { label: step("note") },
        )
      }
      onClose={() => {
        setPanelOpen(false);
        refocus();
      }}
    />
  ) : undefined;

  const activeAddress = `${columnLetter(sel.active.col)}${sel.active.row < viewRows.length ? viewRows[sel.active.row] + 1 : sheet.rows.length + sel.active.row - viewRows.length + 1}`;
  const editingActive = editing !== null && editing.row === sel.active.row && editing.col === sel.active.col;
  const barValue = activeColumn?.formula
    ? `= ${activeColumn.formula}`
    : editingActive
      ? editing.text
      : editText(sheet.rows[storedRow(sel.active.row)]?.[activeColumn?.key ?? ""], locale);

  return (
    <EditorShell editor={editor} title={node.title} onDone={onDone} toolbar={toolbar} side={side} bodyClassName="relative flex flex-col overflow-hidden">
      <div className="flex h-9 shrink-0 items-center gap-2 border-b border-border px-2" data-sheet-formula-bar="">
        <span className="w-16 shrink-0 rounded border border-border px-2 py-0.5 text-center font-mono text-xs" aria-label={t("nodes.editor.sheets.bar.address")}>
          {activeAddress}
        </span>
        <span className="text-xs italic text-muted-foreground" aria-hidden>
          fx
        </span>
        <input
          aria-label={t("nodes.editor.sheets.bar.value")}
          value={barValue}
          readOnly={Boolean(activeColumn?.formula)}
          title={activeColumn?.formula ? t("nodes.editor.sheets.message.formula_cell") : undefined}
          className="h-7 min-w-0 flex-1 bg-transparent px-1 text-sm focus:outline-none"
          data-own-undo=""
          data-testid="sheet-formula-bar"
          onFocus={() => {
            if (!activeColumn?.formula && !editingActive) {
              setEditing({ row: sel.active.row, col: sel.active.col, mode: "edit", text: barValue });
            }
          }}
          onChange={(event) => {
            if (activeColumn?.formula) return;
            setEditing({ row: sel.active.row, col: sel.active.col, mode: "edit", text: event.target.value });
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === "Tab") {
              event.preventDefault();
              if (editing) commit(editing.row, editing.col, editing.text);
              setEditing(null);
              refocus();
            } else if (event.key === "Escape") {
              event.preventDefault();
              setEditing(null);
              refocus();
            }
          }}
          onBlur={(event) => {
            const next = event.relatedTarget as HTMLElement | null;
            if (next?.dataset.testid === "sheet-cell-input") return;
            if (editing && editingActive) commit(editing.row, editing.col, editing.text);
            setEditing(null);
          }}
        />
        {filtering && (
          <span className="shrink-0 text-xs text-muted-foreground" data-testid="sheet-filter-count">
            {t("nodes.editor.sheets.filter.count").replace("{0}", String(viewRows.length)).replace("{1}", String(sheet.rows.length))}
          </span>
        )}
      </div>
      <div className="min-h-0 flex-1">
        <SheetGrid
          key={sheetIndex}
          sheet={sheet}
          computed={computed}
          views={views}
          viewRows={viewRows}
          rowCount={rowCount}
          selection={sel}
          onSelect={setSelection}
          editing={editing}
          setEditing={setEditing}
          actions={actions}
          filtered={filteredKeys}
          sorted={sorted && sorted.sheet === sheetIndex ? sorted : null}
          totals={totals}
          totalMarks={totalMarks}
          locale={locale}
          label={sheet.name}
          focusToken={focusToken}
          labels={{
            columnMenu: (column) => t("nodes.editor.sheets.grid.column_menu").replace("{0}", column),
            resize: (column) => t("nodes.editor.sheets.grid.resize").replace("{0}", column),
            rowNumber: (row) => t("nodes.editor.sheets.grid.row").replace("{0}", String(row)),
            cell: (address, column, value) =>
              t("nodes.editor.sheets.grid.cell").replace("{0}", address).replace("{1}", column).replace("{2}", value),
            empty: t("nodes.editor.sheets.grid.empty"),
            selectAll: t("nodes.editor.sheets.grid.select_all"),
            newRow: t("nodes.editor.sheets.grid.new_row"),
          }}
        />
      </div>
      {sheet.charts && sheet.charts.length > 0 && (
        <ChartStrip
          charts={sheet.charts}
          draw={(chart) => drawnChart(chart, sheet, computed)}
          onEdit={(index) => openChart(index)}
          onDelete={(index) => change(step("delete_chart"), (draft) => ops.deleteChart(draft, index))}
        />
      )}
      <SheetTabs
        names={spec.sheets.map((s) => s.name)}
        active={sheetIndex}
        onPick={pickSheet}
        onAdd={addSheet}
        onRename={(index, name) => {
          if (name.trim() && name.trim() !== spec.sheets[index]?.name) {
            editor.apply((draft) => ops.renameSheet(draft, index, name), { label: step("rename_sheet") });
          }
        }}
        onMove={(from, to) => {
          editor.apply((draft) => ops.moveSheet(draft, from, to), { label: step("move_sheet") });
          if (from === sheetIndex) setActiveSheet(to);
        }}
        onMenu={(index, x, y) => setMenu({ kind: "tab", index, x, y })}
        renameToken={renameToken}
      />
      <div role="status" aria-live="polite" className="sr-only" data-testid="sheet-status">
        {message}
      </div>
      {message && (
        <div className="pointer-events-none absolute bottom-14 left-1/2 z-50 -translate-x-1/2 rounded-md bg-foreground px-3 py-1.5 text-sm text-background shadow-float" aria-hidden>
          {message}
        </div>
      )}
      {menu?.kind === "cells" && <ContextMenu x={menu.x} y={menu.y} label={t("nodes.editor.sheets.menu.label")} lines={cellLines()} onClose={closeMenu} />}
      {menu?.kind === "column" && (
        <ContextMenu
          x={menu.x}
          y={menu.y}
          label={t("nodes.editor.sheets.menu.column_label").replace("{0}", sheet.columns[menu.col]?.label ?? "")}
          lines={columnLines(menu.col)}
          onClose={() => setMenu((now) => (now?.kind === "column" ? null : now))}
        />
      )}
      {menu?.kind === "tab" && (
        <ContextMenu x={menu.x} y={menu.y} label={t("nodes.editor.sheets.tabs.menu")} lines={tabLines(menu.index)} onClose={() => setMenu(null)} />
      )}
      {menu?.kind === "filter" && sheet.columns[menu.col] && (
        <FilterPanel
          x={menu.x}
          y={menu.y}
          column={sheet.columns[menu.col].label}
          values={filterValues(menu.col)}
          allowed={sheetFilters[sheet.columns[menu.col].key] ?? null}
          onApply={(allowed) => {
            const key = sheet.columns[menu.col].key;
            setFilters((all) => {
              const mine = { ...(all[filterKey] ?? {}) };
              if (allowed === null) delete mine[key];
              else mine[key] = allowed;
              return { ...all, [filterKey]: mine };
            });
            setSelection(at(0, menu.col));
          }}
          onClose={closeMenu}
        />
      )}
      <ChartEditor
        open={chartDialog !== null}
        value={chartDialog?.value ?? null}
        source={chartDialog?.source}
        binding={chartDialog?.binding ?? null}
        onSave={saveChart}
        onCancel={() => {
          setChartDialog(null);
          refocus();
        }}
      />
    </EditorShell>
  );
}

/** What a filter compares: the cell as the grid shows it ("" for an empty cell, ✓/– for a check). */
function cellToken(value: CellValue | undefined, view: ReturnType<typeof columnViews>[number], locale?: string): string {
  if (value === undefined) return "";
  if (typeof value === "boolean") return value ? "✓" : "–";
  return displayText(value, view, locale);
}

/** The sheet's charts under the grid, drawn natively, each with Edit and Delete. */
function ChartStrip({
  charts,
  draw,
  onEdit,
  onDelete,
}: {
  charts: readonly SheetChart[];
  draw: (chart: SheetChart) => ChartJson;
  onEdit: (index: number) => void;
  onDelete: (index: number) => void;
}) {
  const t = useT();
  return (
    <section
      aria-label={t("nodes.editor.sheets.charts.label")}
      className="flex max-h-[42%] shrink-0 gap-3 overflow-x-auto border-t border-border bg-secondary/40 p-3"
      data-testid="sheet-charts"
    >
      {charts.map((chart, index) => {
        const literal = draw(chart);
        const check = validateChart(literal);
        return (
          <figure key={index} className="flex w-[360px] shrink-0 flex-col gap-2 rounded-lg border border-border bg-background p-3">
            <figcaption className="flex items-center gap-2">
              <span className="min-w-0 flex-1 truncate text-sm font-medium">{chart.title || t("nodes.editor.sheets.charts.untitled")}</span>
              <button type="button" className="rounded px-2 py-0.5 text-xs hover:bg-secondary" onClick={() => onEdit(index)} data-testid={`sheet-chart-edit-${index}`}>
                {t("nodes.editor.sheets.charts.edit")}
              </button>
              <button
                type="button"
                aria-label={t("nodes.editor.sheets.charts.delete").replace("{0}", chart.title || String(index + 1))}
                className="rounded p-1 text-muted-foreground hover:bg-secondary hover:text-destructive"
                onClick={() => onDelete(index)}
                data-testid={`sheet-chart-delete-${index}`}
              >
                <Trash2 className="h-3.5 w-3.5" aria-hidden />
              </button>
            </figcaption>
            {check.chart ? (
              <ChartPreview chart={check.chart} height={180} />
            ) : (
              <p className="flex h-[180px] items-center justify-center text-center text-xs text-muted-foreground">{t("nodes.editor.sheets.charts.cannot_draw")}</p>
            )}
          </figure>
        );
      })}
    </section>
  );
}

