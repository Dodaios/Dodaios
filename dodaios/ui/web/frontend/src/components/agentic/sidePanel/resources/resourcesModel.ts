import type {
  ResourceAgent,
  ResourceGroupKey,
  ResourceHistory,
  ResourceLoad,
} from "@/lib/resourcesApi";

/** What the view is looking at: every chart, bar and sort order follows it. */
export type Metric = "cpu" | "memory" | "gpu";

export const METRICS: readonly Metric[] = ["cpu", "memory", "gpu"];

/**
 * The four owners of load, in stacking order from the baseline up. Each keeps
 * its colour whatever the others do; "everything else" is neutral on purpose,
 * it is the remainder and not a series to follow.
 */
export const GROUPS: readonly { key: ResourceGroupKey; color: string }[] = [
  { key: "agents", color: "var(--rs-agents)" },
  { key: "linked", color: "var(--rs-linked)" },
  { key: "app", color: "var(--rs-app)" },
  { key: "other", color: "var(--rs-other)" },
];

/** The least a chart's time axis covers, so two early samples are not a cliff. */
const MIN_SPAN_S = 10;

/** A row by its history id and the name it is shown under. */
export interface NamedRow {
  id: string;
  label: string;
}

/** One contributor to a group at one moment, as percent of the machine. */
export interface SharePart extends NamedRow {
  value: number;
}

/**
 * How many seconds the history covers right now. The charts span exactly
 * this, so they are full from the first samples on and reach back further
 * as more are measured.
 */
export function historySpan(t: readonly number[]): number {
  if (t.length < 2) return MIN_SPAN_S;
  return Math.max(MIN_SPAN_S, t[t.length - 1] - t[0]);
}

/** Axis ticks for a span ending at `end`: a handful, on round steps back from now. */
export function axisTicks(end: number, span: number): number[] {
  const step = [10, 15, 30, 60].find((candidate) => span / candidate <= 5) ?? 60;
  const ticks: number[] = [];
  for (let ago = 0; ago <= span + 0.5; ago += step) ticks.unshift(end - ago);
  return ticks;
}

/**
 * What "everything else" was made of at one sample: its largest rows, as
 * percent of the machine. A row's line is shorter than the series and ends
 * with it, so the sample is counted back from the end.
 */
export function elseAt(
  history: ResourceHistory,
  rows: readonly NamedRow[],
  index: number,
  metric: Metric,
  memoryTotalMb: number,
  limit = 3,
): SharePart[] {
  if (index < 0) return [];
  const fromEnd = history.t.length - 1 - index;
  const parts: SharePart[] = [];
  for (const row of rows) {
    const line = history.rows[row.id]?.[metric];
    const raw = line ? line[line.length - 1 - fromEnd] : undefined;
    if (raw === null || raw === undefined) continue;
    const value = metric === "memory" ? (memoryTotalMb > 0 ? (raw / memoryTotalMb) * 100 : 0) : raw;
    if (value >= 0.1) parts.push({ ...row, value });
  }
  return parts.sort((a, b) => b.value - a.value).slice(0, limit);
}

/** Row ids the server uses for this app and for the operating system. */
export const SELF_ROW = "self";
export const SYSTEM_ROW = "system";

export interface ChartPoint {
  t: number;
  agents: number;
  linked: number;
  app: number;
  other: number;
  total: number;
}

/** "843 MB", "1.2 GB": the unit a person would say out loud. */
export function formatMemory(mb: number, locale: string): string {
  const value = Math.max(0, mb);
  if (value >= 1024) {
    const gb = value / 1024;
    return `${gb.toLocaleString(locale, { maximumFractionDigits: gb >= 100 ? 0 : 1 })} GB`;
  }
  return `${Math.round(value).toLocaleString(locale)} MB`;
}

/** One decimal below ten, none above: 0.4 %, 9.5 %, 37 %. */
export function formatPercent(value: number, locale: string): string {
  const clamped = Math.max(0, value);
  const digits = clamped > 0 && clamped < 10 ? 1 : 0;
  return `${clamped.toLocaleString(locale, { minimumFractionDigits: digits, maximumFractionDigits: digits })} %`;
}

/** The figure a row is ranked and drawn by under each metric. */
export function metricValue(load: ResourceLoad, metric: Metric): number {
  if (metric === "cpu") return load.cpu_percent;
  if (metric === "memory") return load.memory_mb;
  return load.gpu_memory_mb + load.gpu_percent * 1000;
}

/** Heaviest first under the chosen metric; ties keep the server's order. */
export function sortByMetric<T extends ResourceLoad>(rows: readonly T[], metric: Metric): T[] {
  return rows
    .map((row, index) => ({ row, index }))
    .sort((a, b) => metricValue(b.row, metric) - metricValue(a.row, metric) || a.index - b.index)
    .map((item) => item.row);
}

/** Samples the processor ranking looks back over: half a minute at one every two seconds. */
const RANK_SAMPLES = 15;

/**
 * Rows (agents, or apps) in the order a list shows them: heaviest first, but
 * by a figure that holds still.
 *
 * Processor load jumps from sample to sample, and a list sorted by the latest
 * one reshuffles every two seconds: the row under the pointer is another row
 * by the time it is clicked. So the processor ranking is the mean of the last
 * half minute. Memory moves slowly enough to rank as it stands.
 */
export function rankRows<T extends ResourceLoad & { id: string }>(rows: readonly T[], history: ResourceHistory, metric: Metric): T[] {
  if (metric !== "cpu") return sortByMetric(rows, metric);
  const steady = (row: T) => {
    const recent = (history.rows[row.id]?.cpu ?? []).slice(-RANK_SAMPLES).filter((value): value is number => value !== null);
    return recent.length > 0 ? recent.reduce((sum, value) => sum + value, 0) / recent.length : row.cpu_percent;
  };
  return rows
    .map((row, index) => ({ row, index, value: steady(row) }))
    .sort((a, b) => b.value - a.value || b.row.memory_mb - a.row.memory_mb || a.index - b.index)
    .map((item) => item.row);
}

/** One row's own line under a metric; empty where the server sent none. */
export function rowLine(history: ResourceHistory, id: string, metric: Metric): readonly (number | null)[] {
  return history.rows[id]?.[metric] ?? [];
}

/** The stacked series of one metric as chart rows; the card's load has one series. */
export function chartPoints(history: ResourceHistory, metric: Metric): ChartPoint[] {
  const series = (key: string) => history.series[key] ?? [];
  if (metric === "gpu") {
    const load = series("gpu");
    return history.t.map((t, index) => {
      const value = load[index] ?? 0;
      return { t, agents: value, linked: 0, app: 0, other: 0, total: value };
    });
  }
  const parts = GROUPS.map((group) => series(`${metric}.${group.key}`));
  const total = series(metric);
  return history.t.map((t, index) => ({
    t,
    agents: parts[0][index] ?? 0,
    linked: parts[1][index] ?? 0,
    app: parts[2][index] ?? 0,
    other: parts[3][index] ?? 0,
    total: total[index] ?? 0,
  }));
}

interface PathOptions {
  /** Fixes the top of the scale; without it the line fills the box. */
  ceiling?: number;
  /** The least the top of the scale may be, so a flat idle series stays flat. */
  floor?: number;
  /** Samples a full window holds, so a short history sits at the right edge. */
  slots?: number;
}

function pathPoints(values: readonly (number | null)[], width: number, height: number, options: PathOptions): [number, number][] {
  const slots = Math.max(2, options.slots ?? values.length);
  const offset = slots - values.length;
  const present = values.filter((value): value is number => value !== null);
  if (present.length === 0) return [];
  const top = options.ceiling ?? Math.max(options.floor ?? 0, ...present);
  const scale = top > 0 ? top : 1;
  const points: [number, number][] = [];
  values.forEach((value, index) => {
    if (value === null) return;
    points.push([((index + offset) / (slots - 1)) * width, height - 1 - (Math.min(value, scale) / scale) * (height - 2)]);
  });
  return points;
}

/**
 * An SVG path through a series, left to right, on a box of the given size.
 * Leading nulls (the time before a row existed) are skipped, so its line
 * starts where it started.
 */
export function sparkPath(values: readonly (number | null)[], width: number, height: number, options: PathOptions = {}): string {
  const points = pathPoints(values, width, height, options);
  if (points.length === 0) return "";
  if (points.length === 1) points.push(points[0]);
  return points.map(([x, y], index) => `${index === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
}

/** The same line, and the area under it down to the baseline. */
export function areaPath(values: readonly (number | null)[], width: number, height: number, options: PathOptions = {}): { line: string; area: string } {
  const line = sparkPath(values, width, height, options);
  const points = pathPoints(values, width, height, options);
  if (points.length === 0) return { line: "", area: "" };
  const first = points[0][0].toFixed(1);
  const last = points[points.length - 1][0].toFixed(1);
  return { line, area: `${line} L${last} ${height} L${first} ${height} Z` };
}

/** What an agent row is called: its pane or thread name, else the CLI's. */
export function agentTitle(agent: ResourceAgent, untitledThread: string): string {
  if (agent.kind === "pane") return agent.detail ? `${agent.label} · ${agent.detail}` : agent.label;
  if (agent.kind === "thread") return agent.label || untitledThread;
  return agent.label || agent.agent_label || agent.agent;
}

/** Longest value of a list under a metric, for bars drawn relative to it. */
export function largest(rows: readonly ResourceLoad[], metric: Metric): number {
  return rows.reduce((max, row) => Math.max(max, metricValue(row, metric)), 0);
}
