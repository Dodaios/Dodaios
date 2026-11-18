/**
 * Leaving an open node while its editor still has unsaved work.
 *
 * A node opens straight in its editor and has no Done button: it is left by
 * closing it. The stage asks its guard before it closes; an open editor holds
 * the guard, saves first, and only then lets the node close. When the save
 * cannot go through (offline, refused, the node moved on), the editor stays
 * and says so, with "Leave anyway" next to it, instead of dropping the
 * person's work without a word.
 */
import { createContext, useContext } from "react";

/** Close the node (`go`) once the editor's work is safe. */
export type Leave = (go: () => void) => void;

export interface LeaveGuard {
  /** The open editor takes the guard; the returned function gives it back. */
  hold: (leave: Leave) => () => void;
  /** Close the node through the editor that holds the guard, or at once. */
  leave: (go: () => void) => void;
}

export function createLeaveGuard(): LeaveGuard {
  let held: Leave | null = null;
  return {
    hold(leave) {
      held = leave;
      return () => {
        if (held === leave) held = null;
      };
    },
    leave(go) {
      if (held) held(go);
      else go();
    },
  };
}

export const LeaveGuardContext = createContext<LeaveGuard | null>(null);

export function useLeaveGuard(): LeaveGuard | null {
  return useContext(LeaveGuardContext);
}
