/**
 * Which turn the work inspector shows while turns keep arriving.
 *
 * Opened on the newest turn, the inspector follows the conversation: when
 * the next turn starts, it moves to that live turn, so the person watches
 * the work as it happens. Opened on an older turn, it is pinned there: the
 * person picked that turn on purpose and keeps reading it while new turns
 * run. Pure, so the rule is testable without a conversation.
 */

import { useCallback, useEffect, useRef, useState } from "react";

export interface Inspection {
  /** The turn on screen. */
  turnId: string;
  /** Picked as an older turn: stays put while new turns run. */
  pinned: boolean;
}

interface TurnLike {
  type: string;
  id: string;
}

/** The newest turn of a conversation, or null when it has none. */
export function latestTurnId(items: readonly TurnLike[]): string | null {
  for (let i = items.length - 1; i >= 0; i--) {
    if (items[i].type === "turn") return items[i].id;
  }
  return null;
}

/** Opening on a turn: pinned unless it is the newest one. */
export function openInspection(turnId: string, latest: string | null): Inspection {
  return { turnId, pinned: latest !== null && turnId !== latest };
}

/** The inspection after the conversation changed: a following one moves to the newest turn. */
export function followInspection(current: Inspection | null, latest: string | null): Inspection | null {
  if (!current || current.pinned || latest === null || current.turnId === latest) return current;
  return { turnId: latest, pinned: false };
}

/**
 * The inspector's turn for a conversation: `inspecting` is the turn on
 * screen (null when closed), `open` picks one, `close` closes it.
 */
export function useInspectedTurn(items: readonly TurnLike[]) {
  const latest = latestTurnId(items);
  const [inspection, setInspection] = useState<Inspection | null>(null);
  useEffect(() => {
    setInspection((current) => followInspection(current, latest));
  }, [latest]);
  // Stable across new turns, so the conversation's rows do not redraw for it.
  const latestRef = useRef(latest);
  useEffect(() => {
    latestRef.current = latest;
  }, [latest]);
  const open = useCallback((turnId: string) => setInspection(openInspection(turnId, latestRef.current)), []);
  const close = useCallback(() => setInspection(null), []);
  // Render the followed turn at once, without a frame on the old one.
  const shown = followInspection(inspection, latest);
  return { inspecting: shown?.turnId ?? null, pinned: shown?.pinned ?? false, open, close };
}
