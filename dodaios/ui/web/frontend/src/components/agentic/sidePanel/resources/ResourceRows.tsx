import { useState, type ReactNode } from "react";
import {
  Bot,
  Box,
  Cable,
  ChevronRight,
  Cpu,
  FileCode,
  FlaskConical,
  GitBranch,
  Globe,
  Hammer,
  MoreHorizontal,
  Plug,
  SquareTerminal,
  Terminal,
  type LucideIcon,
} from "lucide-react";
import { fill, useT } from "@/i18n";
import type { ResourceAgent, ResourceHistory, ResourceLoad, ResourceTool } from "@/lib/resourcesApi";
import { cn } from "@/lib/utils";
import { AgentMark } from "../../AgentMark";
import {
  agentTitle,
  areaPath,
  formatMemory,
  formatPercent,
  metricValue,
  rowLine,
  sortByMetric,
  sparkPath,
  type Metric,
} from "./resourcesModel";

const CATEGORY_ICON: Record<string, LucideIcon> = {
  mcp: Plug,
  test: FlaskConical,
  build: Hammer,
  vcs: GitBranch,
  browser: Globe,
  runtime: FileCode,
  shell: SquareTerminal,
  command: Terminal,
  subagent: Bot,
  more: MoreHorizontal,
};

/** Roles of this app's own processes that have a translated name. */
const KNOWN_ROLES = new Set(["core", "window", "terminal_host", "thread_host"]);

const ROW_BUTTON =
  "flex w-full items-center gap-2 rounded-md px-1.5 py-1.5 text-left hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

/** The two figures every row ends in; the one the view is sorted by is in full ink. */
export function Figures({ load, metric, locale }: { load: ResourceLoad; metric: Metric; locale: string }) {
  const graphics = metric === "gpu";
  const first = formatPercent(graphics ? load.gpu_percent : load.cpu_percent, locale);
  const second = formatMemory(graphics ? load.gpu_memory_mb : load.memory_mb, locale);
  const firstStrong = metric === "cpu";
  return (
    <span className="flex shrink-0 items-baseline text-[11.5px] tabular-nums">
      <span data-figure="share" className={cn("w-[52px] text-right", firstStrong ? "text-foreground" : "text-muted-foreground")}>
        {first}
      </span>
      <span data-figure="memory" className={cn("w-[62px] text-right", firstStrong ? "text-muted-foreground" : "text-foreground")}>
        {second}
      </span>
    </span>
  );
}

/** A row's share of the heaviest row in its list, as a thin bar under it. */
function ShareBar({ value, max, color }: { value: number; max: number; color: string }) {
  const percent = max > 0 ? Math.max(0, Math.min(100, (value / max) * 100)) : 0;
  return (
    <div aria-hidden className="mx-1.5 h-[3px] overflow-hidden rounded-full bg-foreground/[0.07]">
      <div className="h-full rounded-full" style={{ width: `${percent}%`, background: color }} />
    </div>
  );
}

/** A row's own last minutes, scaled to its own peak: the shape is the point, the figures say how much. */
function Spark({ values, slots }: { values: readonly (number | null)[]; slots: number }) {
  const path = sparkPath(values, 56, 18, { floor: 2, slots });
  if (!path) return <span aria-hidden className="w-14 shrink-0" />;
  return (
    <svg aria-hidden viewBox="0 0 56 18" className="h-[18px] w-14 shrink-0 text-muted-foreground">
      <path d={path} fill="none" stroke="currentColor" strokeWidth={1.25} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

/**
 * The row's own curve, large enough to read: what it did over the last
 * minutes under the chosen metric, with its peak named beside it.
 */
function RowChart({
  rowId,
  history,
  metric,
  locale,
  color,
  minutes,
}: {
  rowId: string;
  history: ResourceHistory;
  metric: Metric;
  locale: string;
  color: string;
  minutes: number;
}) {
  const t = useT();
  const values = rowLine(history, rowId, metric);
  const present = values.filter((value): value is number => value !== null);
  if (present.length < 2) return null;
  const peak = Math.max(...present);
  const floor = metric === "memory" ? 1 : 2;
  const { line, area } = areaPath(values, 100, 40, { floor, slots: history.row_points });
  return (
    <figure data-testid="resources-row-chart" className="mb-1 px-1.5 pt-1">
      <svg aria-hidden viewBox="0 0 100 40" preserveAspectRatio="none" className="h-10 w-full">
        <path d={area} fill={color} fillOpacity={0.16} />
        <path d={line} fill="none" stroke={color} strokeWidth={1.5} vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
      </svg>
      <figcaption className="mt-0.5 flex justify-between text-[10.5px] text-muted-foreground">
        <span>
          {fill(t("ide_side_panel.resources.peak"), {
            value: metric === "memory" ? formatMemory(peak, locale) : formatPercent(peak, locale),
          })}
        </span>
        <span>{fill(t("ide_side_panel.resources.row_window"), { minutes })}</span>
      </figcaption>
    </figure>
  );
}

function DetailLine({
  icon: Icon,
  title,
  note,
  load,
  metric,
  locale,
  action,
  testId,
}: {
  icon: LucideIcon;
  title: ReactNode;
  note?: ReactNode;
  load: ResourceLoad;
  metric: Metric;
  locale: string;
  action?: ReactNode;
  testId?: string;
}) {
  return (
    <li data-testid={testId} className="group/line flex items-center gap-2 py-1 pl-1.5 pr-1.5">
      <Icon aria-hidden className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[12px] text-foreground">{title}</span>
        {note ? <span className="block truncate text-[11px] text-muted-foreground">{note}</span> : null}
      </span>
      {action}
      <Figures load={load} metric={metric} locale={locale} />
    </li>
  );
}

function processCount(t: (key: string) => string, count: number): string {
  return count === 1
    ? t("ide_side_panel.resources.process_one")
    : fill(t("ide_side_panel.resources.processes"), { count });
}

interface AgentRowProps {
  agent: ResourceAgent;
  history: ResourceHistory;
  metric: Metric;
  locale: string;
  max: number;
  /** Minutes a row's own curve covers. */
  minutes: number;
  open: boolean;
  onToggle: () => void;
  onEnd: (tool: ResourceTool) => Promise<void>;
}

/** One agent: a line that says who and how much, and under it what it is made of. */
export function AgentRow({ agent, history, metric, locale, max, minutes, open, onToggle, onEnd }: AgentRowProps) {
  const t = useT();
  const [confirm, setConfirm] = useState<string | null>(null);
  const [ending, setEnding] = useState(false);
  const title = agentTitle(agent, t("ide_side_panel.resources.thread_untitled"));
  const sub = [
    agent.kind === "pane" || agent.kind === "thread" ? agent.agent_label : "",
    t(`ide_side_panel.resources.kind.${agent.kind}`),
    agent.workspace,
    processCount(t, agent.processes),
  ].filter(Boolean);
  const tools = sortByMetric(agent.tools, metric);
  const toolKey = (tool: ResourceTool) => `${tool.category}:${tool.label}`;

  const end = async (tool: ResourceTool) => {
    setEnding(true);
    try {
      await onEnd(tool);
    } finally {
      setEnding(false);
      setConfirm(null);
    }
  };

  return (
    <li data-testid="resources-agent" data-agent-id={agent.id} data-kind={agent.kind} className="space-y-1">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        aria-label={fill(t("ide_side_panel.resources.details_of"), { target: title })}
        className={ROW_BUTTON}
      >
        <ChevronRight
          aria-hidden
          className={cn("h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform motion-reduce:transition-none", open && "rotate-90")}
        />
        <AgentMark agent={agent.agent} label={agent.agent_label || agent.label} size="sm" variant="plain" />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[12.5px] font-medium text-foreground">{title}</span>
          <span className="block truncate text-[11px] text-muted-foreground">{sub.join(" · ")}</span>
        </span>
        <Spark values={rowLine(history, agent.id, metric)} slots={history.row_points} />
        <Figures load={agent} metric={metric} locale={locale} />
      </button>
      <ShareBar value={metricValue(agent, metric)} max={max} color="var(--rs-agents)" />
      {open ? (
        <div className="ml-[22px] border-l border-border pl-2">
          <RowChart rowId={agent.id} history={history} metric={metric} locale={locale} color="var(--rs-agents)" minutes={minutes} />
          <ul>
            <DetailLine
              icon={Cpu}
              title={t("ide_side_panel.resources.runtime")}
              note={processCount(t, agent.runtime.processes)}
              load={agent.runtime}
              metric={metric}
              locale={locale}
              testId="resources-runtime"
            />
            {tools.map((tool) => {
              const key = toolKey(tool);
              const name = tool.label || t("ide_side_panel.resources.category.more");
              if (confirm === key) {
                return (
                  <li key={key} role="alertdialog" aria-label={fill(t("ide_side_panel.resources.end_confirm"), { target: name })} className="flex items-center gap-2 py-1 pl-1.5 pr-1.5">
                    <span className="min-w-0 flex-1 truncate text-[12px] text-foreground">
                      {fill(t("ide_side_panel.resources.end_confirm"), { target: name })}
                    </span>
                    <button
                      type="button"
                      disabled={ending}
                      onClick={() => void end(tool)}
                      data-testid="resources-end-confirm"
                      className="rounded-md bg-destructive px-2 py-0.5 text-[11px] font-medium text-destructive-foreground hover:bg-destructive/90 disabled:opacity-60"
                    >
                      {t("ide_side_panel.resources.end_yes")}
                    </button>
                    <button
                      type="button"
                      disabled={ending}
                      onClick={() => setConfirm(null)}
                      className="rounded-md border border-border px-2 py-0.5 text-[11px] text-foreground hover:bg-muted"
                    >
                      {t("ide_side_panel.resources.end_cancel")}
                    </button>
                  </li>
                );
              }
              return (
                <DetailLine
                  key={key}
                  testId="resources-tool"
                  icon={CATEGORY_ICON[tool.category] ?? Terminal}
                  title={
                    <>
                      {tool.category === "more" ? t("ide_side_panel.resources.category.more") : tool.label}
                      {tool.instances > 1 ? (
                        <span className="ml-1 text-muted-foreground">
                          {fill(t("ide_side_panel.resources.instances"), { count: tool.instances })}
                        </span>
                      ) : null}
                    </>
                  }
                  note={
                    tool.category === "more"
                      ? processCount(t, tool.processes)
                      : `${t(`ide_side_panel.resources.category.${tool.category}`)} · ${processCount(t, tool.processes)}`
                  }
                  load={tool}
                  metric={metric}
                  locale={locale}
                  action={
                    tool.ids.length > 0 ? (
                      <button
                        type="button"
                        onClick={() => setConfirm(key)}
                        aria-label={fill(t("ide_side_panel.resources.end_named"), { target: name })}
                        data-testid="resources-end"
                        className="shrink-0 rounded px-1.5 py-0.5 text-[11px] text-muted-foreground opacity-0 hover:bg-destructive/10 hover:text-destructive focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring group-hover/line:opacity-100"
                      >
                        {t("ide_side_panel.resources.end")}
                      </button>
                    ) : undefined
                  }
                />
              );
            })}
          </ul>
          {agent.linked.length > 0 ? (
            <div className="mt-1 border-t border-dashed border-border pt-1">
              <p className="px-1.5 pb-0.5 text-[11px] text-muted-foreground">{t("ide_side_panel.resources.linked_note")}</p>
              <ul>
                {agent.linked.map((app) => (
                  <DetailLine
                    key={app.id}
                    testId="resources-linked"
                    icon={Cable}
                    title={app.label}
                    note={[
                      app.via
                        ? fill(t("ide_side_panel.resources.linked_via"), { tool: app.via, port: app.port })
                        : fill(t("ide_side_panel.resources.linked_port"), { port: app.port }),
                      app.shared_with > 0
                        ? fill(t("ide_side_panel.resources.linked_shared"), { count: app.shared_with })
                        : "",
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                    load={app}
                    metric={metric}
                    locale={locale}
                  />
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}

interface LoadRowProps {
  testId: string;
  /** The row's id in the history; also names the row for tests. */
  rowId: string;
  title: ReactNode;
  /** The title as plain words, for the button's label. */
  name: string;
  note: string;
  color: string;
  load: ResourceLoad;
  parts: (ResourceLoad & { label: string })[];
  history: ResourceHistory;
  metric: Metric;
  locale: string;
  /** The heaviest row of the list, for the bar; omitted = no bar. */
  max?: number;
  minutes: number;
  open: boolean;
  onToggle: () => void;
}

/**
 * Anything that is not an agent: an app, this app, the system. The same line
 * as an agent's, and its own curve and its largest parts when opened.
 */
export function LoadRow({
  testId,
  rowId,
  title,
  name,
  note,
  color,
  load,
  parts,
  history,
  metric,
  locale,
  max,
  minutes,
  open,
  onToggle,
}: LoadRowProps) {
  const t = useT();
  const rows = sortByMetric(parts, metric);
  return (
    <li data-testid={testId} data-row-id={rowId} className="space-y-1">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        aria-label={fill(t("ide_side_panel.resources.details_of"), { target: name })}
        className={ROW_BUTTON}
      >
        <ChevronRight
          aria-hidden
          className={cn("h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform motion-reduce:transition-none", open && "rotate-90")}
        />
        <span aria-hidden className="mx-[3px] h-2.5 w-2.5 shrink-0 rounded-[3px]" style={{ background: color }} />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[12.5px] font-medium text-foreground">{title}</span>
          <span className="block truncate text-[11px] text-muted-foreground">{note}</span>
        </span>
        <Spark values={rowLine(history, rowId, metric)} slots={history.row_points} />
        <Figures load={load} metric={metric} locale={locale} />
      </button>
      {max !== undefined ? <ShareBar value={metricValue(load, metric)} max={max} color={color} /> : null}
      {open ? (
        <div className="ml-[22px] border-l border-border pl-2">
          <RowChart rowId={rowId} history={history} metric={metric} locale={locale} color={color} minutes={minutes} />
          <ul>
            {rows.map((part) => (
              <DetailLine
                key={part.label}
                testId="resources-part"
                icon={Box}
                title={part.label}
                note={processCount(t, part.processes)}
                load={part}
                metric={metric}
                locale={locale}
              />
            ))}
          </ul>
        </div>
      ) : null}
    </li>
  );
}

/** A role of this app's own processes as a person would name it. */
export function roleLabel(t: (key: string) => string, role: string): string {
  return KNOWN_ROLES.has(role) ? t(`ide_side_panel.resources.role.${role}`) : role;
}

/** "12 processes", for a row's second line. */
export function processesText(t: (key: string) => string, count: number): string {
  return processCount(t, count);
}
