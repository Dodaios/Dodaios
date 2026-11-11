import { useMemo } from "react";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { fill, useT } from "@/i18n";
import type { ResourceHistory } from "@/lib/resourcesApi";
import { GROUPS, WINDOW_S, chartPoints, formatPercent, type ChartPoint, type Metric } from "./resourcesModel";

const AXIS_TINT = "hsl(var(--muted-foreground))";
const GRID_TINT = "hsl(var(--foreground) / 0.1)";
const SURFACE = "hsl(var(--background))";

interface Props {
  history: ResourceHistory;
  metric: Metric;
  locale: string;
}

/**
 * The last five minutes of one metric, stacked by who used it.
 *
 * The scale is always the whole machine (0-100 %), never the peak of the
 * window: the empty space above the stack is the headroom, and that is half of
 * what the chart is for. The graphics card has one series, because no platform
 * splits its load by owner over time.
 */
export function ResourceChart({ history, metric, locale }: Props) {
  const t = useT();
  const data = useMemo(() => chartPoints(history, metric), [history, metric]);
  const end = data.length > 0 ? data[data.length - 1].t : 0;
  const ticks = useMemo(
    () => [4, 3, 2, 1, 0].map((minutes) => end - minutes * 60),
    [end],
  );
  const stacked = metric !== "gpu";
  const series = stacked ? GROUPS : GROUPS.slice(0, 1);

  return (
    <div data-testid="resources-chart" data-metric={metric} className="h-[168px] w-full">
      <ResponsiveContainer
        width="100%"
        height="100%"
        // Without a positive floor the first measure is 0x0 and the areas bake
        // in a collapsed scale.
        minHeight={160}
        minWidth={0}
        initialDimension={{ width: 420, height: 168 }}
      >
        <AreaChart data={data} margin={{ top: 6, right: 6, bottom: 0, left: 0 }}>
          <CartesianGrid vertical={false} stroke={GRID_TINT} />
          <XAxis
            dataKey="t"
            type="number"
            domain={[end - WINDOW_S, end]}
            ticks={ticks}
            tickFormatter={(value: number) => {
              const minutes = Math.round((end - value) / 60);
              return minutes === 0
                ? t("ide_side_panel.resources.axis_now")
                : fill(t("ide_side_panel.resources.axis_ago"), { minutes: String(minutes) });
            }}
            tick={{ fill: AXIS_TINT, fontSize: 10 }}
            axisLine={false}
            tickLine={false}
            allowDataOverflow
            dy={2}
          />
          <YAxis
            width={38}
            domain={[0, 100]}
            ticks={[0, 50, 100]}
            tickFormatter={(value: number) => `${value} %`}
            tick={{ fill: AXIS_TINT, fontSize: 10 }}
            axisLine={false}
            tickLine={false}
            allowDataOverflow
          />
          <Tooltip
            isAnimationActive={false}
            cursor={{ stroke: "hsl(var(--foreground) / 0.35)", strokeWidth: 1 }}
            content={<ChartTooltip metric={metric} locale={locale} />}
          />
          {series.map((group) => (
            <Area
              key={group.key}
              dataKey={group.key}
              stackId={stacked ? "owners" : undefined}
              type="linear"
              fill={group.color}
              fillOpacity={stacked ? 0.9 : 0.25}
              // A surface-coloured edge is the gap between two touching fills.
              stroke={stacked ? SURFACE : group.color}
              strokeWidth={stacked ? 1.5 : 2}
              isAnimationActive={false}
              activeDot={false}
            />
          ))}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

interface TooltipProps {
  metric: Metric;
  locale: string;
  active?: boolean;
  payload?: { payload?: ChartPoint }[];
}

function ChartTooltip({ metric, locale, active, payload }: TooltipProps) {
  const t = useT();
  const point = payload?.[0]?.payload;
  if (!active || !point) return null;
  const time = new Date(point.t * 1000).toLocaleTimeString(locale, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
  const rows = metric === "gpu" ? [] : [...GROUPS].reverse();
  return (
    <div className="rounded-md border border-border bg-popover px-2.5 py-2 text-[11px] text-popover-foreground shadow-float">
      <div className="mb-1 tabular-nums text-muted-foreground">{time}</div>
      {rows.map((group) => (
        <div key={group.key} className="flex items-center gap-2">
          <span aria-hidden className="h-2 w-2 shrink-0 rounded-[2px]" style={{ background: group.color }} />
          <span className="min-w-0 flex-1 truncate">{t(`ide_side_panel.resources.group.${group.key}`)}</span>
          <span className="tabular-nums">{formatPercent(point[group.key], locale)}</span>
        </div>
      ))}
      <div className={`flex items-center gap-2 font-medium ${rows.length > 0 ? "mt-1 border-t border-border pt-1" : ""}`}>
        <span className="min-w-0 flex-1 truncate">
          {t(metric === "gpu" ? "ide_side_panel.resources.metric.gpu" : "ide_side_panel.resources.total")}
        </span>
        <span className="tabular-nums">{formatPercent(point.total, locale)}</span>
      </div>
    </div>
  );
}
