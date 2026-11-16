import { useState, type ReactNode } from "react";
import { Check, ChevronRight } from "lucide-react";
import { planProgress, type PlanItem, type PlanStatus, type PlanView } from "@/components/agentchat/agentPlan";
import { plural, traceDuration } from "@/components/agentchat/traceEntries";
import { fill, useT } from "@/i18n";
import { cn } from "@/lib/utils";

/**
 * The to-do list a coding agent keeps for itself, as a checklist: one row per
 * entry with a small box in front — filled with a check once it is done, with
 * a breathing core in the signal colour on the one the agent works on, empty
 * on what is still open. A thread shows it without a frame where the agent
 * last touched the list, under a head that counts the entries and draws one
 * bar segment per entry; an opened step of the work log shows the same rows
 * smaller, as the list stood at that step. A checked entry says at its right
 * end how long it took.
 */

/** How many entries a card shows before the finished ones on top and the far ones below fold. */
export const PLAN_SHOWN = 8;

type Translate = (key: string) => string;

/** An entry's state as its mark. The core breathes only while the turn itself still works. */
function Mark({ status, running, compact }: { status: PlanStatus; running: boolean; compact: boolean }) {
  const box = cn("flex shrink-0 items-center justify-center rounded-[4px]", compact ? "h-3 w-3" : "h-3.5 w-3.5");
  if (status === "completed") {
    return <span aria-hidden data-plan-mark="completed" className={cn(box, "bg-muted-foreground/25")}>
      <Check strokeWidth={3.5} className={cn(compact ? "h-2 w-2" : "h-2.5 w-2.5", "text-foreground-secondary")} />
    </span>;
  }
  if (status === "in_progress") {
    return <span aria-hidden data-plan-mark="in_progress" data-live={running || undefined}
      className={cn(box, "border-[1.5px]", running ? "border-accent" : "border-foreground-secondary")}>
      <span className={cn("rounded-[1.5px]", compact ? "h-1 w-1" : "h-1.5 w-1.5",
        running ? "animate-pulse bg-accent motion-reduce:animate-none" : "bg-foreground-secondary")} />
    </span>;
  }
  return <span aria-hidden data-plan-mark="pending" className={cn(box, "border-[1.5px] border-muted-foreground/45")} />;
}

/**
 * How long a checked entry took, as its row says it ("42s", "3m 05s",
 * "1h 20m"); nothing under a second, when the agent only ticked it off.
 */
export function tookLabel(ms: number | undefined): string {
  if (ms == null || !Number.isFinite(ms) || ms < 1000) return "";
  if (ms < 3_600_000) return traceDuration(ms);
  const minutes = Math.floor(ms / 60_000);
  return `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, "0")}m`;
}

function Row({ item, running, compact, t }: { item: PlanItem; running: boolean; compact: boolean; t: Translate }) {
  const took = item.status === "completed" ? tookLabel(item.tookMs) : "";
  return <li data-status={item.status} className={cn("flex min-w-0 items-start", compact ? "gap-2 text-sm leading-5" : "gap-3 text-[15px] leading-[21px]")}>
    <span className={cn("flex shrink-0 items-center justify-center", compact ? "h-5 w-4" : "h-[21px] w-4")}>
      <Mark status={item.status} running={running} compact={compact} />
    </span>
    <span className="sr-only">{t(`thread_turn.plan.status_${item.status}`)}: </span>
    <span data-plan-text title={item.active && item.status === "in_progress" ? item.active : undefined} className={cn(
      "min-w-0 [overflow-wrap:anywhere]",
      item.status === "completed" ? "text-muted-foreground"
        : compact ? "text-foreground-secondary" : item.status === "in_progress" ? "text-foreground" : "text-foreground/90",
    )}>{item.text}</span>
    {took && <span data-testid="thread-plan-took" title={fill(t("thread_turn.plan.took"), { duration: took })}
      className={cn("ml-auto shrink-0 pl-2 tabular-nums text-muted-foreground/80", compact ? "text-xs leading-5" : "text-[13px] leading-[21px]")}>
      <span className="sr-only">, </span>{took}
    </span>}
  </li>;
}

/** A row that stands for entries folded away; a click shows the whole list. */
function FoldRow({ icon, label, compact, onClick }: { icon: ReactNode; label: string; compact: boolean; onClick: () => void }) {
  return <li className="min-w-0">
    <button type="button" onClick={onClick} data-testid="thread-plan-more"
      className={cn(
        "group/more flex w-full min-w-0 items-center rounded-md text-left text-muted-foreground transition-colors hover:text-foreground-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        compact ? "gap-2 text-sm leading-5" : "gap-3 text-[15px] leading-[21px]",
      )}>
      <span aria-hidden className={cn("flex shrink-0 items-center justify-center", compact ? "h-5 w-4" : "h-[21px] w-4")}>{icon}</span>
      <span className="min-w-0 truncate">{label}</span>
      <ChevronRight aria-hidden strokeWidth={2.25} className="h-3.5 w-3.5 shrink-0 opacity-0 transition-opacity group-hover/more:opacity-100 group-focus-visible/more:opacity-100" />
    </button>
  </li>;
}

/**
 * The rows of a list. A long list keeps the entry in work in view: finished
 * entries on top fold into one row ("5 done") and entries far below into
 * another ("3 more"), until the reader opens either.
 */
export function PlanList({ items, running, compact = false }: {
  items: readonly PlanItem[];
  /** The turn still works: the entry in progress turns. */
  running: boolean;
  /** The smaller rows of an opened step. */
  compact?: boolean;
}) {
  const t = useT();
  const lang = t("trace_report.locale");
  const [all, setAll] = useState(false);
  const { done, total } = planProgress(items);
  let top = 0;
  let bottom = 0;
  if (!all && items.length > PLAN_SHOWN) {
    const leading = items.findIndex((item) => item.status !== "completed");
    // Finished entries give way first, the last of them stays as context.
    top = Math.min(Math.max(0, (leading < 0 ? items.length : leading) - 1), items.length - PLAN_SHOWN);
    bottom = Math.max(0, items.length - top - PLAN_SHOWN);
    // One entry behind a row of its own gains nothing.
    if (top === 1) top = 0;
    if (bottom === 1) bottom = 0;
  }
  const shown = items.slice(top, items.length - bottom);
  return <ul role="list" aria-label={`${t("thread_turn.plan.label")}, ${fill(t("thread_turn.plan.progress"), { done, total })}`}
    data-testid="thread-plan-list" className={cn("m-0 flex min-w-0 list-none flex-col p-0", compact ? "gap-1" : "gap-2.5")}>
    {top > 0 && <FoldRow compact={compact} onClick={() => setAll(true)}
      icon={<Mark status="completed" running={false} compact={compact} />}
      label={fill(t(`thread_turn.plan.done_hidden_${plural(lang, top)}`), { count: top })} />}
    {shown.map((item) => <Row key={item.id} item={item} running={running} compact={compact} t={t} />)}
    {bottom > 0 && <FoldRow compact={compact} onClick={() => setAll(true)}
      icon={<Mark status="pending" running={false} compact={compact} />}
      label={fill(t(`thread_turn.plan.more_hidden_${plural(lang, bottom)}`), { count: bottom })} />}
  </ul>;
}

/** The bar of a list: one segment per entry, in the entry's state. */
const SEGMENT: Record<PlanStatus, string> = {
  completed: "bg-foreground-secondary/70",
  in_progress: "bg-accent",
  pending: "bg-muted-foreground/20",
};

/**
 * The agent's list in the thread, where the agent last touched it: a head
 * with the count and the bar, the rows under it. No frame; the bar is what
 * sets it apart from the lines around it.
 */
export function PlanCard({ plan, running }: { plan: PlanView; running: boolean }) {
  const t = useT();
  const { done, total } = planProgress(plan.items);
  return <section data-testid="thread-plan" className="min-w-0 py-1">
    <div aria-hidden className="mb-3">
      <div className="flex items-baseline justify-between gap-3 text-[13px] leading-5 text-muted-foreground">
        <span className="truncate">{t("thread_turn.plan.label")}</span>
        <span data-testid="thread-plan-count" className="shrink-0 tabular-nums">{fill(t("thread_turn.plan.progress"), { done, total })}</span>
      </div>
      <div data-testid="thread-plan-bar" className="mt-1.5 flex gap-[3px]">
        {plan.items.map((item) => <span key={item.id} data-status={item.status}
          className={cn("h-[3px] min-w-0 flex-1 rounded-full", item.status === "in_progress" && !running ? "bg-foreground-secondary/40" : SEGMENT[item.status])} />)}
      </div>
    </div>
    <PlanList items={plan.items} running={running} />
  </section>;
}

/** A piece of a step's line: plain words, or an entry of the list by its own words. */
export type PlanPart = string | { entry: string };

/** A sentence with its `{item}` and `{next}` places filled by entries of the list. */
function sentence(template: string, entries: Record<string, string>): PlanPart[] {
  return template.split(/(\{item\}|\{next\})/).filter(Boolean)
    .map((piece) => piece === "{item}" || piece === "{next}" ? { entry: entries[piece.slice(1, -1)] ?? "" } : piece);
}

/**
 * What a run of list calls did, as one line of the work log: the list it
 * made, the entry it finished or began ("Completed the draft, started the
 * review"), else that it changed the list. An entry's own words come as a
 * part of their own, so a step can set them a tone brighter than its verb.
 */
export function planParts(plan: PlanView, t: Translate, lang: string): PlanPart[] {
  const key = (name: string) => t(`thread_turn.plan.${name}`);
  if (plan.items.length === 0) return [key("cleared")];
  if (plan.fresh) return [fill(key(`made_${plural(lang, plan.items.length)}`), { count: plan.items.length })];
  const of = (kind: string) => plan.changes.filter((change) => change.kind === kind);
  const completed = of("completed");
  const started = of("started");
  if (completed.length === 1 && started.length === 1) {
    return sentence(key("completed_started"), { item: completed[0].text, next: started[0].text });
  }
  if (completed.length === 1) return sentence(key("completed"), { item: completed[0].text });
  if (completed.length > 1) return [fill(key("completed_n"), { count: completed.length })];
  if (started.length > 0) return sentence(key("started"), { item: started[started.length - 1].text });
  const added = of("added");
  if (added.length === 1) return sentence(key("added"), { item: added[0].text });
  if (added.length > 1) return [fill(key("added_n"), { count: added.length })];
  const removed = of("removed");
  if (removed.length === 1) return sentence(key("removed"), { item: removed[0].text });
  if (removed.length > 1) return [fill(key("removed_n"), { count: removed.length })];
  return [key("updated")];
}

/** The same line as plain text: a line of the thread, a label a screen reader hears. */
export function planText(plan: PlanView, t: Translate, lang: string): string {
  return planParts(plan, t, lang).map((part) => typeof part === "string" ? part : part.entry).join("");
}
