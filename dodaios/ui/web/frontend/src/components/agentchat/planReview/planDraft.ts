/**
 * What a person did to a plan before they answered its card: the text as they
 * left it, their comments on passages, a note on the whole plan.
 *
 * It lives outside the card on purpose. The review window closes and opens
 * again, the card itself is redrawn when the thread is switched, the window
 * reloads after a rebuild and the app restarts, and none of that may lose a
 * half-written review: the drafts are kept in this browser's storage. A draft
 * ends when its card is answered.
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
  /** When the person last touched it: the oldest drafts leave the storage first. */
  savedMs?: number;
}

export const EMPTY_DRAFT: PlanDraft = { plan: null, comments: [], note: "" };

export const PLAN_DRAFTS_KEY = "dodaios.planDrafts.v1";
/** A card nobody answered (a thread left behind) does not keep its draft for ever. */
const KEEP_MS = 14 * 24 * 60 * 60 * 1000;
const KEEP_DRAFTS = 8;

function isBlank(draft: PlanDraft): boolean {
  return draft.plan === null && draft.comments.length === 0 && !draft.note;
}

function readComment(raw: unknown): PlanComment | null {
  const row = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : null;
  if (!row || typeof row.id !== "string" || typeof row.quote !== "string" || typeof row.text !== "string") return null;
  return { id: row.id, quote: row.quote, at: typeof row.at === "number" ? row.at : 0, text: row.text };
}

/** The drafts this browser kept, without the ones too old to matter. */
export function loadPlanDrafts(now = Date.now()): Record<string, PlanDraft> {
  const out: Record<string, PlanDraft> = {};
  try {
    const raw: unknown = JSON.parse(localStorage.getItem(PLAN_DRAFTS_KEY) ?? "{}");
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) return out;
    for (const [cardId, value] of Object.entries(raw as Record<string, unknown>)) {
      const row = value && typeof value === "object" ? (value as Record<string, unknown>) : null;
      if (!row) continue;
      const savedMs = typeof row.savedMs === "number" ? row.savedMs : 0;
      if (now - savedMs > KEEP_MS) continue;
      const draft: PlanDraft = {
        plan: typeof row.plan === "string" ? row.plan : null,
        comments: Array.isArray(row.comments) ? row.comments.flatMap((entry) => readComment(entry) ?? []) : [],
        note: typeof row.note === "string" ? row.note : "",
        savedMs,
      };
      if (!isBlank(draft)) out[cardId] = draft;
    }
  } catch {
    // Storage blocked or an unreadable copy: the person starts without drafts.
  }
  return out;
}

function savePlanDrafts(drafts: Record<string, PlanDraft>): void {
  try {
    const newest = Object.entries(drafts)
      .sort(([, a], [, b]) => (b.savedMs ?? 0) - (a.savedMs ?? 0))
      .slice(0, KEEP_DRAFTS);
    if (newest.length) localStorage.setItem(PLAN_DRAFTS_KEY, JSON.stringify(Object.fromEntries(newest)));
    else localStorage.removeItem(PLAN_DRAFTS_KEY);
  } catch {
    // Storage full or blocked: the draft still lives as long as this window does.
  }
}

let lastStamp = 0;

/** Now, and never the same twice: two drafts touched in one millisecond still have an order. */
function stamp(): number {
  lastStamp = Math.max(Date.now(), lastStamp + 1);
  return lastStamp;
}

interface PlanDraftStore {
  drafts: Record<string, PlanDraft>;
  patch: (cardId: string, change: Partial<PlanDraft>) => void;
  clear: (cardId: string) => void;
}

export const usePlanDrafts = create<PlanDraftStore>((set) => ({
  drafts: loadPlanDrafts(),
  patch: (cardId, change) => set((state) => {
    const next: PlanDraft = { ...(state.drafts[cardId] ?? EMPTY_DRAFT), ...change, savedMs: stamp() };
    const { [cardId]: _was, ...rest } = state.drafts;
    // A draft the person emptied again is no draft.
    const drafts = isBlank(next) ? rest : { ...rest, [cardId]: next };
    savePlanDrafts(drafts);
    return { drafts };
  }),
  clear: (cardId) => set((state) => {
    if (!(cardId in state.drafts)) return state;
    const { [cardId]: _gone, ...rest } = state.drafts;
    savePlanDrafts(rest);
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
