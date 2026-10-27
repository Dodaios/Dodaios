import { create } from "zustand";
import type { QuestionSubmitAnswer } from "@/lib/agentChatApi";
import type { QuestionAnswerState } from "../reduce";
import type { LocalAnswer } from "./questionModel";

/**
 * What the person did on a question card that the server does not know yet,
 * keyed by question id: the step they are on, their picks and words, and an
 * answer on its way. It lives outside the card, so a card that remounts (the
 * chat re-renders, the person switches agents and back) resumes mid-series
 * with every pick in place.
 *
 * `submission` is the optimistic answer: the card settles the moment it is
 * set and only reopens when the request failed, with the exact same request
 * ready to try again.
 */

/** What went to the server; a retry replays it unchanged. */
export type QuestionRequest =
  | { kind: "submit"; answers: QuestionSubmitAnswer[] }
  | { kind: "decide_all" };

export interface QuestionSubmission {
  status: "sending" | "sent" | "failed";
  request: QuestionRequest;
  /** The answers the card shows while the request is on its way. */
  answers: (QuestionAnswerState | null)[];
  error?: string;
}

export interface QuestionDraft {
  /** The step on screen; `questions.length` is the review step, -1 the first open one. */
  step: number;
  /** The step on screen was opened from the review: finishing it goes back there. */
  returnToReview: boolean;
  answers: LocalAnswer[];
  submission: QuestionSubmission | null;
  /** A settled card the person opened to read again, and the page they are on. */
  expanded: boolean;
  page: number;
}

export const EMPTY_DRAFT: QuestionDraft = { step: -1, returnToReview: false, answers: [], submission: null, expanded: false, page: 0 };

interface DraftStore {
  drafts: Record<string, QuestionDraft>;
  patch: (questionId: string, fn: (draft: QuestionDraft) => QuestionDraft) => void;
  clear: (questionId: string) => void;
}

/** Drafts kept at most; the oldest go first (a long-running app asks a lot). */
const MAX_DRAFTS = 64;

export const useQuestionDrafts = create<DraftStore>((set) => ({
  drafts: {},
  patch: (questionId, fn) =>
    set((state) => {
      const next = fn(state.drafts[questionId] ?? EMPTY_DRAFT);
      const { [questionId]: _old, ...rest } = state.drafts;
      const ids = Object.keys(rest);
      const kept = ids.length >= MAX_DRAFTS ? Object.fromEntries(ids.slice(ids.length - MAX_DRAFTS + 1).map((id) => [id, rest[id]])) : rest;
      return { drafts: { ...kept, [questionId]: next } };
    }),
  clear: (questionId) =>
    set((state) => {
      if (!(questionId in state.drafts)) return state;
      const { [questionId]: _gone, ...rest } = state.drafts;
      return { drafts: rest };
    }),
}));

export function useQuestionDraft(questionId: string): QuestionDraft {
  return useQuestionDrafts((state) => state.drafts[questionId] ?? EMPTY_DRAFT);
}

export function readQuestionDraft(questionId: string): QuestionDraft {
  return useQuestionDrafts.getState().drafts[questionId] ?? EMPTY_DRAFT;
}

export function patchQuestionDraft(questionId: string, fn: (draft: QuestionDraft) => QuestionDraft): void {
  useQuestionDrafts.getState().patch(questionId, fn);
}
