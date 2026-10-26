/**
 * The one card a plain key press answers.
 *
 * Several cards can be open in a chat at once. Only one of them is the
 * keyboard target: the newest open card of the highest priority (a pending
 * approval outranks a question). Esc then answers that card's dismiss action
 * (an approval's "Deny") — and only when the press is not meant for anything
 * else: no modifier, no key repeat, no text field, contenteditable or open
 * dialog holding focus, and the card actually on screen.
 *
 * A card claims the target while it is open and releases it when it settles
 * or unmounts. One capture-phase listener serves every card.
 */

export interface KeyboardTarget {
  /** Higher wins; equal priority goes to the newest claim. */
  priority: number;
  /** The card's element, to check it is on screen. */
  element: () => HTMLElement | null;
  onEscape: () => void;
}

/** Priorities for the cards that claim the target. */
export const TARGET_PRIORITY = { approval: 2, question: 1 } as const;

interface Claim extends KeyboardTarget {
  order: number;
}

const claims = new Map<symbol, Claim>();
let order = 0;
let listening = false;

function current(): Claim | null {
  let best: Claim | null = null;
  for (const claim of claims.values()) {
    if (!best || claim.priority > best.priority || (claim.priority === best.priority && claim.order > best.order)) best = claim;
  }
  return best;
}

function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  const tag = target.tagName;
  if (tag === "TEXTAREA" || tag === "SELECT") return true;
  if (tag === "INPUT") {
    const type = (target as HTMLInputElement).type;
    return !["button", "checkbox", "radio", "submit", "reset"].includes(type);
  }
  return Boolean(target.closest("[contenteditable='true'], .xterm"));
}

function dialogOpen(): boolean {
  return Boolean(document.querySelector("[role='dialog'][data-state='open'], [aria-modal='true'], [role='alertdialog']"));
}

function onScreen(element: HTMLElement | null): boolean {
  if (!element || !element.isConnected || element.closest("[hidden]")) return false;
  // Without a layout engine (tests) there is nothing more to measure.
  if (typeof element.checkVisibility !== "function") return true;
  if (!element.checkVisibility()) return false;
  const rect = element.getBoundingClientRect();
  return rect.bottom > 0 && rect.top < window.innerHeight;
}

function onKeyDown(event: KeyboardEvent): void {
  if (event.key !== "Escape" || event.repeat || event.defaultPrevented) return;
  if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
  if (document.visibilityState === "hidden" || isTyping(event.target) || dialogOpen()) return;
  const target = current();
  if (!target || !onScreen(target.element())) return;
  event.preventDefault();
  event.stopPropagation();
  target.onEscape();
}

/** Claim the keyboard target; the returned function releases it. */
export function claimKeyboardTarget(target: KeyboardTarget): () => void {
  const key = Symbol("keyboard-target");
  claims.set(key, { ...target, order: ++order });
  if (!listening && typeof window !== "undefined") {
    window.addEventListener("keydown", onKeyDown, true);
    listening = true;
  }
  return () => {
    claims.delete(key);
    if (claims.size === 0 && listening) {
      window.removeEventListener("keydown", onKeyDown, true);
      listening = false;
    }
  };
}

/** Whether `element` belongs to the card that holds the target right now. */
export function holdsKeyboardTarget(element: HTMLElement | null): boolean {
  const target = current();
  return Boolean(target && element && target.element() === element);
}
