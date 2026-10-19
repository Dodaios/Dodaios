import { useState } from "react";
import { Check, ChevronDown, ChevronRight, Eye, Hammer, ListChecks, RotateCcw, TriangleAlert } from "lucide-react";
import { fill, useT } from "@/i18n";
import type { TeamPlan, TeamPlanStep, TeamThread } from "@/lib/teamThreadsApi";
import { cn } from "@/lib/utils";

/**
 * The planner's living plan, on top of the board: the newest version, each
 * step with where it stands and who holds it. A version the reviewers have
 * not agreed to yet says so; a builder's request for a new version shows
 * under the list.
 */
export function PlanPanel({ thread, names }: { thread: TeamThread; names: Map<string, string> }) {
  const t = useT();
  const [open, setOpen] = useState(true);
  const plan = thread.plan;
  if (!plan) return null;
  const total = plan.steps.length;
  const accepted = plan.steps.filter((step) => step.status === "accepted").length;
  const over = thread.state === "done" || thread.state === "stopped" || thread.state === "failed";
  return <section className="rounded-xl border border-border bg-card" data-testid="team-plan" aria-label={t("team_threads.phase.planning")}>
    <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} title={t("team_threads.plan.toggle")}
      className="flex w-full min-w-0 items-center gap-2 rounded-xl px-3 py-2 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
      {open ? <ChevronDown aria-hidden className="h-3.5 w-3.5 shrink-0 text-muted-foreground" /> : <ChevronRight aria-hidden className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />}
      <ListChecks aria-hidden className="h-4 w-4 shrink-0 text-muted-foreground" />
      <span className="shrink-0 text-sm font-medium text-foreground">
        {plan.version > 0 ? fill(t("team_threads.plan.title"), { version: plan.version }) : t("team_threads.phase.planning")}
      </span>
      {plan.version > 0 && !plan.agreed && <span className="shrink-0 rounded-full border border-warning/40 px-1.5 py-px text-[11px] text-warning" data-testid="team-plan-proposed">
        {t("team_threads.plan.proposed")}
      </span>}
      {total > 0 && <span className="ml-auto flex min-w-0 items-center gap-2 text-xs text-muted-foreground">
        <span aria-hidden className="hidden h-1 w-24 overflow-hidden rounded-full bg-secondary sm:block">
          <span className="block h-full rounded-full bg-success transition-[width] duration-500" style={{ width: `${(accepted / total) * 100}%` }} />
        </span>
        <span className="truncate tabular-nums">{fill(t("team_threads.plan.progress"), { done: accepted, total })}</span>
      </span>}
    </button>
    {open && <div className="border-t border-border">
      {total === 0
        ? <p className="px-3 py-2.5 text-xs text-muted-foreground">{t("team_threads.plan.writing")}</p>
        : <ol className="max-h-[32vh] overflow-y-auto py-1" aria-label={t("team_threads.phase.planning")}>
          {plan.steps.map((step) => <StepRow key={step.number} step={step} names={names} live={!over && thread.state === "running"} />)}
        </ol>}
      {plan.revision && !over && <Revision revision={plan.revision} names={names} />}
    </div>}
  </section>;
}

const TONE: Record<TeamPlanStep["status"], string> = {
  accepted: "border-success/40 text-success",
  building: "border-accent/40 text-accent",
  in_review: "border-accent/40 text-accent",
  changes: "border-warning/40 text-warning",
  open: "border-border text-muted-foreground",
};

function StepRow({ step, names, live }: { step: TeamPlanStep; names: Map<string, string>; live: boolean }) {
  const t = useT();
  const active = step.status === "building" || step.status === "in_review" || step.status === "changes";
  return <li data-testid={`team-plan-step-${step.number}`} data-status={step.status} aria-current={active ? "step" : undefined}
    className={cn("flex min-w-0 items-start gap-2.5 px-3 py-1.5", active && "bg-accent/5")}>
    <StepGlyph step={step} live={live} />
    <div className="min-w-0 flex-1">
      <p className={cn("truncate text-sm", step.status === "accepted" ? "text-muted-foreground" : "text-foreground", active && "font-medium")} title={step.goal || step.title}>
        {step.title}
      </p>
      <p className="truncate text-xs text-muted-foreground" title={step.done_when}>
        <span className="text-foreground/70">{t("team_threads.plan.done_when")}:</span> {step.done_when}
      </p>
    </div>
    <div className="flex shrink-0 flex-col items-end gap-0.5 pt-px">
      <span className={cn("rounded-full border px-1.5 py-px text-[11px]", step.open_findings ? TONE.changes : TONE[step.status])}
        title={step.open_findings ? t("team_threads.plan.open_findings") : undefined}>
        {t(`team_threads.step_status.${step.status}`)}
      </span>
      {(step.holders.length > 0 || step.rounds > 1) && <span className="text-[11px] text-muted-foreground">
        {[step.holders.map((id) => names.get(id) ?? id).join(", "), step.rounds > 1 ? fill(t("team_threads.round"), { round: step.rounds }) : ""]
          .filter(Boolean).join(" · ")}
      </span>}
    </div>
  </li>;
}

function StepGlyph({ step, live }: { step: TeamPlanStep; live: boolean }) {
  const ring = "mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border text-[10px] font-medium tabular-nums";
  if (step.status === "accepted") {
    return <span aria-hidden className={cn(ring, step.open_findings ? "border-warning bg-warning text-background" : "border-success bg-success text-background")}>
      <Check className="h-3 w-3" strokeWidth={3} />
    </span>;
  }
  const Glyph = step.status === "building" ? Hammer : step.status === "in_review" ? Eye : step.status === "changes" ? RotateCcw : null;
  if (!Glyph) return <span aria-hidden className={cn(ring, "border-border text-muted-foreground")}>{step.number}</span>;
  return <span aria-hidden className={cn(ring, step.status === "changes" ? "border-warning text-warning" : "border-accent text-accent", live && "team-step-now")}>
    <Glyph className="h-3 w-3" />
  </span>;
}

function Revision({ revision, names }: { revision: NonNullable<TeamPlan["revision"]>; names: Map<string, string> }) {
  const t = useT();
  const detail = [revision.note, revision.plan_change && fill(t("team_threads.plan.plan_change"), { text: revision.plan_change })].filter(Boolean).join(" · ");
  return <div role="status" data-testid="team-plan-revision"
    className="flex items-start gap-2 border-t border-border bg-warning/10 px-3 py-2 text-xs text-foreground">
    <TriangleAlert aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" />
    <span className="min-w-0 [overflow-wrap:anywhere]">
      <span className="font-medium">{fill(t("team_threads.plan.revision"), { member: names.get(revision.by) ?? revision.by, number: revision.step })}</span>
      {revision.status === "blocked" && <span className="text-warning"> · {t("team_threads.plan.blocked")}</span>}
      {detail && <span className="text-muted-foreground"> · {detail}</span>}
    </span>
  </div>;
}
