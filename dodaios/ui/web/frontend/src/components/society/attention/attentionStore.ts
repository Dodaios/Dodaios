import { create } from "zustand";

import { fetchAttention, type AttentionItem, type AttentionList } from "./attentionApi";

/**
 * The "needs you" list and its count, held once for the whole app.
 *
 * A plain store rather than a query: the socket feeds it from outside any
 * React tree (`attentionBus`), and the bell must work in every shell that
 * renders the Agents section, with or without a query client around it.
 */

export type AttentionStatus = "idle" | "loading" | "ready" | "error";

interface AttentionState {
  /** The badge: open items across every agent (the window title carries it too). */
  count: number;
  /** The last list read; null until someone asked for it. */
  list: AttentionList | null;
  status: AttentionStatus;
  /** When the list was last read (ms), 0 for never. */
  readAt: number;
  /**
   * Cards the person answered here (approval, question, proposal ids): the
   * roster and the chat header stop saying "needs you" for them at once,
   * before the next roster read confirms it.
   */
  answered: readonly string[];
}

/** How many answered ids are remembered; older ones have long left the roster. */
const ANSWERED_KEEP = 64;

export const useAttentionStore = create<AttentionState>(() => ({ count: 0, list: null, status: "idle", readAt: 0, answered: [] }));

/** Note that the card `refId` was answered here, so nothing keeps asking for it. */
export function markAnswered(refId: string): void {
  if (!refId) return;
  const { answered } = useAttentionStore.getState();
  if (answered.includes(refId)) return;
  useAttentionStore.setState({ answered: [...answered, refId].slice(-ANSWERED_KEEP) });
}

/** Whether the card `refId` was answered here. */
export function wasAnswered(refId: string | undefined): boolean {
  return Boolean(refId) && useAttentionStore.getState().answered.includes(refId!);
}

const TITLE_BADGE = /^\(\d+\)\s+/;

/** Prefix the window title with the count ("(2) Dodaios"); restore it at zero. */
export function applyTitleBadge(count: number): void {
  if (typeof document === "undefined") return;
  const base = document.title.replace(TITLE_BADGE, "");
  const next = count > 0 ? `(${count}) ${base}` : base;
  if (document.title !== next) document.title = next;
}

/** Set the badge (the bell and the window title). */
export function syncAttentionCount(count: number): void {
  const safe = Number.isFinite(count) && count > 0 ? Math.floor(count) : 0;
  if (useAttentionStore.getState().count !== safe) useAttentionStore.setState({ count: safe });
  applyTitleBadge(safe);
}

let inflight: Promise<void> | null = null;
/** A change arrived while a read was on its way: read once more after it. */
let again = false;

/**
 * Read the list again, one request at a time. A call during a read asks for
 * one more read after it, so a change the running read may have missed is
 * never lost.
 */
export function refreshAttention(): Promise<void> {
  if (inflight) {
    again = true;
    return inflight;
  }
  if (!useAttentionStore.getState().list) useAttentionStore.setState({ status: "loading" });
  inflight = fetchAttention()
    .then((list) => {
      useAttentionStore.setState({ list, status: "ready", readAt: Date.now() });
      syncAttentionCount(list.count);
    })
    .catch(() => {
      // Keep what is on screen; the next change or reconnect tries again.
      useAttentionStore.setState((state) => ({ status: state.list ? state.status : "error" }));
    })
    .finally(() => {
      inflight = null;
      if (again) {
        again = false;
        void refreshAttention();
      }
    });
  return inflight;
}

/** Drop an answered item right away; the next read confirms it. */
export function forgetAttentionItem(item: AttentionItem): void {
  const { list } = useAttentionStore.getState();
  if (!list) return;
  markAnswered(item.refId);
  const items = list.items.filter((other) => !(other.refId === item.refId && other.sessionId === item.sessionId));
  if (items.length === list.items.length) return;
  const count = Math.max(0, list.count - (list.items.length - items.length));
  useAttentionStore.setState({ list: { items, count } });
  syncAttentionCount(count);
}

/** For tests: back to an empty, unread store. */
export function resetAttentionStore(): void {
  inflight = null;
  again = false;
  useAttentionStore.setState({ count: 0, list: null, status: "idle", readAt: 0, answered: [] });
}
