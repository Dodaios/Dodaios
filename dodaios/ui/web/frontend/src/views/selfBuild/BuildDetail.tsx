/**
 * One build, read top to bottom as its own case file: the sentence it exists
 * for, where it stands on its path, why it was built, what it noticed, how it
 * was checked, what it made, how it was used, what it cost, and every move it
 * made — with the one or two actions that apply to it right now.
 */
import type { ReactNode } from "react";
import { Code2, ExternalLink, Loader2, X } from "lucide-react";
import { fill, useT } from "@/i18n";
import { useRunLocale, fmtInt } from "@/components/runs/format";
import { cn } from "@/lib/utils";
import { useSelfBuildDetail } from "@/hooks/useSelfBuild";
import { openCodingThread } from "@/components/agentic/threads/openCodingThread";
import { reachedStep, trialProgress, type Build, type BuildOutcome } from "@/lib/selfBuildApi";
import { KindIcon, LifecycleRail, formatUsd, relativeTime } from "./shared";
import { BuildActions, type ActionHandler } from "./BuildActions";

const OUTCOMES: readonly BuildOutcome[] = ["accepted", "used", "corrected", "ignored"];

export function BuildDetail({
  build,
  limits,
  canBuild,
  blockedTitle,
  busy,
  onAction,
  onClose,
}: {
  build: Build;
  limits: { trial_days: number; trial_uses: number } | undefined;
  canBuild: boolean;
  blockedTitle?: string;
  busy: boolean;
  onAction: ActionHandler;
  onClose: () => void;
}) {
  const t = useT();
  const locale = useRunLocale();
  const detail = useSelfBuildDetail(build.id);
  const history = detail.data?.history;
  const cost = detail.data?.cost;
  // The list row may be newer than the detail fetch (a socket event landed).
  const current = detail.data && detail.data.build.updated_ms > build.updated_ms ? detail.data.build : build;
  const reached = reachedStep(current, history);
  const trial = trialProgress(current, limits);
  const railLabels: Record<string, string> = {
    proposed: t("self_build.step.proposed"),
    building: t("self_build.step.building"),
    proving: t("self_build.step.proving"),
    trial: t("self_build.step.trial"),
    kept: t("self_build.step.kept"),
    [`end:${current.state}`]: t(`self_build.state.${current.state}`),
  };
  const proof = current.proof ?? {};
  const hasProof = typeof proof.passed === "boolean";
  const artefact = current.artefact ?? {};
  // A code build's coding run is a thread in the Agentic IDE: every step it took.
  const thread = artefact.type === "code" && typeof artefact.thread === "string" ? artefact.thread.trim() : "";
  const outcomes = OUTCOMES.filter((o) => (current.outcomes[o] ?? 0) > 0);

  return (
    <article
      data-testid="build-detail"
      data-build-id={current.id}
      className="flex min-h-0 flex-col rounded-xl border border-border bg-card"
    >
      <header className="border-b border-border px-6 pb-5 pt-5">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <KindIcon kind={current.kind} />
          <span>{t(`self_build.kind.${current.kind}`)}</span>
          <span aria-hidden>·</span>
          <span>{t(`self_build.state.${current.state}`)}</span>
          <span aria-hidden>·</span>
          <span title={new Date(current.created_ms).toLocaleString(locale)}>
            {t("self_build.detail.opened")} {relativeTime(current.created_ms, locale)}
          </span>
          <button
            type="button"
            onClick={onClose}
            aria-label={t("self_build.detail.close")}
            className="ml-auto rounded-md p-1 text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <X className="h-4 w-4" aria-hidden />
          </button>
        </div>
        <h2 className="mt-3 font-display text-xl leading-snug text-foreground-strong">{current.title}</h2>
        <div className="mt-6">
          <LifecycleRail state={current.state} reached={reached} labels={railLabels} />
        </div>
        {trial && (
          <div className="mt-4">
            <div className="h-1 overflow-hidden rounded-full bg-secondary" aria-hidden>
              <div className="h-full rounded-full bg-accent" style={{ width: `${Math.round(trial.share * 100)}%` }} />
            </div>
            <p className="mt-1.5 text-xs tabular-nums text-muted-foreground">
              {fill(t("self_build.trial_progress"), {
                days: trial.days,
                dayLimit: trial.dayLimit,
                uses: trial.uses,
                useLimit: trial.useLimit,
              })}
            </p>
          </div>
        )}
        <div className="mt-5">
          <BuildActions build={current} canBuild={canBuild} blockedTitle={blockedTitle} busy={busy} onAction={onAction} size="default" />
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
        <dl className="space-y-6">
          {current.case && (
            <Section label={t("self_build.detail.why")}>
              <p className="whitespace-pre-line text-base leading-relaxed text-foreground">{current.case}</p>
            </Section>
          )}

          <Section label={t("self_build.detail.noticed")}>
            {current.evidence.length ? (
              <ul className="space-y-1">
                {current.evidence.map((ref, index) => (
                  <li key={`${ref}-${index}`} className="truncate font-mono text-xs text-muted-foreground" title={ref}>
                    {ref}
                  </li>
                ))}
              </ul>
            ) : (
              <Quiet>{t("self_build.detail.noticed_empty")}</Quiet>
            )}
          </Section>

          <Section label={t("self_build.detail.proof")}>
            {hasProof ? (
              <div className="space-y-1">
                <p className="flex items-center gap-2 text-base text-foreground">
                  <span
                    aria-hidden
                    className={cn("h-2 w-2 rounded-full", proof.passed ? "bg-success" : "bg-destructive")}
                  />
                  {proof.passed ? t("self_build.detail.proof_passed") : t("self_build.detail.proof_failed")}
                  {proof.judge && <span className="text-sm text-muted-foreground">· {proof.judge}</span>}
                </p>
                {proof.detail && <p className="text-sm leading-relaxed text-muted-foreground">{proof.detail}</p>}
              </div>
            ) : (
              <Quiet>{t("self_build.detail.proof_none")}</Quiet>
            )}
          </Section>

          <Section label={t("self_build.detail.made")}>
            {artefact.type && (artefact.id || artefact.branch) ? (
              <p className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5 text-base text-foreground">
                <span className="truncate">{artefactLabel(artefact, t)}</span>
                <span className="shrink-0 text-sm text-muted-foreground">{artefactKind(artefact, t)}</span>
                {typeof artefact.url === "string" && /^https?:\/\//.test(artefact.url) && (
                  <a
                    href={artefact.url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex shrink-0 items-center gap-1 text-sm text-accent hover:underline"
                  >
                    {t("self_build.detail.open_link")}
                    <ExternalLink className="h-3.5 w-3.5" aria-hidden />
                  </a>
                )}
                {thread && (
                  <button
                    type="button"
                    onClick={() => openCodingThread(thread)}
                    title={t("self_build.detail.open_thread_title")}
                    data-testid="build-open-thread"
                    className="inline-flex shrink-0 items-center gap-1 rounded-sm text-sm text-accent hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    {t("self_build.detail.open_thread")}
                    <Code2 className="h-3.5 w-3.5" aria-hidden />
                  </button>
                )}
              </p>
            ) : (
              <Quiet>{t("self_build.detail.made_none")}</Quiet>
            )}
          </Section>

          <div className="grid grid-cols-2 gap-6">
            <Section label={t("self_build.detail.use")}>
              {current.uses > 0 ? (
                <div className="space-y-0.5">
                  <p className="text-base tabular-nums text-foreground">
                    {fill(t("self_build.detail.uses"), { count: fmtInt(current.uses, locale) })}
                  </p>
                  {outcomes.length > 0 && (
                    <p className="text-sm text-muted-foreground">
                      {outcomes
                        .map((o) => `${fmtInt(current.outcomes[o] ?? 0, locale)} ${t(`self_build.outcome.${o}`)}`)
                        .join(" · ")}
                    </p>
                  )}
                  {current.last_used_ms > 0 && (
                    <p className="text-xs text-muted-foreground">{relativeTime(current.last_used_ms, locale)}</p>
                  )}
                </div>
              ) : (
                <Quiet>{t("self_build.detail.unused")}</Quiet>
              )}
            </Section>
            <Section label={t("self_build.detail.cost")}>
              {cost === undefined ? (
                <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" aria-hidden />
              ) : cost.usd > 0 || cost.tokens > 0 ? (
                <div className="space-y-0.5">
                  <p className="text-base tabular-nums text-foreground">{formatUsd(cost.usd, locale)}</p>
                  <p className="text-sm tabular-nums text-muted-foreground">
                    {fill(t("self_build.detail.tokens"), { count: fmtInt(cost.tokens, locale) })}
                  </p>
                </div>
              ) : (
                <Quiet>{t("self_build.detail.cost_none")}</Quiet>
              )}
            </Section>
          </div>

          {/* The last move's note explains an ending ("archived: not used
              enough"); on a live build it only repeats the history. */}
          {current.note && ["archived", "undone", "rejected", "failed"].includes(current.state) && (
            <Section label={t("self_build.detail.note")}>
              <p className="text-sm text-muted-foreground">{current.note}</p>
            </Section>
          )}

          <Section label={t("self_build.detail.history")}>
            {history === undefined ? (
              <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" aria-hidden />
            ) : (
              <ol className="relative space-y-3 border-l border-border pl-4" data-testid="build-history">
                {[...history].reverse().map((entry, index) => (
                  <li key={`${entry.ts_ms}-${index}`} className="relative">
                    <span
                      aria-hidden
                      className={cn(
                        "absolute -left-[21px] top-1.5 h-2 w-2 rounded-full border border-card",
                        index === 0 ? "bg-foreground-strong" : "bg-border-strong",
                      )}
                    />
                    <p className="text-sm text-foreground">
                      {entry.from ? `${stateLabel(t, entry.from)} → ` : ""}
                      <span className="font-medium">{stateLabel(t, entry.to)}</span>
                    </p>
                    <p className="text-xs text-muted-foreground" title={new Date(entry.ts_ms).toLocaleString(locale)}>
                      {relativeTime(entry.ts_ms, locale)}
                      {entry.note ? ` · ${entry.note}` : ""}
                    </p>
                  </li>
                ))}
              </ol>
            )}
          </Section>
        </dl>
      </div>
    </article>
  );
}

/** What the person reads for what a build made: its name, never a raw id when a better one exists. */
function artefactLabel(artefact: Build["artefact"], t: (key: string) => string): string {
  const str = (key: string) => (typeof artefact[key] === "string" ? (artefact[key] as string) : "");
  if (artefact.type === "code") {
    const repo = str("repo");
    if (typeof artefact.number === "number") return `${repo}#${artefact.number}`;
    return `${repo}${repo && str("branch") ? " · " : ""}${str("branch")}` || t("self_build.detail.made_none");
  }
  return str("label") || str("name") || str("id");
}

function artefactKind(artefact: Build["artefact"], t: (key: string) => string): string {
  if (artefact.type !== "code") return String(artefact.type);
  if (typeof artefact.number !== "number") return t("self_build.detail.code_branch");
  return artefact.draft === false ? t("self_build.detail.code_pr") : t("self_build.detail.code_draft");
}

function stateLabel(t: (key: string) => string, state: string): string {
  const key = `self_build.state.${state}`;
  const label = t(key);
  return label === key ? state : label;
}

function Section({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="mb-1.5 text-sm font-medium text-muted-foreground">{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

function Quiet({ children }: { children: ReactNode }) {
  return <p className="text-sm text-muted-foreground">{children}</p>;
}
