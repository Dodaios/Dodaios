/**
 * The pieces the standing tasks share between their list, their form and a
 * task's own page: the dot that says whether a task runs, the level as one
 * radio group, and the pace picker.
 */
import { BrandedSelect } from "@/components/ui/select";
import { useT, useUiLanguage } from "@/i18n";
import type { StandingAutonomy, StandingLimits, StandingState, StandingTask } from "@/lib/standingTasksApi";
import { cn } from "@/lib/utils";
import { AUTONOMY_ORDER, TONE_INK, outcomeTone, outcomeWords, paceOptions } from "@/views/assistant/standingWords";

const DOT: Record<StandingState, string> = {
  // A suggestion is news, a running task is live, a paused or ended one is neither.
  proposed: "bg-info",
  active: "bg-success",
  paused: "bg-foreground-faint",
  ended: "bg-foreground-faint",
};

export function StateDot({ state, className }: { state: StandingState; className?: string }) {
  return <span aria-hidden data-state={state} className={cn("h-1.5 w-1.5 shrink-0 rounded-full", DOT[state] ?? DOT.ended, className)} />;
}

/**
 * What the last look found: the outcome in words, then its summary. Only the
 * words wear a status hue (a look that needs the person, one that failed);
 * the sentence stays in the ink of the line it sits in.
 */
export function Finding({ task }: { task: Pick<StandingTask, "last_outcome" | "last_summary"> }) {
  const t = useT();
  const words = outcomeWords(task.last_outcome, t);
  const summary = task.last_summary.trim();
  if (!words) return summary ? <>{summary}</> : null;
  const tone = outcomeTone(task.last_outcome);
  return (
    <>
      <span data-outcome={task.last_outcome} className={cn(tone !== "plain" && "font-medium", TONE_INK[tone])}>
        {words}
      </span>
      {summary ? `: ${summary}` : ""}
    </>
  );
}

/**
 * How far the assistant may go, in the grammar of the Initiative setting: a
 * plain ring that fills for the chosen level, its name, and what it means.
 */
export function AutonomyChoice({
  value,
  levels,
  onChange,
  disabled = false,
  testId,
}: {
  value: StandingAutonomy;
  /** The levels the server offers; all three while it has not answered. */
  levels?: readonly StandingAutonomy[];
  onChange: (level: StandingAutonomy) => void;
  disabled?: boolean;
  testId: string;
}) {
  const t = useT();
  const offered = AUTONOMY_ORDER.filter((level) => !levels?.length || levels.includes(level));
  return (
    <div role="radiogroup" aria-label={t("standing.autonomy_label")} className="flex flex-col gap-1">
      {offered.map((level) => {
        const selected = level === value;
        return (
          <button
            key={level}
            type="button"
            role="radio"
            aria-checked={selected}
            data-testid={`${testId}-${level}`}
            disabled={disabled}
            onClick={() => onChange(level)}
            className={cn(
              "flex w-full flex-col gap-x-4 rounded-sm text-left text-base leading-7 sm:flex-row",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              "disabled:cursor-default",
            )}
          >
            <span className="flex h-7 w-32 shrink-0 items-center gap-2.5">
              <span
                aria-hidden
                className={cn(
                  "flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-full border",
                  selected ? "border-foreground-strong" : "border-muted-foreground",
                )}
              >
                {selected && <span className="h-1.5 w-1.5 rounded-full bg-foreground-strong" />}
              </span>
              <span className={selected ? "font-medium text-foreground-strong" : "text-muted-foreground"}>
                {t(`standing.autonomy_${level}`)}
              </span>
            </span>
            <span className={cn("min-w-0 flex-1", selected ? "text-foreground" : "text-muted-foreground")}>
              {t(`standing.autonomy_${level}_hint`)}
            </span>
          </button>
        );
      })}
    </div>
  );
}

/** How often the assistant looks, as one of a few natural paces. */
export function PaceSelect({
  value,
  limits,
  onChange,
  disabled = false,
  testId,
  id,
}: {
  value: number;
  limits: StandingLimits | undefined;
  onChange: (minutes: number) => void;
  disabled?: boolean;
  testId: string;
  id?: string;
}) {
  const t = useT();
  const lang = useUiLanguage();
  return (
    <BrandedSelect
      id={id}
      value={String(Math.round(value))}
      options={paceOptions(limits, value, t, lang)}
      onValueChange={(minutes) => onChange(Number(minutes))}
      ariaLabel={t("standing.pace_label")}
      disabled={disabled}
      testId={testId}
      className="h-9 w-60 max-w-full text-base"
    />
  );
}
