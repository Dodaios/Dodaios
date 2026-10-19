import { useCallback, useSyncExternalStore } from "react";
import { requestConnect, spreadDelay } from "@/lib/connectBudget";

/** The verdicts a pane header shows; NONE and HOLD arrive as null. */
export type DoneGateVerdict = "DONE" | "WAIT" | "FIX" | "STUCK";

/** What `scripts/agent_done_gate.py` last said about a pane's session. */
export interface PaneDoneGate {
  verdict: DoneGateVerdict;
  reason: string;
  next: string;
  pr: number | null;
  branch: string;
  /** ISO time of the check, UTC. */
  at: string;
  /** `folder`: matched by the pane's folder or branch, not its own session id. */
  matched: "session" | "folder";
}

type Panes = Record<string, PaneDoneGate | null>;
type Entry = { panes: Panes; listeners: Set<() => void>; stop: () => void };

/**
 * The gate writes its verdict when an agent tries to stop, so a few seconds'
 * delay is invisible; reading it is a handful of local files, never GitHub.
 */
export const POLL_MS = 15_000;
const VERDICTS: ReadonlySet<string> = new Set(["DONE", "WAIT", "FIX", "STUCK"]);
const EMPTY: Panes = {};
const entries = new Map<string, Entry>();
// A workspace's last answer outlives its listeners, so a pane coming back on
// stage shows its verdict at once and the refresh follows.
const remembered = new Map<string, Panes>();

function clean(data: unknown): Panes {
  if (!data || typeof data !== "object") return {};
  const panes: Panes = {};
  for (const [name, value] of Object.entries(data as Record<string, unknown>)) {
    const item = value as Partial<PaneDoneGate> | null;
    panes[name] = item && typeof item === "object" && VERDICTS.has(String(item.verdict))
      ? {
        verdict: item.verdict as DoneGateVerdict,
        reason: typeof item.reason === "string" ? item.reason : "",
        next: typeof item.next === "string" ? item.next : "",
        pr: typeof item.pr === "number" ? item.pr : null,
        branch: typeof item.branch === "string" ? item.branch : "",
        at: typeof item.at === "string" ? item.at : "",
        matched: item.matched === "folder" ? "folder" : "session",
      }
      : null;
  }
  return panes;
}

function start(workspaceId: string): Entry {
  const entry: Entry = { panes: remembered.get(workspaceId) ?? EMPTY, listeners: new Set(), stop: () => {} };
  let disposed = false;
  let controller: AbortController | undefined;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let cancelConnect: (() => void) | undefined;

  const schedule = (delay: number) => {
    clearTimeout(timer);
    cancelConnect?.();
    if (disposed || document.hidden) return;
    cancelConnect = requestConnect(() => { void poll(); }, delay);
  };
  const poll = async () => {
    if (disposed || controller || document.hidden) return;
    controller = new AbortController();
    const timeout = setTimeout(() => controller?.abort(), 15_000);
    try {
      const query = new URLSearchParams({ workspace_id: workspaceId });
      const response = await fetch(`/api/agentic-ide/git/done-gate?${query}`, { signal: controller.signal });
      if (response.ok) {
        const data = await response.json() as { panes?: unknown };
        const panes = clean(data.panes);
        // An unchanged answer keeps its identity, so no header redraws for it.
        if (!disposed && JSON.stringify(panes) !== JSON.stringify(entry.panes)) {
          entry.panes = panes;
          remembered.set(workspaceId, entry.panes);
          entry.listeners.forEach((listener) => listener());
        }
      }
      // A failed read keeps the last answer: the verdict is the gate's
      // last word, which a missed poll does not change.
    } catch {
      // Same: offline or aborted, the last answer stands.
    } finally {
      clearTimeout(timeout);
      controller = undefined;
      if (!disposed) timer = setTimeout(() => schedule(0), spreadDelay(POLL_MS));
    }
  };
  const resume = () => {
    if (document.hidden) {
      clearTimeout(timer);
      cancelConnect?.();
      return;
    }
    if (!controller) schedule(spreadDelay(500));
  };
  document.addEventListener("visibilitychange", resume);
  entry.stop = () => {
    disposed = true;
    clearTimeout(timer);
    cancelConnect?.();
    controller?.abort();
    document.removeEventListener("visibilitychange", resume);
  };
  schedule(spreadDelay(150));
  return entry;
}

/** The done gate's last shown verdict for one pane, or null. One poll per workspace. */
export function usePaneDoneGate(workspaceId?: string, pane?: string): PaneDoneGate | null {
  const subscribe = useCallback((listener: () => void) => {
    if (!workspaceId) return () => {};
    let entry = entries.get(workspaceId);
    if (!entry) {
      entry = start(workspaceId);
      entries.set(workspaceId, entry);
    }
    entry.listeners.add(listener);
    return () => {
      entry.listeners.delete(listener);
      if (!entry.listeners.size) {
        entry.stop();
        entries.delete(workspaceId);
      }
    };
  }, [workspaceId]);
  const snapshot = useCallback(
    () => workspaceId ? entries.get(workspaceId)?.panes ?? remembered.get(workspaceId) ?? EMPTY : EMPTY,
    [workspaceId],
  );
  const panes = useSyncExternalStore(subscribe, snapshot, () => EMPTY);
  return pane ? panes[pane] ?? null : null;
}

/** Forget every remembered answer; tests only. */
export function resetPaneDoneGateForTests() {
  remembered.clear();
}
