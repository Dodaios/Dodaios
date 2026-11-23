/**
 * What a person did to a plan before they answered its card: the text as they
 * left it, their comments on passages, a note on the whole plan.
 *
 * It lives outside the card on purpose. The review window closes and opens
 * again, the card itself is redrawn when the thread is switched, and none of
 * that may lose a half-written comment. A draft ends when its card is answered.
 */
import { create } from "zustand";
import type { PlanReviewPayload } from "@/lib/agentChatApi";

export interface PlanComment {
  id: string;
  /** The passage the comment is about, as it stood when the person marked it. */
  quote: string;
  /** Where the passage started in the plan's text, to tell two equal passages apart. */
  at: number;
  text: string;
}

export interface PlanDraft {
  /** The plan as the person left it; null while they have not changed its text. */
  plan: string | null;
  comments: PlanComment[];
  note: string;
}

export const EMPTY_DRAFT: PlanDraft = { plan: null, comments: [], note: "" };

interface PlanDraftStore {
  drafts: Record<string, PlanDraft>;
  patch: (cardId: string, change: Partial<PlanDraft>) => void;
  clear: (cardId: string) => void;
}

export const usePlanDrafts = create<PlanDraftStore>((set) => ({
  drafts: {},
  patch: (cardId, change) => set((state) => {
    const next = { ...(state.drafts[cardId] ?? EMPTY_DRAFT), ...change };
    return { drafts: { ...state.drafts, [cardId]: next } };
  }),
  clear: (cardId) => set((state) => {
    if (!(cardId in state.drafts)) return state;
    const { [cardId]: _gone, ...rest } = state.drafts;
    return { drafts: rest };
  }),
}));

/** The draft of one plan card (the empty one until the person does something). */
export function usePlanDraft(cardId: string): PlanDraft {
  return usePlanDrafts((state) => state.drafts[cardId] ?? EMPTY_DRAFT);
}

export function planDraftOf(cardId: string): PlanDraft {
  return usePlanDrafts.getState().drafts[cardId] ?? EMPTY_DRAFT;
}

/** The comments that say something: one left empty is not sent. */
export function writtenComments(draft: PlanDraft): PlanComment[] {
  return draft.comments.filter((comment) => comment.text.trim());
}

/** Whether the person changed the plan's text or commented on a passage. */
export function isReviewed(draft: PlanDraft): boolean {
  return draft.plan !== null || writtenComments(draft).length > 0;
}

/**
 * What the answer carries. Undefined when there is nothing to send, so an
 * untouched plan is answered exactly as before the review window existed.
 * `withNote` adds the note on the whole plan (a plain "keep planning" with
 * only a note still goes as the card's ordinary reason).
 */
export function reviewOf(draft: PlanDraft, withNote: boolean): PlanReviewPayload | undefined {
  const comments = writtenComments(draft).map((comment) => ({ quote: comment.quote, text: comment.text.trim() }));
  const note = withNote ? draft.note.trim() : "";
  if (draft.plan === null && !comments.length && !note) return undefined;
  return {
    ...(draft.plan !== null ? { plan: draft.plan } : {}),
    ...(comments.length ? { comments } : {}),
    ...(note ? { note } : {}),
  };
}

/**
 * How a plan card's answer goes out. A plan the person edited or commented on
 * goes with its review; "keep planning" with only a typed note stays the plain
 * reason it always was; "build" takes the note along as a note on the plan.
 */
export function planAnswer(cardId: string, decision: "allow" | "deny"): { feedback?: string; review?: PlanReviewPayload } {
  const draft = planDraftOf(cardId);
  if (decision === "allow" || isReviewed(draft)) {
    const review = reviewOf(draft, true);
    return review ? { review } : {};
  }
  const note = draft.note.trim();
  return note ? { feedback: note } : {};
}

let serial = 0;

export function newCommentId(): string {
  serial += 1;
  return `c${Date.now().toString(36)}${serial}`;
}
