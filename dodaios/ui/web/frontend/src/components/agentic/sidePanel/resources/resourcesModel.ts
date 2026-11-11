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

/** How far back the charts reach, in seconds. */
export const WINDOW_S = 300;

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
 * Agents in the order the list shows them: heaviest first, but by a figure
 * that holds still.
 *
 * Processor load jumps from sample to sample, and a list sorted by the latest
 * one reshuffles every two seconds: the row under the pointer is another row
 * by the time it is clicked. So the processor ranking is the mean of the last
 * half minute. Memory moves slowly enough to rank as it stands.
 */
export function rankAgents(agents: readonly ResourceAgent[], history: ResourceHistory, metric: Metric): ResourceAgent[] {
  if (metric !== "cpu") return sortByMetric(agents, metric);
  const steady = (agent: ResourceAgent) => {
    const recent = (history.agents[agent.id]?.cpu ?? []).slice(-RANK_SAMPLES).filter((value): value is number => value !== null);
    return recent.length > 0 ? recent.reduce((sum, value) => sum + value, 0) / recent.length : agent.cpu_percent;
  };
  return agents
    .map((agent, index) => ({ agent, index, value: steady(agent) }))
    .sort((a, b) => b.value - a.value || b.agent.memory_mb - a.agent.memory_mb || a.index - b.index)
    .map((item) => item.agent);
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

/**
 * An SVG path through a series, left to right, on a box of the given size.
 *
 * Leading nulls (the time before an agent existed) are skipped, so its line
 * starts where it started. ``ceiling`` fixes the top of the scale; without it
 * the line fills the box, with a floor so a flat idle series stays flat
 * instead of being stretched into noise.
 */
export function sparkPath(
  values: readonly (number | null)[],
  width: number,
  height: number,
  options: { ceiling?: number; floor?: number; slots?: number } = {},
): string {
  const slots = Math.max(2, options.slots ?? values.length);
  const offset = slots - values.length;
  const present = values.filter((value): value is number => value !== null);
  if (present.length === 0) return "";
  const top = options.ceiling ?? Math.max(options.floor ?? 0, ...present);
  const scale = top > 0 ? top : 1;
  const points: string[] = [];
  values.forEach((value, index) => {
    if (value === null) return;
    const x = ((index + offset) / (slots - 1)) * width;
    const y = height - 1 - (Math.min(value, scale) / scale) * (height - 2);
    points.push(`${points.length === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`);
  });
  if (points.length === 1) points.push(points[0].replace("M", "L"));
  return points.join(" ");
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
