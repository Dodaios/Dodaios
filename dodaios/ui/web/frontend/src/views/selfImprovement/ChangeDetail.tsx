/**
 * One learned change as its own case file: what the value sets, what it was
 * and is, the measurement that let it in and the one that checked it again,
 * who proposed it and why, and when. The stored reasons are the kernel's own
 * words and are shown as they are; everything else is the page's wording.
 */
import type { ReactNode } from "react";
import { Loader2, X } from "lucide-react";
import { fill, useT } from "@/i18n";
import { NOTE_SURFACE, type LearnedChange, type Measurement } from "@/lib/selfImprovementApi";
import { relativeTime } from "../selfBuild/shared";
import { effectWords, fmtValue, paramAbout, paramTitle, wordFor } from "./words";

export function ChangeDetail({
  change,
  locale,
  busy,
  onUndo,
  onClose,
}: {
  change: LearnedChange;
  locale: string;
  busy: boolean;
  onUndo?: () => void;
  onClose: () => void;
}) {
  const t = useT();
  const title = paramTitle(t, change.target, change.doc);
  const about = paramAbout(t, change.target, change.doc);
  const before = change.before ?? change.default;
  // A note it wrote for itself has words instead of values, and no measurement yet.
  const note = change.surface === NOTE_SURFACE;
  const author = wordFor(t, "author", change.author || "unknown");
  return (
    <article
      data-testid="si-change-detail"
      data-change-id={change.id}
      className="flex min-h-0 flex-col rounded-md border border-border bg-card"
    >
      <header className="border-b border-border px-6 pb-5 pt-5">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <span>{wordFor(t, "state_word", change.state)}</span>
          <span aria-hidden>·</span>
          <span title={new Date(change.since_ms).toLocaleString(locale)}>
            {fill(t("self_improvement.stack.since"), { when: relativeTime(change.since_ms, locale) })}
          </span>
          <button
            type="button"
            onClick={onClose}
            aria-label={t("self_improvement.detail.close")}
            className="ml-auto rounded-sm p-1 text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <X className="h-4 w-4" aria-hidden />
          </button>
        </div>
        <h2 className="mt-3 font-display text-xl leading-snug text-foreground-strong">{title}</h2>
        {note ? (
          change.text?.trim() ? (
            <p className="mt-3 whitespace-pre-line text-base leading-relaxed text-foreground" data-testid="si-detail-note">
              {change.text}
            </p>
          ) : (
            <p className="mt-3 text-sm italic text-muted-foreground" data-testid="si-detail-note-gone">
              {t("self_improvement.stack.note_gone")}
            </p>
          )
        ) : (
          <>
            <p className="mt-2 text-2xl font-semibold tabular-nums text-foreground-strong" data-testid="si-detail-values">
              {fill(t("self_improvement.stack.values"), { before: fmtValue(before, locale), after: fmtValue(change.after, locale) })}
            </p>
            <p className="mt-1 text-sm tabular-nums text-muted-foreground">
              {fill(t("self_improvement.detail.shipped"), { value: fmtValue(change.default, locale) })}
            </p>
          </>
        )}
        {onUndo && (
          <button
            type="button"
            data-testid="si-detail-undo"
            disabled={busy}
            onClick={onUndo}
            className="mt-5 inline-flex h-8 items-center gap-1.5 rounded-md border border-border-strong px-3 text-sm font-medium text-foreground transition-colors hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />}
            {t("self_improvement.stack.take_back")}
          </button>
        )}
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
        <dl className="space-y-6">
          {note ? (
            <Field label={t("self_improvement.detail.measurement")}>
              <p className="text-base text-foreground" data-testid="si-detail-unmeasured">{t("self_improvement.detail.note_unmeasured")}</p>
            </Field>
          ) : (
            <>
              {about && (
                <Field label={t("self_improvement.detail.what")}>
                  <p className="text-base leading-relaxed text-foreground">{about}</p>
                </Field>
              )}
              <Field label={t("self_improvement.detail.admitted")}>
                <MeasurementBlock found={change.admitted} kind="admitted" locale={locale} />
              </Field>
              <Field label={t("self_improvement.detail.checked")}>
                {change.last_check ? (
                  <MeasurementBlock found={change.last_check} kind="checked" locale={locale} />
                ) : (
                  <Quiet>{t("self_improvement.detail.not_checked")}</Quiet>
                )}
              </Field>
            </>
          )}
          <Field label={t("self_improvement.detail.proposed_by")}>
            <p className="text-base text-foreground">{author}</p>
            {change.reason && (
              <p className="mt-1 font-mono text-xs leading-relaxed text-muted-foreground" data-testid="si-detail-proposal">
                {change.reason}
              </p>
            )}
          </Field>
          <Field label={t("self_improvement.detail.dates")}>
            <ul className="space-y-0.5 text-sm tabular-nums text-foreground">
              {change.admitted && (
                <li>{fill(t("self_improvement.detail.date_admitted"), { date: new Date(change.admitted.ts_ms).toLocaleString(locale) })}</li>
              )}
              <li>{fill(t("self_improvement.detail.date_since"), { date: new Date(change.since_ms).toLocaleString(locale) })}</li>
              {change.last_check && (
                <li>{fill(t("self_improvement.detail.date_checked"), { date: new Date(change.last_check.ts_ms).toLocaleString(locale) })}</li>
              )}
            </ul>
            <p className="mt-1 font-mono text-xs text-muted-foreground">{change.target} · {change.id}</p>
          </Field>
        </dl>
      </div>
    </article>
  );
}

function MeasurementBlock({ found, kind, locale }: { found: Measurement | null; kind: "admitted" | "checked"; locale: string }) {
  const t = useT();
  if (!found) return <Quiet>{t("self_improvement.effect.none")}</Quiet>;
  return (
    <div className="space-y-1">
      <p className="text-base tabular-nums text-foreground">{effectWords(t, found, locale)}</p>
      <p className="text-sm text-muted-foreground">
        {fill(t(`self_improvement.detail.${kind}_on`), { n: found.n, when: relativeTime(found.ts_ms, locale) })}
      </p>
      {found.reason && (
        <p className="font-mono text-xs leading-relaxed text-muted-foreground" data-testid={`si-detail-reason-${kind}`}>
          {found.reason}
        </p>
      )}
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
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
