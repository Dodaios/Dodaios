/**
 * The small chart an answer can carry: a fenced `chart` block holding one
 * JSON object, which the chat draws instead of showing the JSON.
 *
 * The model is told the format in `CHART_GUIDANCE`
 * (dodaios/core/response_style.py); the fence name is pinned to the server's
 * by a parity test (tests/unit/agent_chat/test_response_style.py). Everything here
 * is pure: reading the block, and writing its numbers the way the reader's
 * language writes them. A block that does not hold a drawable chart returns
 * `null` and stays an ordinary code block, so nothing is ever drawn from
 * numbers that do not line up.
 */

/** The fence language of a chart block. */
export const CHART_FENCE = "chart";

export type ChartType = "line" | "area" | "column" | "bar";

export interface ChartSeries {
  name: string;
  /** One value per x label; `null` is a gap. */
  data: (number | null)[];
}

export interface ChartSpec {
  type: ChartType;
  title: string;
  /** A line under the title: the source, the date range. */
  note: string;
  unit: string;
  /** The headline figure and its change, as the model wrote them. */
  value: string;
  delta: string;
  x: string[];
  series: ChartSeries[];
}

/** Six hues stay apart for every reader; a seventh series belongs in a table. */
export const MAX_SERIES = 6;
export const MAX_POINTS = 366;
/** A horizontal bar is one row each; more rows than this is a table. */
export const MAX_BAR_ROWS = 24;
const MAX_SOURCE_CHARS = 60_000;

const TYPE_ALIASES: Record<string, ChartType> = {
  line: "line",
  lines: "line",
  area: "area",
  column: "column",
  columns: "column",
  bar: "bar",
  bars: "bar",
};

function text(value: unknown, limit: number): string {
  if (typeof value !== "string" && typeof value !== "number") return "";
  return String(value).replace(/\s+/g, " ").trim().slice(0, limit);
}

function point(value: unknown): number | null | undefined {
  if (value === null) return null;
  if (typeof value === "number") return Number.isFinite(value) ? value : undefined;
  if (typeof value === "string" && /^-?\d+(?:\.\d+)?(?:e[+-]?\d+)?$/i.test(value.trim())) return Number(value);
  return undefined;
}

/** The chart a fenced block describes, or `null` when it cannot be drawn. */
export function parseChartSpec(code: string): ChartSpec | null {
  if (code.length > MAX_SOURCE_CHARS) return null;
  let raw: unknown;
  try { raw = JSON.parse(code); } catch { return null; } // Still arriving, or not JSON.
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const source = raw as Record<string, unknown>;

  const type = TYPE_ALIASES[text(source.type, 20).toLowerCase() || "line"];
  if (!type) return null;

  const labels = Array.isArray(source.x) ? source.x : Array.isArray(source.labels) ? source.labels : null;
  if (!labels || labels.length < 2 || labels.length > (type === "bar" ? MAX_BAR_ROWS : MAX_POINTS)) return null;
  const x = labels.map(label => text(label, 40));
  if (x.some(label => !label)) return null;

  const title = text(source.title, 120);
  // One list of numbers on the object itself is a chart of one series.
  const lone = Array.isArray(source.data) ? source.data : Array.isArray(source.values) ? source.values : null;
  const listed: unknown[] = Array.isArray(source.series) ? source.series : lone ? [{ name: title, data: lone }] : [];
  if (!listed.length || listed.length > MAX_SERIES) return null;

  const series: ChartSeries[] = [];
  for (const entry of listed) {
    if (!entry || typeof entry !== "object" || Array.isArray(entry)) return null;
    const item = entry as Record<string, unknown>;
    const values = Array.isArray(item.data) ? item.data : Array.isArray(item.values) ? item.values : null;
    // A list of another length would put numbers under the wrong labels.
    if (!values || values.length !== x.length) return null;
    const data = values.map(point);
    if (data.some(value => value === undefined) || !data.some(value => value !== null)) return null;
    series.push({ name: text(item.name, 60), data: data as (number | null)[] });
  }
  // Two or more series are told apart by name.
  if (series.length > 1 && series.some(item => !item.name)) return null;

  return {
    type,
    title,
    note: text(source.note ?? source.subtitle ?? source.source, 200),
    unit: text(source.unit, 12),
    value: text(source.value, 40),
    delta: text(source.delta, 40),
    x,
    series,
  };
}

/** Whether `markdown` ends inside a code fence that is still being written. */
export function endsInOpenFence(markdown: string): boolean {
  let fence: string | null = null;
  for (const line of markdown.split("\n")) {
    const mark = /^ {0,3}(`{3,}|~{3,})(.*)$/.exec(line.replace(/\r$/, ""));
    if (!mark) continue;
    if (!fence) {
      if (!(mark[1][0] === "`" && mark[2].includes("`"))) fence = mark[1];
    } else if (mark[1][0] === fence[0] && mark[1].length >= fence.length && !mark[2].trim()) {
      fence = null;
    }
  }
  return fence !== null;
}

/** Whether a Markdown block (its lines) is a chart fence. */
export function isChartFenceLine(line: string): boolean {
  return new RegExp("^ {0,3}(?:`{3,}|~{3,})[ \\t]*" + CHART_FENCE + "[ \\t]*$", "i").test(line.replace(/\r$/, ""));
}

const UNIT_BEFORE = new Set(["$", "£", "¥", "US$"]);

/** A value with its unit: "$12.50", "4.2%", "142.3 USD". */
export function withUnit(value: string, unit: string): string {
  if (!unit) return value;
  if (UNIT_BEFORE.has(unit)) return value.startsWith("-") ? `-${unit}${value.slice(1)}` : `${unit}${value}`;
  return unit === "%" ? `${value}%` : `${value} ${unit}`;
}

/** A number in full, as the reader's language writes it (tooltip, table). */
export function formatChartValue(value: number, language: string): string {
  const size = Math.abs(value);
  const digits = size >= 1000 ? 0 : size >= 100 ? 1 : size >= 1 ? 2 : 4;
  try {
    return new Intl.NumberFormat(language, { maximumFractionDigits: digits }).format(value);
  } catch { return String(value); } // An unknown language tag.
}

/** A number on an axis: in full under 10,000, compact on an axis that reaches it. */
export function formatChartTick(value: number, language: string, reach: number): string {
  try {
    if (reach >= 10_000) return new Intl.NumberFormat(language, { notation: "compact", maximumFractionDigits: 1 }).format(value);
    return new Intl.NumberFormat(language, { maximumFractionDigits: reach < 10 ? 2 : reach < 100 ? 1 : 0 }).format(value);
  } catch { return String(value); }
}

/** The largest absolute value drawn, which picks the axis style. */
export function chartReach(spec: ChartSpec): number {
  let reach = 0;
  for (const item of spec.series) for (const value of item.data) if (value !== null) reach = Math.max(reach, Math.abs(value));
  return reach;
}

/** -1, 0 or 1 for a change the model wrote as text ("+2.1 %", "-0.4", "−3"). */
export function deltaDirection(delta: string): -1 | 0 | 1 {
  const sign = /^\s*([+\-−–])?\s*[^\d]*(\d[\d.,]*)/.exec(delta);
  if (!sign || !/[1-9]/.test(sign[2])) return 0;
  return sign[1] && sign[1] !== "+" ? -1 : 1;
}
