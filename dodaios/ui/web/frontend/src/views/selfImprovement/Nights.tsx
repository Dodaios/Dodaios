/**
 * "The last nights": per night its date and one short line for each thing it
 * did — an update it found, the test tasks it built from the person's own
 * memory and messages (or that no model could be asked for them), what it
 * checked, proposed and decided (with the
 * outcome and the numbers), and the advantage it measured. Three show; the
 * rest fold away. A change that was already kept and still holds is not news,
 * so those are counted in one line instead of listed.
 */
import { useState } from "react";
import { ChevronDown } from "lucide-react";
import { fill, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import type { Night, NightDecision } from "@/lib/selfImprovementApi";
import { Section } from "../selfBuild/List";
import { areaName, effectWords, fmtPoints, fmtValue, nightDate, paramTitle, wordFor } from "./words";

const SHOWN = 3;

type T = (key: string) => string;

function decisionEffect(t: T, row: NightDecision, locale: string): string {
  const target = row.evidence?.target;
  if (!target) return "";
  return effectWords(
    t,
    {
      ts_ms: 0,
      step: "",
      verdict: row.evidence.verdict,
      split: row.evidence.split,
      reason: "",
      domain: target.domain,
      diff: target.diff,
      low: target.low,
      high: target.high,
      n: target.n,
      cost_diff: target.cost_diff,
    },
    locale,
  );
}

/** The lines of one night, in the order it worked. */
export function nightLines(t: T, night: Night, locale: string): string[] {
  if (night.paused) return [t("self_improvement.nights.paused")];
  const out: string[] = [];
  if (night.updated_from) {
    out.push(fill(t("self_improvement.nights.updated"), { from: night.updated_from, to: night.app }));
  }
  // A night builds tasks first, so what it built comes first.
  const made = night.made ?? {};
  const built = (made.questions ?? 0) + (made.messages ?? 0);
  if (built > 0) {
    out.push(fill(t(built === 1 ? "self_improvement.nights.built_one" : "self_improvement.nights.built_other"), { count: built }));
  }
  if ((made.forgotten ?? 0) > 0) {
    const count = made.forgotten ?? 0;
    out.push(fill(t(count === 1 ? "self_improvement.nights.erased_one" : "self_improvement.nights.erased_other"), { count }));
  }
  if (made.deferred && built === 0) out.push(t("self_improvement.nights.deferred"));
  let holding = 0;
  for (const row of night.settled ?? []) {
    if (row.outcome === "kept" && row.was === "live") {
      holding += 1;
      continue;
    }
    const effect = decisionEffect(t, row, locale);
    out.push(
      fill(t(effect ? "self_improvement.nights.checked" : "self_improvement.nights.checked_bare"), {
        title: paramTitle(t, row.target),
        outcome: wordFor(t, "outcome", row.outcome),
        effect,
      }),
    );
  }
  if (holding > 0) {
    out.push(fill(t(holding === 1 ? "self_improvement.nights.holding_one" : "self_improvement.nights.holding_other"), { count: holding }));
  }
  for (const row of night.proposed ?? []) {
    out.push(
      fill(t("self_improvement.nights.proposed"), {
        title: paramTitle(t, row.target),
        from: fmtValue(row.current, locale),
        to: fmtValue(row.value, locale),
      }),
    );
  }
  for (const row of night.decided ?? []) {
    const effect = decisionEffect(t, row, locale);
    out.push(
      fill(t(effect ? "self_improvement.nights.decided" : "self_improvement.nights.decided_bare"), {
        title: paramTitle(t, row.target),
        outcome: wordFor(t, "outcome", row.outcome),
        effect,
      }),
    );
  }
  for (const point of night.measured ?? []) {
    out.push(
      fill(t("self_improvement.nights.measured"), {
        area: areaName(t, point.domain),
        points: fmtPoints(point.diff, locale),
        n: point.n,
      }),
    );
  }
  return out.length ? out : [t("self_improvement.nights.idle")];
}

export function NightsSection({ nights, locale }: { nights: readonly Night[]; locale: string }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  if (!nights.length) return null;
  const shown = open ? nights : nights.slice(0, SHOWN);
  const more = nights.length - SHOWN;
  return (
    <Section
      id="si-nights"
      title={t("self_improvement.nights.title")}
      aside={
        more > 0 ? (
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            data-testid="si-nights-toggle"
            className="inline-flex items-center gap-1 rounded-sm text-sm text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {open
              ? t("self_improvement.nights.hide")
              : fill(t(more === 1 ? "self_improvement.nights.show_one" : "self_improvement.nights.show_other"), { count: more })}
            <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", open && "rotate-180")} aria-hidden />
          </button>
        ) : undefined
      }
    >
      <ol className="divide-y divide-border overflow-hidden rounded-md border border-border bg-card">
        {shown.map((night) => (
          <li key={night.ts_ms} data-testid="si-night" className="grid grid-cols-[9.5rem_1fr] gap-4 px-4 py-3">
            <time
              dateTime={new Date(night.ts_ms).toISOString()}
              className="text-sm tabular-nums text-muted-foreground"
            >
              {nightDate(night.ts_ms, locale)}
            </time>
            <ul className="min-w-0 space-y-1">
              {nightLines(t, night, locale).map((line, index) => (
                <li key={index} className="text-sm leading-relaxed text-foreground">
                  {line}
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ol>
    </Section>
  );
}
