import { create } from "zustand";

import { useAgentChatStore } from "@/store/agentChat";
import { useEventStore } from "@/store/events";

/**
 * One way to bring an agent (and one card in its chat) on screen, from
 * anywhere in the app: the "needs you" inbox, a desktop notification, a toast.
 *
 * `openAgent` records the request and switches to the Agents section;
 * `SocietyView` takes the request, opens that agent's chat and then calls
 * `revealCard`, which waits for the card to render, scrolls it into view and
 * marks it for a moment. Nothing here knows how a chat is laid out: a card is
 * found by its `data-card-ref`, or else as the newest open card of its kind.
 */

/** The roster's fixed lead id: the assistant, whose chat is the front page. */
const LEAD_AGENT_ID = "jarvis";

export type CardKind = "question" | "approval" | "credential" | "proposal";

export interface AgentNavigationRequest {
  agentId: string;
  /** The chat the card lives in, when it is not the agent's main chat. */
  sessionId?: string;
  /** The card to reveal (a question, approval or credential request id). */
  cardRef?: string;
  kind?: CardKind;
  /** Distinguishes two requests for the same agent. */
  nonce: number;
}

export interface AgentOnScreen {
  agentId: string;
  sessionId?: string;
}

interface AgentNavigationState {
  request: AgentNavigationRequest | null;
  /** The agent whose chat the person is looking at, if any. */
  onScreen: AgentOnScreen | null;
}

export const useAgentNavigation = create<AgentNavigationState>(() => ({ request: null, onScreen: null }));

/**
 * Bring the card an agent's notice points at on screen.
 *
 * Named agents are retired (2026-11-11) and the Agents page with them: the one
 * agent left is the assistant, whose cards live in its conversation. So every
 * caller (a "needs you" notice, a desktop notification, a status row, an
 * approval card) lands in the conversation and marks the card there; it never
 * opens the old Agents page.
 */
export function openAgent(
  agentId: string,
  opts: { sessionId?: string; cardRef?: string; kind?: CardKind } = {},
): void {
  if (!agentId) return;
  useEventStore.getState().setActiveSection("chats");
  // A `society:` id names the conversation itself, which is already the one on stage.
  if (opts.sessionId && !opts.sessionId.startsWith("society:")) {
    const chat = useAgentChatStore.getState();
    if (chat.activeSessionId !== opts.sessionId) chat.openSession(opts.sessionId);
  }
  void revealCard({ cardRef: opts.cardRef, kind: opts.kind });
}

/** Take the pending request (once): the caller is about to honour it. */
export function takeAgentRequest(): AgentNavigationRequest | null {
  const { request } = useAgentNavigation.getState();
  if (request) useAgentNavigation.setState({ request: null });
  return request;
}

/** Record which agent is on screen (`null` when none is). */
export function setAgentOnScreen(next: AgentOnScreen | null): void {
  const current = useAgentNavigation.getState().onScreen;
  if (current?.agentId === next?.agentId && current?.sessionId === next?.sessionId) return;
  useAgentNavigation.setState({ onScreen: next });
}

/** Whether the person is looking at `agentId` right now. */
export function isAgentOnScreen(agentId: string): boolean {
  const section = useEventStore.getState().activeSection;
  // The assistant's conversation is the front page.
  if (agentId === LEAD_AGENT_ID) return section === "chats";
  const { onScreen } = useAgentNavigation.getState();
  return section === "agents" && onScreen?.agentId === agentId;
}

/** The newest open card of each kind, as the chat cards mark themselves. */
const OPEN_CARD: Record<CardKind, string> = {
  question: '[data-testid="question-card"][data-state="open"]',
  approval: '[data-testid="thread-approval"]',
  // An agent asks for a secret, a login or a service to connect: three cards, one kind.
  credential: ':is([data-testid="credential-card"], [data-testid="login-card"], [data-testid="connect-card"])[data-state="open"]',
  proposal: '[data-card-kind="proposal"]',
};

/** How long a revealed card stays marked. */
export const HIGHLIGHT_MS = 1800;

function cssEscape(value: string): string {
  return typeof CSS !== "undefined" && typeof CSS.escape === "function"
    ? CSS.escape(value)
    : value.replace(/["\\]/g, "\\$&");
}

/** The card for `ref` (or the newest open card of `kind`) inside `root`. */
export function findCard(root: ParentNode, ref?: string, kind?: CardKind): HTMLElement | null {
  if (ref) {
    const exact = root.querySelector<HTMLElement>(`[data-card-ref="${cssEscape(ref)}"]`);
    if (exact) return exact;
  }
  if (!kind) return null;
  const all = root.querySelectorAll<HTMLElement>(OPEN_CARD[kind]);
  return all.length > 0 ? all[all.length - 1] : null;
}

function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** Scroll `el` into view and mark it for {@link HIGHLIGHT_MS}. */
export function highlightCard(el: HTMLElement): void {
  const reduced = prefersReducedMotion();
  el.scrollIntoView?.({ block: "center", behavior: reduced ? "auto" : "smooth" });
  // A card that takes keys (the question card) gets them right away.
  if (el.hasAttribute("tabindex")) el.focus({ preventScroll: true });
  el.dataset.attentionHighlight = "true";
  if (!reduced && typeof el.animate === "function") {
    const ring = "hsl(var(--warning) / 0.55)";
    const none = "hsl(var(--warning) / 0)";
    el.animate(
      [
        { boxShadow: `0 0 0 0 ${none}` },
        { boxShadow: `0 0 0 3px ${ring}`, offset: 0.25 },
        { boxShadow: `0 0 0 3px ${ring}`, offset: 0.7 },
        { boxShadow: `0 0 0 0 ${none}` },
      ],
      { duration: HIGHLIGHT_MS, easing: "cubic-bezier(0.2, 0, 0, 1)" },
    );
  }
  window.setTimeout(() => {
    delete el.dataset.attentionHighlight;
  }, HIGHLIGHT_MS);
}

/**
 * Wait (up to `timeoutMs`) for the card to render, then reveal it.
 * Resolves `true` when a card was found.
 */
export function revealCard(
  target: { cardRef?: string; kind?: CardKind },
  { root = document, timeoutMs = 4000, intervalMs = 120 }: { root?: ParentNode; timeoutMs?: number; intervalMs?: number } = {},
): Promise<boolean> {
  if (!target.cardRef && !target.kind) return Promise.resolve(false);
  const started = Date.now();
  return new Promise((resolve) => {
    const look = () => {
      const el = findCard(root, target.cardRef, target.kind);
      if (el) {
        highlightCard(el);
        resolve(true);
        return;
      }
      if (Date.now() - started >= timeoutMs) {
        resolve(false);
        return;
      }
      window.setTimeout(look, intervalMs);
    };
    look();
  });
}
