/** A routine's runs: outcome, when, how it started, how long, what it cost, what it said. */
import { useEffect, useState } from "react";
import { ChevronRight } from "lucide-react";
import { useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { routineSkipReason } from "@/lib/skipReasons";
import { RunStatusIcon } from "./RunStatus";
import { fill, formatCost, formatDuration, shortDateTime } from "./format";
import type { Run } from "./runs";

const FIRST_PAGE = 12;

function useTicking(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [active]);
  return now;
}

export function runStateLabel(t: (key: string) => string, status: string): string {
  if (status === "legacy") return t("society.routine_detail.legacy");
  if (status === "skipped") return t("society.routine_detail.skipped");
  const own = t(`society.agent_routines.status.${status}`);
  return own.startsWith("society.") ? t(`tasks_view.state.${status}`) : own;
}

export function runReason(t: (key: string) => string, run: Run): string {
  if (run.status === "skipped") {
    return run.skipCode === "away_parked" ? t("society.agent_routines.runs.skip_away") : routineSkipReason(t, run.skipCode, run.skipProvider, run.text);
  }
  if (run.status === "failed" || run.status === "interrupted") return run.error || run.text;
  return run.summary ?? "";
}

export function RunHistory({ runs, ready, locale, onOpen }: {
  runs: Run[]; ready: boolean; locale: string; onOpen: (run: Run) => void;
}) {
  const t = useT();
  const label = (key: string) => t(`society.routine_detail.${key}`);
  const own = (key: string) => t(`society.agent_routines.runs.${key}`);
  const [all, setAll] = useState(false);
  const running = runs.some((run) => run.status === "running");
  const now = useTicking(running);
  const shown = all ? runs : runs.slice(0, FIRST_PAGE);
  return <section className="space-y-2" aria-labelledby="routine-runs-heading">
    <div className="flex items-center justify-between gap-2">
      <h4 id="routine-runs-heading" className="text-xs font-medium text-muted-foreground">
        {label("history")}{runs.length > 0 && <span className="ml-1.5 font-normal normal-case tracking-normal text-faint-foreground">{runs.length}</span>}
      </h4>
      {runs.length > 0 && <button type="button" className="rounded-md px-1.5 py-0.5 text-xs text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground" onClick={() => onOpen(runs[0])}>{label("latest_chat")}</button>}
    </div>
    {ready && runs.length === 0 && <p className="rounded-xl border border-dashed border-border px-3 py-4 text-center text-[12px] leading-snug text-muted-foreground">{own("empty")}</p>}
    {runs.length > 0 && <ol className="divide-y divide-border/50 overflow-hidden rounded-2xl bg-card">
      {shown.map((run) => {
        const state = runStateLabel(t, run.status);
        const reason = runReason(t, run);
        const elapsed = run.status === "running" && run.startedMs ? Math.max(0, now - run.startedMs) : undefined;
        const duration = formatDuration(elapsed ?? run.durationMs);
        const cost = formatCost(run.costUsd, locale);
        const at = new Date(run.timestamp);
        return <li key={run.id}>
          <button type="button" data-testid={`routine-run-${run.id}`}
            aria-label={`${label("open_chat")} · ${at.toLocaleString(locale)} · ${state}`}
            onClick={() => onOpen(run)}
            className="group flex w-full cursor-pointer items-start gap-2.5 px-3 py-2 text-left transition-colors duration-150 hover:bg-secondary/60 focus-visible:bg-secondary/60 focus-visible:outline-none">
            <RunStatusIcon status={run.status} label={state} className="mt-[1px]" />
            <span className="min-w-0 flex-1">
              <span className="flex items-baseline gap-2">
                <time dateTime={at.toISOString()} title={at.toLocaleString(locale)} className="text-[12px] font-medium text-foreground">{shortDateTime(run.timestamp, now, locale)}</time>
                {run.origin === "manual" && <span className="rounded-full border border-border px-1.5 text-xs leading-4 text-muted-foreground">{own("manual")}</span>}
                <span className="ml-auto flex shrink-0 items-baseline gap-1.5 text-xs tabular-nums text-muted-foreground">
                  {duration && <span>{duration}</span>}
                  {duration && cost && <span aria-hidden className="text-faint-foreground">·</span>}
                  {cost && <span title={run.billedViaKey === false ? own("included") : undefined}>{cost}</span>}
                </span>
              </span>
              {reason && <span data-testid={run.status === "skipped" ? "routine-run-skip-reason" : undefined}
                className={cn("mt-0.5 block truncate text-xs leading-snug", run.status === "failed" ? "text-destructive/90" : "text-muted-foreground")}
                title={reason}>{reason}</span>}
            </span>
            <ChevronRight size={14} aria-hidden className="mt-0.5 shrink-0 text-faint-foreground opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100" />
          </button>
        </li>;
      })}
    </ol>}
    {runs.length > FIRST_PAGE && <button type="button" className="text-xs text-muted-foreground hover:text-foreground" onClick={() => setAll((v) => !v)}>
      {all ? own("show_less") : fill(own("show_all"), { n: runs.length })}
    </button>}
  </section>;
}
