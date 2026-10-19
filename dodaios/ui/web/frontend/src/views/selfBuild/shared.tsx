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
  return (
    <div
      className={cn("flex items-center", compact ? "gap-1" : "gap-0")}
      data-testid={compact ? "build-rail-mini" : "build-rail"}
      data-state={state}
      data-reached={reached}
    >
      {steps.map((step, index) => {
        const done = index <= reached;
        const here = onPath && index === reached;
        const live = here && state !== "kept" && state !== "proposed";
        return (
          <div key={step} className={cn("flex items-center", !compact && "min-w-0 flex-1")}>
            <div className={cn("flex flex-col items-center", !compact && "min-w-0")}>
              <span
                aria-hidden
                className={cn(
                  "block rounded-full border transition-colors",
                  compact ? "h-1.5 w-1.5" : "h-2.5 w-2.5",
                  done ? "border-foreground-strong bg-foreground-strong" : "border-border-strong bg-transparent",
                  here && !compact && "ring-4 ring-accent/25",
                  live && "motion-safe:animate-pulse",
                  !onPath && done && index === reached && "border-muted-foreground bg-muted-foreground",
                )}
              />
              {!compact && labels && (
                <span
                  className={cn(
                    "mt-2 truncate text-xs",
                    here ? "font-medium text-foreground-strong" : done ? "text-foreground" : "text-muted-foreground",
                  )}
                >
                  {labels[step]}
                </span>
              )}
            </div>
            {index < steps.length - 1 && (
              <span
                aria-hidden
                className={cn(
                  "block h-px",
                  compact ? "w-2" : "mx-1.5 mb-6 flex-1",
                  index < reached ? "bg-foreground-strong" : "bg-border-strong",
                  !onPath && index >= reached && "bg-border",
                )}
              />
            )}
          </div>
        );
      })}
      {!onPath && !compact && endLabel && (
        <span
          className={cn(
            "mb-6 ml-2 shrink-0 rounded-full border border-border px-2 py-0.5 text-xs",
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
