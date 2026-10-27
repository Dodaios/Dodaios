/**
 * The page's state in one calm line under the title: learning (with how far
 * along), paused, off or stopped, each with the one button that changes it.
 * While it is simply watching there is nothing to say, so nothing shows.
 */
import type { ReactNode } from "react";
import { Loader2, OctagonX, Pause, Power, Sprout } from "lucide-react";
import { fill, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { DAY_MS, type SelfBuildStatus } from "@/lib/selfBuildApi";

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

export interface BannerAction {
  label: string;
  onClick: () => void;
  busy?: boolean;
  testId: string;
}

export function StatusBanner({
  tone,
  quiet,
  locale,
  action,
}: {
  tone: HeroTone;
  quiet: { days: number; since_ms: number; until_ms: number } | undefined;
  locale: string;
  action?: BannerAction;
}) {
  const t = useT();
  if (tone === "running") return null;

  let icon: ReactNode;
  let title: string;
  let body: string;
  let progress: number | null = null;
  if (tone === "silent") {
    const days = quiet?.days ?? 7;
    const day = quiet ? quietDay(quiet.since_ms, days) : 1;
    const date = quiet?.until_ms
      ? new Date(quiet.until_ms).toLocaleDateString(locale, { weekday: "long", day: "numeric", month: "long" })
      : "";
    icon = <Sprout className="h-4 w-4" aria-hidden />;
    title = fill(t("self_build.page.learning_title"), { day, days });
    body = date
      ? fill(t("self_build.page.learning_body"), { date })
      : fill(t("self_build.page.learning_body_nodate"), { days });
    progress = days > 0 ? day / days : 0;
  } else {
    icon =
      tone === "paused" ? (
        <Pause className="h-4 w-4" aria-hidden />
      ) : tone === "stopped" ? (
        <OctagonX className="h-4 w-4" aria-hidden />
      ) : (
        <Power className="h-4 w-4" aria-hidden />
      );
    title = t(`self_build.hero.${tone}_title`);
    body = t(`self_build.hero.${tone}_body`);
  }

  return (
    <section
      data-testid="self-build-banner"
      data-tone={tone}
      className="mt-8 flex flex-wrap items-center gap-x-4 gap-y-3 rounded-xl border border-border bg-card px-4 py-3.5"
    >
      <span
        className={cn(
          "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg",
          tone === "stopped" ? "bg-destructive/10 text-destructive" : "bg-secondary text-foreground",
        )}
      >
        {icon}
      </span>
      <div className="min-w-0 flex-1 basis-[240px]">
        <p className="text-sm font-medium text-foreground-strong">{title}</p>
        <p className="mt-0.5 text-sm text-muted-foreground">{body}</p>
      </div>
      {progress !== null && (
        <div
          className="h-1.5 w-28 shrink-0 overflow-hidden rounded-full bg-secondary"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(progress * 100)}
          aria-label={title}
        >
          <div className="h-full rounded-full bg-accent" style={{ width: `${Math.round(progress * 100)}%` }} />
        </div>
      )}
      {action && (
        <button
          type="button"
          data-testid={action.testId}
          onClick={action.onClick}
          disabled={action.busy}
          className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60"
        >
          {action.busy && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />}
          {action.label}
        </button>
      )}
    </section>
  );
}
