/**
 * A fenced `chart` block DRAWN: the small chart an answer carries when it
 * rests on a series of numbers (a price over a month, a forecast, a
 * comparison of amounts). The format and its reading live in
 * `@/lib/chartSpec`; the model learns it from `CHART_GUIDANCE`
 * (dodaios/core/response_style.py).
 *
 * The card is the app's own: its surface, its ink, its hairlines, in both
 * themes. Only the marks carry colour, from six fixed hues in a fixed order
 * that stay apart for colour-blind readers (checked against the card surface
 * of each theme; three of the light steps are below 3:1 on white, which is
 * why the Table view exists and is always one click away). Two or more
 * series get a legend; one series needs none, the title names it. Hovering
 * reads every series at that point; nothing is readable ONLY by hovering,
 * because the table holds every number.
 *
 * Every string comes from the model and is written as text, never as markup.
 */
import { useMemo, useState, type ReactElement } from "react";
import { ArrowDownRight, ArrowUpRight } from "lucide-react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { useThemeValue, type Theme } from "@/hooks/useTheme";
import { useT, useUiLanguage } from "@/i18n";
import {
  chartReach,
  deltaDirection,
  formatChartTick,
  formatChartValue,
  withUnit,
  type ChartSpec,
} from "@/lib/chartSpec";
import { cn } from "@/lib/utils";

/** Fixed order, never cycled: the order is what keeps neighbours apart. */
export const SERIES_COLORS: Record<Theme, readonly string[]> = {
  light: ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"],
  dark: ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300"],
};

const AXIS_TINT = "hsl(var(--muted-foreground))";
const GRID_TINT = "hsl(var(--foreground) / 0.08)";
const SURFACE = "hsl(var(--card))";
const TICK = { fill: AXIS_TINT, fontSize: 11 } as const;

const PLOT_HEIGHT = 208;
const CARD = "not-prose my-3 w-[34rem] max-w-full overflow-hidden rounded-xl border border-border bg-card text-left text-foreground";

type Row = { x: string } & Record<string, string | number | null>;

function seriesKey(index: number): string {
  return `s${index}`;
}

function clip(label: string, limit: number): string {
  return label.length > limit ? `${label.slice(0, limit - 1).trimEnd()}…` : label;
}

/** The mark's key beside a name: a stroke for a line, a square for a bar. */
function Key({ color, line }: { color: string; line: boolean }) {
  return (
    <span
      aria-hidden
      className={cn("shrink-0", line ? "h-0.5 w-3 rounded-full" : "h-2 w-2 rounded-[2px]")}
      style={{ background: color }}
    />
  );
}

interface TooltipItem {
  dataKey?: string | number;
  value?: number | string | null;
}

function ChartTooltip({
  spec,
  colors,
  language,
  active,
  payload,
  label,
}: {
  spec: ChartSpec;
  colors: readonly string[];
  language: string;
  active?: boolean;
  payload?: TooltipItem[];
  label?: string | number;
}) {
  if (!active || !payload?.length) return null;
  const line = spec.type === "line" || spec.type === "area";
  const lone = spec.series.length === 1;
  return (
    <div className="max-w-[260px] rounded-md border border-border bg-popover px-2.5 py-2 text-[11px] text-popover-foreground shadow-float">
      <div className="mb-1 text-muted-foreground">{String(label ?? "")}</div>
      {spec.series.map((item, index) => {
        const value = payload.find(entry => entry.dataKey === seriesKey(index))?.value;
        if (typeof value !== "number") return null;
        return (
          <div key={index} className="flex items-center gap-2 py-0.5">
            <Key color={colors[index]} line={line} />
            {/* The value leads: the reader has the series and wants the number. */}
            <span className="font-semibold tabular-nums text-foreground">
              {withUnit(formatChartValue(value, language), spec.unit)}
            </span>
            {lone ? null : <span className="min-w-0 truncate text-muted-foreground">{item.name}</span>}
          </div>
        );
      })}
    </div>
  );
}

function ChartTable({ spec, language }: { spec: ChartSpec; language: string }) {
  return (
    <div className="max-h-72 overflow-auto px-4 pb-3 pt-2" data-testid="chart-fence-table">
      <table className="w-full border-collapse text-xs">
        <thead>
          <tr className="text-muted-foreground">
            <th scope="col" className="border-b border-border py-1 pr-3 text-left font-medium" />
            {spec.series.map((item, index) => (
              <th key={index} scope="col" className="border-b border-border py-1 pl-3 text-right font-medium">
                {item.name || spec.unit || spec.title}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {spec.x.map((label, row) => (
            <tr key={row}>
              <th scope="row" className="border-b border-border/50 py-1 pr-3 text-left font-normal text-foreground">
                {label}
              </th>
              {spec.series.map((item, index) => {
                const value = item.data[row];
                return (
                  <td key={index} className="border-b border-border/50 py-1 pl-3 text-right tabular-nums text-foreground">
                    {value === null ? "–" : withUnit(formatChartValue(value, language), spec.unit)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ChartPlot({ spec, language }: { spec: ChartSpec; language: string }) {
  const theme = useThemeValue();
  const colors = SERIES_COLORS[theme];
  const reach = useMemo(() => chartReach(spec), [spec]);
  const data = useMemo<Row[]>(
    () =>
      spec.x.map((label, row) => {
        const point: Row = { x: label };
        spec.series.forEach((item, index) => { point[seriesKey(index)] = item.data[row]; });
        return point;
      }),
    [spec],
  );
  const tick = (value: number) => formatChartTick(value, language, reach);
  const tooltip = <ChartTooltip spec={spec} colors={colors} language={language} />;
  const lone = spec.series.length === 1;

  if (spec.type === "bar") {
    // One row per named thing; the names sit on the left, in full where they fit.
    const thickness = lone ? 14 : 10;
    const row = spec.series.length * (thickness + 2) + 12;
    const longest = Math.max(...spec.x.map(label => Math.min(label.length, 24)));
    const height = spec.x.length * row + 28;
    return (
      <div style={{ height }} className="w-full" data-testid="chart-fence-plot">
        <ResponsiveContainer width="100%" height="100%" minWidth={0} initialDimension={{ width: 520, height }}>
          <BarChart data={data} layout="vertical" margin={{ top: 2, right: 16, bottom: 0, left: 4 }} barGap={2} barCategoryGap={6}>
            <CartesianGrid horizontal={false} stroke={GRID_TINT} />
            <XAxis type="number" tick={TICK} tickFormatter={tick} axisLine={false} tickLine={false} />
            <YAxis
              type="category"
              dataKey="x"
              width={Math.max(40, Math.round(longest * 6.8) + 12)}
              tick={TICK}
              tickFormatter={(label: string) => clip(String(label), 24)}
              axisLine={false}
              tickLine={false}
              interval={0}
            />
            <Tooltip isAnimationActive={false} cursor={{ fill: "hsl(var(--foreground) / 0.06)" }} content={tooltip} />
            {spec.series.map((_item, index) => (
              <Bar
                key={index}
                dataKey={seriesKey(index)}
                fill={colors[index]}
                barSize={thickness}
                radius={[0, 4, 4, 0]}
                isAnimationActive={false}
              />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
    );
  }

  const frame = { data, margin: { top: 8, right: 14, bottom: 0, left: 0 } };
  const axes = (
    <>
      <CartesianGrid vertical={false} stroke={GRID_TINT} />
      <XAxis
        dataKey="x"
        tick={TICK}
        axisLine={false}
        tickLine={false}
        interval="preserveStartEnd"
        minTickGap={28}
        dy={4}
        padding={spec.type === "column" ? undefined : { left: 6, right: 6 }}
      />
      <YAxis
        width={46}
        tick={TICK}
        tickFormatter={tick}
        axisLine={false}
        tickLine={false}
        // A price that moves between 140 and 150 is unreadable from zero; a
        // bar's length IS its value, so bars always start at zero.
        domain={spec.type === "column" ? undefined : ["auto", "auto"]}
      />
    </>
  );
  const container = (chart: ReactElement) => (
    <div style={{ height: PLOT_HEIGHT }} className="w-full" data-testid="chart-fence-plot">
      <ResponsiveContainer width="100%" height="100%" minWidth={0} initialDimension={{ width: 520, height: PLOT_HEIGHT }}>
        {chart}
      </ResponsiveContainer>
    </div>
  );

  if (spec.type === "column") {
    return container(
      <BarChart {...frame} barGap={2} barCategoryGap="22%">
        {axes}
        <Tooltip isAnimationActive={false} cursor={{ fill: "hsl(var(--foreground) / 0.06)" }} content={tooltip} />
        {spec.series.map((_item, index) => (
          <Bar
            key={index}
            dataKey={seriesKey(index)}
            fill={colors[index]}
            maxBarSize={24}
            radius={[4, 4, 0, 0]}
            isAnimationActive={false}
          />
        ))}
      </BarChart>,
    );
  }

  const cursor = { stroke: "hsl(var(--foreground) / 0.35)", strokeWidth: 1 };
  // A single line ends in a dot, where the eye looks for "now".
  const lastPoint = lone ? spec.series[0].data.reduce<number>((last, value, row) => (value === null ? last : row), -1) : -1;
  const endDot = (color: string) => (props: { cx?: number; cy?: number; index?: number }) =>
    props.index === lastPoint && typeof props.cx === "number" && typeof props.cy === "number"
      ? <circle key={props.index} cx={props.cx} cy={props.cy} r={4} fill={color} stroke={SURFACE} strokeWidth={2} />
      : <g key={props.index} />;
  const active = { r: 4, stroke: SURFACE, strokeWidth: 2 };

  if (spec.type === "area") {
    return container(
      <AreaChart {...frame}>
        {axes}
        <Tooltip isAnimationActive={false} cursor={cursor} content={tooltip} />
        {spec.series.map((_item, index) => (
          <Area
            key={index}
            dataKey={seriesKey(index)}
            type="linear"
            stroke={colors[index]}
            strokeWidth={2}
            strokeLinejoin="round"
            strokeLinecap="round"
            fill={colors[index]}
            fillOpacity={0.1}
            dot={lone ? endDot(colors[index]) : false}
            activeDot={active}
            isAnimationActive={false}
          />
        ))}
      </AreaChart>,
    );
  }
  return container(
    <LineChart {...frame}>
      {axes}
      <Tooltip isAnimationActive={false} cursor={cursor} content={tooltip} />
      {spec.series.map((_item, index) => (
        <Line
          key={index}
          dataKey={seriesKey(index)}
          type="linear"
          stroke={colors[index]}
          strokeWidth={2}
          strokeLinejoin="round"
          strokeLinecap="round"
          dot={lone ? endDot(colors[index]) : false}
          activeDot={active}
          isAnimationActive={false}
        />
      ))}
    </LineChart>,
  );
}

export function ChartFence({ spec }: { spec: ChartSpec }) {
  const t = useT();
  const language = useUiLanguage();
  const theme = useThemeValue();
  const [view, setView] = useState<"chart" | "table">("chart");
  const colors = SERIES_COLORS[theme];
  const line = spec.type === "line" || spec.type === "area";
  const direction = deltaDirection(spec.delta);
  const caption = [spec.unit, spec.note].filter(Boolean).join(" · ");

  const segment = (value: "chart" | "table", label: string) => (
    <button
      type="button"
      aria-pressed={view === value}
      onClick={() => setView(value)}
      className={cn(
        "rounded-sm px-2 py-0.5 text-micro font-medium transition-colors",
        view === value ? "bg-background text-foreground" : "text-muted-foreground hover:text-foreground",
      )}
    >
      {label}
    </button>
  );

  return (
    <figure className={CARD} data-testid="chart-fence" data-chart-type={spec.type} data-view={view}>
      <figcaption className="flex items-start justify-between gap-3 px-4 pt-3">
        <div className="min-w-0">
          {spec.title ? <div className="text-sm font-medium leading-5 text-foreground">{spec.title}</div> : null}
          {caption ? <div className="text-xs leading-4 text-muted-foreground">{caption}</div> : null}
        </div>
        <div role="group" className="inline-flex shrink-0 rounded border border-border/60 bg-muted/40 p-0.5">
          {segment("chart", t("outputs_view.chart_view"))}
          {segment("table", t("outputs_view.chart_table"))}
        </div>
      </figcaption>
      {spec.value ? (
        <div className="flex flex-wrap items-baseline gap-x-2 px-4 pt-1.5">
          <span className="text-2xl font-semibold leading-8 text-foreground">{spec.value}</span>
          {spec.delta ? (
            // Up is not always good (a price, a fever), so the change keeps the ink colour.
            <span className="inline-flex items-center gap-0.5 text-sm text-muted-foreground" data-testid="chart-fence-delta">
              {direction > 0 ? <ArrowUpRight className="h-3.5 w-3.5" aria-hidden /> : null}
              {direction < 0 ? <ArrowDownRight className="h-3.5 w-3.5" aria-hidden /> : null}
              {spec.delta}
            </span>
          ) : null}
        </div>
      ) : null}
      {view === "table" ? (
        <ChartTable spec={spec} language={language} />
      ) : (
        <>
          {spec.series.length > 1 ? (
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 pt-2" data-testid="chart-fence-legend">
              {spec.series.map((item, index) => (
                <span key={index} className="flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground">
                  <Key color={colors[index]} line={line} />
                  <span className="truncate">{item.name}</span>
                </span>
              ))}
            </div>
          ) : null}
          <div className="px-2 pb-3 pt-2">
            <ChartPlot spec={spec} language={language} />
          </div>
        </>
      )}
    </figure>
  );
}

/** The chart's place while its block is still being written. */
export function ChartFencePending() {
  const t = useT();
  return (
    <figure className={CARD} data-testid="chart-fence-pending" role="status" aria-label={t("outputs_view.chart_pending")}>
      <div className="flex items-end gap-2 px-4 pb-4 pt-5" style={{ height: PLOT_HEIGHT }}>
        {[34, 46, 40, 58, 52, 66, 60, 74, 68, 82].map((height, index) => (
          <div key={index} className="flex-1 animate-pulse rounded-sm bg-foreground/10" style={{ height: `${height}%` }} />
        ))}
      </div>
    </figure>
  );
}
