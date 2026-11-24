/**
 * The learned advantage of one area over the nights: the measured difference
 * as a line, the range the true value lies in as a band around it, the zero
 * line, and a mark where the app was updated between two nights.
 *
 * Built like the chat's chart card (components/outputs/ChartFence.tsx,
 * docs/chat-charts.md): the app's own card and ink, one fixed hue for the
 * marks, hovering reads the values, and a Table switch shows every number, so
 * nothing is readable only by hovering. Fewer than two points draw no chart.
 */
import { useMemo, useState } from "react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useThemeValue } from "@/hooks/useTheme";
import { fill, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import type { AdvantagePoint } from "@/lib/selfImprovementApi";
import { SERIES_COLORS } from "@/components/outputs/ChartFence";
import { fmtPoints, shortDate } from "./words";

const AXIS_TINT = "hsl(var(--muted-foreground))";
const GRID_TINT = "hsl(var(--foreground) / 0.08)";
const ZERO_TINT = "hsl(var(--foreground) / 0.35)";
const SURFACE = "hsl(var(--card))";
const TICK = { fill: AXIS_TINT, fontSize: 11 } as const;
const PLOT_HEIGHT = 200;

interface Row {
  i: number;
  label: string;
  diff: number;
  band: [number, number];
  point: AdvantagePoint;
}

/** Indexes of the points measured by another app version than the point before. */
export function updateMarks(points: readonly AdvantagePoint[]): number[] {
  const marks: number[] = [];
  for (let i = 1; i < points.length; i++) {
    if (points[i].app && points[i - 1].app && points[i].app !== points[i - 1].app) marks.push(i);
  }
  return marks;
}

function CurveTooltip({ active, payload, locale }: { active?: boolean; payload?: { payload?: Row }[]; locale: string }) {
  const t = useT();
  const row = payload?.[0]?.payload;
  if (!active || !row) return null;
  return (
    <div className="rounded-md border border-border bg-popover px-2.5 py-2 text-[11px] text-popover-foreground shadow-float">
      <div className="mb-1 text-muted-foreground">{row.label}</div>
      <div className="font-semibold tabular-nums text-foreground">
        {fill(t("self_improvement.area.points"), { value: fmtPoints(row.point.diff, locale) })}
      </div>
      <div className="tabular-nums text-muted-foreground">
        {fill(t("self_improvement.curve.range_value"), {
          low: fmtPoints(row.point.low, locale),
          high: fmtPoints(row.point.high, locale),
        })}
      </div>
    </div>
  );
}

export function AdvantageCurve({ points, locale }: { points: readonly AdvantagePoint[]; locale: string }) {
  const t = useT();
  const theme = useThemeValue();
  const hue = SERIES_COLORS[theme][0];
  const [view, setView] = useState<"chart" | "table">("chart");
  const rows = useMemo<Row[]>(
    () =>
      points.map((point, i) => ({
        i,
        label: shortDate(point.ts_ms, locale),
        diff: Math.round(point.diff * 1000) / 10,
        band: [Math.round(point.low * 1000) / 10, Math.round(point.high * 1000) / 10],
        point,
      })),
    [points, locale],
  );
  const marks = useMemo(() => updateMarks(points), [points]);

  if (points.length < 2) {
    return (
      <p className="mt-4 text-sm text-muted-foreground" data-testid="si-curve-few">
        {t("self_improvement.curve.few")}
      </p>
    );
  }

  const segment = (value: "chart" | "table", label: string) => (
    <button
      type="button"
      aria-pressed={view === value}
      onClick={() => setView(value)}
      className={cn(
        "rounded-sm px-2 py-0.5 text-micro font-medium transition-colors",
        view === value ? "bg-card text-foreground" : "text-muted-foreground hover:text-foreground",
      )}
    >
      {label}
    </button>
  );

  return (
    <figure
      className="mt-5 overflow-hidden rounded-md border border-border bg-card text-left text-foreground"
      data-testid="si-curve"
      data-view={view}
    >
      <figcaption className="flex items-start justify-between gap-3 px-4 pt-3">
        <div className="min-w-0">
          <div className="text-sm font-medium text-foreground">{t("self_improvement.curve.title")}</div>
          <div className="text-xs text-muted-foreground">{t("self_improvement.curve.caption")}</div>
        </div>
        <div role="group" className="inline-flex shrink-0 rounded border border-border bg-secondary p-0.5">
          {segment("chart", t("outputs_view.chart_view"))}
          {segment("table", t("outputs_view.chart_table"))}
        </div>
      </figcaption>
      {view === "table" ? (
        <div className="max-h-72 overflow-auto px-4 pb-3 pt-2" data-testid="si-curve-table">
          <table className="w-full border-collapse text-xs">
            <thead>
              <tr className="text-muted-foreground">
                <th scope="col" className="border-b border-border py-1 pr-3 text-left font-medium">{t("self_improvement.curve.col_night")}</th>
                <th scope="col" className="border-b border-border py-1 pl-3 text-right font-medium">{t("self_improvement.curve.col_advantage")}</th>
                <th scope="col" className="border-b border-border py-1 pl-3 text-right font-medium">{t("self_improvement.curve.col_range")}</th>
                <th scope="col" className="border-b border-border py-1 pl-3 text-right font-medium">{t("self_improvement.curve.col_tasks")}</th>
                <th scope="col" className="border-b border-border py-1 pl-3 text-right font-medium">{t("self_improvement.curve.col_app")}</th>
              </tr>
            </thead>
            <tbody>
              {[...rows].reverse().map((row) => (
                <tr key={row.i}>
                  <th scope="row" className="border-b border-border/50 py-1 pr-3 text-left font-normal text-foreground">
                    {new Date(row.point.ts_ms).toLocaleString(locale, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}
                  </th>
                  <td className="border-b border-border/50 py-1 pl-3 text-right tabular-nums text-foreground">{fmtPoints(row.point.diff, locale)}</td>
                  <td className="border-b border-border/50 py-1 pl-3 text-right tabular-nums text-muted-foreground">
                    {fmtPoints(row.point.low, locale)} … {fmtPoints(row.point.high, locale)}
                  </td>
                  <td className="border-b border-border/50 py-1 pl-3 text-right tabular-nums text-foreground">{row.point.n}</td>
                  <td
                    className={cn(
                      "border-b border-border/50 py-1 pl-3 text-right tabular-nums",
                      marks.includes(row.i) ? "text-foreground" : "text-muted-foreground",
                    )}
                  >
                    {row.point.app}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="px-2 pb-3 pt-3">
          <div style={{ height: PLOT_HEIGHT }} className="w-full" data-testid="si-curve-plot">
            <ResponsiveContainer width="100%" height="100%" minWidth={0} initialDimension={{ width: 680, height: PLOT_HEIGHT }}>
              <ComposedChart data={rows} margin={{ top: 14, right: 14, bottom: 0, left: 0 }}>
                <CartesianGrid vertical={false} stroke={GRID_TINT} />
                <XAxis
                  dataKey="i"
                  type="number"
                  domain={[0, rows.length - 1]}
                  ticks={rows.map((row) => row.i)}
                  tickFormatter={(i: number) => rows[i]?.label ?? ""}
                  tick={TICK}
                  axisLine={false}
                  tickLine={false}
                  interval="preserveStartEnd"
                  minTickGap={28}
                  dy={4}
                  padding={{ left: 6, right: 6 }}
                />
                <YAxis
                  width={42}
                  tick={TICK}
                  tickFormatter={(value: number) => fmtPoints(value / 100, locale)}
                  axisLine={false}
                  tickLine={false}
                  domain={[(min: number) => Math.min(0, Math.floor(min)), (max: number) => Math.max(0, Math.ceil(max))]}
                />
                <Tooltip isAnimationActive={false} cursor={{ stroke: "hsl(var(--foreground) / 0.35)", strokeWidth: 1 }} content={<CurveTooltip locale={locale} />} />
                <ReferenceLine y={0} stroke={ZERO_TINT} strokeWidth={1} />
                {marks.map((i) => (
                  <ReferenceLine
                    key={`update-${i}`}
                    x={i - 0.5}
                    stroke={AXIS_TINT}
                    strokeDasharray="3 3"
                    label={{
                      value: fill(t("self_improvement.curve.update"), { version: points[i].app }),
                      position: "insideTopLeft",
                      fill: AXIS_TINT,
                      fontSize: 11,
                    }}
                  />
                ))}
                <Area
                  dataKey="band"
                  type="linear"
                  stroke="none"
                  fill={hue}
                  fillOpacity={0.14}
                  isAnimationActive={false}
                  activeDot={false}
                />
                <Line
                  dataKey="diff"
                  type="linear"
                  stroke={hue}
                  strokeWidth={2}
                  strokeLinejoin="round"
                  dot={{ r: 2.5, fill: hue, stroke: SURFACE, strokeWidth: 1 }}
                  activeDot={{ r: 4, stroke: SURFACE, strokeWidth: 2 }}
                  isAnimationActive={false}
                />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-2 pt-2 text-xs text-muted-foreground" data-testid="si-curve-legend">
            <span className="flex items-center gap-1.5">
              <span aria-hidden className="h-0.5 w-3" style={{ background: hue }} />
              {t("self_improvement.curve.legend_line")}
            </span>
            <span className="flex items-center gap-1.5">
              <span aria-hidden className="h-2 w-3 opacity-30" style={{ background: hue }} />
              {t("self_improvement.curve.legend_band")}
            </span>
            {marks.length > 0 && (
              <span className="flex items-center gap-1.5">
                <span aria-hidden className="h-3 w-0 border-l border-dashed border-muted-foreground" />
                {t("self_improvement.curve.legend_update")}
              </span>
            )}
          </div>
        </div>
      )}
    </figure>
  );
}
