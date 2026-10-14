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

export type SessionCiState = CiStatus["state"] | "cancelled" | "neutral" | "skipped"
  | "action_required" | "timed_out" | "startup_failure" | "stale" | "unknown"
  | "waiting" | "requested" | "expected" | "error";

/** What a pane header shows: the last answer, and whether it is still being confirmed. */
export interface PaneGitHub {
  status: SessionGitHubStatus | null;
  /**
   * The status is being read, or read again because the one on screen is old.
   * The header shows a spinner meanwhile instead of passing it off as current.
   */
  pending: boolean;
}

type Panes = Record<string, SessionGitHubStatus | null>;
interface Board {
  panes: Panes;
  /**
   * This window's clock when the backend last read the answer, or when a
   * failed refresh marked it unavailable; null before any answer. An answer
   * older than {@link FRESH_MS} spins until a newer one replaces it.
   */
  readAt: number | null;
  /** Panes without an answer that one is being read for; null before the backend answered. */
  waiting: ReadonlySet<string> | null;
}
type Entry = { board: Board; listeners: Set<() => void>; refresh: () => void; stop: () => void };

/**
 * An answer younger than this is shown as current while a newer one is read.
 * The backend keeps the tabs behind the front one younger than this.
 */
export const FRESH_MS = 120_000;
/**
 * While the backend reads a newer answer, the next request asks it to hold on
 * for that read this long, so the answer lands the moment the read does.
 */
const WAIT_S = 4;
/** After this many follow-ups a read that does not land is asked about less often. */
const MAX_FOLLOW_UPS = 30;
const POLL_MS = 20_000;

const UNKNOWN: Board = { panes: {}, readAt: null, waiting: null };
const NONE: ReadonlySet<string> = new Set();
const IDLE: PaneGitHub = { status: null, pending: false };
const entries = new Map<string, Entry>();
// A workspace's last answer outlives its listeners: a pane coming back on
// stage shows its branch at once, and the refresh follows.
const remembered = new Map<string, Board>();

const old = (readAt: number | null) => readAt === null || Date.now() - readAt > FRESH_MS;
/** GitHub's own answer about the branch is older than {@link FRESH_MS}. */
const outdated = (status: SessionGitHubStatus | null) =>
  status !== null && Date.now() - status.fetched_at * 1000 > FRESH_MS;

function start(workspaceId: string): Entry {
  // What this window saw last is shown at once; once it is old it spins until
  // the backend has confirmed or replaced it.
  const entry: Entry = {
    board: remembered.get(workspaceId) ?? UNKNOWN, listeners: new Set(), refresh: () => {}, stop: () => {},
  };
  let disposed = false;
  let followUps = 0;
  let controller: AbortController | undefined;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let cancelConnect: (() => void) | undefined;

  const publish = (board: Board) => {
    entry.board = board;
    remembered.set(workspaceId, board);
    entry.listeners.forEach((listener) => listener());
  };
  const unavailable = (reason: string) => {
    publish({
      // Nothing is on its way any more: no header may keep spinning.
      readAt: Date.now(),
      waiting: NONE,
      panes: Object.fromEntries(Object.entries(entry.board.panes).map(([name, status]) => [
        name, status ? {
          ...status, available: false, reason,
          others: status.others?.map((other) => ({ ...other, available: false, reason })),
        } : null,
      ])),
    });
  };
  const schedule = (delay: number) => {
    clearTimeout(timer);
    cancelConnect?.();
    if (disposed || document.hidden) return;
    cancelConnect = requestConnect(() => { void poll(); }, delay);
  };
  const poll = async () => {
    if (disposed || controller || document.hidden) return;
    let refreshing = false;
    controller = new AbortController();
    const timeout = setTimeout(() => controller?.abort(), 30_000);
    try {
      // `instant`: answer from the last read at once; this header asks again.
      const query = new URLSearchParams({ workspace_id: workspaceId, instant: "1" });
      if (followUps) query.set("wait", String(WAIT_S));
      const response = await fetch(`/api/agentic-ide/git/session-status?${query}`, { signal: controller.signal });
      if (!response.ok) throw new Error("GitHub status could not be refreshed.");
      const data = await response.json() as {
        panes: Panes; refreshing?: boolean; age?: number | null; waiting?: string[]; failed?: boolean;
      };
      if (disposed) return;
      // The backend answers with what it last read and reads on in the
      // background; an older backend answers only once it has read.
      refreshing = data.refreshing === true;
      const readAt = data.refreshing === undefined ? Date.now()
        : typeof data.age === "number" ? Date.now() - data.age * 1000 : null;
      const previous = entry.board.panes;
      // After logout/offline, keep a previously confirmed branch visible with
      // an unknown status. Never borrow identity across a checkout change.
      const panes = Object.fromEntries(Object.entries(data.panes).map(([name, status]) => {
        const before = previous[name];
        if (status?.owned && !status.available && before?.owned && before.published
          && status.repo === before.repo && status.branch === before.branch) {
          return [name, { ...status, published: true }];
        }
        return [name, status];
      }));
      publish({ panes, readAt, waiting: refreshing ? new Set(data.waiting ?? []) : NONE });
      // The backend's last read failed and nothing newer is being read: what
      // it holds is old, and says so instead of spinning.
      if (data.failed && !refreshing) unavailable(translate("ide_panes.github.refresh_failed"));
    } catch {
      if (!disposed) unavailable(translate("ide_panes.github.refresh_failed"));
    } finally {
      clearTimeout(timeout);
      controller = undefined;
      followUps = refreshing ? followUps + 1 : 0;
      // A follow-up waits on the backend for the read, so it is sent at once.
      const delay = !refreshing ? POLL_MS : followUps <= MAX_FOLLOW_UPS ? 100 : 5_000;
      if (!disposed) timer = setTimeout(() => schedule(0), spreadDelay(delay));
    }
  };
  const resume = () => {
    if (document.hidden) {
      clearTimeout(timer);
      cancelConnect?.();
      return;
    }
    // A suspended window must not present its last badge as live data: drawn
    // again now, an old one spins until the backend has confirmed it.
    if (old(entry.board.readAt)) publish({ ...entry.board });
    if (!controller) schedule(spreadDelay(500));
  };
  document.addEventListener("visibilitychange", resume);
  window.addEventListener("online", resume);
  entry.refresh = () => {
    if (!controller) schedule(spreadDelay(120));
  };
  entry.stop = () => {
    disposed = true;
    clearTimeout(timer);
    cancelConnect?.();
    controller?.abort();
    document.removeEventListener("visibilitychange", resume);
    window.removeEventListener("online", resume);
  };
  // The backend answers from what it last read, so asking at once is cheap.
  schedule(spreadDelay(120));
  return entry;
}

function paneOf(board: Board, pane: string): PaneGitHub {
  if (pane in board.panes) {
    const status = board.panes[pane];
    // A status that could not be read says so instead of spinning.
    return { status, pending: old(board.readAt) || (outdated(status) && status?.available !== false) };
  }
  const pending = board.waiting === null || board.waiting.has(pane);
  return pending ? { status: null, pending } : IDLE;
}

export function useSessionGitHubPane(workspaceId?: string, pane?: string): PaneGitHub {
  const subscribe = useCallback((listener: () => void) => {
    if (!workspaceId) return () => {};
    let entry = entries.get(workspaceId);
    if (!entry) {
      entry = start(workspaceId);
      entries.set(workspaceId, entry);
    } else {
      // A pane that joins a running workspace may reuse a closed pane's name;
      // the backend tells them apart, so it is asked at once rather than in
      // twenty seconds.
      entry.refresh();
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
  // Before the first subscription, what this window saw last already paints.
  const snapshot = useCallback(
    () => workspaceId ? entries.get(workspaceId)?.board ?? remembered.get(workspaceId) ?? UNKNOWN : null,
    [workspaceId],
  );
  const board = useSyncExternalStore(subscribe, snapshot, () => null);
  return board && pane ? paneOf(board, pane) : IDLE;
}

export function useSessionGitHub(workspaceId?: string, pane?: string): SessionGitHubStatus | null {
  return useSessionGitHubPane(workspaceId, pane).status;
}

/** Forget every remembered answer; tests only. */
export function resetSessionGitHubForTests() {
  remembered.clear();
}
