import type { WorkspacePaneRow } from "@/lib/agenticIdeApi";
import { pullRequestsOf, type ThreadPullRequest } from "../threads/ThreadPullRequests";
import type { SessionCiState, SessionGitHubStatus } from "../useSessionGitHub";

/**
 * The pure half of the Agents board: where a coding agent's card stands and
 * what its footer says.
 *
 * Nobody moves a card by hand. Its column follows from what is true about the
 * work: no pull request yet (Building), a pull request whose checks run or
 * fail (Checks), one that waits for a review (In review), one that can merge
 * (Ready). Work whose pull requests are all merged or closed leaves the
 * columns for the Finished list.
 */

export type BoardColumn = "building" | "checks" | "review" | "ready";
export type BoardPlace = BoardColumn | "finished";

export const BOARD_COLUMNS: readonly BoardColumn[] = ["building", "checks", "review", "ready"];

/** What the agent itself is doing, as far as a card's place and colour care. */
export type BoardActivity = "working" | "attention" | "failed" | "idle";

/** The colour of a card's footer: its column's, or one that asks for a look. */
export type BoardTone = BoardColumn | "attention" | "danger" | "merged" | "quiet";

export interface BoardItem {
  /** `thread:<session id>` or `pane:<history id>`. */
  id: string;
  kind: "thread" | "pane";
  title: string;
  /** The coding CLI's id for its brand mark ("" when unknown) and its name. */
  agent: string;
  agentLabel: string;
  activity: BoardActivity;
  /** i18n key, under `ide_side_panel.agents`, of what the agent itself is doing. */
  activityKey: string;
  /** It rests with something the person has not looked at yet. */
  news: boolean;
  /** The project's name when several projects are listed, else "". */
  project: string;
  /** The worktree or workspace it runs in, shown while GitHub names no branch. */
  place: string;
  status: SessionGitHubStatus | null;
  /** When it last did something, in milliseconds. */
  atMs: number;
  thread?: { sessionId: string; projectId: string; startedBy: string };
  pane?: WorkspacePaneRow;
}

export interface BoardVerdict {
  place: BoardPlace;
  /** i18n key, under `ide_side_panel.agents`, of the footer's words. */
  label: string;
  tone: BoardTone;
  /** The agent is at work: the footer leads with a spinner. */
  spin: boolean;
  /** Its pull requests, most pressing first. */
  requests: ThreadPullRequest[];
  /** The branch to name while it has no pull request. */
  branch: string;
}

const LIVE: ReadonlySet<string> = new Set(["open", "draft", "queued"]);
const FAILING: ReadonlySet<SessionCiState> = new Set<SessionCiState>([
  "failure", "error", "timed_out", "startup_failure", "action_required", "cancelled",
]);
const RUNNING: ReadonlySet<SessionCiState> = new Set<SessionCiState>([
  "pending", "running", "waiting", "requested", "expected",
]);
/** Branch names a repository's main line goes by. */
const TRUNKS: ReadonlySet<string> = new Set(["main", "master", "trunk", "develop"]);
/** GitHub's merge states that mean "nothing stands in the way". */
const MERGEABLE: ReadonlySet<string> = new Set(["clean", "has_hooks"]);

/**
 * Where a card stands and what its footer says.
 *
 * The pull request decides the column. What the agent itself is doing decides
 * the words while it works, asks or has failed, because that is what the
 * person can act on first.
 */
export function boardVerdict(item: Pick<BoardItem, "activity" | "activityKey" | "news" | "status">): BoardVerdict {
  const { activity, activityKey, status } = item;
  const requests = pullRequestsOf(status);
  const lead = requests.find((request) => LIVE.has(request.state)) ?? null;
  const row = lead && status ? [status, ...(status.others ?? [])].find((entry) => entry.number === lead.number) ?? null : null;
  let place: BoardPlace = "building";
  let label = activityKey;
  // A resting agent with nothing new stays quiet, so the ones at work stand out.
  let tone: BoardTone = activity === "idle" && !item.news ? "quiet" : "building";

  if (!lead) {
    const settled = requests[0];
    if (settled && activity === "idle") {
      place = "finished";
      label = `status.${settled.state}`;
      tone = settled.state === "merged" ? "merged" : "quiet";
    }
  } else if (lead.state === "draft") {
    label = "status.draft";
    tone = "quiet";
  } else if (lead.state === "queued") {
    place = tone = "ready";
    label = "status.queued";
  } else {
    // A status that could not be read says nothing about checks or reviews.
    const known = row !== null && row.available !== false;
    const ci: SessionCiState = known ? row.ci.state : "none";
    const merge = known ? row.merge_status ?? "" : "";
    const review = known ? row.review ?? "" : "";
    if (FAILING.has(ci)) {
      place = "checks";
      label = "status.checks_failed";
      tone = "danger";
    } else if (merge === "dirty") {
      place = "checks";
      label = "status.conflicts";
      tone = "danger";
    } else if (RUNNING.has(ci)) {
      place = tone = "checks";
      label = "status.checks_running";
    } else if (review === "changes_requested") {
      place = "review";
      label = "status.changes_requested";
      tone = "attention";
    } else if (MERGEABLE.has(merge) || review === "approved") {
      place = tone = "ready";
      label = "status.mergeable";
    } else {
      place = tone = "review";
      label = "status.awaiting_review";
    }
  }

  if (activity === "attention") {
    label = activityKey;
    tone = "attention";
  } else if (activity === "failed") {
    label = activityKey;
    tone = "danger";
  } else if (activity === "working") {
    label = activityKey;
    tone = place === "finished" ? "building" : place;
  }

  // The branch is named while no pull request stands for it. The project's
  // own line says nothing about the work, so it is left out.
  const own = status && status.owned !== false && !TRUNKS.has(status.branch) ? status.branch : "";
  const branch = requests.length === 0 ? own : "";
  return { place, label, tone, spin: activity === "working", requests, branch };
}

const ACTIVITY_RANK: Record<BoardActivity, number> = { attention: 0, failed: 1, working: 2, idle: 3 };

/** A column's order: what asks for the person first, then work in progress, then the newest. */
export function sortBoardItems<T extends Pick<BoardItem, "activity" | "news" | "atMs">>(items: T[]): T[] {
  return [...items].sort((a, b) =>
    ACTIVITY_RANK[a.activity] - ACTIVITY_RANK[b.activity] || Number(b.news) - Number(a.news) || b.atMs - a.atMs);
}

/**
 * Nothing about this thread's GitHub state can change by itself: the backend
 * has answered since the thread last moved, the agent rests, and none of its
 * pull requests is still open. Such a thread is not asked about again.
 */
export function gitHubSettled(
  thread: { running: boolean; waiting: boolean; updatedMs: number },
  reading: { answered: boolean; readAt: number | null; status: SessionGitHubStatus | null } | undefined,
): boolean {
  if (!reading || !reading.answered || reading.readAt === null) return false;
  if (thread.running || thread.waiting || thread.updatedMs > reading.readAt) return false;
  const rows = reading.status ? [reading.status, ...(reading.status.others ?? [])] : [];
  return rows.every((row) => !LIVE.has(row.state));
}
