/**
 * Pieces "Built for you" shares between its list and its detail: the glyph
 * per kind, the lifecycle rail, and short relative times.
 */
import { Clock } from "lucide-react";
import { AgentsIcon, CodeIcon, SkillIcon, WikiIcon } from "@/components/icons/sectionIcons";
import { cn } from "@/lib/utils";
import {
  lifecycleSteps,
  type BuildKind,
  type BuildState,
} from "@/lib/selfBuildApi";

const KIND_ICON = {
  memory: WikiIcon,
  skill: SkillIcon,
  routine: Clock,
  agent: AgentsIcon,
  code: CodeIcon,
} as const;

export function KindIcon({ kind, className }: { kind: BuildKind; className?: string }) {
  const Icon = KIND_ICON[kind] ?? SkillIcon;
  return <Icon aria-hidden strokeWidth={1.6} className={cn("h-4 w-4 shrink-0", className)} />;
}

/** The states that end a build off the forward path, and the ink each one carries. */
const END_TONE: Partial<Record<BuildState, string>> = {
  archived: "text-muted-foreground",
  undone: "text-muted-foreground",
  rejected: "text-muted-foreground",
  failed: "text-destructive",
};

/**
 * Where a build stands on the path Noticed → Built → Checked → Trial → Kept.
 *
 * Reached steps are filled, the step the build stands on carries a ring, the
 * rest are hollow. A build that left the path (archived, undone, turned down,
 * failed) keeps its reached steps and ends in a short branch with the end
 * state's name, so "how far did it get before it stopped" stays readable.
 */
export function LifecycleRail({
  state,
  reached,
  labels,
  compact = false,
}: {
  state: BuildState;
  reached: number;
  labels?: Record<string, string>;
  compact?: boolean;
}) {
  const steps = lifecycleSteps();
  const onPath = steps.includes(state);
  const endLabel = !onPath && labels ? labels[`end:${state}`] : undefined;
  if (!compact) {
    // Five equal columns over one track: the filled part of the track runs
    // from the first step to the last one reached.
    const span = steps.length - 1;
    const filled = Math.max(0, Math.min(reached, span)) / span;
    return (
      <div className="flex items-start gap-3" data-testid="build-rail" data-state={state} data-reached={reached}>
        <div className="relative grid min-w-0 flex-1 grid-cols-5">
          <span aria-hidden className="absolute left-[10%] right-[10%] top-[5px] h-px bg-border-strong" />
          <span
            aria-hidden
            className={cn("absolute left-[10%] top-[5px] h-px", onPath ? "bg-foreground-strong" : "bg-muted-foreground")}
            style={{ width: `${filled * 80}%` }}
          />
          {steps.map((step, index) => {
            const done = index <= reached;
            const here = onPath && index === reached;
            const live = here && state !== "kept" && state !== "proposed";
            return (
              <div key={step} className="relative flex min-w-0 flex-col items-center">
                <span
                  aria-hidden
                  className={cn(
                    "block h-[11px] w-[11px] rounded-full border-2 transition-colors",
                    done
                      ? onPath
                        ? "border-foreground-strong bg-foreground-strong"
                        : "border-muted-foreground bg-muted-foreground"
                      : "border-border-strong bg-card",
                    here && "ring-4 ring-accent/25",
                    live && "motion-safe:animate-pulse",
                  )}
                />
                {labels && (
                  <span
                    className={cn(
                      "mt-2 max-w-full truncate text-xs",
                      here ? "font-medium text-foreground-strong" : done ? "text-foreground" : "text-muted-foreground",
                    )}
                  >
                    {labels[step]}
                  </span>
                )}
              </div>
            );
          })}
        </div>
        {!onPath && endLabel && (
          <span
            className={cn(
              "-mt-1 shrink-0 rounded-full border border-border px-2 py-0.5 text-xs",
              END_TONE[state] ?? "text-muted-foreground",
            )}
            data-testid="build-rail-end"
          >
            {endLabel}
          </span>
        )}
      </div>
    );
  }
  // The row's mini rail: five dots and four short rules, no labels.
  return (
    <div className="flex items-center gap-1" data-testid="build-rail-mini" data-state={state} data-reached={reached}>
      {steps.map((step, index) => {
        const done = index <= reached;
        return (
          <div key={step} className="flex items-center gap-1">
            <span
              aria-hidden
              className={cn(
                "block h-1.5 w-1.5 rounded-full border",
                done
                  ? onPath
                    ? "border-foreground-strong bg-foreground-strong"
                    : "border-muted-foreground bg-muted-foreground"
                  : "border-border-strong bg-transparent",
              )}
            />
            {index < steps.length - 1 && (
              <span aria-hidden className={cn("block h-px w-2", index < reached && onPath ? "bg-foreground-strong" : "bg-border-strong")} />
            )}
          </div>
        );
      })}
    </div>
  );
}

/** "3 hours ago", "yesterday" — short, in the interface language. */
export function relativeTime(ms: number, locale: string, now = Date.now()): string {
  if (!ms) return "";
  const seconds = Math.round((ms - now) / 1000);
  const abs = Math.abs(seconds);
  const format = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  if (abs < 60) return format.format(Math.round(seconds), "second");
  if (abs < 3_600) return format.format(Math.round(seconds / 60), "minute");
  if (abs < 86_400) return format.format(Math.round(seconds / 3_600), "hour");
  if (abs < 30 * 86_400) return format.format(Math.round(seconds / 86_400), "day");
  return new Date(ms).toLocaleDateString(locale, { day: "numeric", month: "short", year: "numeric" });
}

export function formatUsd(usd: number, locale: string): string {
  return new Intl.NumberFormat(locale, {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: usd < 1 ? 3 : 2,
  }).format(usd);
}
