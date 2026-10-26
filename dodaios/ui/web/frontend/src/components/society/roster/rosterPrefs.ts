/**
 * The person's own arrangement of the roster, kept in this browser profile:
 * which agents are hidden, the hand-made order, the pinned agents and the
 * list filter. Every read survives bad or missing storage (private mode, a
 * hand-edited value) by falling back to the default.
 */
import { useCallback, useState } from "react";

export const HIDDEN_AGENTS_KEY = "society.roster.hidden-agent-ids";
export const ORDER_KEY = "society.roster.order";
export const PINNED_KEY = "society.roster.pinned.v1";
export const FILTER_KEY = "society.roster.filter.v1";

/** Two rows of four pinned tiles; a ninth pin would only push one off screen. */
export const MAX_PINNED = 8;

export type RosterFilter = "all" | "needs-you" | "unread";
const FILTERS: readonly RosterFilter[] = ["all", "needs-you", "unread"];

export function readIdList(key: string): string[] {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(key) ?? "[]");
    return Array.isArray(value) ? value.filter((id): id is string => typeof id === "string") : [];
  } catch {
    return [];
  }
}

export function writeIdList(key: string, ids: string[]): void {
  try {
    localStorage.setItem(key, JSON.stringify(ids));
  } catch {
    // Private mode: the arrangement holds for this window.
  }
}

export function readFilter(): RosterFilter {
  try {
    const value = localStorage.getItem(FILTER_KEY);
    return FILTERS.includes(value as RosterFilter) ? (value as RosterFilter) : "all";
  } catch {
    return "all";
  }
}

/** A persisted id list with a setter that writes through. */
export function usePersistedIds(key: string): [string[], (update: (current: string[]) => string[]) => void] {
  const [ids, setIds] = useState(() => readIdList(key));
  const update = useCallback((fn: (current: string[]) => string[]) => {
    setIds((current) => {
      const next = fn(current);
      if (next === current) return current;
      writeIdList(key, next);
      return next;
    });
  }, [key]);
  return [ids, update];
}

/** Pin or unpin; a new pin goes last, and the list never grows past `MAX_PINNED`. */
export function togglePin(current: string[], agentId: string): string[] {
  if (current.includes(agentId)) return current.filter((id) => id !== agentId);
  if (current.length >= MAX_PINNED) return current;
  return [...current, agentId];
}

export function useRosterFilter(): [RosterFilter, (filter: RosterFilter) => void] {
  const [filter, setFilter] = useState(readFilter);
  const update = useCallback((next: RosterFilter) => {
    setFilter(next);
    try {
      localStorage.setItem(FILTER_KEY, next);
    } catch {
      // Private mode: the filter holds for this window.
    }
  }, []);
  return [filter, update];
}
