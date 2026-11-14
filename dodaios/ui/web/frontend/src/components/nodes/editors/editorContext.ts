/**
 * How the stage tells an open editor that the node changed on the server.
 *
 * The stage already watches every open typed node (`NodeUpkeepBar` asks every
 * few seconds and reports the node's `updated_at`). It hands those reports to
 * the editor through this context, so every editor built on
 * `useNodeSpecEditor` follows the assistant's revisions without wiring
 * anything itself. Outside a stage (a test, a story) there is no source, and
 * the editor simply hears nothing.
 */
import { createContext, useContext } from "react";

export type RevisionListener = (updatedAt: number) => void;

export interface RevisionSource {
  /** Hear each `updated_at` the watcher reports. Returns the unsubscribe. */
  subscribe: (listener: RevisionListener) => () => void;
}

export const RevisionContext = createContext<RevisionSource | null>(null);

export function useRevisionSource(): RevisionSource | null {
  return useContext(RevisionContext);
}

/** A source the stage feeds with `emit` (one per open editor). */
export function createRevisionSource(): RevisionSource & { emit: RevisionListener } {
  const listeners = new Set<RevisionListener>();
  let last: number | null = null;
  return {
    subscribe(listener) {
      listeners.add(listener);
      // A report that came before the editor finished loading is not lost.
      if (last !== null) listener(last);
      return () => listeners.delete(listener);
    },
    emit(updatedAt) {
      last = updatedAt;
      for (const listener of listeners) listener(updatedAt);
    },
  };
}
