import { translate } from "@/i18n";
import { useCallback, useSyncExternalStore } from "react";
import { requestConnect, spreadDelay } from "@/lib/connectBudget";
import type { CiStatus, PullRequestState } from "./sidePanel/git/gitOverviewApi";

export interface SessionGitHubStatus {
  repo: string;
  branch: string;
  url: string;
  published: boolean;
  owned: boolean;
  available: boolean;
  reason: string;
  fetched_at: number;
  state: "branch" | PullRequestState;
  number: number | null;
  ci: Omit<CiStatus, "state"> & { state: SessionCiState; states?: SessionCiState[] };
  ci_stale: boolean;
  merge_status?: string;
  review?: string;
  locked?: boolean;
  /** The session's other branches, newest first. Absent from an older backend. */
  others?: SessionGitHubStatus[];
}

/** A status as a header shows it: the backend's answer, plus what this window knows. */
export interface PaneGitHubStatus extends SessionGitHubStatus {
  /**
   * Set here, never by the backend: this is the last known answer and a newer
   * one is being read. It keeps its state on screen meanwhile instead of
   * turning into "unavailable" for the seconds the read takes.
   */
  refreshing?: boolean;
  others?: PaneGitHubStatus[];
}

export type SessionCiState = CiStatus["state"] | "cancelled" | "neutral" | "skipped"
  | "action_required" | "timed_out" | "startup_failure" | "stale" | "unknown"
  | "waiting" | "requested" | "expected" | "error";

type Panes = Record<string, PaneGitHubStatus | null>;
/** Which session each pane ran when its status was read. */
type Sessions = Record<string, string>;
type Known = { panes: Panes; sessions: Sessions; answered: boolean };
type Entry = {
  panes: Panes;
  sessions: Sessions;
  /**
   * The panes whose status is still being read for the first time. Null until
   * the backend has answered once: nothing is known yet, so every pane is.
   */
  awaited: ReadonlySet<string> | null;
  listeners: Set<() => void>;
  stop: () => void;
};
const entries = new Map<string, Entry>();
const EMPTY: Panes = {};
const UNKNOWN: Known = { panes: EMPTY, sessions: {}, answered: false };
const NONE: ReadonlySet<string> = new Set();
// A workspace's last answer outlives its listeners, and a reload of the window:
// a pane coming back on stage shows its branch at once, and the refresh follows.
const remembered = new Map<string, Known>();
const STORE = "ide-pane-github:";
// While a newer answer is being read the backend is asked again this soon.
const FOLLOW_UP_MS = 700;
// A read that long is not coming; the steady rhythm takes over.
const MAX_FOLLOW_UPS = 30;

function mark(status: PaneGitHubStatus | null, refreshing: boolean): PaneGitHubStatus | null {
  return status && {
    ...status, refreshing,
    others: status.others?.map((other) => ({ ...other, refreshing })),
  };
}

function markAll(panes: Panes, refreshing: boolean): Panes {
  return Object.fromEntries(Object.entries(panes).map(([name, status]) => [name, mark(status, refreshing)]));
}

/** What was last known about a workspace, as an answer still being refreshed. */
function recall(workspaceId: string): Known {
  let known = remembered.get(workspaceId);
  if (!known) {
    known = UNKNOWN;
    try {
      const stored = JSON.parse(sessionStorage.getItem(STORE + workspaceId) ?? "null") as Partial<Known> | null;
      if (stored?.panes && typeof stored.panes === "object" && stored.sessions && typeof stored.sessions === "object") {
        known = { panes: markAll(stored.panes, true), sessions: stored.sessions, answered: true };
      }
    } catch {
      // Blocked or unreadable storage only costs the head start; the poll follows.
    }
    remembered.set(workspaceId, known);
  }
  return known;
}

function remember(workspaceId: string, known: Omit<Known, "answered">) {
  remembered.set(workspaceId, { panes: markAll(known.panes, true), sessions: known.sessions, answered: true });
  try {
    sessionStorage.setItem(STORE + workspaceId, JSON.stringify(known));
  } catch {
    // Storage is full or blocked: the answer still lives in memory.
  }
}

function start(workspaceId: string): Entry {
  const known = recall(workspaceId);
  const entry: Entry = {
    panes: known.panes, sessions: known.sessions, awaited: known.answered ? NONE : null,
    listeners: new Set(), stop: () => {},
  };
  let disposed = false;
  let followUps = 0;
  let controller: AbortController | undefined;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let cancelConnect: (() => void) | undefined;

  const notify = () => entry.listeners.forEach((listener) => listener());
  const unavailable = (reason: string) => {
    entry.panes = Object.fromEntries(Object.entries(entry.panes).map(([name, status]) => [
      name, status ? {
        ...status, available: false, reason,
        others: status.others?.map((other) => ({ ...other, available: false, reason })),
      } : null,
    ]));
    notify();
  };
  const schedule = (delay: number) => {
    clearTimeout(timer);
    cancelConnect?.();
    if (disposed || document.hidden) return;
    cancelConnect = requestConnect(() => { void poll(); }, delay);
  };
  const poll = async () => {
    if (disposed || controller || document.hidden) return;
    let waiting = false;
    controller = new AbortController();
    const timeout = setTimeout(() => controller?.abort(), 30_000);
    try {
      const query = new URLSearchParams({ workspace_id: workspaceId });
      const response = await fetch(`/api/agentic-ide/git/session-status?${query}`, { signal: controller.signal });
      if (!response.ok) throw new Error("GitHub status could not be refreshed.");
      const data = await response.json() as { panes: Panes; refreshing?: boolean; sessions?: Sessions };
      if (disposed) return;
      // The backend answers with what it last read and reads on in the
      // background; until that lands, this answer is the last known one.
      waiting = data.refreshing === true;
      // A read that never lands must not pass its old answer off as current.
      const pending = waiting && followUps < MAX_FOLLOW_UPS;
      // After logout/offline, keep a previously confirmed branch visible with
      // an unknown status. Never borrow identity across a checkout change.
      const next = Object.fromEntries(Object.entries(data.panes).map(([name, status]) => {
        const previous = entry.panes[name];
        if (status?.owned && !status.available && previous?.owned && previous.published
          && status.repo === previous.repo && status.branch === previous.branch) {
          return [name, mark({ ...status, published: true }, pending)];
        }
        return [name, mark(status, pending)];
      }));
      // A pane the backend has not read yet keeps what was last known of it,
      // as long as it still runs the session that answer was read for.
      const sessions = data.sessions ?? {};
      const kept = pending ? Object.entries(entry.panes).filter(([name]) => !(name in next)
        && sessions[name] !== undefined && sessions[name] === entry.sessions[name]) : [];
      entry.panes = { ...markAll(Object.fromEntries(kept), true), ...next };
      entry.sessions = sessions;
      // What the backend is reading and has no answer for yet shows as loading.
      entry.awaited = pending ? new Set(Object.keys(sessions).filter((name) => !(name in entry.panes))) : NONE;
      if (!pending) remember(workspaceId, { panes: entry.panes, sessions });
      notify();
    } catch {
      // Nothing is on its way any more: a header must not keep spinning.
      entry.awaited = NONE;
      if (!disposed) unavailable(translate("ide_panes.github.refresh_failed"));
    } finally {
      clearTimeout(timeout);
      controller = undefined;
      followUps = waiting ? followUps + 1 : 0;
      const soon = waiting && followUps <= MAX_FOLLOW_UPS;
      if (!disposed) timer = setTimeout(() => schedule(0), spreadDelay(soon ? FOLLOW_UP_MS : 20_000));
    }
  };
  const resume = () => {
    if (document.hidden) {
      clearTimeout(timer);
      cancelConnect?.();
      return;
    }
    // A suspended window must not present its last green badge as live data.
    if (Object.values(entry.panes).some((value) => value && Date.now() / 1000 - value.fetched_at > 60)) {
      unavailable(translate("ide_panes.github.refreshing"));
    }
    if (!controller) schedule(spreadDelay(500));
  };
  document.addEventListener("visibilitychange", resume);
  window.addEventListener("online", resume);
  entry.stop = () => {
    disposed = true;
    clearTimeout(timer);
    cancelConnect?.();
    controller?.abort();
    document.removeEventListener("visibilitychange", resume);
    window.removeEventListener("online", resume);
  };
  schedule(spreadDelay(250));
  return entry;
}

/**
 * What a header can say about its pane before it has a status to show:
 * "loading" while the first answer is being read, "none" once it is known
 * that the session works in no branch, "idle" otherwise.
 */
export type PaneGitHubState = "loading" | "none" | "idle";

function stateOf(workspaceId: string, pane: string): PaneGitHubState {
  const entry = entries.get(workspaceId);
  const known = recall(workspaceId);
  const panes = entry ? entry.panes : known.panes;
  if (pane in panes) return panes[pane] === null ? "none" : "idle";
  const awaited = entry ? entry.awaited : known.answered ? NONE : null;
  return awaited === null || awaited.has(pane) ? "loading" : "idle";
}

export function useSessionGitHub(workspaceId?: string, pane?: string): PaneGitHubStatus | null {
  return useSessionGitHubState(workspaceId, pane).status;
}

export function useSessionGitHubState(workspaceId?: string, pane?: string): {
  status: PaneGitHubStatus | null;
  state: PaneGitHubState;
} {
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
        remembered.set(workspaceId, {
          panes: markAll(entry.panes, true), sessions: entry.sessions, answered: entry.awaited !== null,
        });
        entry.stop();
        entries.delete(workspaceId);
      }
    };
  }, [workspaceId]);
  // Before the first subscription the last known answer already paints.
  const snapshot = useCallback(() => workspaceId ? entries.get(workspaceId)?.panes ?? recall(workspaceId).panes : EMPTY, [workspaceId]);
  const panes = useSyncExternalStore(subscribe, snapshot, () => EMPTY);
  const state = useSyncExternalStore(
    subscribe,
    () => workspaceId && pane ? stateOf(workspaceId, pane) : "idle",
    () => "idle" as const,
  );
  return { status: pane ? panes[pane] ?? null : null, state };
}
