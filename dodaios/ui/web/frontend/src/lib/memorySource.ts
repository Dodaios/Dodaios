/**
 * "Where do I know this from?": the conversation message a memory was learned
 * from, and the jump to it.
 *
 * The learning loop records where a line was said in the memory's `source`
 * (`session_id`, `turn_id`, `message_seq`, plus the quoted `evidence`;
 * `dodaios/memory/vault/reconcile.py`). The conversation renders a person's
 * message as `[data-message-id="u-<seq>"]` and an answer as
 * `[data-message-id="<turn id>"]` (components/agentchat/reduce.ts), so the
 * jump tries the message, then its turn, then the person's message that holds
 * the quote (a spoken turn has no recorded number).
 */
import { useEventStore } from "@/store/events";
import { useHomeStore } from "@/store/home";

export interface MessageAnchor {
  sessionId?: string;
  turnId?: string;
  seq?: number;
  evidence?: string;
}

function text(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

/** The anchor a memory's `source` (or a learned notice's row) carries, if any. */
export function anchorOf(source: Record<string, unknown> | null | undefined): MessageAnchor | null {
  if (!source) return null;
  const seq = Number(source.message_seq);
  const anchor: MessageAnchor = {
    sessionId: text(source.session_id) || undefined,
    turnId: text(source.turn_id) || undefined,
    seq: Number.isFinite(seq) && seq > 0 ? seq : undefined,
    evidence: text(source.evidence) || undefined,
  };
  // A quote alone is enough only for what was said in a conversation.
  const conversational = Boolean(anchor.sessionId || anchor.turnId || anchor.seq) ||
    ["review", "explicit request", "remember tool"].includes(text(source.via));
  if (!conversational) return null;
  return anchor.seq || anchor.turnId || anchor.evidence ? anchor : null;
}

function byId(root: ParentNode, id: string): HTMLElement | null {
  // Attribute compare instead of a selector: ids may hold characters a selector would need escaped.
  for (const el of Array.from(root.querySelectorAll<HTMLElement>("[data-message-id]"))) {
    if (el.dataset.messageId === id) return el;
  }
  return null;
}

function squash(value: string): string {
  return value.toLocaleLowerCase().replace(/\s+/g, " ").replace(/^["'“”„.,!? ]+|["'“”„.,!? ]+$/g, "");
}

/** The element of the message an anchor points at, in what is on screen now. */
export function findMessage(anchor: MessageAnchor, root: ParentNode = document): HTMLElement | null {
  if (anchor.seq) {
    const hit = byId(root, `u-${anchor.seq}`);
    if (hit) return hit;
  }
  const quote = anchor.evidence ? squash(anchor.evidence) : "";
  if (quote) {
    const mine = Array.from(root.querySelectorAll<HTMLElement>("[data-message-id^='u-']"));
    for (let i = mine.length - 1; i >= 0; i -= 1) {
      if (squash(mine[i].textContent ?? "").includes(quote)) return mine[i];
    }
  }
  return anchor.turnId ? byId(root, anchor.turnId) : null;
}

function reveal(el: HTMLElement) {
  const reduce = typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  el.scrollIntoView?.({ behavior: reduce ? "auto" : "smooth", block: "center" });
  el.setAttribute("data-memory-source", "true");
  el.classList.add("ring-2", "ring-accent/60", "rounded-lg");
  window.setTimeout(() => {
    el.classList.remove("ring-2", "ring-accent/60", "rounded-lg");
    el.removeAttribute("data-memory-source");
  }, 2400);
}

/**
 * Bring the message into view and mark it for a moment. With `navigate`, the
 * front page (the one conversation) opens first. Resolves false when the
 * message is not on screen (further back than the loaded conversation).
 */
export function jumpToMessage(anchor: MessageAnchor, { navigate = false, timeoutMs = 2500 } = {}): Promise<boolean> {
  if (navigate) {
    useHomeStore.getState().openAgentChat(null);
    useEventStore.getState().setActiveSection("chats");
  }
  const started = Date.now();
  return new Promise((resolve) => {
    const look = () => {
      const el = findMessage(anchor);
      if (el) {
        reveal(el);
        resolve(true);
      } else if (Date.now() - started >= timeoutMs) {
        resolve(false);
      } else {
        window.setTimeout(look, 120);
      }
    };
    look();
  });
}
