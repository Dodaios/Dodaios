/**
 * The chart grammar in TypeScript: what `parse_chart` in
 * `dodaios/artifacts/report_blocks.py` accepts, and the same refusals.
 *
 * Every node type that holds charts (a doc's fenced `chart` block, a chart
 * slide, a dashboard figure, a sheet's chart) stores this one JSON shape and
 * the server draws it with one renderer. The chart editor builds it and
 * checks it here first, so the person learns what is wrong while editing,
 * not after a save the server refuses or a chart that silently stays a code
 * block. Keep the limits below equal to the Python constants.
 */

export const CHART_KINDS = ["column", "bar", "line", "area", "pie", "donut"] as const;
export type ChartKind = (typeof CHART_KINDS)[number];

export const MAX_SERIES = 6;
export const MAX_POINTS = 366;
export const MAX_BAR_ROWS = 24;
export const MAX_SLICES = 12;
export const MAX_LABEL_CHARS = 40;
export const MAX_TITLE_CHARS = 120;
export const MAX_NAME_CHARS = 60;
export const MAX_NOTE_CHARS = 200;
export const MAX_UNIT_CHARS = 12;
export const MAX_VALUE_CHARS = 40;

/** Kinds whose single series is cut into slices of a whole. */
export function isRound(kind: ChartKind): boolean {
  return kind === "pie" || kind === "donut";
}

/** Kinds that can stack their series. */
export function canStack(kind: ChartKind): boolean {
  return kind === "column" || kind === "bar";
}

export interface ChartSeriesJson {
  name: string;
  /** One value per label; null is a gap (a slice left out of a pie). */
  data: (number | null)[];
}

/** One chart, exactly as `parse_chart` reads it. */
export interface ChartJson {
  type: ChartKind;
  title?: string;
  note?: string;
  unit?: string;
  /** A headline figure drawn above the chart, and its change. */
  value?: string;
  delta?: string;
  /** Column and bar only: the series stacked instead of side by side. */
  stacked?: boolean;
  /** The labels along the axis (the slices of a pie). */
  x: string[];
  series: ChartSeriesJson[];
  /** "#rrggbb" per series (per slice for a pie or donut); "" is the kit's colour for that place. */
  colors?: string[];
}

/** Why a chart cannot be drawn; the editor names each in the person's language. */
export type ChartErrorCode =
  | "not_object"
  | "type"
  | "labels_count"
  | "label_empty"
  | "series_count"
  | "series_length"
  | "value"
  | "series_empty"
  | "series_name"
  | "round_one_series"
  | "round_negative"
  | "round_zero";

export interface ChartCheck {
  /** The chart as the server will read it (texts trimmed and clipped), or null. */
  chart: ChartJson | null;
  errors: ChartErrorCode[];
}

const TYPE_ALIASES: Record<string, ChartKind> = {
  line: "line",
  lines: "line",
  area: "area",
  column: "column",
  columns: "column",
  bar: "bar",
  bars: "bar",
  pie: "pie",
  donut: "donut",
  doughnut: "donut",
};

const NUMBER_RE = /^-?\d+(?:\.\d+)?(?:e[+-]?\d+)?$/i;
const HEX_RE = /^#[0-9a-f]{6}$/i;

/** A text field as the server keeps it: whitespace folded, clipped. */
export function cleanText(value: unknown, limit: number): string {
  if (typeof value === "number" && Number.isFinite(value)) return String(value).slice(0, limit);
  if (typeof value !== "string") return "";
  return value.split(/\s+/).filter(Boolean).join(" ").slice(0, limit);
}

/** A number, null for a gap, or undefined for something that is neither. */
export function readPoint(value: unknown): number | null | undefined {
  if (value === null || value === undefined) return value === null ? null : undefined;
  if (typeof value === "boolean") return undefined;
  if (typeof value === "number") return Number.isFinite(value) ? value : undefined;
  if (typeof value === "string") {
    const text = value.trim();
    if (text === "") return null;
    return NUMBER_RE.test(text) ? Number(text) : undefined;
  }
  return undefined;
}

/** The most labels a kind takes. */
export function maxLabels(kind: ChartKind): number {
  if (isRound(kind)) return MAX_SLICES;
  return kind === "bar" ? MAX_BAR_ROWS : MAX_POINTS;
}

/**
 * Check `raw` the way `parse_chart` does. Returns every problem found (not
 * only the first), and the cleaned chart when there is none.
 */
export function validateChart(raw: unknown): ChartCheck {
  if (raw === null || typeof raw !== "object" || Array.isArray(raw)) return { chart: null, errors: ["not_object"] };
  const source = raw as Record<string, unknown>;
  const errors: ChartErrorCode[] = [];
  const typeText = cleanText(source.type, 20).toLowerCase() || "line";
  const kind = TYPE_ALIASES[typeText];
  if (!kind) return { chart: null, errors: ["type"] };

  const labelsRaw = Array.isArray(source.x) ? source.x : Array.isArray(source.labels) ? source.labels : null;
  const x = (labelsRaw ?? []).map((label) => cleanText(label, MAX_LABEL_CHARS));
  if (labelsRaw === null || x.length < 2 || x.length > maxLabels(kind)) errors.push("labels_count");
  if (x.some((label) => !label)) errors.push("label_empty");

  const title = cleanText(source.title, MAX_TITLE_CHARS);
  const lone = Array.isArray(source.data) ? source.data : Array.isArray(source.values) ? source.values : null;
  let listed: unknown[] = Array.isArray(source.series) ? source.series : lone !== null ? [{ name: title, data: lone }] : [];
  if (listed.length < 1 || listed.length > MAX_SERIES) {
    errors.push("series_count");
    listed = listed.slice(0, MAX_SERIES);
  }
  if (isRound(kind) && listed.length > 1) errors.push("round_one_series");

  const series: ChartSeriesJson[] = [];
  for (const entry of listed) {
    if (entry === null || typeof entry !== "object" || Array.isArray(entry)) {
      errors.push("series_length");
      continue;
    }
    const item = entry as Record<string, unknown>;
    const values = Array.isArray(item.data) ? item.data : Array.isArray(item.values) ? item.values : null;
    if (values === null || values.length !== x.length) {
      if (!errors.includes("series_length")) errors.push("series_length");
      continue;
    }
    const data = values.map(readPoint);
    if (data.some((value) => value === undefined)) {
      if (!errors.includes("value")) errors.push("value");
      continue;
    }
    const numbers = data as (number | null)[];
    if (numbers.every((value) => value === null)) {
      if (!errors.includes("series_empty")) errors.push("series_empty");
      continue;
    }
    series.push({ name: cleanText(item.name, MAX_NAME_CHARS), data: numbers });
  }
  if (series.length > 1 && !series.every((entry) => entry.name)) errors.push("series_name");
  if (isRound(kind) && series.length === 1) {
    const values = series[0].data;
    if (values.some((value) => value !== null && value < 0)) errors.push("round_negative");
    else if (!values.some((value) => value !== null && value > 0)) errors.push("round_zero");
  }
  if (errors.length > 0) return { chart: null, errors };

  const slots = isRound(kind) ? x.length : series.length;
  const colorsRaw = Array.isArray(source.colors) ? source.colors : [];
  const colors = Array.from({ length: slots }, (_, index) => {
    const value = colorsRaw[index];
    return typeof value === "string" && HEX_RE.test(value.trim()) ? value.trim().toUpperCase() : "";
  });
  const note = source.note ?? source.subtitle ?? source.source;
  const chart: ChartJson = {
    type: kind,
    x,
    series,
  };
  if (title) chart.title = title;
  const cleanNote = cleanText(note, MAX_NOTE_CHARS);
  if (cleanNote) chart.note = cleanNote;
  const unit = cleanText(source.unit, MAX_UNIT_CHARS);
  if (unit) chart.unit = unit;
  const value = cleanText(source.value, MAX_VALUE_CHARS);
  if (value) chart.value = value;
  const delta = cleanText(source.delta, MAX_VALUE_CHARS);
  if (delta) chart.delta = delta;
  if (source.stacked === true && canStack(kind)) chart.stacked = true;
  if (colors.some(Boolean)) chart.colors = colors;
  return { chart, errors: [] };
}

/** A small chart to start from when the person makes a new one. */
export function starterChart(kind: ChartKind = "column"): ChartJson {
  return {
    type: kind,
    title: "",
    x: ["Q1", "Q2", "Q3", "Q4"],
    series: [{ name: "Series 1", data: [12, 18, 15, 22] }],
  };
}

/** A column of a sheet range a chart can be made from. */
export interface ChartSourceColumn {
  key: string;
  label: string;
}

/** A table to take a chart from: columns, and rows of cells in column order. */
export interface ChartSource {
  columns: ChartSourceColumn[];
  rows: (string | number | boolean | null)[][];
}

/** Which source columns a chart was taken from: the labels, and one per series. */
export interface ChartBinding {
  x: string;
  series: string[];
}

/** Whether a source column holds numbers (every filled cell reads as one). */
export function isNumericColumn(source: ChartSource, index: number): boolean {
  let filled = 0;
  for (const row of source.rows) {
    const cell = row[index];
    if (cell === null || cell === undefined || cell === "") continue;
    filled += 1;
    if (typeof cell === "boolean" || readPoint(typeof cell === "string" ? cell.replace(/[,\s]/g, "") : cell) === undefined) return false;
  }
  return filled > 0;
}

/** The columns a chart would naturally be made of: the first text column, then the number columns. */
export function guessBinding(source: ChartSource): ChartBinding | null {
  if (source.columns.length === 0) return null;
  const numeric = source.columns.map((_, index) => isNumericColumn(source, index));
  const xIndex = Math.max(0, numeric.findIndex((value) => !value));
  const series = source.columns
    .filter((_, index) => numeric[index] && index !== xIndex)
    .slice(0, MAX_SERIES)
    .map((column) => column.key);
  return { x: source.columns[xIndex].key, series };
}

/** A cell as a chart value: numbers kept, thousands separators dropped, anything else a gap. */
function cellNumber(cell: string | number | boolean | null | undefined): number | null {
  if (typeof cell === "number") return Number.isFinite(cell) ? cell : null;
  if (typeof cell !== "string") return null;
  const value = readPoint(cell.replace(/[,\s]/g, ""));
  return typeof value === "number" ? value : null;
}

/** The chart's labels and series taken from `source` along `binding`, merged into `base`. */
export function chartFromSource(base: ChartJson, source: ChartSource, binding: ChartBinding): ChartJson {
  const at = (key: string) => source.columns.findIndex((column) => column.key === key);
  const xIndex = at(binding.x);
  const limit = maxLabels(base.type);
  const rows = source.rows.slice(0, limit);
  const x = rows.map((row, index) => cleanText(xIndex >= 0 ? row[xIndex] : "", MAX_LABEL_CHARS) || String(index + 1));
  const keys = isRound(base.type) ? binding.series.slice(0, 1) : binding.series.slice(0, MAX_SERIES);
  const series = keys
    .map((key) => ({ key, index: at(key) }))
    .filter((entry) => entry.index >= 0)
    .map(({ index }) => ({
      name: cleanText(source.columns[index].label, MAX_NAME_CHARS),
      data: rows.map((row) => cellNumber(row[index])),
    }));
  return { ...base, x, series };
}
