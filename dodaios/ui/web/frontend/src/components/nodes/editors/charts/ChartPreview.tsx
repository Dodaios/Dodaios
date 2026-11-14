/**
 * One chart of the report grammar drawn natively, with recharts.
 *
 * The page a node renders draws its charts on the server (one renderer for
 * every type); this is the in-app twin for editors, so a chart can be seen
 * while it is being made without a round trip. It follows the same reading
 * rules: one series of columns marks nothing extra, stacked series share a
 * bar, a pie or donut cuts its one series into slices, and the kit's series
 * colours apply in slot order unless the chart names its own.
 */
import { useMemo } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { KIT_COLORS } from "../controls";
import { isRound, type ChartJson } from "./chartModel";

/** The kit's six series colours, in slot order. */
export const SERIES_COLORS: readonly string[] = KIT_COLORS.slice(0, 6);

/** The colour of slot `index`: the chart's own, or the kit's. */
export function slotColor(chart: Pick<ChartJson, "colors">, index: number): string {
  return chart.colors?.[index] || SERIES_COLORS[index % SERIES_COLORS.length];
}

function formatValue(value: unknown, unit: string | undefined): string {
  if (typeof value !== "number") return "–";
  const text = value.toLocaleString(undefined, { maximumFractionDigits: 2 });
  if (!unit) return text;
  if (["$", "£", "¥", "US$", "€"].includes(unit)) return `${unit}${text}`;
  return unit === "%" ? `${text}%` : `${text} ${unit}`;
}

export interface ChartPreviewProps {
  chart: ChartJson;
  /** Height in pixels (the width follows the container). */
  height?: number;
  className?: string;
}

export function ChartPreview({ chart, height = 240, className }: ChartPreviewProps) {
  const rows = useMemo(
    () =>
      chart.x.map((label, index) => {
        const row: Record<string, string | number | null> = { label };
        chart.series.forEach((series, slot) => {
          row[`s${slot}`] = series.data[index] ?? null;
        });
        return row;
      }),
    [chart],
  );
  const described = chart.title || chart.series.map((series) => series.name).filter(Boolean).join(", ");
  const tooltip = (
    <Tooltip
      formatter={(value) => formatValue(value, chart.unit)}
      contentStyle={{
        background: "hsl(var(--popover))",
        border: "1px solid hsl(var(--border))",
        borderRadius: 8,
        color: "hsl(var(--popover-foreground))",
        fontSize: 12,
      }}
    />
  );
  const axisTick = { fill: "hsl(var(--muted-foreground))", fontSize: 11 };
  const many = chart.series.length > 1;
  const name = (slot: number) => chart.series[slot]?.name || chart.title || `${slot + 1}`;

  let body: JSX.Element;
  if (isRound(chart.type)) {
    const slices = chart.x
      .map((label, index) => ({ label, value: chart.series[0]?.data[index] ?? null, index }))
      .filter((slice) => slice.value !== null && slice.value > 0);
    body = (
      <PieChart>
        {tooltip}
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Pie
          data={slices}
          dataKey="value"
          nameKey="label"
          innerRadius={chart.type === "donut" ? "55%" : 0}
          outerRadius="80%"
          stroke="hsl(var(--background))"
          strokeWidth={2}
          isAnimationActive={false}
        >
          {slices.map((slice) => (
            <Cell key={slice.index} fill={slotColor(chart, slice.index)} />
          ))}
        </Pie>
      </PieChart>
    );
  } else if (chart.type === "line" || chart.type === "area") {
    const Chart = chart.type === "area" ? AreaChart : LineChart;
    body = (
      <Chart data={rows} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
        <CartesianGrid stroke="hsl(var(--border))" vertical={false} />
        <XAxis dataKey="label" tick={axisTick} tickLine={false} axisLine={false} />
        <YAxis tick={axisTick} tickLine={false} axisLine={false} width={44} />
        {tooltip}
        {many && <Legend wrapperStyle={{ fontSize: 12 }} />}
        {chart.series.map((_, slot) =>
          chart.type === "area" ? (
            <Area
              key={slot}
              dataKey={`s${slot}`}
              name={name(slot)}
              stroke={slotColor(chart, slot)}
              fill={slotColor(chart, slot)}
              fillOpacity={0.12}
              strokeWidth={2}
              connectNulls={false}
              isAnimationActive={false}
            />
          ) : (
            <Line
              key={slot}
              dataKey={`s${slot}`}
              name={name(slot)}
              stroke={slotColor(chart, slot)}
              strokeWidth={2}
              dot={false}
              connectNulls={false}
              isAnimationActive={false}
            />
          ),
        )}
      </Chart>
    );
  } else {
    const horizontal = chart.type === "bar";
    body = (
      <BarChart
        data={rows}
        layout={horizontal ? "vertical" : "horizontal"}
        margin={{ top: 8, right: 16, bottom: 0, left: 0 }}
      >
        <CartesianGrid stroke="hsl(var(--border))" vertical={horizontal} horizontal={!horizontal} />
        {horizontal ? (
          <>
            <XAxis type="number" tick={axisTick} tickLine={false} axisLine={false} />
            <YAxis type="category" dataKey="label" tick={axisTick} tickLine={false} axisLine={false} width={88} />
          </>
        ) : (
          <>
            <XAxis dataKey="label" tick={axisTick} tickLine={false} axisLine={false} />
            <YAxis tick={axisTick} tickLine={false} axisLine={false} width={44} />
          </>
        )}
        {tooltip}
        {many && <Legend wrapperStyle={{ fontSize: 12 }} />}
        {chart.series.map((_, slot) => (
          <Bar
            key={slot}
            dataKey={`s${slot}`}
            name={name(slot)}
            fill={slotColor(chart, slot)}
            stackId={chart.stacked ? "stack" : undefined}
            radius={chart.stacked ? 0 : horizontal ? [0, 3, 3, 0] : [3, 3, 0, 0]}
            isAnimationActive={false}
          />
        ))}
      </BarChart>
    );
  }

  return (
    <figure className={className} role="img" aria-label={described} data-testid="chart-preview" data-kind={chart.type}>
      <ResponsiveContainer width="100%" height={height}>
        {body}
      </ResponsiveContainer>
    </figure>
  );
}
