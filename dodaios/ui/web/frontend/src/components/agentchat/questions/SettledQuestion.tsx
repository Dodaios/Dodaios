import { useEffect, useState, type CSSProperties } from "react";
import { ArrowRight, Check, ChevronDown, Clock3, Copy, CornerUpRight, Sparkles } from "lucide-react";
import { useT } from "@/i18n";
import type { SocietyAgent } from "@/components/society/data";
import type { QuestionItem, QuestionState } from "../reduce";
import { AskerMark } from "./askerLook";
import { KeyCap } from "./KeyCap";
import { patchQuestionDraft, useQuestionDraft } from "./questionDraftStore";
import {
  answeredByMessage,
  copyText,
  isDismissed,
  LETTERS,
  ownWords,
  pickedIndices,
  settledNote,
  type SettledNote,
} from "./questionModel";

const NOTE_KEY: Partial<Record<SettledNote, string>> = {
  auto: "question_card.note_auto",
  agent: "question_card.note_agent",
  declined: "question_card.note_declined",
  moved_on: "question_card.note_moved_on",
  message: "question_card.note_message",
  unanswered: "question_card.unanswered",
  own: "question_card.own_words",
};

const QUIET_MARK = { auto: Clock3, agent: Sparkles, moved_on: CornerUpRight } as const;

/** A short line under each answer: how it came about, when that is not obvious. */
function useNoteText() {
  const t = useT();
  return (note: SettledNote, agentName: string) => {
    const key = NOTE_KEY[note];
    return key ? t(key).replace("{agent}", agentName) : "";
  };
}

/**
 * A question card after it settled: one quiet line, "prompt → chosen answers",
 * that opens into a read-only review of every step. A card nobody answered
 * reads muted with a dotted chip. A card answered from the chat settles the
 * same way (the typed reply as its answer chip, under the option's letter when
 * it named one) and keeps the person's reply as their bubble below it.
 */
export function SettledQuestion({
  question,
  agent,
  style,
  agentName,
  pending,
}: {
  question: QuestionState;
  agent: SocietyAgent | null;
  style: CSSProperties | undefined;
  agentName: string;
  /** The answer is on its way (optimistic). */
  pending: boolean;
}) {
  const t = useT();
  const draft = useQuestionDraft(question.questionId);
  const noteText = useNoteText();
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const id = window.setTimeout(() => setCopied(false), 1500);
    return () => window.clearTimeout(id);
  }, [copied]);

  const total = question.questions.length;
  const dismissed = isDismissed(question);
  const expanded = draft.expanded;
  const page = Math.min(draft.page, total - 1);
  const sources = question.answers.map((a) => a?.source ?? "closed").join(" ");
  const toggle = () => patchQuestionDraft(question.questionId, (d) => ({ ...d, expanded: !d.expanded }));
  const copy = () => {
    void navigator.clipboard?.writeText(copyText(question)).then(() => setCopied(true), () => undefined);
  };
  // An answer nobody picked by hand gets a quiet mark; its sentence is the tooltip.
  const quiet = question.answers.map(settledNote).find((note) => note in QUIET_MARK) as keyof typeof QUIET_MARK | undefined;
  const marker = quiet && !dismissed ? { Icon: QUIET_MARK[quiet], text: noteText(quiet, agentName) } : null;
  const summary = total > 1
    ? t("question_card.title_many").replace("{agent}", agentName).replace("{count}", String(total))
    : question.questions[0].question;

  const card = (
    <div
      className="qc"
      data-settled=""
      data-dismissed={dismissed ? "" : undefined}
      data-testid="question-card"
      data-state={sources}
      data-in-chat={answeredByMessage(question) ? "" : undefined}
      style={style}
    >
      <div className="flex items-center">
        <button type="button" className="qc-sum" aria-expanded={expanded} onClick={toggle}
          aria-label={`${summary} — ${expanded ? t("question_card.collapse") : t("question_card.expand")}`}>
          <AskerMark agent={agent} size={20} />
          <span className="qc-sum-prompt">{summary}</span>
          <ArrowRight aria-hidden className="qc-sum-arrow h-3.5 w-3.5" />
          <span className="qc-chips">
            {dismissed ? (
              <span className="qc-chip" data-muted="" data-plain="">{t("question_card.skipped_chip")}</span>
            ) : (
              question.questions.flatMap((item, i) => answerChips(item, question.answers[i], i, t("question_card.skipped_chip")))
            )}
          </span>
          <span className="qc-sum-tail">
            {marker ? <marker.Icon aria-label={marker.text} className="h-3.5 w-3.5" /> : null}
            {pending ? <span className="qc-pending" title={t("question_card.sending")} aria-label={t("question_card.sending")} role="status" /> : null}
            <ChevronDown aria-hidden className="qc-chevron h-4 w-4" />
          </span>
        </button>
        <button type="button" className="qc-icon-btn mr-1.5" onClick={copy}
          aria-label={copied ? t("question_card.copied") : t("question_card.copy")}
          title={copied ? t("question_card.copied") : t("question_card.copy")}>
          {copied ? <Check aria-hidden className="h-3.5 w-3.5" /> : <Copy aria-hidden className="h-3.5 w-3.5" />}
        </button>
      </div>
      <div className="qc-collapse" data-open={expanded ? "" : undefined}>
        <div>
          {expanded ? (
            <>
              <div className="qc-steps">
                {question.questions.map((item, i) => {
                  const answer = question.answers[i];
                  const picked = pickedIndices(answer);
                  const own = ownWords(answer, item);
                  const note = settledNote(answer);
                  const text = noteText(note === "picked" || note === "own" ? "picked" : note, agentName);
                  return (
                    <div key={i} className="qc-step" data-active={i === page ? "" : undefined} aria-hidden={i === page ? undefined : true}>
                      <h3 className="qc-title">{item.question}</h3>
                      <div className="qc-list" role="group" aria-label={t("question_card.answer_label")}>
                        {picked.map((index) => (
                          <div key={index} className="qc-row" data-described={item.options[index]?.description ? "" : undefined}>
                            <KeyCap on>{LETTERS[index]}</KeyCap>
                            <span className="qc-row-body">
                              <span className="qc-label">{item.options[index]?.label}</span>
                              {item.options[index]?.description ? <span className="qc-desc">{item.options[index].description}</span> : null}
                            </span>
                          </div>
                        ))}
                        {own ? (
                          <div className="qc-row">
                            <KeyCap on>{LETTERS[item.options.length] ?? "·"}</KeyCap>
                            <span className="qc-row-body"><span className="qc-label whitespace-pre-line">{own}</span></span>
                          </div>
                        ) : null}
                        {!picked.length && !own ? (
                          item.options.map((option, index) => (
                            <div key={index} className="qc-row" aria-disabled>
                              <KeyCap>{LETTERS[index]}</KeyCap>
                              <span className="qc-row-body"><span className="qc-label text-muted-foreground">{option.label}</span></span>
                            </div>
                          ))
                        ) : null}
                      </div>
                      {text ? <p className="qc-note">{text}</p> : null}
                    </div>
                  );
                })}
              </div>
              {total > 1 ? (
                <div className="qc-foot">
                  <Dots total={total} current={page} done={total} label={t("question_card.step")} />
                  <span className="qc-foot-end">
                    <button type="button" className="qc-btn qc-btn-quiet" disabled={page === 0}
                      onClick={() => patchQuestionDraft(question.questionId, (d) => ({ ...d, page: Math.max(0, page - 1) }))}>
                      {t("question_card.back")}
                    </button>
                    <button type="button" className="qc-btn qc-btn-quiet" disabled={page >= total - 1}
                      onClick={() => patchQuestionDraft(question.questionId, (d) => ({ ...d, page: Math.min(total - 1, page + 1) }))}>
                      {t("question_card.next")}
                    </button>
                  </span>
                </div>
              ) : <div className="h-2" />}
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
  const reply = chatReply(question);
  if (!reply) return card;
  return (
    <div className="flex w-full flex-col gap-1.5" data-testid="question-answered-in-chat">
      {card}
      <div className="qc-reply"><div className="qc-reply-bubble">{reply}</div></div>
    </div>
  );
}

function answerChips(item: QuestionItem, answer: QuestionState["answers"][number], index: number, skippedLabel: string) {
  const picked = pickedIndices(answer);
  const own = ownWords(answer, item);
  const chips = picked.map((i) => (
    <span key={`${index}:${i}`} className="qc-chip">
      <KeyCap on size="sm">{LETTERS[i]}</KeyCap>
      <span>{item.options[i]?.label}</span>
    </span>
  ));
  if (own) chips.push(<span key={`${index}:own`} className="qc-chip" data-plain=""><span>{own.split("\n").join(", ")}</span></span>);
  if (!chips.length) chips.push(<span key={`${index}:none`} className="qc-chip" data-muted="" data-plain=""><span>{skippedLabel}</span></span>);
  return chips;
}

/**
 * Progress dots of a series, one per question: a wide pill for the step on
 * screen, a filled dot for an answered one, a hollow ring for one still open.
 * On the review step (`current === total`) every dot reads by its own state.
 */
export function Dots({
  total,
  current,
  done,
  label,
  progressLabel,
}: {
  total: number;
  current: number;
  done: number | readonly boolean[];
  label: string;
  /** "{answered} of {total} answered", read out beside the step. */
  progressLabel?: string;
}) {
  const isDone = (i: number) => (typeof done === "number" ? i < done : Boolean(done[i]));
  const answered = Array.from({ length: total }, (_, i) => isDone(i)).filter(Boolean).length;
  const onStep = current < total;
  const stepText = label.replace("{current}", String(Math.min(current + 1, total))).replace("{total}", String(total));
  const progressText = progressLabel?.replace("{answered}", String(answered)).replace("{total}", String(total)) ?? "";
  const text = [onStep ? stepText : "", progressText].filter(Boolean).join(", ") || stepText;
  return (
    <span className="qc-dots" role="img" aria-label={text} data-testid="question-dots">
      {Array.from({ length: total }, (_, i) => {
        const state = i === current ? "current" : isDone(i) ? "done" : "open";
        return (
          <span
            key={i}
            className="qc-dot"
            data-state={state}
            data-on={state === "current" ? "" : undefined}
            data-done={isDone(i) ? "" : undefined}
          />
        );
      })}
    </span>
  );
}

/**
 * The reply the person typed into the chat to answer a live card. The chat
 * sent no message of its own for it, so the card keeps it as their bubble;
 * an end-of-turn card's reply went out as an ordinary message instead.
 */
function chatReply(question: QuestionState): string {
  if (question.deferred) return "";
  return question.answers.find((a) => a?.source === "message")?.text ?? "";
}
