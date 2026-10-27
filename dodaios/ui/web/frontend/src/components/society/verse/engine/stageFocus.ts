/**
 * Who gets the keys: the stage reads 1/2/3, V, WASD and E only while the
 * keyboard focus is inside it (or on nothing in particular). In the IDE the
 * terminal beside the side panel usually holds the focus, so a press on the
 * stage takes it, and only then: the stage never pulls focus on its own
 * and never from a field someone is typing in.
 */
import { useCallback, useEffect, useState, type PointerEvent as ReactPointerEvent, type RefObject } from "react";

/** The element takes text (a field, a terminal's input): its keys are not the stage's. */
export function typesText(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  return !!el && (el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName));
}

/** The stage's keys reach it with `focused` holding the focus: inside the stage, or nowhere in particular. Pure. */
export function keysReachStage(host: Element | null, focused: Element | null): boolean {
  if (!focused || focused === document.body || focused === document.documentElement) return true;
  return !!host && host.contains(focused);
}

/**
 * Focus on the stage for a pointer press on it (`onPointerDownCapture` on
 * the host): the press itself, never a timer or a global listener.
 */
export function takeFocusOnPress(host: HTMLElement | null, target: EventTarget | null): boolean {
  if (!host || typesText(target)) return false;
  if (host.contains(document.activeElement)) return false;
  host.focus({ preventScroll: true });
  return true;
}

/** Whether the keys reach the stage right now (kept current while `active`), and the press handler for its host. */
export function useStageFocus(hostRef: RefObject<HTMLElement | null>, active: boolean) {
  const [keysReach, setKeysReach] = useState(true);
  useEffect(() => {
    if (!active) return;
    const update = () => setKeysReach(keysReachStage(hostRef.current, document.activeElement));
    // On focusout the next element is not focused yet: read it once the move is done.
    let pending: ReturnType<typeof setTimeout> | null = null;
    const later = () => {
      if (pending) clearTimeout(pending);
      pending = setTimeout(() => { pending = null; update(); }, 0);
    };
    update();
    document.addEventListener("focusin", update);
    document.addEventListener("focusout", later);
    return () => {
      document.removeEventListener("focusin", update);
      document.removeEventListener("focusout", later);
      if (pending) clearTimeout(pending);
    };
  }, [hostRef, active]);
  const onPointerDownCapture = useCallback((e: ReactPointerEvent) => {
    if (takeFocusOnPress(hostRef.current, e.target)) setKeysReach(true);
  }, [hostRef]);
  return { keysReach, onPointerDownCapture };
}
