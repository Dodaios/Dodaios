/**
 * Make or change one chart in the report chart grammar.
 *
 * Used by every editor whose type holds charts: the doc's fenced chart
 * block, a chart slide, a dashboard figure, a sheet's chart. It works on a
 * DRAFT kept as typed text (a half-typed "1." or an empty cell is fine while
 * editing), checks it on every keystroke against the same rules the server
 * applies (`chartModel.validateChart`), shows the chart live, and only hands
 * a chart back when it would draw: what `onSave` receives is exactly the JSON
 * `parse_chart` accepts.
 *
 * Data comes from one of two places. Typed into a small grid (labels down,
 * one column per series; a block pasted from a spreadsheet app fills the grid
 * from the cell it lands in), or taken from a SOURCE table (a sheet's
 * selection): the person picks the label column and the value columns, and
 * `onSave` also returns that binding so the caller can keep the chart tied to
 * its columns.
 *
 * The dialog marks itself `data-own-undo`: inside it, Cmd/Ctrl+Z belongs to
 * its fields, not to the node editor underneath.
 */
import { useEffect, useId, useMemo, useRef, useState, type ClipboardEvent, type ReactNode } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import {
  AreaChart as AreaIcon,
  BarChart3,
  BarChartHorizontal,
  LineChart as LineIcon,
  PieChart as PieIcon,
  Plus,
  Trash2,
  X,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { ColorPicker, Select } from "../controls";
import {
  CHART_KINDS,
  MAX_SERIES,
  canStack,
  chartFromSource,
  guessBinding,
  isNumericColumn,
  isRound,
  maxLabels,
  starterChart,
  validateChart,
  type ChartBinding,
  type ChartErrorCode,
  type ChartJson,
  type ChartKind,
  type ChartSource,
} from "./chartModel";
import { ChartPreview } from "./ChartPreview";

export type { ChartBinding, ChartJson, ChartKind, ChartSource } from "./chartModel";

export interface ChartEditorPanelProps {
  /** The chart to change; null or absent starts a new one. */
  value?: ChartJson | null;
  /** A table to take the data from (a sheet's selection). */
  source?: ChartSource;
  /** The columns the chart was taken from before, to open with them. */
  binding?: ChartBinding | null;
  /** The finished chart, and its source columns (null without a source). */
  onSave: (chart: ChartJson, binding: ChartBinding | null) => void;
  onCancel: () => void;
  /** The heading; "New chart" / "Edit chart" by default. */
  heading?: string;
}

export interface ChartEditorProps extends ChartEditorPanelProps {
  open: boolean;
}

/* --------------------------------------------------------------- draft */

interface DraftSeries {
  name: string;
  /** One typed cell per label. */
  cells: string[];
}

export interface ChartDraft {
  kind: ChartKind;
  title: string;
  unit: string;
  note: string;
  value: string;
  delta: string;
  stacked: boolean;
  labels: string[];
  series: DraftSeries[];
  colors: string[];
}

export function draftOf(chart: ChartJson): ChartDraft {
  return {
    kind: chart.type,
    title: chart.title ?? "",
    unit: chart.unit ?? "",
    note: chart.note ?? "",
    value: chart.value ?? "",
    delta: chart.delta ?? "",
    stacked: chart.stacked === true,
    labels: [...chart.x],
    series: chart.series.map((series) => ({
      name: series.name,
      cells: series.data.map((value) => (value === null ? "" : String(value))),
    })),
    colors: [...(chart.colors ?? [])],
  };
}

/** The draft as chart JSON (not checked yet). Cells are read with a decimal comma too. */
export function chartOf(draft: ChartDraft): Record<string, unknown> {
  const out: Record<string, unknown> = {
    type: draft.kind,
    title: draft.title,
    x: draft.labels,
    series: draft.series.map((series) => ({
      name: series.name,
      data: series.cells.map((cell) => {
        const text = cell.trim().replace(/\s/g, "");
        if (text === "") return null;
        // "1,5" is one and a half; "1,234.5" keeps its point.
        const normal = /^-?\d+,\d+$/.test(text) ? text.replace(",", ".") : text.replace(/,/g, "");
        return normal;
      }),
    })),
  };
  if (draft.unit) out.unit = draft.unit;
  if (draft.note) out.note = draft.note;
  if (draft.value) out.value = draft.value;
  if (draft.delta) out.delta = draft.delta;
  if (draft.stacked && canStack(draft.kind)) out.stacked = true;
  if (draft.colors.some(Boolean)) out.colors = draft.colors;
  return out;
}

const KIND_ICONS: Record<ChartKind, ReactNode> = {
  column: <BarChart3 aria-hidden />,
  bar: <BarChartHorizontal aria-hidden />,
  line: <LineIcon aria-hidden />,
  area: <AreaIcon aria-hidden />,
  pie: <PieIcon aria-hidden />,
  donut: <PieIcon aria-hidden />,
};

/* --------------------------------------------------------------- panel */

export function ChartEditorPanel({ value, source, binding, onSave, onCancel, heading }: ChartEditorPanelProps) {
  const t = useT();
  const ids = useId();
  const [draft, setDraft] = useState<ChartDraft>(() => draftOf(value ?? starterChart()));
  const [bound, setBound] = useState<ChartBinding | null>(() =>
    source ? (binding ?? guessBinding(source)) : null,
  );

  // With a source, the labels and series follow the chosen columns.
  const sourced = useMemo<ChartDraft>(() => {
    if (!source || !bound) return draft;
    const merged = chartFromSource({ type: draft.kind, x: [], series: [] }, source, bound);
    return {
      ...draft,
      labels: merged.x,
      series: merged.series.map((series) => ({
        name: series.name,
        cells: series.data.map((cell) => (cell === null ? "" : String(cell))),
      })),
    };
  }, [draft, source, bound]);

  const check = useMemo(() => validateChart(chartOf(sourced)), [sourced]);
  const round = isRound(draft.kind);
  const slots = round ? sourced.labels.length : sourced.series.length;

  const patch = (change: Partial<ChartDraft>) => setDraft((now) => ({ ...now, ...change }));
  const setKind = (kind: ChartKind) =>
    setDraft((now) => {
      // A pie keeps the first series; its colours are per slice from now on.
      const series = isRound(kind) ? now.series.slice(0, 1) : now.series;
      const colors = isRound(kind) !== isRound(now.kind) ? [] : now.colors;
      return { ...now, kind, series, colors, stacked: canStack(kind) ? now.stacked : false };
    });

  const save = () => {
    if (!check.chart) return;
    onSave(check.chart, source ? bound : null);
  };

  return (
    <div className="flex min-h-0 flex-col gap-4" data-own-undo="" data-testid="chart-editor">
      <h2 className="text-lg font-semibold text-foreground-strong">
        {heading ?? (value ? t("nodes.editor.chart.edit") : t("nodes.editor.chart.new"))}
      </h2>
      <div className="grid min-h-0 gap-5 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <div className="flex min-w-0 flex-col gap-4">
          <fieldset>
            <legend className="mb-1.5 text-xs text-muted-foreground">{t("nodes.editor.chart.kind")}</legend>
            <div role="radiogroup" aria-label={t("nodes.editor.chart.kind")} className="flex flex-wrap gap-1">
              {CHART_KINDS.map((kind) => (
                <button
                  key={kind}
                  type="button"
                  role="radio"
                  aria-checked={draft.kind === kind}
                  onClick={() => setKind(kind)}
                  data-testid={`chart-kind-${kind}`}
                  className={cn(
                    "inline-flex h-8 items-center gap-1.5 rounded-md border px-2.5 text-sm [&_svg]:h-4 [&_svg]:w-4",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    draft.kind === kind
                      ? "border-accent bg-secondary text-foreground"
                      : "border-border text-muted-foreground hover:bg-secondary",
                  )}
                >
                  {KIND_ICONS[kind]}
                  {t(`nodes.editor.chart.kinds.${kind}`)}
                </button>
              ))}
            </div>
          </fieldset>
          {canStack(draft.kind) && (
            <label className="flex items-center gap-2 text-sm">
              <Switch
                checked={draft.stacked}
                onCheckedChange={(stacked: boolean) => patch({ stacked })}
                aria-label={t("nodes.editor.chart.stacked")}
                data-testid="chart-stacked"
              />
              {t("nodes.editor.chart.stacked")}
            </label>
          )}
          <div className="grid grid-cols-[minmax(0,1fr)_7rem] gap-2">
            <TextField id={`${ids}-title`} label={t("nodes.editor.chart.title")} value={draft.title} onChange={(title) => patch({ title })} />
            <TextField id={`${ids}-unit`} label={t("nodes.editor.chart.unit")} value={draft.unit} onChange={(unit) => patch({ unit })} placeholder="%, €, h" />
          </div>
          <TextField id={`${ids}-note`} label={t("nodes.editor.chart.note")} value={draft.note} onChange={(note) => patch({ note })} />

          {source && bound ? (
            <SourcePicker source={source} binding={bound} single={round} onChange={setBound} />
          ) : (
            <DataGrid draft={draft} single={round} onChange={setDraft} />
          )}
        </div>

        <div className="flex min-w-0 flex-col gap-3">
          <div className="rounded-lg border border-border bg-background p-3">
            {check.chart ? (
              <ChartPreview chart={check.chart} height={220} />
            ) : (
              <div className="flex h-[220px] items-center justify-center px-6 text-center text-sm text-muted-foreground">
                {t("nodes.editor.chart.preview_empty")}
              </div>
            )}
          </div>
          {slots > 0 && (
            <fieldset>
              <legend className="mb-1.5 text-xs text-muted-foreground">
                {round ? t("nodes.editor.chart.slice_colors") : t("nodes.editor.chart.series_colors")}
              </legend>
              <div className="flex flex-wrap gap-2">
                {Array.from({ length: Math.min(slots, round ? maxLabels("pie") : MAX_SERIES) }, (_, index) => {
                  const name = round ? sourced.labels[index] : sourced.series[index]?.name;
                  return (
                    <span key={index} className="inline-flex items-center gap-1.5 text-sm">
                      <ColorPicker
                        label={t("nodes.editor.chart.color_of").replace("{0}", name || String(index + 1))}
                        value={draft.colors[index] ?? ""}
                        onChange={(colour) =>
                          setDraft((now) => {
                            const colors = [...now.colors];
                            while (colors.length <= index) colors.push("");
                            colors[index] = colour;
                            return { ...now, colors };
                          })
                        }
                      />
                      <span className="max-w-[8rem] truncate text-muted-foreground">{name || index + 1}</span>
                    </span>
                  );
                })}
              </div>
            </fieldset>
          )}
          <ChartErrors errors={check.errors} kind={draft.kind} />
        </div>
      </div>
      <div className="flex justify-end gap-2 border-t border-border pt-4">
        <Button variant="ghost" onClick={onCancel} data-testid="chart-cancel">
          {t("nodes.editor.chart.cancel")}
        </Button>
        <Button onClick={save} disabled={!check.chart} data-testid="chart-save">
          {value ? t("nodes.editor.chart.apply") : t("nodes.editor.chart.insert")}
        </Button>
      </div>
    </div>
  );
}

function TextField({
  id,
  label,
  value,
  onChange,
  placeholder,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
}) {
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <label htmlFor={id} className="text-xs text-muted-foreground">
        {label}
      </label>
      <input
        id={id}
        type="text"
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        className="h-8 min-w-0 rounded-md border border-border-strong bg-input px-2 text-sm text-foreground placeholder:text-foreground-faint focus-visible:border-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      />
    </div>
  );
}

function ChartErrors({ errors, kind }: { errors: ChartErrorCode[]; kind: ChartKind }) {
  const t = useT();
  return (
    <div aria-live="polite" data-testid="chart-errors">
      {errors.length > 0 && (
        <ul className="list-disc space-y-0.5 pl-5 text-sm text-warning">
          {errors.map((code) => (
            <li key={code}>{t(`nodes.editor.chart.errors.${code}`).replace("{0}", String(maxLabels(kind)))}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

/* ---------------------------------------------------------------- grid */

/** Rows of tab-separated cells, as a spreadsheet app puts them on the clipboard. */
export function parseTsv(text: string): string[][] {
  const lines = text.replace(/\r\n?/g, "\n").replace(/\n$/, "").split("\n");
  return lines.map((line) => line.split("\t"));
}

function DataGrid({
  draft,
  single,
  onChange,
}: {
  draft: ChartDraft;
  single: boolean;
  onChange: (update: (draft: ChartDraft) => ChartDraft) => void;
}) {
  const t = useT();
  const limit = maxLabels(draft.kind);
  const grid = useRef<HTMLTableElement>(null);

  const setLabel = (row: number, text: string) =>
    onChange((now) => ({ ...now, labels: now.labels.map((label, index) => (index === row ? text : label)) }));
  const setCell = (slot: number, row: number, text: string) =>
    onChange((now) => ({
      ...now,
      series: now.series.map((series, index) =>
        index === slot ? { ...series, cells: series.cells.map((cell, at) => (at === row ? text : cell)) } : series,
      ),
    }));
  const setName = (slot: number, name: string) =>
    onChange((now) => ({ ...now, series: now.series.map((series, index) => (index === slot ? { ...series, name } : series)) }));
  const addRow = () =>
    onChange((now) => ({
      ...now,
      labels: [...now.labels, ""],
      series: now.series.map((series) => ({ ...series, cells: [...series.cells, ""] })),
    }));
  const removeRow = (row: number) =>
    onChange((now) => ({
      ...now,
      labels: now.labels.filter((_, index) => index !== row),
      series: now.series.map((series) => ({ ...series, cells: series.cells.filter((_, index) => index !== row) })),
    }));
  const addSeries = () =>
    onChange((now) => ({
      ...now,
      series: [
        ...now.series,
        { name: t("nodes.editor.chart.series_name").replace("{0}", String(now.series.length + 1)), cells: now.labels.map(() => "") },
      ],
    }));
  const removeSeries = (slot: number) =>
    onChange((now) => ({
      ...now,
      series: now.series.filter((_, index) => index !== slot),
      colors: isRound(now.kind) ? now.colors : now.colors.filter((_, index) => index !== slot),
    }));

  /* A block pasted into a cell fills the grid from that cell on: column 0
   * is the labels, the next columns the series. Rows and series are added as
   * needed, within the grammar's limits. */
  const onPaste = (event: ClipboardEvent<HTMLInputElement>, row: number, column: number) => {
    const text = event.clipboardData.getData("text/plain");
    if (!text.includes("\t") && !text.includes("\n")) return;
    event.preventDefault();
    const block = parseTsv(text);
    onChange((now) => {
      const labels = [...now.labels];
      const series = now.series.map((entry) => ({ ...entry, cells: [...entry.cells] }));
      const maxSeries = isRound(now.kind) ? 1 : MAX_SERIES;
      block.forEach((cells, offset) => {
        const at = row + offset;
        if (at >= limit) return;
        while (labels.length <= at) {
          labels.push("");
          series.forEach((entry) => entry.cells.push(""));
        }
        cells.forEach((cell, step) => {
          const col = column + step;
          if (col === 0) labels[at] = cell.trim();
          else if (col - 1 < maxSeries) {
            while (series.length < col) series.push({ name: "", cells: labels.map(() => "") });
            series[col - 1].cells[at] = cell.trim();
          }
        });
      });
      return { ...now, labels, series };
    });
  };

  /* Arrow keys and Enter move between cells, the way a grid is expected to behave. */
  const move = (event: React.KeyboardEvent<HTMLInputElement>) => {
    const keys: Record<string, [number, number]> = { ArrowUp: [-1, 0], ArrowDown: [1, 0], Enter: [1, 0] };
    const step = keys[event.key];
    if (!step || event.shiftKey || event.altKey || event.metaKey || event.ctrlKey) return;
    const cell = event.currentTarget;
    const row = Number(cell.dataset.row);
    const col = Number(cell.dataset.col);
    const next = grid.current?.querySelector<HTMLInputElement>(`input[data-row="${row + step[0]}"][data-col="${col}"]`);
    if (next) {
      event.preventDefault();
      next.focus();
      next.select();
    }
  };

  const cellClass =
    "h-8 w-full min-w-[4.5rem] bg-transparent px-2 text-sm tabular-nums text-foreground focus:bg-input focus:outline-none focus:ring-2 focus:ring-inset focus:ring-ring";

  return (
    <fieldset className="min-w-0">
      <legend className="mb-1.5 text-xs text-muted-foreground">{t("nodes.editor.chart.data")}</legend>
      <div className="max-h-72 overflow-auto rounded-md border border-border">
        <table ref={grid} className="w-full border-collapse text-sm" aria-label={t("nodes.editor.chart.data")}>
          <thead className="sticky top-0 z-[1] bg-sidebar">
            <tr>
              <th scope="col" className="border-b border-r border-border px-2 py-1 text-left text-xs font-medium text-muted-foreground">
                {t("nodes.editor.chart.labels")}
              </th>
              {draft.series.map((series, slot) => (
                <th key={slot} scope="col" className="border-b border-r border-border p-0">
                  <div className="flex items-center">
                    <input
                      aria-label={t("nodes.editor.chart.series_name_of").replace("{0}", String(slot + 1))}
                      value={series.name}
                      placeholder={t("nodes.editor.chart.series_name").replace("{0}", String(slot + 1))}
                      onChange={(event) => setName(slot, event.target.value)}
                      className={cn(cellClass, "font-medium")}
                    />
                    {draft.series.length > 1 && (
                      <button
                        type="button"
                        aria-label={t("nodes.editor.chart.remove_series").replace("{0}", series.name || String(slot + 1))}
                        onClick={() => removeSeries(slot)}
                        className="mr-1 rounded p-1 text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      >
                        <X className="h-3.5 w-3.5" aria-hidden />
                      </button>
                    )}
                  </div>
                </th>
              ))}
              <th scope="col" className="w-8 border-b border-border p-0">
                {!single && draft.series.length < MAX_SERIES && (
                  <button
                    type="button"
                    aria-label={t("nodes.editor.chart.add_series")}
                    onClick={addSeries}
                    data-testid="chart-add-series"
                    className="flex h-8 w-8 items-center justify-center text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
                  >
                    <Plus className="h-4 w-4" aria-hidden />
                  </button>
                )}
              </th>
            </tr>
          </thead>
          <tbody>
            {draft.labels.map((label, row) => (
              <tr key={row}>
                <td className="border-b border-r border-border p-0">
                  <input
                    aria-label={t("nodes.editor.chart.label_of").replace("{0}", String(row + 1))}
                    value={label}
                    data-row={row}
                    data-col={0}
                    onChange={(event) => setLabel(row, event.target.value)}
                    onPaste={(event) => onPaste(event, row, 0)}
                    onKeyDown={move}
                    className={cellClass}
                  />
                </td>
                {draft.series.map((series, slot) => (
                  <td key={slot} className="border-b border-r border-border p-0">
                    <input
                      inputMode="decimal"
                      aria-label={t("nodes.editor.chart.value_of")
                        .replace("{0}", series.name || String(slot + 1))
                        .replace("{1}", label || String(row + 1))}
                      value={series.cells[row] ?? ""}
                      data-row={row}
                      data-col={slot + 1}
                      onChange={(event) => setCell(slot, row, event.target.value)}
                      onPaste={(event) => onPaste(event, row, slot + 1)}
                      onKeyDown={move}
                      className={cn(cellClass, "text-right")}
                    />
                  </td>
                ))}
                <td className="border-b border-border p-0">
                  {draft.labels.length > 2 && (
                    <button
                      type="button"
                      aria-label={t("nodes.editor.chart.remove_row").replace("{0}", label || String(row + 1))}
                      onClick={() => removeRow(row)}
                      className="flex h-8 w-8 items-center justify-center text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
                    >
                      <Trash2 className="h-3.5 w-3.5" aria-hidden />
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {draft.labels.length < limit && (
        <Button variant="ghost" size="sm" onClick={addRow} className="mt-1.5" data-testid="chart-add-row">
          <Plus aria-hidden />
          {t("nodes.editor.chart.add_row")}
        </Button>
      )}
      <p className="mt-1 text-xs text-muted-foreground">{t("nodes.editor.chart.paste_hint")}</p>
    </fieldset>
  );
}

/* -------------------------------------------------------------- source */

function SourcePicker({
  source,
  binding,
  single,
  onChange,
}: {
  source: ChartSource;
  binding: ChartBinding;
  single: boolean;
  onChange: (binding: ChartBinding) => void;
}) {
  const t = useT();
  const numeric = source.columns.map((_, index) => isNumericColumn(source, index));
  const options = source.columns.map((column) => ({ value: column.key, label: column.label || column.key }));
  const toggle = (key: string) => {
    const has = binding.series.includes(key);
    let series = has ? binding.series.filter((entry) => entry !== key) : [...binding.series, key];
    if (single) series = has ? [] : [key];
    onChange({ ...binding, series: series.slice(0, MAX_SERIES) });
  };
  return (
    <div className="flex flex-col gap-3">
      <Select
        label={t("nodes.editor.chart.label_column")}
        showLabel
        value={binding.x}
        options={options}
        onChange={(x) => onChange({ x, series: binding.series.filter((key) => key !== x) })}
      />
      <fieldset>
        <legend className="mb-1.5 text-xs text-muted-foreground">
          {single ? t("nodes.editor.chart.value_column") : t("nodes.editor.chart.value_columns")}
        </legend>
        <div className="flex flex-col gap-1">
          {source.columns.map((column, index) =>
            column.key === binding.x ? null : (
              <label key={column.key} className={cn("flex items-center gap-2 text-sm", !numeric[index] && "text-muted-foreground")}>
                <input
                  type={single ? "radio" : "checkbox"}
                  name="chart-source-series"
                  checked={binding.series.includes(column.key)}
                  onChange={() => toggle(column.key)}
                  className="h-4 w-4 accent-[hsl(var(--accent))]"
                />
                {column.label || column.key}
                {!numeric[index] && <span className="text-xs">({t("nodes.editor.chart.not_numbers")})</span>}
              </label>
            ),
          )}
        </div>
      </fieldset>
    </div>
  );
}

/* -------------------------------------------------------------- dialog */

/** The chart editor in a dialog over the editor. */
export function ChartEditor({ open, onCancel, ...panel }: ChartEditorProps) {
  // A fresh draft every time it opens.
  const [session, setSession] = useState(0);
  useEffect(() => {
    if (open) setSession((n) => n + 1);
  }, [open]);
  const t = useT();
  return (
    <Dialog.Root open={open} onOpenChange={(next) => !next && onCancel()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[80] bg-scrim/50 backdrop-blur-[2px] data-[state=open]:animate-in data-[state=open]:fade-in-0" />
        <Dialog.Content
          aria-describedby={undefined}
          data-own-undo=""
          className="fixed left-1/2 top-1/2 z-[90] flex max-h-[min(860px,calc(100vh-2rem))] w-[min(960px,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 flex-col overflow-auto rounded-xl border border-border bg-popover p-5 text-popover-foreground shadow-float data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95"
        >
          <Dialog.Title className="sr-only">
            {panel.heading ?? (panel.value ? t("nodes.editor.chart.edit") : t("nodes.editor.chart.new"))}
          </Dialog.Title>
          <ChartEditorPanel key={session} {...panel} onCancel={onCancel} />
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
