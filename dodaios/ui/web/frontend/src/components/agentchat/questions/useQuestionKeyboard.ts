import { useEffect, useRef, useSyncExternalStore, type RefObject } from "react";

/**
 * One keyboard target for every open question card on screen.
 *
 * Plain letter keys answer a card without clicking it first, but only ONE
 * card may hear them: the newest open one, i.e. the last registered card in
 * document order that is actually visible. Keys never reach it while the
 * person types in a field, holds a modifier, or works inside a dialog or a
 * menu that is not part of the card.
 */

type KeyHandler = (event: KeyboardEvent) => boolean;

interface Entry {
  el: HTMLElement;
  onKey: KeyHandler;
}

const entries = new Set<Entry>();
const listeners = new Set<() => void>();
let installed = false;

// jsdom lays nothing out, so every connected card counts as shown there.
const NO_LAYOUT = typeof navigator !== "undefined" && /jsdom/i.test(navigator.userAgent);

function visible(el: HTMLElement): boolean {
  if (!el.isConnected || el.closest("[hidden],[inert]")) return false;
  return NO_LAYOUT || el.getClientRects().length > 0;
}

/** The card that hears plain letter keys right now, if any. */
export function currentTarget(): HTMLElement | null {
  let best: Entry | null = null;
  for (const entry of entries) {
    if (!visible(entry.el)) continue;
    // A later card in the document is a newer question.
    if (!best || best.el.compareDocumentPosition(entry.el) & Node.DOCUMENT_POSITION_FOLLOWING) best = entry;
  }
  return best?.el ?? null;
}

function editable(node: EventTarget | null): boolean {
  if (!(node instanceof HTMLElement)) return false;
  if (node.isContentEditable) return true;
  const tag = node.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
}

function onWindowKey(event: KeyboardEvent): void {
  if (event.defaultPrevented || event.repeat || event.isComposing || event.ctrlKey || event.metaKey || event.altKey) return;
  if (editable(event.target)) return;
  const el = currentTarget();
  if (!el) return;
  const active = document.activeElement;
  // A dialog or menu elsewhere owns the keyboard while it has focus.
  if (active instanceof HTMLElement && !el.contains(active) && active.closest('[role="dialog"],[role="menu"],[role="listbox"]')) return;
  for (const entry of entries) {
    if (entry.el === el) {
      if (entry.onKey(event)) event.preventDefault();
      return;
    }
  }
}

function notify(): void {
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/**
 * Register `ref`'s card as a keyboard target while `active`; returns whether
 * it is THE target (so it can show its key hints). `onKey` returns true when
 * it used the key.
 */
export function useQuestionKeyboard(ref: RefObject<HTMLElement | null>, onKey: KeyHandler, active: boolean): boolean {
  const handler = useRef(onKey);
  handler.current = onKey;
  useEffect(() => {
    const el = ref.current;
    if (!active || !el) return;
    if (!installed && typeof window !== "undefined") {
      window.addEventListener("keydown", onWindowKey);
      installed = true;
    }
    const entry: Entry = { el, onKey: (event) => handler.current(event) };
    entries.add(entry);
    notify();
    return () => {
      entries.delete(entry);
      notify();
    };
  }, [ref, active]);
  return useSyncExternalStore(
    subscribe,
    () => active && ref.current !== null && currentTarget() === ref.current,
    () => false,
  );
}

/** Test seam: forget every registered card. */
export function resetQuestionKeyboard(): void {
  entries.clear();
  notify();
}
