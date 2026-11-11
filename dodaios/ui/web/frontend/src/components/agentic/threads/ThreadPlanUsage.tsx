import { useEffect, useRef, useState } from "react";
import { Gauge } from "lucide-react";
import { fill, useT } from "@/i18n";
import {
  fetchAgentAccounts,
  fetchAgentUsage,
  type AccountUsage,
  type AgentAccount,
  type UsageWindow,
} from "@/lib/agentAccountsApi";
import { cn } from "@/lib/utils";
import { isSectionOnScreen } from "@/store/tiling";
import { UsageDetails } from "../sidePanel/subscriptions/SubscriptionsTab";
import { headlineWindow, windowLength } from "../sidePanel/subscriptions/subscriptionsModel";
import { ThreadMenuHeading, ThreadPopover } from "./ThreadPopover";

/**
 * Never faster than the server's usage cache (`agent_usage.USAGE_TTL_S`): a
 * plan percentage moves over minutes, and every tick is jittered (AP-33).
 */
const MIN_POLL_MS = 60_000;
const POLL_JITTER_MS = 10_000;

const BAR_TONE: Record<string, string> = {
  normal: "bg-primary",
  warning: "bg-warning",
  critical: "bg-destructive",
};

const TEXT_TONE: Record<string, string> = {
  normal: "",
  warning: "text-warning",
  critical: "text-destructive",
};

export interface PlanReading {
  account: AgentAccount;
  usage: AccountUsage;
}

/**
 * The plan usage of the subscription a coding CLI runs on now: its active seat.
 * Polled while the IDE is in front; a failed tick keeps the last reading, and
 * an older backend without the usage route simply shows nothing.
 */
export function usePlanUsage(platform: string): PlanReading | null {
  const [reading, setReading] = useState<PlanReading | null>(null);
  useEffect(() => {
    setReading(null);
    if (!platform) return;
    let alive = true;
    let timer: number | undefined;
    let pollMs = MIN_POLL_MS;
    const tick = async () => {
      if (document.visibilityState !== "hidden" && isSectionOnScreen("agentic-ide")) {
        try {
          const [accounts, usage] = await Promise.all([fetchAgentAccounts(), fetchAgentUsage()]);
          if (usage) pollMs = Math.max(MIN_POLL_MS, usage.ttl_seconds * 1000);
          const group = accounts.platforms.find((entry) => entry.platform === platform);
          const account = group?.accounts.find((entry) => entry.id === group.active_account);
          const found = account ? usage?.accounts.find((entry) => entry.account_id === account.id) : undefined;
          if (alive) setReading(account && found ? { account, usage: found } : null);
        } catch (error) {
          console.debug("plan usage unavailable", error);
        }
      }
      if (alive) timer = window.setTimeout(tick, pollMs + Math.random() * POLL_JITTER_MS);
    };
    void tick();
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, [platform]);
  return reading;
}

/** The chip's few words for a limit: "5 h", "Week", "Month", or the provider's own name. */
function shortLabel(t: (key: string) => string, window: UsageWindow): string {
  if (window.kind === "session") return windowLength(window.window_minutes) || t("ide_threads.plan_usage.session");
  if (window.kind === "weekly") return t("ide_threads.plan_usage.weekly");
  if (window.kind === "weekly_scoped") {
    return window.scope_label
      ? fill(t("ide_threads.plan_usage.weekly_scoped"), { scope: window.scope_label })
      : t("ide_threads.plan_usage.weekly");
  }
  if (window.kind === "monthly") return t("ide_threads.plan_usage.monthly");
  return window.raw_label || t("ide_threads.plan_usage.other");
}

/**
 * How much of the plan the thread's agent runs on is spent, at the right end
 * of the strip under the composer. The chip names the plan's weekly limit
 * (`headlineWindow`); a click shows every limit of the plan, model-scoped
 * ones included, with its reset time. Nothing is
 * drawn when the CLI has no readable plan (an API key, a signed-out seat, a
 * CLI that publishes no usage) — an empty spot is honest, a guessed number is not.
 */
export function ThreadPlanUsage({ platform, className }: {
  /** The Agentic IDE registry key of the thread's CLI ("claude", "codex", …); "" = none. */
  platform: string;
  className: string;
}) {
  const t = useT();
  const reading = usePlanUsage(platform);
  const [open, setOpen] = useState(false);
  const anchor = useRef<HTMLButtonElement | null>(null);
  const shown = headlineWindow(reading?.usage ?? null);
  if (!reading || !shown) return null;

  const percent = Math.round(Math.min(100, Math.max(0, shown.percent)));
  const label = shortLabel(t, shown);
  const plan = reading.usage.plan?.trim() || reading.account.tier?.trim() || "";
  const who = reading.account.email || reading.account.label;
  const title = fill(t("ide_threads.plan_usage.title"), { plan: plan || who, limit: label, percent });
  return <>
    <button ref={anchor} type="button" className={cn(className, "shrink-0")} aria-haspopup="dialog" aria-expanded={open}
      data-testid="thread-plan-usage" data-severity={shown.severity} title={title} onClick={() => setOpen(!open)}>
      <Gauge aria-hidden className="h-3.5 w-3.5 shrink-0" />
      {plan && <span className="max-w-[120px] truncate">{plan}</span>}
      <span aria-hidden className="h-1.5 w-10 shrink-0 overflow-hidden rounded-full bg-muted">
        <span className={cn("block h-full rounded-full", BAR_TONE[shown.severity] ?? BAR_TONE.normal)} style={{ width: `${percent}%` }} />
      </span>
      <span className={cn("shrink-0 tabular-nums", TEXT_TONE[shown.severity])}>{fill(t("ide_threads.plan_usage.chip"), { limit: label, percent })}</span>
    </button>
    <ThreadPopover anchor={anchor} open={open} onClose={() => setOpen(false)} label={t("ide_threads.plan_usage.heading")} side="top" align="end" width={280}>
      <ThreadMenuHeading>{plan ? `${t("ide_threads.plan_usage.heading")} · ${plan}` : t("ide_threads.plan_usage.heading")}</ThreadMenuHeading>
      <p className="truncate px-2 pb-2 text-[11px] text-muted-foreground">{who}</p>
      <div className="px-2 pb-2" data-testid="thread-plan-usage-details">
        <UsageDetails usage={reading.usage} now={Date.now()} />
      </div>
    </ThreadPopover>
  </>;
}
