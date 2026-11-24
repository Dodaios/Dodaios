/**
 * "In daily use": how the person's own requests went, week by week — the share
 * that went through without a correction, a repeat, a stop or an error.
 *
 * This is what happened, not a proof of cause: the requests of one week are
 * not those of the next, and the page says so in one sentence. So there is no
 * trend line, no arrow and no good or bad colour; every figure stands beside
 * its number of requests, so a week of 3 is not read like a week of 60. The
 * measured areas above are the ones that compare like with like.
 */
import { fill, useT } from "@/i18n";
import type { DailyUse } from "@/lib/selfImprovementApi";
import { Section } from "../selfBuild/List";
import { fmtPercent } from "./words";

/** The section has something to say only when at least one week was rated. */
export function hasDailyUse(daily: DailyUse | null | undefined): daily is DailyUse {
  return Boolean(daily && daily.weeks.some((week) => week.rated && typeof week.score === "number"));
}

export function DailyUseSection({ daily, locale }: { daily: DailyUse | null | undefined; locale: string }) {
  const t = useT();
  if (!hasDailyUse(daily)) return null;
  const weeks = [...daily.weeks].reverse(); // newest first, like the nights
  return (
    <Section id="si-daily" title={t("self_improvement.daily.title")}>
      <div className="rounded-md border border-border bg-card px-5 py-4" data-testid="si-daily">
        {typeof daily.score === "number" && (
          <p className="text-sm leading-relaxed text-foreground" data-testid="si-daily-summary">
            {fill(t("self_improvement.daily.summary"), {
              pct: fmtPercent(daily.score, locale),
              n: daily.turns.toLocaleString(locale),
              weeks: daily.weeks.length,
            })}
          </p>
        )}
        <p className="mt-1 text-sm leading-relaxed text-muted-foreground" data-testid="si-daily-caveat">
          {t("self_improvement.daily.caveat")}
        </p>
        <table className="mt-4 w-full border-collapse text-sm" data-testid="si-daily-table">
          <thead>
            <tr className="text-muted-foreground">
              <th scope="col" className="border-b border-border py-1.5 pr-3 text-left font-medium">{t("self_improvement.daily.col_week")}</th>
              <th scope="col" className="border-b border-border py-1.5 pl-3 text-right font-medium">{t("self_improvement.daily.col_requests")}</th>
              <th scope="col" className="border-b border-border py-1.5 pl-3 text-right font-medium">{t("self_improvement.daily.col_through")}</th>
            </tr>
          </thead>
          <tbody>
            {weeks.map((week) => (
              <tr key={week.start_ms} data-testid="si-daily-week">
                <th scope="row" className="border-b border-border/50 py-1.5 pr-3 text-left font-normal tabular-nums text-foreground">
                  {fill(t("self_improvement.daily.week_of"), {
                    date: new Date(week.start_ms).toLocaleDateString(locale, { day: "numeric", month: "short" }),
                  })}
                </th>
                <td className="border-b border-border/50 py-1.5 pl-3 text-right tabular-nums text-foreground">
                  {week.turns.toLocaleString(locale)}
                </td>
                <td className="border-b border-border/50 py-1.5 pl-3 text-right tabular-nums text-foreground">
                  {week.rated && typeof week.score === "number" ? (
                    fmtPercent(week.score, locale)
                  ) : (
                    <span className="text-muted-foreground">{t("self_improvement.daily.unrated")}</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Section>
  );
}
