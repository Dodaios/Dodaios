import { createContext, useContext } from "react";
import type { AgentChatSession } from "@/lib/agentChatApi";
import type { IdeProject } from "@/lib/agenticIdeApi";
import { createAgentChatStore, type ProviderOption } from "@/store/agentChat";
import { fill, translate } from "@/i18n";

/**
 * The pure half of the IDE's thread layout: which project a thread belongs
 * to, what it is called, and what state its row shows.
 *
 * A thread is one agent-chat session on the IDE's own surface (`agent`): a
 * coding CLI driven through its own binary, so its tools, skills, MCP servers
 * and login are the CLI's, and the conversation is the CLI's own session.
 */

/** The IDE threads' chat store — one socket, one draft, one session list. */
export const useThreadChatStore = createAgentChatStore("agent", "threads");

/** A thread chat store: the main one, or a side column's own. */
export type ThreadChatStore = typeof useThreadChatStore;

/**
 * The store a thread view and its composer talk to. The main column uses the
 * default; every side column provides its own, so each holds its own socket
 * and conversation while they sit next to each other.
 */
export const ThreadChatContext = createContext<ThreadChatStore>(useThreadChatStore);

export function useThreadChat(): ThreadChatStore {
  return useContext(ThreadChatContext);
}

/** What a dragged thread row carries: its session id, so only a thread is a valid drop. */
export const THREAD_DRAG_MIME = "application/x-jarvis-thread";
/** The dragged thread's project, carried next to its session id. */
export const THREAD_PROJECT_DRAG_MIME = "application/x-jarvis-thread-project";

/**
 * The thread being dragged right now. A drag's data can only be read on the
 * drop, but the thread columns must know during the drag whether it is
 * already on screen, so the row says it here too.
 */
let draggedThreadId: string | null = null;

export function setDraggedThread(sessionId: string | null): void {
  draggedThreadId = sessionId;
}

export function draggedThread(): string | null {
  return draggedThreadId;
}

/** How a row in the thread list reads at a glance. */
export type ThreadStatus = "approval" | "running" | "unseen" | "idle";

/** What a thread is called in the list and its header. */
export function threadTitle(session: Pick<AgentChatSession, "title" | "cli_title"> | null | undefined): string {
  const raw = session?.cli_title?.trim() || session?.title?.trim() || "";
  return compactTitle(raw) || translate("ide_threads.new_thread");
}

const GITHUB_ITEM = /\bhttps?:\/\/(?:www\.)?github\.com\/[\w.-]+\/[\w.-]+\/(issues|pull)\/(\d+)\S*/gi;
const ANY_URL = /\bhttps?:\/\/(?:www\.)?([^\s/]+)\S*/gi;

/**
 * A title short enough to read in a narrow list. A thread's first message
 * often opens with a pasted link; a GitHub issue or pull request link becomes
 * "Issue #12" / "PR #12", any other link its host name.
 */
export function compactTitle(text: string): string {
  const out = text
    .replace(GITHUB_ITEM, (_match, kind: string, number: string) => `${kind.toLowerCase() === "pull" ? "PR" : "Issue"} #${number}`)
    .replace(ANY_URL, (_match, host: string) => host)
    .replace(/\s+/g, " ")
    .trim();
  return out;
}

/** Folders that hold linked git worktrees: the IDE's own and Claude Code's. */
const WORKTREE_FOLDERS = new Set([".worktrees", "worktrees"]);

/**
 * The worktree a thread works in, when its folder is one inside the project
 * (`<project>/.worktrees/<name>`, `<project>/.claude/worktrees/<name>`);
 * null when it works in the project's own checkout.
 */
export function threadWorktree(cwd: string, projectPath: string): string | null {
  if (!cwd || !projectPath || !isInside(cwd, projectPath)) return null;
  const base = comparablePath(projectPath);
  const rest = comparablePath(cwd).slice(base.length).split("/").filter(Boolean);
  const at = rest.findIndex((part) => WORKTREE_FOLDERS.has(part));
  if (at < 0 || at + 1 >= rest.length) return null;
  // The name as written, not case-folded.
  const written = cwd.replace(/\\/g, "/").split("/").filter(Boolean);
  return written[written.length - (rest.length - at - 1)] ?? rest[at + 1];
}

/** A path in one comparable spelling: forward slashes, no trailing slash, case folded on drive paths. */
export function comparablePath(path: string): string {
  let text = path.trim().replace(/\\/g, "/");
  while (text.length > 1 && text.endsWith("/") && !/^[A-Za-z]:\/$/.test(text)) text = text.slice(0, -1);
  // Windows paths are case-insensitive; POSIX paths are not and stay as written.
  return /^[A-Za-z]:\//.test(text) || text.startsWith("//") ? text.toLowerCase() : text;
}

/** True when `child` is `parent` or lies inside it. */
export function isInside(child: string, parent: string): boolean {
  const a = comparablePath(child);
  const b = comparablePath(parent);
  if (!a || !b) return false;
  return a === b || a.startsWith(b.endsWith("/") ? b : `${b}/`);
}

/**
 * The project a thread belongs to: the one it was started in when that is
 * remembered, else the deepest project folder holding the thread's folder.
 */
export function projectIdFor(
  session: Pick<AgentChatSession, "session_id" | "cwd">,
  projects: readonly IdeProject[],
  projectOf: Readonly<Record<string, string>>,
): string | null {
  const remembered = projectOf[session.session_id];
  if (remembered && projects.some((project) => project.id === remembered)) return remembered;
  let best: IdeProject | null = null;
  for (const project of projects) {
    if (!project.path || !isInside(session.cwd, project.path)) continue;
    if (!best || comparablePath(project.path).length > comparablePath(best.path).length) best = project;
  }
  return best?.id ?? null;
}

/**
 * The moment a thread row is ordered by: the last message that reached it.
 * Tool calls and answers of a working thread leave it alone, so threads that
 * run side by side keep their places; `updated_ms` is the fallback for a
 * backend without the field.
 */
export function threadOrderMs(session: Pick<AgentChatSession, "updated_ms" | "last_message_ms">): number {
  return session.last_message_ms || session.updated_ms;
}

/** Every project's threads, newest message first. Threads outside every project are left out. */
export function threadsByProject(
  sessions: readonly AgentChatSession[],
  projects: readonly IdeProject[],
  projectOf: Readonly<Record<string, string>>,
): Map<string, AgentChatSession[]> {
  const out = new Map<string, AgentChatSession[]>();
  for (const session of sessions) {
    const projectId = projectIdFor(session, projects, projectOf);
    if (!projectId) continue;
    const list = out.get(projectId);
    if (list) list.push(session);
    else out.set(projectId, [session]);
  }
  for (const list of out.values()) list.sort((a, b) => threadOrderMs(b) - threadOrderMs(a));
  return out;
}

/** The row's state: a waiting approval first, then work, then news since the last look. */
export function threadStatus(
  session: Pick<AgentChatSession, "session_id" | "running" | "pending_approvals" | "updated_ms">,
  seen: Readonly<Record<string, number>>,
  openSessionId: string | null,
): ThreadStatus {
  if (session.pending_approvals && session.pending_approvals.length > 0) return "approval";
  if (session.running) return "running";
  if (session.session_id !== openSessionId && session.updated_ms > (seen[session.session_id] ?? Number.POSITIVE_INFINITY)) {
    return "unseen";
  }
  return "idle";
}

/** The CLIs a thread can run on: the catalog's coding-agent rows, installed ones first. */
export function threadAgents(options: readonly ProviderOption[]): ProviderOption[] {
  return options
    .filter((option) => Boolean(option.agent))
    .sort((a, b) => Number(b.connected) - Number(a.connected));
}

/** "now", "5m", "3h", "2d", "4w" — how long ago, the way a dense list says it. */
export function shortAge(ms: number, now = Date.now()): string {
  const seconds = Math.max(0, Math.round((now - ms) / 1000));
  if (seconds < 60) return translate("ide_threads.age_now");
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return fill(translate("ide_threads.age_minutes"), { count: minutes });
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return fill(translate("ide_threads.age_hours"), { count: hours });
  const days = Math.floor(hours / 24);
  if (days < 7) return fill(translate("ide_threads.age_days"), { count: days });
  return fill(translate("ide_threads.age_weeks"), { count: Math.floor(days / 7) });
}

/** Midnight, local time, of the day a moment falls on. */
function dayStart(ms: number): number {
  const day = new Date(ms);
  day.setHours(0, 0, 0, 0);
  return day.getTime();
}

/** Whole calendar days between two moments; rounding absorbs a daylight-saving hour. */
function daysApart(laterMs: number, earlierMs: number): number {
  return Math.round((dayStart(laterMs) - dayStart(earlierMs)) / 86_400_000);
}

/**
 * The day a thread row opens in a list sorted by last activity: "Yesterday",
 * then "Mon, 9 Nov". Null while the row shares its day with the row above, and
 * for today's rows at the top of the list, which need no heading.
 *
 * The day is the one of the thread's last message (`threadOrderMs`), the same
 * moment the list is sorted by: a thread started on Monday and written to
 * again on Wednesday stands under Wednesday.
 */
export function threadDayBreak(activityMs: number, aboveMs: number | null, locale: string, now = Date.now()): string | null {
  const age = daysApart(now, activityMs);
  if (aboveMs === null ? age <= 0 : daysApart(aboveMs, activityMs) === 0) return null;
  let label: string;
  if (age <= 1) {
    label = new Intl.RelativeTimeFormat(locale, { numeric: "auto" }).format(-Math.max(age, 0), "day");
  } else {
    const sameYear = new Date(activityMs).getFullYear() === new Date(now).getFullYear();
    label = new Date(activityMs).toLocaleDateString(locale, {
      weekday: "short", day: "numeric", month: "short", ...(sameYear ? {} : { year: "numeric" }),
    });
  }
  return label.charAt(0).toLocaleUpperCase(locale) + label.slice(1);
}

/** The last folder name of a path — what a branch-less checkout is called. */
export function folderLabel(path: string): string {
  const parts = path.split(/[\\/]/).filter(Boolean);
  return parts[parts.length - 1] ?? path;
}

/** The agent, model, effort and access the person picked last — what every new thread starts on. */
export interface ThreadSeat {
  provider: string;
  model: string;
  effort: string;
  permissionMode: string;
}

const SEAT_KEY = "jarvis.ide.threadSeat.v1";

/** Remember an explicit pick. Opening an old thread never calls this, so it never moves the seat. */
export function rememberSeat(seat: ThreadSeat): void {
  if (!seat.provider) return;
  try {
    localStorage.setItem(SEAT_KEY, JSON.stringify({
      provider: seat.provider, model: seat.model, effort: seat.effort, permissionMode: seat.permissionMode,
    }));
  } catch { /* storage blocked: new threads start on the provider's defaults */ }
}

export function rememberedSeat(): ThreadSeat | null {
  try {
    const raw: unknown = JSON.parse(localStorage.getItem(SEAT_KEY) ?? "null");
    if (!raw || typeof raw !== "object") return null;
    const row = raw as Record<string, unknown>;
    if (typeof row.provider !== "string" || !row.provider) return null;
    const text = (value: unknown) => (typeof value === "string" ? value : "");
    return { provider: row.provider, model: text(row.model), effort: text(row.effort), permissionMode: text(row.permissionMode) };
  } catch {
    return null;
  }
}
