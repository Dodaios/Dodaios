/**
 * What the agent pane remembers between visits: the open tab (one for every
 * agent, so "I manage tools now" carries over when the person switches agents)
 * and the next-step suggestions the person dismissed (per agent).
 *
 * Browser storage is a convenience here, never a source of truth: every read
 * and write is guarded, and the pane works the same with storage blocked.
 */
import { useCallback, useState } from "react";

export const PANE_TABS = ["overview", "tools", "memory", "tasks", "browser", "history"] as const;
export type PaneTab = (typeof PANE_TABS)[number];

const TAB_KEY = "society.agentPane.tab";
const DISMISSED_KEY = "society.agentPane.dismissed";

function read(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* storage blocked: the choice lasts for this view only */
  }
}

export function isPaneTab(value: unknown): value is PaneTab {
  return typeof value === "string" && (PANE_TABS as readonly string[]).includes(value);
}

export function readStoredTab(): PaneTab {
  const stored = read(TAB_KEY);
  return isPaneTab(stored) ? stored : "overview";
}

/** The open tab, persisted. `available` drops tabs this agent does not have (History is lead-only). */
export function usePaneTab(available: readonly PaneTab[]): [PaneTab, (tab: PaneTab) => void] {
  const [tab, setTab] = useState<PaneTab>(readStoredTab);
  const choose = useCallback((next: PaneTab) => {
    setTab(next);
    write(TAB_KEY, next);
  }, []);
  return [available.includes(tab) ? tab : "overview", choose];
}

function readDismissed(): Record<string, string[]> {
  const raw = read(DISMISSED_KEY);
  if (!raw) return {};
  try {
    const parsed = JSON.parse(raw) as unknown;
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? (parsed as Record<string, string[]>) : {};
  } catch {
    return {};
  }
}

/** The suggestion ids this person dismissed for one agent, plus a way to dismiss another. */
export function useDismissedSuggestions(agentId: string): [Set<string>, (id: string) => void] {
  const [all, setAll] = useState(readDismissed);
  const dismiss = useCallback((id: string) => {
    setAll((prev) => {
      // A counted id ("review:3") replaces its older counts, so the list stays small.
      const family = id.includes(":") ? `${id.split(":")[0]}:` : null;
      const kept = (prev[agentId] ?? []).filter((x) => !family || !x.startsWith(family));
      const next = { ...prev, [agentId]: [...new Set([...kept, id])] };
      write(DISMISSED_KEY, JSON.stringify(next));
      return next;
    });
  }, [agentId]);
  return [new Set(all[agentId] ?? []), dismiss];
}

/** One level of in-pane drill-down: a sub-page with a title and a way back. */
export interface PanePage {
  id: string;
  title: string;
}

/** A small stack of sub-pages; the pane header shows Back while it is not empty. */
export function usePaneStack(): {
  page: PanePage | null;
  push: (page: PanePage) => void;
  back: () => void;
  reset: () => void;
} {
  const [stack, setStack] = useState<PanePage[]>([]);
  return {
    page: stack.length ? stack[stack.length - 1] : null,
    push: useCallback((page: PanePage) => setStack((prev) => [...prev, page]), []),
    back: useCallback(() => setStack((prev) => prev.slice(0, -1)), []),
    reset: useCallback(() => setStack([]), []),
  };
}
