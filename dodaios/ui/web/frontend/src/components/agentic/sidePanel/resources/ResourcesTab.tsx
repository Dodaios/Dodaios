import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, Loader2 } from "lucide-react";
import { fill, useT } from "@/i18n";
import { useRunLocale } from "@/components/runs/format";
import {
  endResourceTools,
  fetchResources,
  type ResourceSnapshot,
  type ResourceTool,
} from "@/lib/resourcesApi";
import { cn } from "@/lib/utils";
import { isSectionOnScreen } from "@/store/tiling";
import { ResourceChart } from "./ResourceChart";
import { AgentRow, Figures, LoadRow, processesText, roleLabel, windowText } from "./ResourceRows";
import {
  GROUPS,
  METRICS,
  SELF_ROW,
  SYSTEM_ROW,
  agentTitle,
  formatMemory,
  formatPercent,
  historySpan,
  largest,
  metricValue,
  rankRows,
  sortByMetric,
  sparkPath,
  type Metric,
} from "./resourcesModel";

/** One sample every two seconds while the view is on screen. */
const POLL_MS = 2000;
/**
 * Twice as often while the charts are still short: opened a moment ago, the
 * view should have a curve to show within seconds, not minutes.
 */
const FAST_POLL_MS = 1000;
const FAST_SAMPLES = 30;
/** Apps named under the chart as what "everything else" is mostly made of. */
const ELSE_SHOWN = 4;
const METRIC_KEY = "jarvis.agenticIde.resources.metric";
/** Apps listed before the reader asks for all of them. */
const APPS_SHOWN = 10;

/**
 * The colours of the four owners, as custom properties so one set serves the
 * chart, the legend and the bars, and the dark theme swaps them in one place.
 * Each mode's steps were checked for separation under colour-vision deficiency
 * against that mode's surface.
 */
const PALETTE = cn(
  "[--rs-agents:#2a78d6] [--rs-linked:#eb6834] [--rs-app:#1baf7a] [--rs-other:#a3a3a3]",
  "dark:[--rs-agents:#3987e5] dark:[--rs-linked:#d95926] dark:[--rs-app:#199e70] dark:[--rs-other:#5c5c5c]",
);

function storedMetric(): Metric {
  try {
    const value = localStorage.getItem(METRIC_KEY);
    return METRICS.includes(value as Metric) ? (value as Metric) : "cpu";
  } catch {
    return "cpu";
  }
}

/**
 * The machine's load, polled while the Agentic IDE is in front. A failed poll
 * keeps the last reading on screen and says so; nothing is asked while the
 * window is hidden, and the server measures only when asked.
 */
function useResources() {
  const [snapshot, setSnapshot] = useState<ResourceSnapshot | null>(null);
  const [error, setError] = useState("");
  const [nonce, setNonce] = useState(0);
  useEffect(() => {
    let alive = true;
    let timer: number | undefined;
    let filling = true;
    const controller = new AbortController();
    const tick = async () => {
      if (!document.hidden && isSectionOnScreen("agentic-ide")) {
        try {
          const next = await fetchResources(controller.signal);
          if (alive) {
            filling = next.history.t.length < FAST_SAMPLES;
            setSnapshot(next);
            setError("");
          }
        } catch (err) {
          if (alive && !controller.signal.aborted) setError((err as Error).message);
        }
      }
      if (alive) timer = window.setTimeout(tick, filling ? FAST_POLL_MS : POLL_MS);
    };
    void tick();
    return () => {
      alive = false;
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [nonce]);
  const refresh = useCallback(() => setNonce((value) => value + 1), []);
  return { snapshot, error, refresh };
}

interface TileProps {
  metric: Metric;
  selected: boolean;
  disabled?: boolean;
  label: string;
  value: string;
  hint: string;
  series: readonly number[];
  onSelect: () => void;
}

/** One of the three headline meters; choosing it turns the whole view to that metric. */
function Tile({ metric, selected, disabled, label, value, hint, series, onSelect }: TileProps) {
  const path = sparkPath(series, 100, 22, { ceiling: 100 });
  return (
    <button
      type="button"
      onClick={onSelect}
      disabled={disabled}
      aria-pressed={selected}
      data-testid={`resources-tile-${metric}`}
      className={cn(
        "relative min-w-0 flex-1 overflow-hidden rounded-lg border px-2.5 pb-1.5 pt-2 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        selected ? "border-foreground/60 bg-secondary" : "border-border hover:bg-muted",
        disabled && "cursor-default opacity-60 hover:bg-transparent",
      )}
    >
      <span className="block truncate text-[11px] text-muted-foreground">{label}</span>
      <span className="block truncate text-[19px] font-semibold leading-tight tabular-nums text-foreground-strong">{value}</span>
      <span className="block truncate text-[10.5px] text-muted-foreground">{hint}</span>
      <svg aria-hidden viewBox="0 0 100 22" preserveAspectRatio="none" className="mt-1 h-[22px] w-full text-foreground/55">
        {path ? (
          <path d={path} fill="none" stroke="currentColor" strokeWidth={1.25} vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
        ) : null}
      </svg>
    </button>
  );
}

/** Every logical core as one cell, darker the busier it is. */
function Cores({ cores, locale }: { cores: readonly number[]; locale: string }) {
  const t = useT();
  return (
    <div data-testid="resources-cores" className="flex items-center gap-2">
      <span className="shrink-0 text-[11px] text-muted-foreground">{t("ide_side_panel.resources.cores")}</span>
      <div role="img" aria-label={fill(t("ide_side_panel.resources.cores_aria"), { count: cores.length })} className="flex min-w-0 flex-1 flex-wrap gap-[2px]">
        {cores.map((load, index) => (
          <span
            key={index}
            title={fill(t("ide_side_panel.resources.core"), { n: index + 1, percent: formatPercent(load, locale) })}
            className="h-3.5 min-w-[6px] flex-1 rounded-[2px] bg-foreground/[0.07]"
            style={{ maxWidth: 18 }}
          >
            <span
              className="block h-full w-full rounded-[2px]"
              style={{ background: "var(--rs-agents)", opacity: Math.max(0, Math.min(1, load / 100)) }}
            />
          </span>
        ))}
      </div>
    </div>
  );
}

function SectionHead({ title, count, countTestId, columns }: { title: string; count: number; countTestId: string; columns?: [string, string] }) {
  return (
    <h3 className="mb-1 flex items-center gap-2 px-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
      <span className="min-w-0 flex-1 truncate">
        {title}
        <span data-testid={countTestId} className="ml-2 rounded bg-muted px-1.5 text-[10px] font-normal tabular-nums">
          {count}
        </span>
      </span>
      {columns ? (
        <span className="flex shrink-0 text-[10px] font-normal normal-case tracking-normal tabular-nums">
          <span className="w-[52px] text-right">{columns[0]}</span>
          <span className="w-[62px] text-right">{columns[1]}</span>
        </span>
      ) : null}
    </h3>
  );
}

/**
 * The resource view: three meters, who used what over time, and under them
 * every agent and every app on the machine as a row of its own.
 */
export function ResourcesTab() {
  const t = useT();
  const locale = useRunLocale();
  const { snapshot, error, refresh } = useResources();
  const [metric, setMetricState] = useState<Metric>(storedMetric);
  const [open, setOpen] = useState<ReadonlySet<string>>(() => new Set());
  const [allApps, setAllApps] = useState(false);
  const [actionError, setActionError] = useState("");
  const firstRows = useRef(false);
  const root = useRef<HTMLElement>(null);

  const setMetric = useCallback((next: Metric) => {
    setMetricState(next);
    try {
      localStorage.setItem(METRIC_KEY, next);
    } catch {
      /* a convenience only */
    }
  }, []);

  const toggle = useCallback((id: string) => {
    setOpen((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const agents = useMemo(() => (snapshot ? rankRows(snapshot.agents, snapshot.history, metric) : []), [snapshot, metric]);
  const apps = useMemo(() => (snapshot ? rankRows(snapshot.apps, snapshot.history, metric) : []), [snapshot, metric]);

  // The first reading opens the heaviest agent (or, with none running, the
  // heaviest app), so a breakdown is visible without a click; after that the
  // reader's own choices stand.
  useEffect(() => {
    if (firstRows.current || !snapshot) return;
    const first = agents[0]?.id ?? apps[0]?.id;
    if (!first) return;
    firstRows.current = true;
    setOpen(new Set([first]));
  }, [snapshot, agents, apps]);

  const endTool = useCallback(
    async (tool: ResourceTool) => {
      setActionError("");
      try {
        await endResourceTools(tool.ids);
        refresh();
      } catch (err) {
        setActionError(fill(t("ide_side_panel.resources.end_failed"), { message: (err as Error).message }));
      }
    },
    [refresh, t],
  );

  if (!snapshot) {
    return (
      <section data-testid="resources-tab" className="flex h-full min-h-0 flex-col">
        {error ? (
          <p role="alert" className="flex items-start gap-2 px-4 py-3 text-sm text-destructive">
            <AlertTriangle aria-hidden className="mt-0.5 h-4 w-4 shrink-0" />
            {fill(t("ide_side_panel.resources.error"), { message: error })}
          </p>
        ) : (
          <p role="status" data-testid="resources-loading" className="flex items-center gap-2 px-4 py-3 text-sm text-muted-foreground">
            <Loader2 aria-hidden className="h-4 w-4 shrink-0 animate-spin motion-reduce:animate-none" />
            {t("ide_side_panel.resources.loading")}
          </p>
        )}
      </section>
    );
  }

  const { system, groups, history } = snapshot;
  const gpu = system.gpu;
  const shown: Metric = metric === "gpu" && !gpu ? "cpu" : metric;
  // "Everything else" in the chart is the apps no agent is connected to, and
  // the system. Named here so the grey band is not anonymous.
  const elseRows = [
    ...apps.filter((app) => app.used_by.length === 0).map((app) => ({ id: app.id, label: app.label, load: app })),
    { id: SYSTEM_ROW, label: t("ide_side_panel.resources.system_title"), load: snapshot.os },
  ];
  const elseTop = sortByMetric(
    elseRows.map((row) => ({ ...row.load, id: row.id, label: row.label })),
    shown,
  ).filter((row) => metricValue(row, shown) > 0);
  const elseChips = elseTop.slice(0, ELSE_SHOWN);
  const elseTotal = snapshot.app_count - apps.filter((app) => app.used_by.length > 0).length + 1;
  const elseMore = Math.max(0, elseTotal - elseChips.length);
  const showRow = (id: string) => {
    if (id.startsWith("app:") && !apps.slice(0, APPS_SHOWN).some((app) => app.id === id)) setAllApps(true);
    setOpen((current) => new Set(current).add(id));
    // After the row has been drawn (it may have been behind "show all").
    window.setTimeout(() => {
      const rows = Array.from(root.current?.querySelectorAll<HTMLElement>("[data-row-id]") ?? []);
      rows.find((row) => row.dataset.rowId === id)?.scrollIntoView?.({ block: "center", behavior: "smooth" });
    }, 0);
  };
  const showApps = () => {
    setAllApps(true);
    window.setTimeout(() => {
      root.current?.querySelector('[data-testid="resources-self"]')?.scrollIntoView?.({ block: "start", behavior: "smooth" });
    }, 0);
  };
  const agentMax = largest(agents, shown);
  const appMax = Math.max(largest(apps, shown), largest([snapshot.app], shown));
  const visibleApps = allApps ? apps : apps.slice(0, APPS_SHOWN);
  const hiddenApps = snapshot.app_count - snapshot.apps.length;
  const agentNames = new Map(agents.map((agent) => [agent.id, agentTitle(agent, t("ide_side_panel.resources.thread_untitled"))]));
  const groupValue = (key: (typeof GROUPS)[number]["key"]) =>
    shown === "cpu"
      ? formatPercent(groups[key].cpu_percent, locale)
      : formatMemory(groups[key].memory_mb, locale);
  const columns: [string, string] = [
    t(`ide_side_panel.resources.col.${shown === "gpu" ? "gpu" : "cpu"}`),
    t(`ide_side_panel.resources.col.${shown === "gpu" ? "vram" : "memory"}`),
  ];

  return (
    <section ref={root} data-testid="resources-tab" data-metric={shown} className={cn("flex h-full min-h-0 flex-col", PALETTE)}>
      {/* Rows change places as load shifts; the browser must not scroll to follow one. */}
      <div className="scrollbar-jarvis min-h-0 flex-1 space-y-3 overflow-y-auto px-3 pb-4 pt-3 [overflow-anchor:none]">
        <div className="flex gap-2">
          <Tile
            metric="cpu"
            selected={shown === "cpu"}
            label={t("ide_side_panel.resources.metric.cpu")}
            value={formatPercent(system.cpu_percent, locale)}
            hint={fill(t("ide_side_panel.resources.hint.cpu"), { cores: system.cores_logical })}
            series={history.series.cpu ?? []}
            onSelect={() => setMetric("cpu")}
          />
          <Tile
            metric="memory"
            selected={shown === "memory"}
            label={t("ide_side_panel.resources.metric.memory")}
            value={formatPercent(system.memory_percent, locale)}
            hint={fill(t("ide_side_panel.resources.hint.of"), {
              used: formatMemory(system.memory_used_mb, locale),
              total: formatMemory(system.memory_total_mb, locale),
            })}
            series={history.series.memory ?? []}
            onSelect={() => setMetric("memory")}
          />
          <Tile
            metric="gpu"
            selected={shown === "gpu"}
            disabled={!gpu}
            label={t("ide_side_panel.resources.metric.gpu")}
            value={gpu ? formatPercent(gpu.util_percent, locale) : "–"}
            hint={
              !gpu
                ? t("ide_side_panel.resources.gpu_none")
                : gpu.memory_total_mb > 0
                  ? fill(t("ide_side_panel.resources.hint.of"), {
                      used: formatMemory(gpu.memory_used_mb, locale),
                      total: formatMemory(gpu.memory_total_mb, locale),
                    })
                  : formatMemory(gpu.memory_used_mb, locale)
            }
            series={gpu ? (history.series.gpu ?? []) : []}
            onSelect={() => setMetric("gpu")}
          />
        </div>

        <div className="space-y-2 rounded-lg border border-border px-2.5 pb-2.5 pt-2">
          <div className="flex items-baseline justify-between gap-2">
            <h3 className="truncate text-[12.5px] font-medium text-foreground">
              {t(`ide_side_panel.resources.chart_title.${shown}`)}
            </h3>
            <span className="shrink-0 text-[11px] text-muted-foreground">
              {windowText(t, historySpan(history.t))}
            </span>
          </div>
          <ResourceChart history={history} metric={shown} locale={locale} elseRows={elseRows} memoryTotalMb={system.memory_total_mb} />
          {shown === "gpu" ? (
            <p className="truncate text-[11px] text-muted-foreground">
              {[gpu?.name, gpu && !gpu.per_process ? t("ide_side_panel.resources.gpu_whole") : ""].filter(Boolean).join(" · ")}
            </p>
          ) : (
            <ul data-testid="resources-legend" className="grid grid-cols-2 gap-x-3 gap-y-1">
              {GROUPS.map((group) => (
                <li key={group.key} data-group={group.key} className="flex min-w-0 items-center gap-1.5 text-[11.5px]">
                  <span aria-hidden className="h-2.5 w-2.5 shrink-0 rounded-[3px]" style={{ background: group.color }} />
                  <span className="min-w-0 flex-1 truncate text-muted-foreground">{t(`ide_side_panel.resources.group.${group.key}`)}</span>
                  <span className="shrink-0 tabular-nums text-foreground">{groupValue(group.key)}</span>
                </li>
              ))}
            </ul>
          )}
          {shown !== "gpu" && elseTop.length > 0 ? (
            <div data-testid="resources-else" className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-[11px]">
              <span className="text-muted-foreground">{t("ide_side_panel.resources.else_title")}</span>
              {elseChips.map((row) => (
                <button
                  key={row.id}
                  type="button"
                  onClick={() => showRow(row.id)}
                  data-row={row.id}
                  className="rounded-full border border-border px-2 py-0.5 text-foreground hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {row.label}{" "}
                  <span className="tabular-nums text-muted-foreground">
                    {shown === "cpu" ? formatPercent(row.cpu_percent, locale) : formatMemory(row.memory_mb, locale)}
                  </span>
                </button>
              ))}
              {elseMore > 0 ? (
                <button
                  type="button"
                  onClick={showApps}
                  data-testid="resources-else-all"
                  className="rounded-full px-1.5 py-0.5 text-accent hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {fill(t("ide_side_panel.resources.else_more"), { count: elseMore })}
                </button>
              ) : null}
            </div>
          ) : null}
          {shown === "cpu" && system.per_core.length > 1 ? <Cores cores={system.per_core} locale={locale} /> : null}
        </div>

        {error ? (
          <p role="alert" className="flex items-start gap-2 px-1 text-[11.5px] text-warning">
            <AlertTriangle aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            {fill(t("ide_side_panel.resources.stale"), { message: error })}
          </p>
        ) : null}
        {actionError ? (
          <p role="alert" className="px-1 text-[11.5px] text-destructive">{actionError}</p>
        ) : null}

        <section aria-label={t("ide_side_panel.resources.agents_title")}>
          <SectionHead
            title={t("ide_side_panel.resources.agents_title")}
            count={agents.length}
            countTestId="resources-agent-count"
            columns={columns}
          />
          {agents.length === 0 ? (
            <p className="rounded-lg border border-dashed border-border/60 px-3 py-2 text-[11.5px] text-muted-foreground">
              {t("ide_side_panel.resources.agents_empty")}
            </p>
          ) : (
            <ul className="space-y-1.5">
              {agents.map((agent) => (
                <AgentRow
                  key={agent.id}
                  agent={agent}
                  history={history}
                  metric={shown}
                  locale={locale}
                  max={agentMax}
                  open={open.has(agent.id)}
                  onToggle={() => toggle(agent.id)}
                  onEnd={endTool}
                />
              ))}
            </ul>
          )}
        </section>

        <section aria-label={t("ide_side_panel.resources.apps_title")}>
          <SectionHead
            title={t("ide_side_panel.resources.apps_title")}
            count={snapshot.app_count + 1}
            countTestId="resources-app-count"
            columns={columns}
          />
          <ul className="space-y-1.5">
            <LoadRow
              testId="resources-self"
              rowId={SELF_ROW}
              title={t("ide_side_panel.resources.group.app")}
              name={t("ide_side_panel.resources.group.app")}
              note={`${t("ide_side_panel.resources.app_note")} · ${processesText(t, snapshot.app.processes)}`}
              color="var(--rs-app)"
              load={snapshot.app}
              parts={snapshot.app.parts.map((part) => ({ ...part, label: roleLabel(t, part.role) }))}
              history={history}
              metric={shown}
              locale={locale}
              max={appMax}
              open={open.has(SELF_ROW)}
              onToggle={() => toggle(SELF_ROW)}
            />
            {visibleApps.map((app) => {
              const users = app.used_by.map((id) => agentNames.get(id)).filter((name): name is string => Boolean(name));
              return (
                <LoadRow
                  key={app.id}
                  testId="resources-app"
                  rowId={app.id}
                  name={app.label}
                  title={
                    <>
                      {app.label}
                      {app.instances > 1 ? (
                        <span className="ml-1 font-normal text-muted-foreground">
                          {fill(t("ide_side_panel.resources.instances"), { count: app.instances })}
                        </span>
                      ) : null}
                    </>
                  }
                  note={[
                    processesText(t, app.processes),
                    users.length > 0 ? fill(t("ide_side_panel.resources.app_used_by"), { agents: users.join(", ") }) : "",
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                  color={app.used_by.length > 0 ? "var(--rs-linked)" : "var(--rs-other)"}
                  load={app}
                  parts={app.parts}
                  history={history}
                  metric={shown}
                  locale={locale}
                  max={appMax}
                  open={open.has(app.id)}
                  onToggle={() => toggle(app.id)}
                />
              );
            })}
            {apps.length > APPS_SHOWN ? (
              <li>
                <button
                  type="button"
                  onClick={() => setAllApps((value) => !value)}
                  aria-expanded={allApps}
                  data-testid="resources-apps-toggle"
                  className="w-full rounded-md px-1.5 py-1 text-left text-[11.5px] text-accent hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {allApps
                    ? t("ide_side_panel.resources.apps_show_fewer")
                    : fill(t("ide_side_panel.resources.apps_show_all"), { count: apps.length })}
                </button>
              </li>
            ) : null}
            {allApps && hiddenApps > 0 ? (
              <li data-testid="resources-apps-more" className="flex items-center gap-2 px-1.5 py-1">
                <span className="min-w-0 flex-1 truncate pl-[22px] text-[11.5px] text-muted-foreground">
                  {fill(t("ide_side_panel.resources.apps_more"), { count: hiddenApps })}
                </span>
                <Figures load={snapshot.apps_more} metric={shown} locale={locale} />
              </li>
            ) : null}
            <LoadRow
              testId="resources-system"
              rowId={SYSTEM_ROW}
              title={t("ide_side_panel.resources.system_title")}
              name={t("ide_side_panel.resources.system_title")}
              note={t("ide_side_panel.resources.system_note")}
              color="var(--rs-other)"
              load={snapshot.os}
              parts={snapshot.os.parts}
              history={history}
              metric={shown}
              locale={locale}
              open={open.has(SYSTEM_ROW)}
              onToggle={() => toggle(SYSTEM_ROW)}
            />
          </ul>
        </section>
      </div>
    </section>
  );
}
