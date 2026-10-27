/**
 * "Noticed": the requests the person repeats, each with how close it is to
 * becoming a suggestion. It is the proof that the page is working before
 * anything is built. Only the person's own requests count
 * (dodaios/self_build/miner.py); the labels are their own latest wording, cut
 * short by the route.
 *
 * Also "How does this work?": three plain steps behind one quiet toggle.
 */
import { useState } from "react";
import { ChevronDown, MessageSquareText } from "lucide-react";
import { fill, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import type { Noticed as NoticedData, NoticedNeed } from "@/lib/selfBuildApi";
import { Group, Row, Section } from "./List";
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
  if (!data || data.needs.length === 0) return null;
  const { needs, once, more, threshold } = data;
  const footer = [
    more > 0 ? fill(t("self_build.noticed.more"), { count: more }) : "",
    once > 0 ? fill(t(once === 1 ? "self_build.noticed.once_one" : "self_build.noticed.once_other"), { count: once }) : "",
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <div data-testid="self-build-noticed">
      <Section id="noticed" title={t("self_build.noticed.title")} count={needs.length}>
        <Group>
          {needs.map((need) => (
            <NeedRow
              key={need.id}
              need={need}
              days={threshold.days}
              times={threshold.times}
              locale={locale}
              paused={paused}
              onOpenBuild={onOpenBuild}
            />
          ))}
        </Group>
        <p className="mt-2.5 px-1 text-sm text-muted-foreground">
          {fill(t("self_build.page.noticed_rule"), { days: threshold.days })}
          {footer && <span className="text-foreground-faint"> · {footer}</span>}
        </p>
      </Section>
    </div>
  );
}

function NeedRow({
  need,
  days,
  times,
  locale,
  paused,
  onOpenBuild,
}: {
  need: NoticedNeed;
  days: number;
  times: number;
  locale: string;
  paused: boolean;
  onOpenBuild: (id: string) => void;
}) {
  const t = useT();
  const reached = Math.min(need.days, days);
  const sub = [
    fill(t("self_build.noticed.times"), { count: need.times }),
    fill(t(need.days === 1 ? "self_build.noticed.days_one" : "self_build.noticed.days_other"), { count: need.days }),
    relativeTime(need.last_ms, locale),
  ].join(" · ");

  let right: React.ReactNode;
  if (need.stage === "counting") {
    right = (
      <span className="flex items-center gap-3">
        <span className="text-sm tabular-nums text-muted-foreground">{stageText(need, days, times, paused, t).text}</span>
        <span
          role="img"
          aria-label={fill(t("self_build.noticed.progress"), { count: reached, total: days })}
          className="h-1.5 w-16 overflow-hidden rounded-full bg-secondary"
        >
          <span className="block h-full rounded-full bg-foreground-strong" style={{ width: `${Math.round((reached / Math.max(1, days)) * 100)}%` }} />
        </span>
      </span>
    );
  } else if (need.stage === "proposed" && need.build_id) {
    right = (
      <button
        type="button"
        onClick={() => onOpenBuild(need.build_id)}
        className="rounded-sm text-sm font-medium text-accent hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        {t("self_build.noticed.stage.proposed")}
      </button>
    );
  } else {
    const { text, tone } = stageText(need, days, times, paused, t);
    right = <span className={cn("text-sm", tone)}>{text}</span>;
  }

  return (
    <Row
      testId="noticed-need"
      data={{ stage: need.stage }}
      icon={<MessageSquareText className="h-4 w-4" strokeWidth={1.75} />}
      title={
        <span title={need.label}>
          {t("self_build.noticed.quote_open")}
          {need.label}
          {t("self_build.noticed.quote_close")}
        </span>
      }
      sub={sub}
      right={right}
    />
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

// ------------------------------------------------------------------ how it works

const STEPS = ["notice", "suggest", "try"] as const;

export function HowItWorks({ center = false }: { center?: boolean }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  return (
    <section data-testid="self-build-how" className={cn("mt-10 px-1", center && "flex flex-col items-center")}>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1.5 rounded-sm text-sm text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        {t("self_build.page.how_toggle")}
        <ChevronDown aria-hidden className={cn("h-3.5 w-3.5 transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <ol className={cn("mt-4 space-y-3", center && "max-w-[52ch] text-left")}>
          {STEPS.map((key, index) => (
            <li key={key} className="flex gap-3">
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-secondary text-xs tabular-nums text-foreground">
                {index + 1}
              </span>
              <p className="text-sm leading-relaxed text-muted-foreground">
                <span className="font-medium text-foreground">{t(`self_build.how.${key}_title`)}.</span>{" "}
                {t(`self_build.how.${key}_body`)}
              </p>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
