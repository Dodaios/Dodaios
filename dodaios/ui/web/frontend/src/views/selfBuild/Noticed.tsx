/**
 * "Noticed so far": the requests the person repeats, each with how often and
 * on how many days, and how far it is from becoming a suggestion. It is the
 * proof that the page is working before anything is built. Only the person's
 * own requests count (dodaios/self_build/miner.py); the labels are their own
 * latest wording, cut short by the route.
 *
 * Also "How it works": three steps, shown big while nothing is built yet and
 * small once there is.
 */
import { Hand, MessageSquareText, Sparkles } from "lucide-react";
import { fill, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import type { Noticed as NoticedData, NoticedNeed } from "@/lib/selfBuildApi";
import { relativeTime } from "./shared";

export function NoticedSection({
  data,
  locale,
  paused = false,
  onOpenBuild,
}: {
  data: NoticedData | undefined;
  locale: string;
  /** Building is paused: a ready need waits for the resume, not for a look. */
  paused?: boolean;
  onOpenBuild: (id: string) => void;
}) {
  const t = useT();
  if (!data) return null;
  const { needs, once, more, threshold } = data;
  return (
    <section data-testid="self-build-noticed" aria-labelledby="noticed-title" className="mt-12">
      <SectionHead id="noticed-title" title={t("self_build.noticed.title")} hint={t("self_build.noticed.hint")} />
      {needs.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border px-6 py-8 text-center" data-testid="noticed-empty">
          <p className="text-base text-foreground">{t("self_build.noticed.empty")}</p>
          <p className="mt-1 text-sm text-muted-foreground">
            {once > 0
              ? fill(t(once === 1 ? "self_build.noticed.once_one" : "self_build.noticed.once_other"), { count: once })
              : t("self_build.noticed.empty_hint")}
          </p>
        </div>
      ) : (
        <>
          <ul className="overflow-hidden rounded-xl border border-border bg-card">
            {needs.map((need, index) => (
              <NeedRow
                key={need.id}
                need={need}
                days={threshold.days}
                times={threshold.times}
                locale={locale}
                paused={paused}
                first={index === 0}
                onOpenBuild={onOpenBuild}
              />
            ))}
          </ul>
          {(once > 0 || more > 0) && (
            <p className="mt-3 text-sm text-muted-foreground">
              {[
                more > 0 ? fill(t("self_build.noticed.more"), { count: more }) : "",
                once > 0
                  ? fill(t(once === 1 ? "self_build.noticed.once_one" : "self_build.noticed.once_other"), { count: once })
                  : "",
              ]
                .filter(Boolean)
                .join(" · ")}
            </p>
          )}
        </>
      )}
    </section>
  );
}

function NeedRow({
  need,
  days,
  times,
  locale,
  paused,
  first,
  onOpenBuild,
}: {
  need: NoticedNeed;
  days: number;
  times: number;
  locale: string;
  paused: boolean;
  first: boolean;
  onOpenBuild: (id: string) => void;
}) {
  const t = useT();
  const reached = Math.min(need.days, days);
  const meta = [
    fill(t("self_build.noticed.times"), { count: need.times }),
    fill(t(need.days === 1 ? "self_build.noticed.days_one" : "self_build.noticed.days_other"), { count: need.days }),
    relativeTime(need.last_ms, locale),
  ].join(" · ");
  const { text, tone } = stageText(need, days, times, paused, t);
  const stage =
    need.stage === "proposed" && need.build_id ? (
      <button
        type="button"
        onClick={() => onOpenBuild(need.build_id)}
        className="rounded-sm text-sm font-medium text-accent hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        {text}
      </button>
    ) : (
      <span className={cn("text-sm", tone)}>{text}</span>
    );
  return (
    <li
      data-testid="noticed-need"
      data-stage={need.stage}
      className={cn("flex flex-wrap items-center gap-x-6 gap-y-2 px-5 py-4", !first && "border-t border-border")}
    >
      <div className="min-w-0 flex-1 basis-[280px]">
        <p className="truncate text-base text-foreground-strong" title={need.label}>
          {t("self_build.noticed.quote_open")}
          {need.label}
          {t("self_build.noticed.quote_close")}
        </p>
        <p className="mt-0.5 text-sm text-muted-foreground">{meta}</p>
      </div>
      <div className="flex shrink-0 items-center gap-4">
        <span
          className="flex items-center gap-1.5"
          role="img"
          aria-label={fill(t("self_build.noticed.progress"), { count: reached, total: days })}
        >
          {Array.from({ length: days }, (_, i) => (
            <span
              key={i}
              aria-hidden
              className={cn(
                "h-2 w-2 rounded-full",
                i >= reached
                  ? "bg-surface-raised"
                  : need.stage === "counting"
                    ? "bg-foreground-strong"
                    : need.stage === "ready" || need.stage === "proposed"
                      ? "bg-accent"
                      : "bg-foreground-faint",
              )}
            />
          ))}
        </span>
        <span className="w-[240px] text-right">{stage}</span>
      </div>
    </li>
  );
}

function stageText(
  need: NoticedNeed,
  days: number,
  times: number,
  paused: boolean,
  t: (key: string) => string,
): { text: string; tone: string } {
  switch (need.stage) {
    case "counting": {
      const moreDays = Math.max(0, days - need.days);
      if (moreDays > 0) {
        return {
          text: fill(t(moreDays === 1 ? "self_build.noticed.more_days_one" : "self_build.noticed.more_days_other"), { count: moreDays }),
          tone: "text-muted-foreground",
        };
      }
      const moreTimes = Math.max(1, times - need.times);
      return {
        text: fill(t(moreTimes === 1 ? "self_build.noticed.more_times_one" : "self_build.noticed.more_times_other"), { count: moreTimes }),
        tone: "text-muted-foreground",
      };
    }
    case "ready":
      return paused
        ? { text: t("self_build.noticed.stage.ready_paused"), tone: "text-muted-foreground" }
        : { text: t("self_build.noticed.stage.ready"), tone: "text-accent" };
    case "proposed":
      return { text: t("self_build.noticed.stage.proposed"), tone: "text-accent" };
    default:
      return { text: t(`self_build.noticed.stage.${need.stage}`), tone: "text-muted-foreground" };
  }
}

export function SectionHead({ id, title, hint, count }: { id: string; title: string; hint?: string; count?: number }) {
  return (
    <div className="mb-3 flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
      <h2 id={id} className="text-lg font-semibold text-foreground-strong">
        {title}
        {count !== undefined && <span className="ml-2 font-normal tabular-nums text-muted-foreground">{count}</span>}
      </h2>
      {hint && <p className="text-sm text-muted-foreground">{hint}</p>}
    </div>
  );
}

// ------------------------------------------------------------------ how it works

const STEPS = [
  { key: "notice", Icon: MessageSquareText },
  { key: "suggest", Icon: Sparkles },
  { key: "try", Icon: Hand },
] as const;

export function HowItWorks({ compact = false }: { compact?: boolean }) {
  const t = useT();
  return (
    <section
      data-testid="self-build-how"
      data-compact={compact || undefined}
      aria-labelledby="how-title"
      className={compact ? "mt-14" : "mt-10"}
    >
      <h2 id="how-title" className={cn(compact ? "mb-3 text-sm font-medium text-muted-foreground" : "sr-only")}>
        {t("self_build.how.title")}
      </h2>
      <ol className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        {STEPS.map(({ key, Icon }, index) => (
          <li key={key} className={cn("min-w-0", !compact && "rounded-xl border border-border px-5 py-5")}>
            <div className="flex items-center gap-3">
              <span
                aria-hidden
                className={cn(
                  "inline-flex shrink-0 items-center justify-center rounded-lg bg-secondary text-foreground",
                  compact ? "h-7 w-7" : "h-9 w-9",
                )}
              >
                <Icon className={compact ? "h-3.5 w-3.5" : "h-[18px] w-[18px]"} strokeWidth={1.6} />
              </span>
              <p className={cn("font-medium text-foreground-strong", compact ? "text-base" : "text-lg")}>
                <span className="mr-1.5 tabular-nums text-muted-foreground">{index + 1}</span>
                {t(`self_build.how.${key}_title`)}
              </p>
            </div>
            <p className={cn("text-muted-foreground", compact ? "mt-1.5 text-sm" : "mt-3 text-base leading-relaxed")}>
              {t(`self_build.how.${key}_body`)}
            </p>
          </li>
        ))}
      </ol>
    </section>
  );
}
