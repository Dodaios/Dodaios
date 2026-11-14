/**
 * The pieces of the Analytics editor's canvas: a metric tile, a chart tile,
 * a table, and the small row of actions every piece carries.
 *
 * The canvas is laid out like the dashboard page (`data.py`): tiles in rows
 * of even length, charts two per row with wide ones across, tables below.
 * Every text is typed where it stands; what has no place on the page (which
 * way a delta reads, a chart's width, moving a piece to another section)
 * sits in the inspector beside it.
 */
import { useRef, type ClipboardEvent, type DragEvent, type KeyboardEvent, type ReactNode } from "react";
import { ArrowLeft, ArrowRight, Columns2, Copy, GripVertical, Maximize2, Pencil, Plus, Trash2, X } from "lucide-react";

import { useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { ChartPreview } from "../charts/ChartPreview";
import type { ChartJson } from "../charts/chartModel";
import { ToolbarButton } from "../controls";
import {
  LIMITS,
  addColumn,
  addRow,
  cellToInput,
  parsePastedGrid,
  pasteGrid,
  removeColumn,
  removeRow,
  setCell,
  type DashChart,
  type DashMetric,
  type DashSpec,
  type DashTable,
} from "./dashboardModel";

/** A change to the spec: one undo step, or one per typing run with `coalesce`. */
export type Act = (label: string, change: (draft: DashSpec) => void, coalesce?: string) => void;
/** A change to one piece, lifted to a change of the whole spec (`Act`). */
export type Lift<T> = (change: (piece: T) => void) => (draft: DashSpec) => void;

/* --------------------------------------------------------------- inline */

/**
 * A text typed where it stands on the canvas: an input with no frame of its
 * own until it is hovered or focused, so the canvas reads like the page.
 */
export function InlineText({
  value,
  onChange,
  label,
  placeholder,
  maxLength,
  className,
  invalid,
  multiline = false,
  testId,
}: {
  value: string;
  onChange: (value: string) => void;
  label: string;
  placeholder?: string;
  maxLength: number;
  className?: string;
  invalid?: boolean;
  multiline?: boolean;
  testId?: string;
}) {
  const shared = cn(
    "w-full min-w-0 rounded-md border border-transparent bg-transparent px-1.5 py-0.5 text-foreground",
    "placeholder:text-muted-foreground/70 hover:border-border focus:border-accent focus:bg-background focus:outline-none",
    invalid && "border-destructive/70 hover:border-destructive focus:border-destructive",
    className,
  );
  if (multiline) {
    return (
      <textarea
        aria-label={label}
        aria-invalid={invalid || undefined}
        value={value}
        placeholder={placeholder}
        maxLength={maxLength}
        rows={Math.max(1, Math.min(6, Math.ceil(value.length / 90) || 1))}
        onChange={(event) => onChange(event.target.value.replace(/\n/g, " "))}
        className={cn(shared, "resize-none")}
        data-testid={testId}
      />
    );
  }
  return (
    <input
      type="text"
      aria-label={label}
      aria-invalid={invalid || undefined}
      value={value}
      placeholder={placeholder}
      maxLength={maxLength}
      onChange={(event) => onChange(event.target.value)}
      className={shared}
      data-testid={testId}
    />
  );
}

/* -------------------------------------------------------------- actions */

export interface ItemActionsProps {
  /** "earlier"/"later" read left/right for tiles and charts, up/down for tables and sections. */
  vertical?: boolean;
  canEarlier: boolean;
  canLater: boolean;
  canDuplicate: boolean;
  canRemove: boolean;
  onMove: (step: -1 | 1) => void;
  onDuplicate: () => void;
  onRemove: () => void;
  /** The item's name, for the actions' accessible names ("Move Revenue earlier"). */
  name: string;
  children?: ReactNode;
}

/** The actions on one piece, shown while it is hovered, focused or selected. */
export function ItemActions({
  vertical = false,
  canEarlier,
  canLater,
  canDuplicate,
  canRemove,
  onMove,
  onDuplicate,
  onRemove,
  name,
  children,
}: ItemActionsProps) {
  const t = useT();
  const named = (key: string) => t(key).replace("{0}", name);
  return (
    <div
      role="toolbar"
      aria-label={named("nodes.editor.data.actions.label")}
      className="flex items-center gap-0.5 rounded-md border border-border bg-popover p-0.5 shadow-sm [&_button]:h-7 [&_button]:w-7"
    >
      {children}
      <ToolbarButton
        label={named(vertical ? "nodes.editor.data.actions.up" : "nodes.editor.data.actions.earlier")}
        icon={vertical ? <ArrowLeft aria-hidden className="rotate-90" /> : <ArrowLeft aria-hidden />}
        disabled={!canEarlier}
        onClick={() => onMove(-1)}
      />
      <ToolbarButton
        label={named(vertical ? "nodes.editor.data.actions.down" : "nodes.editor.data.actions.later")}
        icon={vertical ? <ArrowRight aria-hidden className="rotate-90" /> : <ArrowRight aria-hidden />}
        disabled={!canLater}
        onClick={() => onMove(1)}
      />
      <ToolbarButton
        label={named("nodes.editor.data.actions.duplicate")}
        icon={<Copy aria-hidden />}
        disabled={!canDuplicate}
        onClick={onDuplicate}
      />
      <ToolbarButton
        label={canRemove ? named("nodes.editor.data.actions.delete") : t("nodes.editor.data.actions.keep_last")}
        icon={<Trash2 aria-hidden />}
        disabled={!canRemove}
        onClick={onRemove}
      />
    </div>
  );
}

/**
 * The handle a piece is dragged by and moved with from the keyboard: the
 * arrow keys move it one place earlier or later in its row.
 */
export function Grip({
  name,
  onMove,
  onDragStart,
  vertical = false,
}: {
  name: string;
  onMove: (step: -1 | 1) => void;
  onDragStart: (event: DragEvent<HTMLElement>) => void;
  vertical?: boolean;
}) {
  const t = useT();
  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    const back = vertical ? "ArrowUp" : "ArrowLeft";
    const on = vertical ? "ArrowDown" : "ArrowRight";
    if (event.key === back || event.key === on) {
      event.preventDefault();
      event.stopPropagation();
      onMove(event.key === back ? -1 : 1);
    }
  };
  return (
    <button
      type="button"
      draggable
      aria-label={t("nodes.editor.data.grip").replace("{0}", name)}
      title={t("nodes.editor.data.grip").replace("{0}", name)}
      onKeyDown={onKeyDown}
      onDragStart={onDragStart}
      className="flex h-6 w-5 shrink-0 cursor-grab items-center justify-center rounded text-muted-foreground opacity-60 hover:bg-secondary hover:opacity-100 focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring active:cursor-grabbing"
    >
      <GripVertical aria-hidden className="h-4 w-4" />
    </button>
  );
}

/* --------------------------------------------------------------- pieces */

/** The frame of a selectable piece: click to select; the outline says which is. */
export function Piece({
  selected,
  onSelect,
  className,
  children,
  testId,
  dropTarget,
  onDragOver,
  onDrop,
  label,
}: {
  selected: boolean;
  onSelect: () => void;
  className?: string;
  children: ReactNode;
  testId?: string;
  dropTarget?: boolean;
  onDragOver?: (event: DragEvent<HTMLElement>) => void;
  onDrop?: (event: DragEvent<HTMLElement>) => void;
  label: string;
}) {
  return (
    <div
      role="group"
      aria-label={label}
      aria-current={selected || undefined}
      onFocusCapture={onSelect}
      onMouseDown={onSelect}
      onDragOver={onDragOver}
      onDrop={onDrop}
      data-testid={testId}
      data-selected={selected || undefined}
      className={cn(
        "group/piece relative min-w-0 rounded-lg outline-none transition-shadow",
        selected ? "ring-2 ring-accent" : "hover:ring-1 hover:ring-border-strong",
        dropTarget && "ring-2 ring-accent/60 ring-offset-2 ring-offset-background",
        className,
      )}
    >
      {children}
    </div>
  );
}

/** Where a piece's actions float: top-right, shown on hover, focus or selection. */
export function Floating({ selected, children }: { selected: boolean; children: ReactNode }) {
  return (
    <div
      className={cn(
        "absolute -top-3.5 right-2 z-10 transition-opacity",
        selected ? "opacity-100" : "pointer-events-none opacity-0 group-focus-within/piece:pointer-events-auto group-focus-within/piece:opacity-100 group-hover/piece:pointer-events-auto group-hover/piece:opacity-100",
      )}
    >
      {children}
    </div>
  );
}

/** The colour the page gives a delta: its sign, flipped when a lower figure is better. */
export function deltaTone(delta: string, better?: "lower"): "up" | "down" | "" {
  const sign = /^\s*([+\-−–])?\s*[^\d]*(\d[\d.,]*)/.exec(delta);
  if (!sign || !/[1-9]/.test(sign[2] ?? "")) return "";
  const up = !sign[1] || sign[1] === "+";
  const tone = up ? "up" : "down";
  return better === "lower" ? (tone === "up" ? "down" : "up") : tone;
}

export function MetricFields({
  metric,
  where,
  act,
  set,
  invalidLabel,
  invalidValue,
}: {
  metric: DashMetric;
  where: string;
  act: Act;
  set: Lift<DashMetric>;
  invalidLabel: boolean;
  invalidValue: boolean;
}) {
  const t = useT();
  const tone = deltaTone(metric.delta ?? "", metric.better);
  const edit = (field: keyof DashMetric, label: string) => (value: string) =>
    act(
      label,
      set((m) => {
        if (field === "label" || field === "value") m[field] = value;
        else if (field === "delta" || field === "detail") {
          if (value) m[field] = value;
          else delete m[field];
          if (field === "delta" && !value) delete m.better;
        }
      }),
      `${where}.${field}`,
    );
  return (
    <div className="flex flex-col gap-0.5 px-3 pb-3 pt-2.5">
      <InlineText
        value={metric.label}
        onChange={edit("label", t("nodes.editor.data.history.metric"))}
        label={t("nodes.editor.data.metric.label")}
        placeholder={t("nodes.editor.data.metric.label_placeholder")}
        maxLength={LIMITS.label}
        className="text-sm text-muted-foreground"
        invalid={invalidLabel}
        testId="data-metric-label"
      />
      <InlineText
        value={metric.value}
        onChange={edit("value", t("nodes.editor.data.history.metric"))}
        label={t("nodes.editor.data.metric.value")}
        placeholder="0"
        maxLength={LIMITS.value}
        className="text-[28px] font-medium leading-9 tracking-tight tabular-nums"
        invalid={invalidValue}
        testId="data-metric-value"
      />
      <div className="flex min-w-0 items-center gap-1">
        <div className="w-24 shrink-0">
          <InlineText
            value={metric.delta ?? ""}
            onChange={edit("delta", t("nodes.editor.data.history.metric"))}
            label={t("nodes.editor.data.metric.delta")}
            placeholder={t("nodes.editor.data.metric.delta_placeholder")}
            maxLength={LIMITS.value}
            className={cn(
              "text-sm font-medium tabular-nums",
              tone === "up" && "text-success",
              tone === "down" && "text-destructive",
            )}
            testId="data-metric-delta"
          />
        </div>
        <InlineText
          value={metric.detail ?? ""}
          onChange={edit("detail", t("nodes.editor.data.history.metric"))}
          label={t("nodes.editor.data.metric.detail")}
          placeholder={t("nodes.editor.data.metric.detail_placeholder")}
          maxLength={LIMITS.detail}
          className="text-sm text-muted-foreground"
        />
      </div>
    </div>
  );
}

export function ChartBody({
  chart,
  onEdit,
  wide,
  onToggleWide,
}: {
  chart: DashChart;
  onEdit: () => void;
  wide: boolean;
  onToggleWide: () => void;
}) {
  const t = useT();
  return (
    <div className="flex h-full flex-col rounded-lg border border-border bg-card p-4">
      <div className="mb-2 flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <h4 className="truncate text-base font-medium">{chart.title || t("nodes.editor.data.chart.untitled")}</h4>
          {chart.value && (
            <p className="text-xl font-medium tabular-nums">
              {chart.value}{" "}
              {chart.delta && (
                <span className={cn("text-sm", deltaTone(chart.delta) === "down" ? "text-destructive" : "text-success")}>
                  {chart.delta}
                </span>
              )}
            </p>
          )}
        </div>
        <ToolbarButton
          label={t(wide ? "nodes.editor.data.chart.half" : "nodes.editor.data.chart.wide")}
          icon={wide ? <Columns2 aria-hidden /> : <Maximize2 aria-hidden />}
          active={chart.wide === true}
          onClick={onToggleWide}
        />
        <ToolbarButton
          label={t("nodes.editor.data.chart.edit")}
          icon={<Pencil aria-hidden />}
          onClick={onEdit}
          data-testid="data-chart-edit"
        />
      </div>
      <button
        type="button"
        onDoubleClick={onEdit}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            onEdit();
          }
        }}
        aria-label={t("nodes.editor.data.chart.open").replace("{0}", chart.title || t("nodes.editor.data.chart.untitled"))}
        className="min-h-0 flex-1 rounded-md text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <ChartPreview chart={chart as unknown as ChartJson} height={wide ? 240 : 200} />
      </button>
      {chart.note && <p className="mt-2 text-xs text-muted-foreground">{chart.note}</p>}
    </div>
  );
}

/* ---------------------------------------------------------------- table */

export function TableGrid({
  table,
  where,
  act,
  setTable,
  invalidColumns,
}: {
  table: DashTable;
  where: string;
  act: Act;
  setTable: Lift<DashTable>;
  invalidColumns: boolean;
}) {
  const t = useT();
  const grid = useRef<HTMLTableElement>(null);
  const focusCell = (row: number, column: number) => {
    window.requestAnimationFrame(() => {
      grid.current?.querySelector<HTMLInputElement>(`[data-cell="${row}:${column}"]`)?.focus();
    });
  };
  const onCellKey = (event: KeyboardEvent<HTMLInputElement>, row: number, column: number) => {
    const input = event.currentTarget;
    const atStart = input.selectionStart === 0 && input.selectionEnd === 0;
    const atEnd = input.selectionStart === input.value.length;
    if (event.key === "Enter" || (event.key === "ArrowDown" && !event.altKey)) {
      event.preventDefault();
      // Enter on the last row opens a new one, the way a list grows while typing.
      if (row === table.rows.length - 1 && event.key === "Enter" && table.rows.length < LIMITS.rows) {
        act(t("nodes.editor.data.history.row_add"), setTable((tb) => void addRow(tb)));
      }
      focusCell(Math.min(row + 1, LIMITS.rows - 1), column);
    } else if (event.key === "ArrowUp" && !event.altKey) {
      event.preventDefault();
      focusCell(row - 1, column);
    } else if (event.key === "ArrowLeft" && atStart && column > 0) {
      event.preventDefault();
      focusCell(row, column - 1);
    } else if (event.key === "ArrowRight" && atEnd && column < table.columns.length - 1) {
      event.preventDefault();
      focusCell(row, column + 1);
    }
  };
  const onPaste = (event: ClipboardEvent<HTMLInputElement>, row: number, column: number) => {
    const text = event.clipboardData.getData("text/plain");
    const cells = parsePastedGrid(text);
    if (cells.length < 2 && (cells[0]?.length ?? 0) < 2) return;
    event.preventDefault();
    act(
      t("nodes.editor.data.history.paste"),
      setTable((tb) => void pasteGrid(tb, row, column, cells)),
    );
  };
  const cellLabel = (row: number, column: number) =>
    t("nodes.editor.data.table.cell")
      .replace("{0}", table.columns[column] || String(column + 1))
      .replace("{1}", String(row + 1));

  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table ref={grid} className="w-full border-collapse text-sm" data-testid="data-table-grid">
        <thead>
          <tr className="bg-secondary/60">
            {table.columns.map((name, column) => (
              <th key={column} scope="col" className="group/col min-w-[120px] border-b border-border p-0 text-left font-medium">
                <div className="flex items-center">
                  <InlineText
                    value={name}
                    onChange={(value) =>
                      act(
                        t("nodes.editor.data.history.column"),
                        setTable((tb) => void (tb.columns[column] = value)),
                        `${where}.col${column}`,
                      )
                    }
                    label={t("nodes.editor.data.table.column").replace("{0}", String(column + 1))}
                    placeholder={t("nodes.editor.data.table.column_placeholder")}
                    maxLength={LIMITS.label}
                    className="font-medium"
                    invalid={invalidColumns}
                  />
                  {table.columns.length > 1 && (
                    <button
                      type="button"
                      aria-label={t("nodes.editor.data.table.remove_column").replace("{0}", name || String(column + 1))}
                      onClick={() =>
                        act(
                          t("nodes.editor.data.history.column_remove"),
                          setTable((tb) => void removeColumn(tb, column)),
                        )
                      }
                      className="mr-1 flex h-6 w-6 shrink-0 items-center justify-center rounded text-muted-foreground opacity-0 hover:bg-secondary hover:text-foreground focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring group-hover/col:opacity-100"
                    >
                      <X aria-hidden className="h-3.5 w-3.5" />
                    </button>
                  )}
                </div>
              </th>
            ))}
            <th className="w-9 border-b border-border p-0">
              <button
                type="button"
                aria-label={t("nodes.editor.data.table.add_column")}
                title={t("nodes.editor.data.table.add_column")}
                disabled={table.columns.length >= LIMITS.columns}
                onClick={() =>
                  act(
                    t("nodes.editor.data.history.column_add"),
                    setTable((tb) => void addColumn(tb, "")),
                  )
                }
                className="flex h-8 w-9 items-center justify-center text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-40"
                data-testid="data-table-add-column"
              >
                <Plus aria-hidden className="h-4 w-4" />
              </button>
            </th>
          </tr>
        </thead>
        <tbody>
          {table.rows.map((cells, row) => (
            <tr key={row} className="group/row border-b border-border last:border-b-0">
              {table.columns.map((_, column) => (
                <td key={column} className="p-0">
                  <input
                    type="text"
                    aria-label={cellLabel(row, column)}
                    data-cell={`${row}:${column}`}
                    value={cellToInput(cells[column])}
                    maxLength={LIMITS.cell}
                    onChange={(event) => {
                      const typed = event.target.value;
                      act(
                        t("nodes.editor.data.history.cell"),
                        setTable((tb) => setCell(tb, row, column, typed)),
                        `${where}.r${row}c${column}`,
                      );
                    }}
                    onKeyDown={(event) => onCellKey(event, row, column)}
                    onPaste={(event) => onPaste(event, row, column)}
                    className={cn(
                      "h-8 w-full min-w-0 bg-transparent px-2.5 focus:bg-background focus:outline-none focus:ring-2 focus:ring-inset focus:ring-accent",
                      typeof cells[column] === "number" && "text-right tabular-nums",
                    )}
                  />
                </td>
              ))}
              <td className="w-9 p-0">
                <button
                  type="button"
                  aria-label={t("nodes.editor.data.table.remove_row").replace("{0}", String(row + 1))}
                  onClick={() => act(t("nodes.editor.data.history.row_remove"), setTable((tb) => removeRow(tb, row)))}
                  className="flex h-8 w-9 items-center justify-center text-muted-foreground opacity-0 hover:bg-secondary hover:text-foreground focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring group-hover/row:opacity-100"
                >
                  <X aria-hidden className="h-3.5 w-3.5" />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <button
        type="button"
        disabled={table.rows.length >= LIMITS.rows}
        onClick={() => {
          act(t("nodes.editor.data.history.row_add"), setTable((tb) => void addRow(tb)));
          focusCell(table.rows.length, 0);
        }}
        className="flex h-8 w-full items-center gap-1.5 px-2.5 text-sm text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring disabled:opacity-40"
        data-testid="data-table-add-row"
      >
        <Plus aria-hidden className="h-4 w-4" />
        {t("nodes.editor.data.table.add_row")}
      </button>
    </div>
  );
}
