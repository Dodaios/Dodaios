/**
 * Self-improvement: is the assistant getting better, what did it change in
 * itself, what proved each change, what did the last nights do — and the two
 * controls the person has: stop (or resume), and take one change back.
 *
 * A measuring instrument, not a celebration: one headline number per measured
 * area with the scores and the range behind it, a curve with a table of the
 * same numbers, plain lists after that. A number whose range includes zero is
 * said to be not certain yet. Until there are tasks from the person's own work
 * nothing is measured, and the page says so instead of drawing anything.
 *
 * Data: `GET /api/self-improvement` (dodaios/rsi/overview.py). Live through
 * `SelfChangeChanged` (hooks/useWebSocket.ts) plus a slow safety poll. It
 * never interrupts: no toast, no sound. docs/self-improvement.md.
 */
import { useMemo, useState, type ReactNode } from "react";
import { Loader2 } from "lucide-react";
import { fill, useLocaleChunk, useT } from "@/i18n";
import { useRunLocale } from "@/components/runs/format";
import { cn } from "@/lib/utils";
import { useSelfImprovement, useSelfImprovementPause, useSelfImprovementUndo } from "@/hooks/useSelfImprovement";
import {
  NOTE_SURFACE,
  SelfImprovementApiError,
  type AdvantagePoint,
  type DomainSummary,
  type LearnedChange,
  type Night,
  type RestingValue,
  type SelfImprovementLimits,
  type SelfImprovementOverview,
  type SelfImprovementStatus,
} from "@/lib/selfImprovementApi";
import { DetailSheet } from "./selfBuild/DetailSheet";
import { Row, Section } from "./selfBuild/List";
import { relativeTime } from "./selfBuild/shared";
import { AdvantageCurve } from "./selfImprovement/AdvantageCurve";
import { ChangeDetail } from "./selfImprovement/ChangeDetail";
import { DailyUseSection } from "./selfImprovement/DailyUse";
import { NightsSection } from "./selfImprovement/Nights";
import { claimWords, isPolicy, policyProof, policySentence } from "./selfImprovement/policy";
import { PolicyLines } from "./selfImprovement/PolicyLines";
import {
  DECIDE_MIN_TASKS,
  MODEL_FREE_DOMAINS,
  SAVING_HEADLINE_SHARE,
  areaAbout,
  areaName,
  certainty,
  effectWords,
  fmtPercent,
  fmtPoints,
  fmtShare,
  fmtTokens,
  fmtValue,
  paramTitle,
  promptSaving,
  wordFor,
} from "./selfImprovement/words";

const LIST = "divide-y divide-border overflow-hidden rounded-md border border-border bg-card";

function nightDidSomething(night: Night): boolean {
  const made = night.made ?? {};
  return Boolean(
    night.paused ||
      night.updated_from ||
      made.questions ||
      made.messages ||
      made.forgotten ||
      made.deferred ||
      night.settled?.length ||
      night.proposed?.length ||
      night.decided?.length ||
      night.measured?.length,
  );
}

/**
 * Nothing to measure yet: no own tasks anywhere and nothing learned. The nights
 * may still have tried to build tasks; they are listed under the empty card.
 */
export function isEmpty(data: SelfImprovementOverview): boolean {
  return (
    data.domains.every((d) => d.tasks_total === 0 && !d.measured) &&
    data.stack.length === 0 &&
    data.candidates.length === 0 &&
    data.resting.length === 0
  );
}

/** Parts of an area the page has words for (``run.parts`` in dodaios/rsi/bench/run.py). */
const PARTS = ["needs_memory", "needs_none"];

export function SelfImprovementView() {
  const ready = useLocaleChunk("self_improvement");
  const t = useT();
  const locale = useRunLocale();
  const query = useSelfImprovement();
  const pause = useSelfImprovementPause();
  const undo = useSelfImprovementUndo();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const data = query.data;
  const selected = useMemo(
    () => data?.stack.find((c) => c.id === selectedId) ?? data?.candidates.find((c) => c.id === selectedId) ?? null,
    [data, selectedId],
  );
  const inStack = Boolean(selected && data?.stack.some((c) => c.id === selected.id));

  const takeBack = (change: LearnedChange) => {
    setError(null);
    undo.mutate(change.id, {
      onError: (err) => setError(fill(t("self_improvement.error.action"), { detail: err.message })),
    });
  };
  const setPaused = (paused: boolean) => {
    setError(null);
    pause.mutate(paused, {
      onError: (err) => setError(fill(t("self_improvement.error.action"), { detail: err.message })),
    });
  };
  const busyId = undo.isPending ? undo.variables ?? null : null;

  if (!ready) return <PageSkeleton />;

  const unavailable = query.error instanceof SelfImprovementApiError && query.error.status === 503;
  const status = data?.status;
  const paused = Boolean(status?.paused);

  return (
    <div data-testid="self-improvement-view" className="flex h-full min-h-0 flex-col overflow-y-auto">
      <div className="mx-auto w-full max-w-[760px] px-6 pb-16 pt-12 sm:px-8">
        <header className="flex items-start gap-6">
          <div className="min-w-0 flex-1">
            <h1 className="font-display text-[26px] font-semibold leading-tight tracking-[-0.02em] text-foreground-strong">
              {t("self_improvement.title")}
            </h1>
            <p className="mt-1.5 max-w-[60ch] text-[15px] leading-relaxed text-muted-foreground">{t("self_improvement.subtitle")}</p>
          </div>
          {status && !status.readonly && (
            <button
              type="button"
              data-testid={paused ? "si-resume" : "si-stop"}
              disabled={pause.isPending}
              onClick={() => setPaused(!paused)}
              className={cn(
                "inline-flex h-8 shrink-0 items-center gap-1.5 rounded-md px-3 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60",
                paused
                  ? "bg-primary text-primary-foreground hover:bg-primary/90"
                  : "border border-border-strong text-foreground hover:bg-secondary",
              )}
            >
              {pause.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />}
              {paused ? t("self_improvement.resume") : t("self_improvement.stop")}
            </button>
          )}
        </header>

        {query.isPending ? (
          <BodySkeleton label={t("self_improvement.loading")} />
        ) : unavailable ? (
          <ErrorNote text={t("self_improvement.error.unavailable")} />
        ) : query.error || !data ? (
          <ErrorNote
            text={fill(t("self_improvement.error.load"), { detail: query.error?.message ?? "" })}
            retry={{ label: t("self_improvement.error.retry"), onClick: () => void query.refetch(), busy: query.isFetching }}
          />
        ) : (
          <>
            <StateLine status={data.status} limits={data.limits} now={data.now_ms} locale={locale} />
            {error && (
              <p role="alert" className="mt-4 rounded-md border border-destructive/40 px-3 py-2 text-sm text-destructive">
                {error}
              </p>
            )}

            {isEmpty(data) ? (
              <>
                <EmptyCard />
                {/* Daily use comes from the chat record, not from the benchmark, so it can exist already. */}
                <DailyUseSection daily={data.daily_use} locale={locale} />
                {/* A night that tried to build tasks says what came of it, even before anything exists. */}
                {data.nights.some(nightDidSomething) && <NightsSection nights={data.nights} locale={locale} />}
              </>
            ) : (
              <>
                {data.domains.map((domain) => (
                  <Area
                    key={domain.domain}
                    domain={domain}
                    points={data.series.filter((p) => p.domain === domain.domain)}
                    locale={locale}
                  />
                ))}

                <DailyUseSection daily={data.daily_use} locale={locale} />

                <Section id="si-stack" title={t("self_improvement.stack.title")} count={data.stack.length || undefined}>
                  {data.stack.length ? (
                    <>
                      <p className="mb-2.5 px-1 text-sm leading-relaxed text-muted-foreground" data-testid="si-stack-kinds">
                        {t("self_improvement.stack.kinds")}
                      </p>
                      <ul className={LIST}>
                        {data.stack.map((change) => (
                          <ChangeRow
                            key={change.id}
                            change={change}
                            locale={locale}
                            selected={change.id === selectedId}
                            onSelect={() => setSelectedId(change.id === selectedId ? null : change.id)}
                            busy={busyId === change.id}
                            onUndo={() => takeBack(change)}
                          />
                        ))}
                      </ul>
                    </>
                  ) : (
                    <p className="px-1 text-sm text-muted-foreground" data-testid="si-stack-none">{t("self_improvement.stack.none")}</p>
                  )}
                </Section>

                <NightsSection nights={data.nights} locale={locale} />

                {data.candidates.length > 0 && (
                  <Section id="si-candidates" title={t("self_improvement.candidates.title")} count={data.candidates.length}>
                    <ul className={LIST}>
                      {data.candidates.map((change) => (
                        <ChangeRow
                          key={change.id}
                          change={change}
                          locale={locale}
                          selected={change.id === selectedId}
                          onSelect={() => setSelectedId(change.id === selectedId ? null : change.id)}
                          candidate
                        />
                      ))}
                    </ul>
                  </Section>
                )}

                {data.resting.length > 0 && (
                  <Section id="si-resting" title={t("self_improvement.resting.title")} count={data.resting.length}>
                    <ul className={LIST}>
                      {data.resting.map((entry) => (
                        <RestingRow key={entry.stored_as} entry={entry} locale={locale} />
                      ))}
                    </ul>
                  </Section>
                )}
              </>
            )}

            <Foot limits={data.limits} domains={data.domains} />
          </>
        )}
      </div>

      {selected && (
        <DetailSheet onClose={() => setSelectedId(null)} testId="si-sheet">
          <ChangeDetail
            key={selected.id}
            change={selected}
            locale={locale}
            busy={busyId === selected.id}
            onUndo={inStack ? () => takeBack(selected) : undefined}
            onClose={() => setSelectedId(null)}
          />
        </DetailSheet>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ head

function StateLine({
  status,
  limits,
  now,
  locale,
}: {
  status: SelfImprovementStatus;
  limits: SelfImprovementLimits;
  now: number;
  locale: string;
}) {
  const t = useT();
  const minutes = Math.round(limits.idle_after_s / 60);
  const state = status.readonly ? "readonly" : status.paused ? "stopped" : "running";
  let body: string;
  if (state === "readonly") body = t("self_improvement.state.readonly_body");
  else if (state === "stopped") body = t("self_improvement.state.stopped_body");
  else if (!status.last_night_ms) body = fill(t("self_improvement.state.running_first"), { minutes });
  else if (status.next_night_ms > now) {
    body = fill(t("self_improvement.state.running_body"), {
      when: relativeTime(status.last_night_ms, locale, now),
      next: new Date(status.next_night_ms).toLocaleString(locale, { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }),
      minutes,
    });
  } else {
    body = fill(t("self_improvement.state.running_due"), { when: relativeTime(status.last_night_ms, locale, now), minutes });
  }
  return (
    <p className="mt-6 flex items-baseline gap-2.5 text-sm leading-relaxed" data-testid="si-state" data-state={state}>
      <span
        aria-hidden
        className={cn(
          "inline-block h-2 w-2 shrink-0 translate-y-[-1px] rounded-[1px]",
          state === "running" ? "bg-success" : state === "stopped" ? "bg-warning" : "bg-muted-foreground",
        )}
      />
      <span>
        <span className="font-medium text-foreground-strong">{t(`self_improvement.state.${state}`)}.</span>{" "}
        <span className="text-muted-foreground">{body}</span>
      </span>
    </p>
  );
}

// ------------------------------------------------------------------ areas

function Area({ domain, points, locale }: { domain: DomainSummary; points: AdvantagePoint[]; locale: string }) {
  const t = useT();
  const point = domain.point;
  return (
    <section data-testid="si-area" data-domain={domain.domain} aria-labelledby={`si-area-${domain.domain}`} className="mt-10">
      <div className="mb-2.5 px-1">
        <h2 id={`si-area-${domain.domain}`} className="text-sm font-medium text-foreground">
          {areaName(t, domain.domain)}
        </h2>
        {areaAbout(t, domain.domain) && <p className="text-sm text-muted-foreground">{areaAbout(t, domain.domain)}</p>}
      </div>
      {domain.measured && point ? (
        <>
          <Headline point={point} locale={locale} />
          <AdvantageCurve points={points} locale={locale} />
        </>
      ) : (
        <p className="rounded-md border border-border bg-card px-5 py-4 text-sm text-muted-foreground" data-testid="si-area-waiting">
          {domain.tasks_total === 0
            ? t("self_improvement.area.no_tasks")
            : (domain.tasks.select ?? 0) < DECIDE_MIN_TASKS
              ? fill(t("self_improvement.area.building"), {
                  n: domain.tasks_total,
                  need: DECIDE_MIN_TASKS,
                  have: domain.tasks.select ?? 0,
                })
              : fill(t("self_improvement.area.waiting"), { n: domain.tasks_total })}
        </p>
      )}
    </section>
  );
}

function Headline({ point, locale }: { point: AdvantagePoint; locale: string }) {
  const t = useT();
  const where = certainty(point.low, point.high);
  const range = { low: fmtPoints(point.low, locale), high: fmtPoints(point.high, locale) };
  const costChanged = Math.round(point.now_tokens) !== Math.round(point.factory_tokens);
  const tokens = { before: fmtTokens(point.factory_tokens, locale), after: fmtTokens(point.now_tokens, locale) };
  const saving = promptSaving(point.now_tokens, point.factory_tokens);
  // A shorter prompt at a quality no worse than shipped is a result of its own,
  // so it stands beside the points in the same weight.
  const savingHeadline = saving >= SAVING_HEADLINE_SHARE;
  const rangeKey = where === "unclear" && savingHeadline ? "range_unclear_cheaper" : `range_${where}`;
  return (
    <div className="rounded-md border border-border bg-card px-5 py-4" data-testid="si-headline" data-certainty={where}>
      <div className="grid gap-x-10 gap-y-4 sm:grid-cols-[auto_auto] sm:justify-start">
        <Figure
          label={t("self_improvement.area.quality_label")}
          value={fmtPoints(point.diff, locale)}
          unit={t("self_improvement.area.unit")}
          // An uncertain number is not a result yet, so it is set in the quieter ink.
          quiet={where === "unclear"}
          testId="si-advantage"
          note={
            <span className={cn("font-medium", where === "worse" ? "text-destructive" : "text-muted-foreground")} data-testid="si-certainty">
              {t(`self_improvement.area.badge_${where}`)}
            </span>
          }
        />
        {savingHeadline && (
          <Figure
            label={t("self_improvement.area.cost_label")}
            value={fmtPercent(saving, locale)}
            unit={t("self_improvement.area.shorter")}
            testId="si-saving"
            note={<span className="tabular-nums text-muted-foreground">{fill(t("self_improvement.area.cost"), tokens)}</span>}
          />
        )}
      </div>
      <p className="mt-4 text-sm leading-relaxed text-foreground">{t("self_improvement.area.meaning")}</p>
      <p className="mt-1 text-sm leading-relaxed text-foreground" data-testid="si-range">
        {fill(t(`self_improvement.area.${rangeKey}`), { ...range, pct: fmtPercent(saving, locale) })}
      </p>
      <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 border-t border-border pt-3 text-sm">
        <div className="contents">
          <dt className="text-muted-foreground">{t("self_improvement.area.scores_label")}</dt>
          <dd className="tabular-nums text-foreground" data-testid="si-scores">
            {fill(t("self_improvement.area.scores"), {
              now: fmtShare(point.now_score, locale),
              shipped: fmtShare(point.factory_score, locale),
              n: point.n,
            })}
          </dd>
        </div>
        {Object.entries(point.parts ?? {})
          .filter(([part]) => PARTS.includes(part))
          .map(([part, row]) => (
            <div className="contents" key={part}>
              <dt className="text-muted-foreground">{t(`self_improvement.area.part_${part}`)}</dt>
              <dd className="tabular-nums text-foreground" data-testid={`si-part-${part}`}>
                {fill(t("self_improvement.area.part_scores"), {
                  now: fmtShare(row.now_score, locale),
                  shipped: fmtShare(row.factory_score, locale),
                  n: row.n,
                })}
              </dd>
            </div>
          ))}
        {!savingHeadline && (
          <div className="contents">
            <dt className="text-muted-foreground">{t("self_improvement.area.cost_label")}</dt>
            <dd className="tabular-nums text-foreground" data-testid="si-cost">
              {fill(t(costChanged ? "self_improvement.area.cost" : "self_improvement.area.cost_same"), tokens)}
            </dd>
          </div>
        )}
      </dl>
    </div>
  );
}

/** One headline figure: what it measures, the number in the display face, one quiet line under it. */
function Figure({
  label,
  value,
  unit,
  note,
  quiet = false,
  testId,
}: {
  label: string;
  value: string;
  unit: string;
  note: ReactNode;
  quiet?: boolean;
  testId: string;
}) {
  return (
    <div className="min-w-0">
      <p className="text-sm text-muted-foreground">{label}</p>
      <p
        className={cn(
          "mt-1 font-display text-[34px] font-semibold leading-none tabular-nums tracking-[-0.02em]",
          quiet ? "text-muted-foreground" : "text-foreground-strong",
        )}
        data-testid={testId}
      >
        {value}
        <span className="ml-1.5 text-lg font-medium tracking-normal">{unit}</span>
      </p>
      <p className="mt-1.5 text-sm">{note}</p>
    </div>
  );
}

// ------------------------------------------------------------------ rows

/** A how-to note the assistant wrote for itself, rather than a tuned value. */
function isNote(change: LearnedChange): boolean {
  return change.surface === NOTE_SURFACE;
}

/** The note's words in full, as the person can read them; or that the note is gone from the memory. */
function NoteWords({ text }: { text: string }) {
  const t = useT();
  return text.trim() ? (
    <span className="mb-1 block whitespace-pre-line text-[15px] leading-snug text-foreground" data-testid="si-note-text">
      {text}
    </span>
  ) : (
    <span className="mb-1 block whitespace-normal italic text-muted-foreground" data-testid="si-note-gone">
      {t("self_improvement.stack.note_gone")}
    </span>
  );
}

function ChangeRow({
  change,
  locale,
  selected,
  onSelect,
  busy = false,
  onUndo,
  candidate = false,
}: {
  change: LearnedChange;
  locale: string;
  selected: boolean;
  onSelect: () => void;
  busy?: boolean;
  onUndo?: () => void;
  candidate?: boolean;
}) {
  const t = useT();
  const note = isNote(change);
  // How coding agents are steered: a sentence instead of a value, proved on requests.
  const policy = isPolicy(change) ? change : null;
  const before = change.before ?? change.default;
  const values = note || policy ? "" : fill(t("self_improvement.stack.values"), { before: fmtValue(before, locale), after: fmtValue(change.after, locale) });
  const when = relativeTime(change.since_ms, locale);
  // Two lines: where the change stands, then what proved it. The proof is the
  // line a person reads for, so it never shares its width with anything else.
  const standing = candidate
    ? [fill(t(policy ? "self_improvement.policy.on_trial" : "self_improvement.candidates.row"), { when })]
    : [wordFor(t, "state_word", change.state), fill(t("self_improvement.stack.since"), { when })];
  if (!candidate && change.last_check && change.last_check.verdict === "accept") {
    standing.push(fill(t("self_improvement.stack.held"), { n: change.last_check.n }));
  }
  // A note it wrote for itself has no measurement: it says so instead of a proof.
  // A policy on trial says what it has to show; one in effect, what showed it.
  const proof = policy
    ? candidate
      ? claimWords(t, policy.policy)
      : policyProof(t, change.admitted, locale)
    : candidate
      ? ""
      : note
        ? t("self_improvement.stack.not_measured")
        : effectWords(t, change.admitted, locale);
  return (
    <Row
      testId="si-change-row"
      data={{ "change-id": change.id, state: change.state, surface: change.surface }}
      selected={selected}
      onClick={onSelect}
      title={
        note ? (
          t("self_improvement.stack.note_title")
        ) : policy ? (
          <span className="whitespace-normal" data-testid="si-policy-sentence">
            {policySentence(t, policy)}
          </span>
        ) : (
          <>
            {paramTitle(t, change.target, change.doc)}
            <span className="ml-2 tabular-nums text-muted-foreground">{values}</span>
          </>
        )
      }
      sub={
        <>
          {note && <NoteWords text={change.text ?? ""} />}
          {policy && policy.policy.lines.length > 0 && <PolicyLines lines={policy.policy.lines} />}
          <span className="block truncate">{standing.join(" · ")}</span>
          {proof && (
            <span
              className={cn("mt-0.5 block truncate tabular-nums", note ? "text-muted-foreground" : "text-foreground")}
              data-testid="si-change-proof"
              title={proof}
            >
              {proof}
            </span>
          )}
        </>
      }
      right={
        onUndo ? (
          <button
            type="button"
            data-testid="si-undo"
            disabled={busy}
            onClick={(event) => {
              event.stopPropagation();
              onUndo();
            }}
            className="inline-flex h-7 items-center gap-1.5 rounded-md border border-border-strong px-2.5 text-sm font-medium text-foreground transition-colors hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />}
            {t("self_improvement.stack.take_back")}
          </button>
        ) : undefined
      }
    />
  );
}

function RestingRow({ entry, locale }: { entry: RestingValue; locale: string }) {
  const t = useT();
  return (
    <Row
      testId="si-resting-row"
      data={{ name: entry.name, status: entry.status }}
      muted
      title={
        <>
          {paramTitle(t, entry.name)}
          <span className="ml-2 tabular-nums text-muted-foreground">{fmtValue(entry.value, locale)}</span>
        </>
      }
      sub={wordFor(t, "resting", entry.status === "restale" ? "restale" : "dormant")}
    />
  );
}

// ------------------------------------------------------------------ empty, foot, states

function EmptyCard() {
  const t = useT();
  return (
    <section data-testid="si-empty" className="mt-10 rounded-md border border-border bg-card px-6 py-8">
      <p className="text-base font-medium text-foreground-strong">{t("self_improvement.empty.title")}</p>
      <p className="mt-1.5 max-w-[60ch] text-sm leading-relaxed text-muted-foreground">{t("self_improvement.empty.body")}</p>
    </section>
  );
}

const STEPS = ["practise", "decide", "check"] as const;

function Foot({ limits, domains }: { limits: SelfImprovementLimits; domains: DomainSummary[] }) {
  const t = useT();
  const minutes = Math.round(limits.idle_after_s / 60);
  const hours = Math.round(limits.every_s / 3600);
  const modelFree = domains.every((d) => MODEL_FREE_DOMAINS.has(d.domain));
  return (
    <section data-testid="si-foot" aria-labelledby="si-foot-title" className="mt-12 border-t border-border px-1 pt-6">
      <h2 id="si-foot-title" className="text-sm font-medium text-foreground">{t("self_improvement.how.title")}</h2>
      <ol className="mt-3 grid gap-4 sm:grid-cols-3">
        {STEPS.map((key, index) => (
          <li key={key} className="text-sm leading-relaxed">
            <p className="font-medium text-foreground">
              <span className="mr-1.5 tabular-nums text-muted-foreground">{index + 1}</span>
              {t(`self_improvement.how.${key}_title`)}
            </p>
            <p className="mt-0.5 text-muted-foreground">{t(`self_improvement.how.${key}_body`)}</p>
          </li>
        ))}
      </ol>
      <div className="mt-5 space-y-2 text-sm leading-relaxed text-muted-foreground">
        <p data-testid="si-limits">
          {fill(t("self_improvement.how.limits"), { minutes, hours })}{" "}
          {limits.ramp_model_calls && limits.ramp_model_calls > (limits.max_model_calls ?? 8)
            ? fill(t("self_improvement.how.models_ramp"), {
                calls: limits.max_model_calls ?? 8,
                ramp: limits.ramp_model_calls,
              })
            : fill(t("self_improvement.how.models"), { calls: limits.max_model_calls ?? 8 })}
          {modelFree ? ` ${t("self_improvement.how.measure_no_model")}` : ""}
        </p>
        <p data-testid="si-privacy">{t("self_improvement.how.privacy")}</p>
      </div>
    </section>
  );
}

function ErrorNote({ text, retry }: { text: string; retry?: { label: string; onClick: () => void; busy: boolean } }) {
  return (
    <div role="alert" className="mt-10 rounded-md border border-border bg-card px-5 py-4" data-testid="si-error">
      <p className="text-sm leading-relaxed text-destructive">{text}</p>
      {retry && (
        <button
          type="button"
          onClick={retry.onClick}
          disabled={retry.busy}
          className="mt-3 inline-flex h-8 items-center gap-1.5 rounded-md border border-border-strong px-3 text-sm font-medium text-foreground hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60"
        >
          {retry.busy && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />}
          {retry.label}
        </button>
      )}
    </div>
  );
}

function Bar({ className }: { className: string }) {
  return <div aria-hidden className={cn("animate-pulse rounded-md bg-secondary motion-reduce:animate-none", className)} />;
}

function BodySkeleton({ label }: { label?: string }) {
  return (
    <div role="status" aria-label={label} data-testid="si-skeleton" className="mt-6">
      <Bar className="h-4 w-80 max-w-full" />
      <Bar className="mt-10 h-4 w-24" />
      <Bar className="mt-3 h-40 w-full" />
      <Bar className="mt-5 h-52 w-full" />
      <Bar className="mt-10 h-4 w-40" />
      <Bar className="mt-3 h-24 w-full" />
    </div>
  );
}

function PageSkeleton() {
  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto">
      <div className="mx-auto w-full max-w-[760px] px-6 pb-16 pt-12 sm:px-8">
        <Bar className="h-7 w-56" />
        <Bar className="mt-3 h-4 w-full max-w-[60ch]" />
        <BodySkeleton />
      </div>
    </div>
  );
}

export default SelfImprovementView;
