/**
 * The top of "Built for you": one sentence that says what this page is and
 * whether it is working, a ring that shows it at a glance (the quiet start's
 * days, the helpers running, or paused), and how far the assistant may go per
 * kind of helper, in plain words.
 */
import type { ReactNode } from "react";
import { Loader2, OctagonX, Pause, Power } from "lucide-react";
import { fill, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { BUILD_KINDS, DAY_MS, type Autonomy, type SelfBuildStatus } from "@/lib/selfBuildApi";
import { KindIcon } from "./shared";

export type HeroTone = "silent" | "running" | "paused" | "off" | "stopped";

export function heroTone(status: SelfBuildStatus | undefined, stopped: boolean): HeroTone | null {
  if (stopped) return "stopped";
  if (!status) return null;
  if (!status.enabled) return "off";
  if (status.paused) return "paused";
  return status.silent ? "silent" : "running";
}

/** Day `n` of the quiet start, counted from 1, never past its last day. */
export function quietDay(sinceMs: number, days: number, now = Date.now()): number {
  if (!sinceMs || days <= 0) return 0;
  return Math.min(days, Math.max(1, Math.floor((now - sinceMs) / DAY_MS) + 1));
}

export function Hero({
  tone,
  status,
  quiet,
  waiting,
  live,
  locale,
  action,
}: {
  tone: HeroTone;
  status: SelfBuildStatus | undefined;
  quiet: { days: number; since_ms: number; until_ms: number } | undefined;
  waiting: number;
  live: number;
  locale: string;
  action?: { label: string; onClick: () => void; busy?: boolean; testId: string; icon?: ReactNode };
}) {
  const t = useT();
  const day = quiet ? quietDay(quiet.since_ms, quiet.days) : 0;
  const until =
    quiet && quiet.until_ms
      ? new Date(quiet.until_ms).toLocaleDateString(locale, { weekday: "long", day: "numeric", month: "long" })
      : "";

  let headline: string;
  let body: string;
  if (tone === "silent") {
    headline = t("self_build.hero.silent_title");
    body = fill(t(until ? "self_build.hero.silent_body" : "self_build.hero.silent_body_nodate"), {
      days: quiet?.days ?? 7,
      date: until,
    });
  } else if (tone === "running") {
    headline =
      waiting > 0
        ? fill(t(waiting === 1 ? "self_build.hero.ideas_title_one" : "self_build.hero.ideas_title_other"), { count: waiting })
        : t("self_build.hero.running_title");
    body = t(waiting > 0 ? "self_build.hero.ideas_body" : "self_build.hero.running_body");
  } else {
    headline = t(`self_build.hero.${tone}_title`);
    body = t(`self_build.hero.${tone}_body`);
  }

  return (
    <section
      data-testid="self-build-hero"
      data-tone={tone}
      aria-labelledby="self-build-hero-title"
      className="mt-6 overflow-hidden rounded-2xl border border-border bg-card"
    >
      <div className="flex flex-col gap-6 px-6 py-7 sm:flex-row sm:items-center sm:gap-8 sm:px-8 sm:py-8">
        <Ring tone={tone} day={day} days={quiet?.days ?? 0} live={live} />
        <div className="min-w-0 flex-1">
          <h2
            id="self-build-hero-title"
            className="font-display text-2xl font-semibold leading-[34px] tracking-[-0.02em] text-foreground-strong"
          >
            {headline}
          </h2>
          <p className="mt-2 max-w-[60ch] text-lg leading-relaxed text-muted-foreground">{body}</p>
          {action && (
            <button
              type="button"
              data-testid={action.testId}
              onClick={action.onClick}
              disabled={action.busy}
              className="mt-5 inline-flex h-9 items-center gap-2 rounded-md bg-primary px-4 text-base font-medium text-primary-foreground transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60"
            >
              {action.busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : action.icon}
              {action.label}
            </button>
          )}
        </div>
      </div>
      {status && tone !== "off" && <Reach status={status} />}
    </section>
  );
}

const RING_R = 44;
const RING_C = 2 * Math.PI * RING_R;

/**
 * The ring: the quiet start fills day by day; while watching it is whole and
 * holds the number of helpers running; paused, off and stopped are grey with
 * their glyph.
 */
function Ring({ tone, day, days, live }: { tone: HeroTone; day: number; days: number; live: number }) {
  const t = useT();
  const share = tone === "silent" ? (days > 0 ? day / days : 0) : tone === "running" ? 1 : 0;
  const label =
    tone === "silent"
      ? fill(t("self_build.hero.ring_day"), { day, days })
      : tone === "running"
        ? fill(t(live === 1 ? "self_build.hero.ring_live_one" : "self_build.hero.ring_live_other"), { count: live })
        : t(`self_build.status.${tone}`);
  return (
    <div
      className="relative h-[112px] w-[112px] shrink-0"
      role="img"
      aria-label={label}
      data-testid="self-build-ring"
    >
      <svg viewBox="0 0 112 112" className="h-full w-full -rotate-90" aria-hidden>
        <circle cx="56" cy="56" r={RING_R} fill="none" strokeWidth="7" className="stroke-secondary" />
        <circle
          cx="56"
          cy="56"
          r={RING_R}
          fill="none"
          strokeWidth="7"
          strokeLinecap="round"
          strokeDasharray={RING_C}
          strokeDashoffset={RING_C * (1 - share)}
          className={cn(
            "transition-[stroke-dashoffset] duration-700 ease-out",
            tone === "running" ? "stroke-success" : "stroke-accent",
          )}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center text-center" aria-hidden>
        {tone === "silent" ? (
          <>
            <span className="font-display text-[30px] font-semibold leading-none tabular-nums text-foreground-strong">{day}</span>
            <span className="mt-1 text-xs text-muted-foreground">{fill(t("self_build.hero.ring_of_days"), { days })}</span>
          </>
        ) : tone === "running" ? (
          live > 0 ? (
            <>
              <span className="font-display text-[30px] font-semibold leading-none tabular-nums text-foreground-strong">{live}</span>
              <span className="mt-1 text-xs text-muted-foreground">{t(live === 1 ? "self_build.hero.ring_helper_one" : "self_build.hero.ring_helper_other")}</span>
            </>
          ) : (
            <span className="relative flex h-3 w-3">
              <span className="absolute inline-flex h-full w-full rounded-full bg-success opacity-60 motion-safe:animate-ping" />
              <span className="relative inline-flex h-3 w-3 rounded-full bg-success" />
            </span>
          )
        ) : tone === "paused" ? (
          <Pause className="h-7 w-7 text-muted-foreground" strokeWidth={1.6} />
        ) : tone === "stopped" ? (
          <OctagonX className="h-7 w-7 text-destructive" strokeWidth={1.6} />
        ) : (
          <Power className="h-7 w-7 text-muted-foreground" strokeWidth={1.6} />
        )}
      </div>
    </div>
  );
}

const LEVEL_TONE: Record<Autonomy, string> = {
  off: "text-foreground-faint",
  suggest: "text-foreground",
  trial: "text-foreground",
  full: "text-foreground",
};

/** How far it may go, per kind of helper, in the words a person uses. */
function Reach({ status }: { status: SelfBuildStatus }) {
  const t = useT();
  return (
    <div className="border-t border-border px-6 py-4 sm:px-8" data-testid="self-build-reach">
      <p className="mb-3 text-sm font-medium text-muted-foreground">{t("self_build.reach.title")}</p>
      <ul className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-3 lg:grid-cols-5">
        {BUILD_KINDS.map((kind) => {
          const level = status.autonomy[kind] ?? "suggest";
          return (
            <li key={kind} className="flex min-w-0 items-start gap-2.5" data-kind={kind} data-level={level}>
              <span className="mt-0.5 text-muted-foreground">
                <KindIcon kind={kind} />
              </span>
              <span className="min-w-0">
                <span className="block truncate text-sm text-muted-foreground">{t(`self_build.kinds.${kind}`)}</span>
                <span className={cn("block text-base leading-snug", LEVEL_TONE[level])}>{t(`self_build.reach.${level}`)}</span>
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
