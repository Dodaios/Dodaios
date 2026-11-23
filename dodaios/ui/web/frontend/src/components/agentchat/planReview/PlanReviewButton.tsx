/**
 * The way from a plan card into the plan's review window, and what the card
 * says about a plan the person has worked on ("Edited · 2 comments").
 *
 * The window is its own chunk (it carries the document editor), loaded with
 * the first plan that is opened.
 */
import { lazy, Suspense, useState } from "react";
import { Maximize2 } from "lucide-react";

import { fill, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { plural } from "@/components/agentchat/traceEntries";
import type { PlanAnswer } from "./PlanReviewDialog";
import { usePlanDraft, writtenComments } from "./planDraft";

const PlanReviewDialog = lazy(() => import("./PlanReviewDialog"));

/** "Edited · 2 comments" for a plan the person changed or commented on; nothing otherwise. */
export function PlanDraftMarks({ cardId, className }: { cardId: string; className?: string }) {
  const t = useT();
  const draft = usePlanDraft(cardId);
  const written = writtenComments(draft).length;
  const marks = [
    draft.plan !== null ? t("plan_review.edited") : "",
    written ? fill(t(`plan_review.comments_${plural(t("trace_report.locale"), written)}`), { count: written }) : "",
  ].filter(Boolean).join(" · ");
  if (!marks) return null;
  return <span data-testid="plan-draft-marks" className={cn("text-xs text-muted-foreground", className)}>{marks}</span>;
}

export function PlanReviewButton({ cardId, plan, supported, onAnswer, pending = null, error, buildHint, className }: {
  cardId: string;
  /** The agent's plan, as Markdown. */
  plan: string;
  /**
   * Whether the backend takes a review with the answer (the catalog's
   * `plan_review`). False on a backend older than this window: the plan is
   * read only until the app has restarted, so no edit is made that would be lost.
   */
  supported: boolean;
  /** Absent where the card cannot be answered: the window only shows the plan. */
  onAnswer?: (answer: PlanAnswer) => void;
  pending?: PlanAnswer | null;
  error?: string;
  buildHint?: string;
  className?: string;
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  // Once opened the window stays mounted, so opening it again is instant.
  const [loaded, setLoaded] = useState(false);
  return <>
    <button type="button" data-testid="plan-review-open" title={t("plan_review.open_title")}
      onClick={() => { setLoaded(true); setOpen(true); }}
      className={cn(
        "flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-sm text-foreground hover:bg-secondary",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        className,
      )}>
      <Maximize2 aria-hidden className="h-3.5 w-3.5" />{t("plan_review.open")}
    </button>
    {loaded && <Suspense fallback={null}>
      <PlanReviewDialog cardId={cardId} plan={plan} open={open} onOpenChange={setOpen}
        onAnswer={supported ? onAnswer : undefined} pending={pending} error={error} buildHint={buildHint}
        readOnlyNote={supported || !onAnswer ? undefined : t("plan_review.needs_restart")} />
    </Suspense>}
  </>;
}
