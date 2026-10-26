/**
 * The one card a plain key press answers.
 *
 * Several cards can be open in a chat at once. Only one of them is the
 * keyboard target: the newest open card of the highest priority (a pending
 * approval outranks a question). Esc then answers that card's dismiss action
 * (an approval's "Deny") — and only when the press is not meant for anything
 * else: no modifier, no key repeat, no text field or contenteditable holding
 * focus, no open dialog, menu, listbox or popover, and the card actually on
 * screen.
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

/**
 * A dialog, menu, listbox or popover is open: its Esc closes it. This
 * listener runs in the window's capture phase, before any of their own
 * handlers, so it must stand back or that Esc would deny the card instead.
 */
const OVERLAYS = [
  "[role='dialog'][data-state='open']",
  "[aria-modal='true']",
  "[role='alertdialog']",
  "[role='menu']",
  "[role='listbox']",
  "[data-radix-popper-content-wrapper]",
  "[popover]:popover-open",
].join(", ");

function overlays(): NodeListOf<Element> {
  try {
    return document.querySelectorAll(OVERLAYS);
  } catch {
    // An engine without `:popover-open` cannot parse the list; check without it.
    return document.querySelectorAll(OVERLAYS.replace(", [popover]:popover-open", ""));
  }
}

function dialogOpen(): boolean {
  // A menu kept mounted but `hidden` while closed is not open.
  return Array.from(overlays()).some((el) => !el.closest("[hidden]"));
}

/** Focus sits on a control whose own popup is open (a combobox, a menu button). */
function popupOpen(target: EventTarget | null): boolean {
  return target instanceof HTMLElement && Boolean(target.closest("[aria-expanded='true'][aria-haspopup]"));
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
  if (document.visibilityState === "hidden" || isTyping(event.target) || popupOpen(event.target) || dialogOpen()) return;
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
