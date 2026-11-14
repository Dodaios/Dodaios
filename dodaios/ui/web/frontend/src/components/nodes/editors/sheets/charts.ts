/**
 * A sheet's charts between the stored spec and the shared chart editor.
 *
 * A chart made from the grid is stored BOUND to the sheet: the column that
 * labels the points, the columns it plots and the rows it covers, not the
 * numbers themselves (see the chart notes in `dodaios/nodes/kinds/sheets.py`).
 * So a chart follows its cells as the person keeps editing. The chart editor
 * (`../charts/ChartEditor`) works on literal charts and a source table; these
 * helpers turn a selection into that source, a stored chart into the literal
 * chart the editor and the preview draw, and the editor's answer back into a
 * stored chart.
 */
import type { ChartBinding, ChartJson, ChartSource } from "../charts/chartModel";
import { maxLabels } from "../charts/chartModel";
import { isNumber, textOf, type BoundSeries, type Row, type Sheet, type SheetChart } from "./model";

export function isBound(chart: SheetChart): boolean {
  return typeof chart.x === "string" || chart.series.some((entry) => "column" in entry);
}

function label(value: Row[string] | undefined, position: number): string {
  let text: string;
  if (typeof value === "boolean") text = value ? "✓" : "–";
  else if (isNumber(value)) text = String(value);
  else text = textOf(value).split(/\s+/).filter(Boolean).join(" ");
  return text.slice(0, 40) || String(position);
}

/**
 * The literal chart a stored one draws: a bound chart reads its labels and
 * numbers from `computed` (the sheet's rows with formula cells filled), the
 * way `drawn_chart` in `sheets.py` does for the page.
 */
export function drawnChart(chart: SheetChart, sheet: Sheet, computed: readonly Row[]): ChartJson {
  if (!isBound(chart)) return chart as unknown as ChartJson;
  let first = 1;
  let last = computed.length;
  if (chart.rows) {
    first = Math.max(1, chart.rows[0]);
    last = Math.min(computed.length, chart.rows[1]);
  }
  const numbered = computed.slice(first - 1, Math.max(first - 1, last)).map((row, i) => [first + i, row] as const);
  const labels = new Map(sheet.columns.map((column) => [column.key, column.label]));
  const xKey = typeof chart.x === "string" ? chart.x : "";
  const { rows: _rows, x: _x, series: _series, ...look } = chart;
  return {
    ...(look as Omit<ChartJson, "x" | "series">),
    x: numbered.map(([n, row]) => label(xKey ? row[xKey] : undefined, n)),
    series: chart.series
      .filter((entry): entry is BoundSeries => "column" in entry)
      .map((entry) => ({
        name: entry.name || labels.get(entry.column) || "",
        data: numbered.map(([, row]) => {
          const value = row[entry.column];
          return isNumber(value) ? value : null;
        }),
      })),
  } as ChartJson;
}

/** The binding a stored chart was made with, to reopen the chart editor on the same columns. */
export function bindingOf(chart: SheetChart): ChartBinding | null {
  if (!isBound(chart)) return null;
  return {
    x: typeof chart.x === "string" ? chart.x : "",
    series: chart.series.filter((entry): entry is BoundSeries => "column" in entry).map((entry) => entry.column),
  };
}

/**
 * The table the chart editor takes a chart from: the selected columns (all
 * of them when a single cell is selected) over the selected rows (all rows
 * when the selection is one row or less). `rows` are stored row indices.
 */
export function chartSource(
  sheet: Sheet,
  computed: readonly Row[],
  columns: readonly number[],
  rows: readonly number[],
): ChartSource {
  const keys = columns.map((index) => sheet.columns[index]).filter(Boolean);
  return {
    columns: keys.map((column) => ({ key: column.key, label: column.label })),
    rows: rows
      .filter((row) => row < computed.length)
      .map((row) =>
        keys.map((column) => {
          const value = computed[row][column.key];
          if (value === undefined) return null;
          if (typeof value === "object") return textOf(value);
          return value;
        }),
      ),
  };
}

/**
 * The stored chart from the chart editor's answer. With a binding the chart
 * keeps only its look and names columns; its rows are the source's (clipped
 * to what the chart type can draw, as the editor's preview did).
 */
export function storedChart(
  chart: ChartJson,
  binding: ChartBinding | null,
  sheet: Sheet,
  rowRange: [number, number] | null,
): SheetChart {
  const { x, series, ...look } = chart;
  const kept: Record<string, unknown> = {};
  for (const [field, value] of Object.entries(look)) {
    if (value === undefined || value === "" || value === false) continue;
    if (Array.isArray(value) && !value.some(Boolean)) continue;
    kept[field] = value;
  }
  if (!binding || !binding.series.length) {
    return { ...kept, type: chart.type, x: [...x], series: series.map((s) => ({ name: s.name, data: [...s.data] })) } as SheetChart;
  }
  const labels = new Map(sheet.columns.map((column) => [column.key, column.label]));
  const bound: BoundSeries[] = binding.series
    .filter((key) => labels.has(key))
    .map((key, index) => {
      const name = series[index]?.name ?? "";
      return name && name !== labels.get(key) ? { column: key, name } : { column: key };
    });
  const stored: SheetChart = { ...(kept as Partial<SheetChart>), type: chart.type, series: bound };
  if (binding.x && labels.has(binding.x)) stored.x = binding.x;
  if (rowRange) {
    const [first, last] = rowRange;
    stored.rows = [first, Math.min(last, first + maxLabels(chart.type) - 1)];
  }
  return stored;
}
