import { memo, useEffect, useId, useLayoutEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type RefObject } from "react";
import { CircleAlert, CornerDownLeft, MoreHorizontal, SkipForward, Sparkles, X } from "lucide-react";
import { useT } from "@/i18n";
import type { QuestionState } from "../reduce";
import { AskerMark, useAskerLook } from "./askerLook";
import { patchQuestionDraft, useQuestionDraft, useQuestionDrafts, type QuestionDraft } from "./questionDraftStore";
import {
  answerAsLocal,
  EMPTY_ANSWER,
  hasAnswer,
  LETTERS,
  pickSingle,
  remainingMs,
  RING_WINDOW_MS,
  toggleMulti,
  withText,
  type LocalAnswer,
} from "./questionModel";
import { QuestionStep } from "./QuestionStep";
import { Dots, SettledQuestion } from "./SettledQuestion";
import { useQuestionActions } from "./useQuestionActions";
import { useQuestionKeyboard } from "./useQuestionKeyboard";
import "./questionCard.css";

/**
 * An agent's question card (dodaios/agent_chat/questions.py).
 *
 * A calm, forgiving exchange: lettered answers the person picks by click or
 * by plain letter key, their own words behind the next letter, several picks
 * for a multi-select question, and a short series with Back, Skip and a
 * review step where any answer can still change before one Send. Answers
 * settle the card at once and roll back with Try again if they did not get
 * through. The quiet window shows only in its last minute; the menu offers
 * to skip this one question or to let the agent decide them all.
 */
export const QuestionCard = memo(function QuestionCard({ question }: { question: QuestionState }) {
  const t = useT();
  const draft = useQuestionDraft(question.questionId);
  const look = useAskerLook(question.asker);
  const agentName = question.asker || t("question_card.fallback_agent");
  const submission = draft.submission;
  // The server's word wins; until it comes, a sent answer already reads as settled.
  useEffect(() => {
    if (question.closed && submission) patchQuestionDraft(question.questionId, (d) => ({ ...d, submission: null, answers: [] }));
  }, [question.closed, question.questionId, submission]);
  if (question.closed) {
    return <SettledQuestion question={question} agent={look.agent} style={look.style} agentName={agentName} pending={false} />;
  }
  if (submission && submission.status !== "failed") {
    return (
      <SettledQuestion
        question={{ ...question, answers: submission.answers, closed: true }}
        agent={look.agent}
        style={look.style}
        agentName={agentName}
        pending
      />
    );
  }
  return <OpenCard question={question} draft={draft} look={look} agentName={agentName} />;
});

function useRemaining(question: QuestionState): number | null {
  const [now, setNow] = useState(() => Date.now());
  const left = remainingMs(question, now);
  useEffect(() => {
    if (left === null || left <= 0) return;
    // Sleep until the last minute starts, then tick once a second.
    const delay = left > RING_WINDOW_MS ? left - RING_WINDOW_MS : 1000;
    const id = window.setTimeout(() => setNow(Date.now()), Math.min(delay, 2_147_000_000));
    return () => window.clearTimeout(id);
  }, [left]);
  return left;
}

/**
 * The pixel height of `inner`, kept current, so a frame around it can ease
 * between steps of different heights (CSS cannot transition `auto`).
 * Null until measured, or where there is no ResizeObserver.
 */
function useMeasuredHeight(inner: RefObject<HTMLElement | null>): number | null {
  const [height, setHeight] = useState<number | null>(null);
  useLayoutEffect(() => {
    const el = inner.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const measure = () => setHeight(el.offsetHeight);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [inner]);
  return height;
}

function clock(ms: number): string {
  const seconds = Math.ceil(ms / 1000);
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

/** A slim ring that empties over the last minute of a live card. */
function CountdownRing({ question }: { question: QuestionState }) {
  const t = useT();
  const left = useRemaining(question);
  if (left === null || left > RING_WINDOW_MS) return null;
  const label = t("question_card.countdown").replace("{time}", clock(left));
  const r = 7;
  const length = 2 * Math.PI * r;
  return (
    <span className="qc-ring" role="timer" aria-live="off" aria-label={label} title={label} data-testid="question-countdown">
      <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden>
        <circle className="qc-ring-track" cx="9" cy="9" r={r} />
        <circle className="qc-ring-left" cx="9" cy="9" r={r} strokeDasharray={length}
          strokeDashoffset={length * (1 - left / RING_WINDOW_MS)} transform="rotate(-90 9 9)" />
      </svg>
    </span>
  );
}

function OpenCard({
  question,
  draft,
  look,
  agentName,
}: {
  question: QuestionState;
  draft: QuestionDraft;
  look: ReturnType<typeof useAskerLook>;
  agentName: string;
}) {
  const t = useT();
  const titleId = useId();
  const cardRef = useRef<HTMLElement>(null);
  const ownRefs = useRef<(HTMLTextAreaElement | null)[]>([]);
  const stepsRef = useRef<HTMLDivElement>(null);
  const stepsHeight = useMeasuredHeight(stepsRef);
  const advance = useRef<number | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [entered] = useState(() => (question.closed ? undefined : "new"));
  const actions = useQuestionActions(question);
  const { questionId, questions } = question;
  const total = questions.length;
  const series = total > 1;
  const failed = draft.submission?.status === "failed" ? draft.submission : null;

  const locals: LocalAnswer[] = questions.map((item, i) => draft.answers[i] ?? answerAsLocal(question.answers[i], item));
  const firstOpen = Math.max(0, question.answers.findIndex((a) => a === null));
  const step = Math.min(draft.step < 0 ? firstOpen : draft.step, series ? total : 0);
  const reviewing = series && step === total;
  const item = reviewing ? null : questions[step];
  const local = reviewing ? EMPTY_ANSWER : locals[step];
  const locked = (i: number) => question.answers[i] !== null;
  // A step opened from the review returns there once it is answered.
  const backToReview = series && !reviewing && draft.returnToReview;

  useEffect(() => () => {
    if (advance.current !== null) window.clearTimeout(advance.current);
  }, []);

  const write = (fn: (d: QuestionDraft, current: LocalAnswer[]) => QuestionDraft) => {
    patchQuestionDraft(questionId, (d) => {
      const current = questions.map((q, i) => d.answers[i] ?? answerAsLocal(question.answers[i], q));
      return fn(d, current);
    });
    actions.touch();
  };
  const setLocal = (index: number, next: LocalAnswer) =>
    write((d, current) => ({ ...d, answers: current.map((a, i) => (i === index ? next : a)) }));
  const goTo = (next: number, fromReview = false) => {
    if (advance.current !== null) window.clearTimeout(advance.current);
    advance.current = null;
    write((d) => ({ ...d, step: Math.max(0, Math.min(next, total)), returnToReview: fromReview }));
  };
  /** Past the step on screen: the next one, or the review it was opened from. */
  const forward = () => goTo(backToReview ? total : step + 1);
  /** Send the whole card with `override` folded in (the read is the store's newest). */
  const submitWith = (index: number, override: LocalAnswer) => {
    const current = questions.map((q, i) => {
      const saved = useQuestionDrafts.getState().drafts[questionId]?.answers[i];
      return i === index ? override : saved ?? answerAsLocal(question.answers[i], q);
    });
    setLocal(index, override);
    void actions.submit(current);
  };

  const pick = (optionIndex: number) => {
    if (!item || locked(step)) return;
    if (item.kind === "multi") {
      setLocal(step, toggleMulti(local, optionIndex));
      return;
    }
    const next = pickSingle(optionIndex);
    if (!series) {
      submitWith(step, next);
      return;
    }
    setLocal(step, next);
    // Let the pick show for a beat, then move on; the review step follows the last.
    if (advance.current !== null) window.clearTimeout(advance.current);
    const from = step;
    advance.current = window.setTimeout(() => {
      advance.current = null;
      patchQuestionDraft(questionId, (d) => ((d.step < 0 ? firstOpen : d.step) === from
        ? { ...d, step: d.returnToReview ? total : from + 1, returnToReview: false }
        : d));
    }, 180);
  };
  const typed = (text: string) => item && setLocal(step, withText(local, item, text));
  const commitStep = () => {
    if (!item) return;
    if (!series) {
      // Done with nothing picked skips the question instead of sending nothing.
      submitWith(step, hasAnswer(local) ? local : { ...EMPTY_ANSWER, skipped: true });
      return;
    }
    forward();
  };
  const skipStep = () => {
    setMenuOpen(false);
    const skipped = { ...EMPTY_ANSWER, skipped: true };
    if (!series) {
      submitWith(step, skipped);
      return;
    }
    setLocal(step, skipped);
    forward();
  };
  const decideAll = () => {
    setMenuOpen(false);
    void actions.decideAll();
  };
  const sendSeries = () => void actions.submit(locals);

  const onKey = (event: KeyboardEvent): boolean => {
    if (!item || menuOpen || draft.submission?.status === "sending") return false;
    if (event.key.length !== 1) return false;
    const index = LETTERS.indexOf(event.key.toUpperCase());
    if (index < 0) return false;
    if (index < item.options.length) {
      pick(index);
      return true;
    }
    if (item.allowCustom && index === item.options.length) {
      ownRefs.current[step]?.focus();
      return true;
    }
    return false;
  };
  const target = useQuestionKeyboard(cardRef, onKey, true);

  // Arrow keys walk the rows of the step on screen once one has focus.
  const onCardKeyDown = (event: ReactKeyboardEvent<HTMLElement>) => {
    if (event.key === "Escape" && menuOpen) {
      event.preventDefault();
      setMenuOpen(false);
      return;
    }
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    const rows = Array.from(cardRef.current?.querySelectorAll<HTMLElement>(
      ".qc-step[data-active] [data-qc-row]:not(:disabled), .qc-step[data-active] [data-qc-own] textarea",
    ) ?? []);
    const at = rows.findIndex((el) => el === document.activeElement);
    if (at < 0 || rows[at].tagName === "TEXTAREA" && event.key === "ArrowDown") return;
    event.preventDefault();
    rows[(at + (event.key === "ArrowDown" ? 1 : rows.length - 1)) % rows.length]?.focus();
  };

  const answered = locals.map(hasAnswer);
  // A lone single question shows Send once the person typed their own words.
  const typedSingle = !series && item?.kind === "single" && Boolean(local.text.trim());
  const footer = series || item?.kind === "multi" || item?.kind === "text" || typedSingle || failed;

  return (
    <section
      ref={cardRef}
      className="qc"
      data-enter={entered}
      data-target={target ? "" : undefined}
      data-testid="question-card"
      data-state="open"
      aria-labelledby={titleId}
      onKeyDown={onCardKeyDown}
      style={look.style}
    >
      <header className="qc-head">
        <AskerMark agent={look.agent} />
        <span className="qc-asker">
          <b>{agentName}</b> {t("question_card.asks")}
        </span>
        {series && !reviewing ? (
          <span className="qc-count" data-testid="question-step">
            {t("question_card.step").replace("{current}", String(Math.min(step + 1, total))).replace("{total}", String(total))}
          </span>
        ) : null}
        <span className="flex-1" />
        <CountdownRing question={question} />
        <button
          type="button"
          className="qc-icon-btn"
          aria-haspopup="menu"
          aria-expanded={menuOpen}
          aria-label={t("question_card.menu")}
          title={t("question_card.menu")}
          onClick={() => setMenuOpen((open) => !open)}
        >
          {menuOpen ? <X aria-hidden className="h-4 w-4" /> : <MoreHorizontal aria-hidden className="h-4 w-4" />}
        </button>
      </header>

      {menuOpen ? (
        <CardMenu
          agentName={agentName}
          canSkipStep={Boolean(item) && !locked(step)}
          onSkipStep={skipStep}
          onDecideAll={decideAll}
          onClose={() => setMenuOpen(false)}
        />
      ) : null}

      <div className="qc-steps-frame" style={stepsHeight === null ? undefined : { height: stepsHeight }}>
      <div ref={stepsRef} className="qc-steps" data-reviewing={reviewing ? "" : undefined}>
        {questions.map((q, i) => (
          <QuestionStep
            key={i}
            ref={(el) => {
              ownRefs.current[i] = el;
            }}
            item={q}
            local={locals[i]}
            active={i === step}
            locked={locked(i)}
            titleId={i === step ? titleId : undefined}
            onPick={pick}
            onText={typed}
            onSubmitText={commitStep}
          />
        ))}
        {series ? (
          <div className="qc-step" data-active={reviewing ? "" : undefined} aria-hidden={reviewing ? undefined : true}
            {...(reviewing ? {} : ({ inert: "" } as Record<string, string>))}>
            <h3 id={reviewing ? titleId : undefined} className="qc-title">{t("question_card.review_title")}</h3>
            <div className="qc-review" data-testid="question-review">
              {questions.map((q, i) => {
                const a = locals[i];
                const text = a.skipped || !hasAnswer(a)
                  ? ""
                  : [...a.picks.map((p) => q.options[p]?.label), ...(a.text.trim() ? [a.text.trim()] : [])].join("\n");
                return (
                  <button key={i} type="button" className="qc-review-row" onClick={() => goTo(i, true)} disabled={locked(i)}
                    aria-label={`${q.question}: ${text || t("question_card.skipped_chip")}. ${t("question_card.change")}`}>
                    <span className="qc-keycap" data-on={text ? "" : undefined} aria-hidden>{i + 1}</span>
                    <span className="min-w-0 flex-1">
                      <span className="qc-review-q">{q.question}</span>
                      <span className="qc-review-a" data-empty={text ? undefined : ""}>{text || t("question_card.skipped_chip")}</span>
                    </span>
                    {locked(i) ? null : <span className="qc-review-edit">{t("question_card.change")}</span>}
                  </button>
                );
              })}
            </div>
          </div>
        ) : null}
      </div>
      </div>

      {footer ? (
        <footer className="qc-foot">
          {failed ? (
            <p role="alert" className="qc-alert">
              <CircleAlert aria-hidden className="h-3.5 w-3.5 shrink-0" />
              <span>{t("question_card.failed")}</span>
            </p>
          ) : series ? (
            <Dots total={total} current={step} done={answered} label={t("question_card.step")} progressLabel={t("question_card.progress")} />
          ) : null}
          <span className="qc-foot-end">
            {failed ? (
              <button type="button" className="qc-btn qc-btn-quiet" onClick={() => void actions.retry()} title={failed.error}>
                {t("question_card.try_again")}
              </button>
            ) : null}
            {series && step > 0 ? (
              <button type="button" className="qc-btn qc-btn-quiet" onClick={() => goTo(step - 1)}>{t("question_card.back")}</button>
            ) : null}
            {series && !reviewing ? (
              <button type="button" className="qc-btn qc-btn-quiet" onClick={skipStep} disabled={locked(step)}>
                {t("question_card.skip")}
              </button>
            ) : null}
            {series && !reviewing ? (
              <button type="button" className="qc-btn qc-btn-primary" onClick={forward} disabled={!hasAnswer(local) && !locked(step)}>
                {step === total - 1 || backToReview ? t("question_card.review") : t("question_card.next")}
              </button>
            ) : null}
            {reviewing ? (
              <button type="button" className="qc-btn qc-btn-primary" data-testid="question-send" onClick={sendSeries}>
                {t("question_card.send_answers")}
              </button>
            ) : null}
            {!series && item && (item.kind !== "single" || typedSingle) && !failed ? (
              <button type="button" className="qc-btn qc-btn-primary" data-testid="question-done" onClick={commitStep}>
                {item.kind === "multi" ? null : <CornerDownLeft aria-hidden className="h-3.5 w-3.5" />}
                {item.kind === "multi" ? t("question_card.done") : t("question_card.send")}
              </button>
            ) : null}
          </span>
        </footer>
      ) : (
        <div className="h-1" />
      )}
      {target ? <span className="qc-sr" aria-live="polite">{t("question_card.keys_hint")}</span> : null}
    </section>
  );
}

/** The card's own menu: two clearly named ways out, never a silent close. */
function CardMenu({
  agentName,
  canSkipStep,
  onSkipStep,
  onDecideAll,
  onClose,
}: {
  agentName: string;
  canSkipStep: boolean;
  onSkipStep: () => void;
  onDecideAll: () => void;
  onClose: () => void;
}) {
  const t = useT();
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current?.querySelector<HTMLButtonElement>("button")?.focus();
    const away = (event: PointerEvent) => {
      const el = ref.current;
      if (el && !el.contains(event.target as Node) && !(event.target as HTMLElement).closest?.(".qc-icon-btn")) onClose();
    };
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [onClose]);
  return (
    <div ref={ref} className="qc-menu" role="menu" aria-label={t("question_card.menu")}>
      {canSkipStep ? (
        <button type="button" role="menuitem" className="qc-menu-item" onClick={onSkipStep}>
          <SkipForward aria-hidden className="h-4 w-4" />
          <span>
            <span className="qc-menu-title">{t("question_card.skip_this")}</span>
            <span className="qc-menu-hint">{t("question_card.skip_this_hint").replace("{agent}", agentName)}</span>
          </span>
        </button>
      ) : null}
      <button type="button" role="menuitem" className="qc-menu-item" onClick={onDecideAll}>
        <Sparkles aria-hidden className="h-4 w-4" />
        <span>
          <span className="qc-menu-title">{t("question_card.let_decide").replace("{agent}", agentName)}</span>
          <span className="qc-menu-hint">{t("question_card.let_decide_hint")}</span>
        </span>
      </button>
    </div>
  );
}
