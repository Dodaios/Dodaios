import type { QuestionSubmitAnswer } from "@/lib/agentChatApi";
import type { QuestionAnswerState, QuestionItem, QuestionState, Timeline, ToolBlock } from "../reduce";

/**
 * The pure rules of the question card: what the person picked locally, what
 * that sends, which card is open, and how a settled answer reads. No React
 * here, so every rule is a plain unit test.
 */

/** Letters for the rows; the row after the last option is the own-answer field. */
export const LETTERS = "ABCDE";

/** What the person picked on one question before anything is sent. */
export interface LocalAnswer {
  /** Picked options (one for a single question). */
  picks: number[];
  /** Their own words (next to the picks of a multi question). */
  text: string;
  /** They skipped this question: an empty answer, the agent decides. */
  skipped: boolean;
}

export const EMPTY_ANSWER: LocalAnswer = { picks: [], text: "", skipped: false };

export function hasAnswer(local: LocalAnswer | undefined): boolean {
  return Boolean(local && (local.skipped || local.picks.length > 0 || local.text.trim()));
}

/** A single question takes one option OR own words; picking one clears the other. */
export function pickSingle(index: number): LocalAnswer {
  return { picks: [index], text: "", skipped: false };
}

export function toggleMulti(local: LocalAnswer, index: number): LocalAnswer {
  const picks = local.picks.includes(index) ? local.picks.filter((i) => i !== index) : [...local.picks, index];
  return { ...local, picks: picks.sort((a, b) => a - b), skipped: false };
}

export function withText(local: LocalAnswer, item: QuestionItem, text: string): LocalAnswer {
  // A typed single answer replaces the picked option; multi keeps both.
  return item.kind === "multi" ? { ...local, text, skipped: false } : { picks: [], text, skipped: false };
}

/** What `/submit` receives for one question; `null` when nothing was chosen. */
export function toSubmit(local: LocalAnswer | undefined, item: QuestionItem): QuestionSubmitAnswer | null {
  if (!local) return null;
  if (local.skipped) return { skip: true };
  const text = local.text.trim();
  if (item.kind === "multi") {
    if (!local.picks.length && !text) return null;
    return text ? { option_indices: local.picks, text } : { option_indices: local.picks };
  }
  if (local.picks.length) return { option_index: local.picks[0] };
  return text ? { text } : null;
}

/** Every answer of the series, a skip for each question left untouched. */
export function seriesPayload(question: QuestionState, locals: LocalAnswer[]): QuestionSubmitAnswer[] {
  return question.questions.map((item, i) => toSubmit(locals[i], item) ?? { skip: true });
}

/** How the agent will read a local answer, for the optimistic settled card. */
export function localAsAnswer(local: LocalAnswer | undefined, item: QuestionItem): QuestionAnswerState {
  if (!local || local.skipped || !hasAnswer(local)) return { text: "", optionIndex: null, source: "declined" };
  const labels = local.picks.map((i) => item.options[i]?.label ?? "").filter(Boolean);
  const text = local.text.trim();
  const lines = [...labels, ...(text ? [text] : [])];
  if (item.kind === "multi") return { text: lines.join("\n"), optionIndex: null, source: "person", optionIndices: local.picks };
  return { text: lines[0] ?? "", optionIndex: local.picks[0] ?? null, source: "person" };
}

/** The server's answer back as local picks, so a reopened card can be changed. */
export function answerAsLocal(answer: QuestionAnswerState | null, item: QuestionItem): LocalAnswer {
  if (!answer) return EMPTY_ANSWER;
  if (answer.source === "declined") return { ...EMPTY_ANSWER, skipped: true };
  if (answer.optionIndices?.length) {
    const labels = new Set(answer.optionIndices.map((i) => item.options[i]?.label));
    const own = answer.text.split("\n").filter((line) => line && !labels.has(line)).join("\n");
    return { picks: [...answer.optionIndices], text: own, skipped: false };
  }
  if (answer.optionIndex !== null) return pickSingle(answer.optionIndex);
  return { picks: [], text: answer.text, skipped: false };
}

/** The picked options of a settled answer (none for own words). */
export function pickedIndices(answer: QuestionAnswerState | null): number[] {
  if (!answer) return [];
  if (answer.optionIndices?.length) return answer.optionIndices;
  return answer.optionIndex !== null ? [answer.optionIndex] : [];
}

/** The person's own words in a settled answer, beside any picked options. */
export function ownWords(answer: QuestionAnswerState | null, item: QuestionItem): string {
  if (!answer) return "";
  const picked = new Set(pickedIndices(answer).map((i) => item.options[i]?.label));
  return answer.text.split("\n").filter((line) => line.trim() && !picked.has(line)).join("\n");
}

/** How a settled answer came about — the card's small note under it. */
export type SettledNote =
  | "picked"
  | "own"
  | "auto"
  | "agent"
  | "declined"
  | "moved_on"
  | "message"
  | "unanswered";

export function settledNote(answer: QuestionAnswerState | null): SettledNote {
  if (!answer) return "unanswered";
  switch (answer.source) {
    case "timeout":
    case "unattended":
      return "auto";
    case "skipped":
      return "agent";
    case "declined":
      return "declined";
    case "moved_on":
      return "moved_on";
    case "message":
      return "message";
    case "cancelled":
    case "closed":
      return "unanswered";
    default:
      return pickedIndices(answer).length ? "picked" : answer.text.trim() ? "own" : "declined";
  }
}

/** Every question was skipped or left unanswered: the card reads as dismissed. */
export function isDismissed(question: QuestionState): boolean {
  return question.closed && question.answers.every((a) => {
    const note = settledNote(a);
    return note === "declined" || note === "unanswered";
  });
}

/** The person answered from the chat: the card reads as a plain question. */
export function answeredByMessage(question: QuestionState): boolean {
  return question.closed && question.answers.some((a) => a?.source === "message");
}

/** "question\nanswer" lines for the clipboard. */
export function copyText(question: QuestionState): string {
  return question.questions
    .map((item, i) => {
      const answer = question.answers[i];
      const text = answer?.text.trim() ? answer.text.split("\n").join(", ") : "—";
      return `${item.question}\n${text}`;
    })
    .join("\n\n");
}

/** Milliseconds left on a live card, or null for an end-of-turn card / no deadline. */
export function remainingMs(question: QuestionState, nowMs: number): number | null {
  if (question.deferred || question.expiresMs === null || question.closed) return null;
  return Math.max(0, question.expiresMs - nowMs);
}

/** Below this, the card shows its quiet countdown ring. */
export const RING_WINDOW_MS = 60_000;

/** The newest card still waiting for the person — what the composer answers. */
export function openQuestionOf(timeline: Pick<Timeline, "items">): { block: ToolBlock; question: QuestionState } | null {
  for (let i = timeline.items.length - 1; i >= 0; i -= 1) {
    const item = timeline.items[i];
    if (item.type === "user" && item.origin !== "control") return null;
    if (item.type !== "turn") continue;
    for (let j = item.blocks.length - 1; j >= 0; j -= 1) {
      const block = item.blocks[j];
      if (block.kind === "tool" && block.question && !block.question.closed) return { block, question: block.question };
    }
  }
  return null;
}

/** The agent's own default for one question, as "let the agent decide" applies it. */
export function recommendationOf(item: QuestionItem, source: string): QuestionAnswerState {
  if (!item.options.length) return { text: "", optionIndex: null, source };
  if (item.kind === "multi") {
    const picks = Array.from({ length: item.recommendedCount }, (_, i) => i);
    return { text: picks.map((i) => item.options[i].label).join("\n"), optionIndex: null, source, optionIndices: picks };
  }
  return { text: item.options[0].label, optionIndex: 0, source };
}
