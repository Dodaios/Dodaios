/**
 * Recently learned — the learning ledger, newest first, set like a journal:
 * when it happened in the label column, what was written beside it, where
 * it went in quiet ink, and the person's own words when there are some —
 * so "why does it think that?" has an answer on the page. Above the list,
 * the newest review: where it ran and how it was billed, and when it failed
 * or gave up, so a cost on the API key or a lost review is never a surprise.
 */
import { useT, useUiLanguage } from "@/i18n";
import { cn } from "@/lib/utils";
import type { SoulActivity, SoulReview } from "@/views/assistant/api";
import { parseLedgerTime, whenShort } from "@/views/assistant/format";
import { splitDated } from "@/views/assistant/MemorySection";
import { Section, SpecRow } from "@/views/assistant/Section";

const KNOWN_OPS = new Set(["add", "replace", "remove"]);
const KNOWN_PLACES = new Set(["soul", "memory", "user"]);
/** Ledger billing value -> locale key suffix. */
const BILLING_KEYS: Record<string, string> = {
  subscription: "subscription",
  local: "local",
  metered: "api_key",
};
const OUTCOMES = new Set(["answered", "failed", "dropped"]);

function LastReview({ review }: { review: SoulReview }) {
  const t = useT();
  const lang = useUiLanguage();
  const outcome = OUTCOMES.has(review.outcome) ? review.outcome : "answered";
  const seat = review.seat_label || review.seat || "";
  const billing = BILLING_KEYS[review.billing ?? ""];
  const line = seat
    ? t(`assistant_view.review_${outcome}`).replace("{0}", seat)
    : t("assistant_view.review_no_seat");
  return (
    <div data-testid="assistant-last-review" className="border-b border-border">
      <SpecRow
        label={<span className="tabular-nums">{whenShort(parseLedgerTime(review.ts), lang) ?? "–"}</span>}
      >
        <p className={cn(outcome !== "answered" && "text-warning")}>{line}</p>
        {/* Only a review that answered was billed. */}
        {outcome === "answered" && seat && billing && (
          <p className="mt-1 text-sm text-muted-foreground">{t(`assistant_view.billing_${billing}`)}</p>
        )}
      </SpecRow>
    </div>
  );
}

export function RecentSection({
  activity,
  lastReview,
}: {
  activity: readonly SoulActivity[];
  lastReview?: SoulReview | null;
}) {
  const t = useT();
  const lang = useUiLanguage();

  return (
    <Section testId="assistant-recent" title={t("assistant_view.recent_title")}>
      {lastReview && <LastReview review={lastReview} />}
      {activity.length === 0 ? (
        <p className="text-base text-muted-foreground">{t("assistant_view.recent_empty")}</p>
      ) : (
        <div className="divide-y divide-border">
          {activity.map((item, i) => {
            const op = KNOWN_OPS.has(item.operation) ? item.operation : "add";
            const place = KNOWN_PLACES.has(item.target)
              ? t(`assistant_view.place_${item.target}`)
              : item.target;
            const said = item.evidence && item.evidence !== "[withheld]" ? item.evidence : "";
            const via = BILLING_KEYS[item.billing ?? ""];
            const opLine = t(`assistant_view.op_${op}`).replace("{0}", place);
            return (
              <SpecRow
                key={`${item.ts}-${i}`}
                label={<span className="tabular-nums">{whenShort(parseLedgerTime(item.ts), lang) ?? "–"}</span>}
              >
                <p className={cn(op === "remove" && "text-muted-foreground line-through decoration-foreground-faint")}>
                  {splitDated(item.text).body || "–"}
                </p>
                <p className="mt-1 text-sm text-muted-foreground">
                  {via ? `${opLine} · ${t(`assistant_view.via_${via}`)}` : opLine}
                </p>
                {said && (
                  <p className="mt-2 text-sm italic leading-6 text-muted-foreground">
                    {t("assistant_view.said").replace("{0}", said)}
                  </p>
                )}
              </SpecRow>
            );
          })}
        </div>
      )}
    </Section>
  );
}
