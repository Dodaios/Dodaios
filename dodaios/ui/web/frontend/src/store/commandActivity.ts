import { create } from "zustand";
import {
  pruneCommandActivity,
  reduceCommandActivity,
  type CommandActivityEntry,
} from "@/lib/commandActivity";

/**
 * Live shell-command activity, fed by the WS wildcard event stream
 * (useWebSocket.ts) and read by the deck's Terminals card
 * (DeckActivityCards.tsx). No card pops up over the app for a command.
 *
 * Deliberately its own store: the entries change at tool-call rhythm, and
 * keeping them out of the big event store means a running command re-renders
 * one deck card, not the whole shell.
 *
 * The store expires its own entries: no component has to be mounted for a
 * finished command to leave the list.
 */
interface CommandActivityState {
  entries: CommandActivityEntry[];
  ingest: (
    eventName: string,
    traceId: string,
    payload: unknown,
    tsMs: number,
  ) => void;
  /** Expires settled and stuck entries; the store's own 1 s tick calls it. */
  prune: (nowMs: number) => void;
}

const PRUNE_INTERVAL_MS = 1_000;

export const useCommandActivityStore = create<CommandActivityState>()(
  (set, get) => {
    let timer: ReturnType<typeof setInterval> | null = null;

    // The tick runs only while there is an entry to expire.
    const syncTimer = () => {
      const pending = get().entries.length > 0;
      if (pending && timer === null) {
        timer = setInterval(() => get().prune(Date.now()), PRUNE_INTERVAL_MS);
      } else if (!pending && timer !== null) {
        clearInterval(timer);
        timer = null;
      }
    };

    return {
      entries: [],

      ingest: (eventName, traceId, payload, tsMs) => {
        const next = reduceCommandActivity(
          get().entries,
          eventName,
          traceId,
          payload,
          tsMs,
        );
        if (!next) return;
        set({ entries: next });
        syncTimer();
      },

      prune: (nowMs) => {
        const next = pruneCommandActivity(get().entries, nowMs);
        if (next) set({ entries: next });
        syncTimer();
      },
    };
  },
);

/** The event names the WS hook needs to forward here (cheap pre-filter). */
export const COMMAND_ACTIVITY_EVENTS: ReadonlySet<string> = new Set([
  "ActionProposed",
  "ActionExecuted",
  "ActionDenied",
]);
