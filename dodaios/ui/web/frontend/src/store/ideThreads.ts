import { create } from "zustand";

/**
 * How the Agentic IDE is laid out, and which thread the thread layout shows.
 *
 * `grid` is the terminal wall: workspaces of panes. `threads` is one
 * conversation at a time — a coding agent (Claude Code, Codex, …) driven
 * through its own CLI, read as a chat. The app sidebar, the IDE view and the
 * thread view all read this; none of them can reach the others by props.
 *
 * The open thread is either an existing chat session (`sessionId`) or a draft
 * in one project (`sessionId: null`) whose first message creates the session.
 * Both survive a reload through localStorage, which may be blocked — every
 * read and write degrades to the defaults instead of throwing. So do the
 * threads the person archived out of the list.
 */

export type IdeLayout = "grid" | "threads";

export const IDE_LAYOUTS: readonly IdeLayout[] = ["grid", "threads"];

export interface ThreadSelection {
  /** The project the thread belongs to; "" while no project is known yet. */
  projectId: string;
  /** The chat session on screen, or null for a new thread's draft. */
  sessionId: string | null;
  /**
   * A team thread on screen instead: its id, or `TEAM_DRAFT` while the person
   * still picks the members and writes the task. Absent for an ordinary thread.
   */
  team?: string;
  /**
   * A team member's own thread opened from its team: the team it belongs to,
   * so the thread view can lead back to it.
   */
  fromTeam?: string;
}

/** `ThreadSelection.team` of a team thread that has not started yet. */
export const TEAM_DRAFT = "new";

/** A thread open in a side column next to the main one. */
export interface SplitThread {
  sessionId: string;
  projectId: string;
}

/** How many threads can sit side by side, the main column included. */
export const MAX_THREAD_COLUMNS = 4;

/** One column of the thread layout: the main one (`null`) or a side thread. */
export type ThreadColumn = SplitThread | null;

/** The columns left to right: the side threads with the main one at `mainAt`. */
export function threadColumns(split: readonly SplitThread[], mainAt: number): ThreadColumn[] {
  const at = Math.max(0, Math.min(mainAt, split.length));
  return [...split.slice(0, at), null, ...split.slice(at)];
}

function fromColumns(columns: readonly ThreadColumn[]): { split: SplitThread[]; mainAt: number } {
  const mainAt = Math.max(0, columns.indexOf(null));
  return { split: columns.filter((column): column is SplitThread => column !== null), mainAt };
}

const LAYOUT_KEY = "jarvis.agenticIde.layout.v1";
const SELECTION_KEY = "jarvis.agenticIde.threadSelection.v1";
const PROJECT_OF_KEY = "jarvis.agenticIde.threadProjects.v1";
const SEEN_KEY = "jarvis.agenticIde.threadSeen.v1";
const ARCHIVED_KEY = "jarvis.agenticIde.threadArchived.v1";
const SPLIT_KEY = "jarvis.agenticIde.threadSplit.v1";
/** Bounds on the two maps kept in storage — oldest entries go first. */
const MAX_REMEMBERED = 400;
/**
 * The archive's bound. Dropping an entry brings an old thread back into the
 * list, so this one is far roomier than the maps above.
 */
const MAX_ARCHIVED = 4000;

function read<T>(key: string, parse: (raw: unknown) => T | null, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    if (raw === null) return fallback;
    return parse(JSON.parse(raw)) ?? fallback;
  } catch {
    return fallback;
  }
}

function write(key: string, value: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* a convenience only: the choice just does not survive this session */
  }
}

const parseLayout = (raw: unknown): IdeLayout | null =>
  typeof raw === "string" && (IDE_LAYOUTS as readonly string[]).includes(raw) ? (raw as IdeLayout) : null;

const parseSelection = (raw: unknown): ThreadSelection | null => {
  if (!raw || typeof raw !== "object") return null;
  const row = raw as Record<string, unknown>;
  const projectId = typeof row.projectId === "string" ? row.projectId : "";
  const sessionId = typeof row.sessionId === "string" && row.sessionId ? row.sessionId : null;
  // A stored draft is not worth restoring; an open team thread is.
  const team = typeof row.team === "string" && row.team && row.team !== TEAM_DRAFT ? row.team : undefined;
  if (team) return { projectId, sessionId: null, team };
  const fromTeam = sessionId && typeof row.fromTeam === "string" && row.fromTeam ? row.fromTeam : undefined;
  return fromTeam ? { projectId, sessionId, fromTeam } : { projectId, sessionId };
};

const parseStringMap = (raw: unknown): Record<string, string> | null => {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  return Object.fromEntries(Object.entries(raw).filter(([, value]) => typeof value === "string")) as Record<string, string>;
};

const parseNumberMap = (raw: unknown): Record<string, number> | null => {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  return Object.fromEntries(Object.entries(raw).filter(([, value]) => typeof value === "number")) as Record<string, number>;
};

const parseSplit = (raw: unknown): { split: SplitThread[]; mainAt: number } | null => {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const row = raw as Record<string, unknown>;
  const split: SplitThread[] = [];
  for (const entry of Array.isArray(row.split) ? row.split : []) {
    if (!entry || typeof entry !== "object") continue;
    const { sessionId, projectId } = entry as Record<string, unknown>;
    if (typeof sessionId !== "string" || !sessionId || split.some((thread) => thread.sessionId === sessionId)) continue;
    split.push({ sessionId, projectId: typeof projectId === "string" ? projectId : "" });
    if (split.length >= MAX_THREAD_COLUMNS - 1) break;
  }
  const mainAt = typeof row.mainAt === "number" && Number.isInteger(row.mainAt) ? Math.max(0, Math.min(row.mainAt, split.length)) : 0;
  return { split, mainAt };
};

/** Drop the oldest keys once a map outgrows `limit` (insertion order). */
function bounded<T>(map: Record<string, T>, limit = MAX_REMEMBERED): Record<string, T> {
  const keys = Object.keys(map);
  if (keys.length <= limit) return map;
  return Object.fromEntries(keys.slice(keys.length - limit).map((key) => [key, map[key]]));
}

interface IdeThreadsState {
  layout: IdeLayout;
  selection: ThreadSelection;
  /**
   * Which project a thread was started in. A thread in a fresh worktree runs
   * in a folder outside the project's own, so its folder alone cannot say.
   */
  projectOf: Record<string, string>;
  /** When each thread was last looked at (its `updated_ms` then) — drives the "new" dot. */
  seen: Record<string, number>;
  /** Threads moved out of the list, with when; each project shows them under "Archived". */
  archived: Record<string, number>;
  /** Bumped to ask the thread view to focus its composer. */
  focusNonce: number;
  /** What was on screen before the team start form opened; its cancel goes back there. */
  beforeTeamDraft: ThreadSelection | null;
  /** Threads open side by side with the main one, left to right. */
  split: SplitThread[];
  /** Where the main column sits among the side ones: 0 is the far left. */
  mainAt: number;

  setLayout: (layout: IdeLayout) => void;
  /** Open an existing thread. */
  openThread: (sessionId: string, projectId: string) => void;
  /** Open an empty draft in a project; its first message starts the thread. */
  newThread: (projectId: string) => void;
  /** Open a team thread. */
  openTeam: (teamId: string, projectId: string) => void;
  /** Open the form that starts a team thread in a project. */
  newTeam: (projectId: string) => void;
  /** Leave the start form for what was on screen before it. */
  cancelTeamDraft: () => void;
  /** Open a team member's own thread, remembering the team to come back to. */
  openMemberThread: (sessionId: string, projectId: string, teamId: string) => void;
  /** The draft became a session: remember where it belongs and show it. */
  adoptThread: (sessionId: string, projectId: string) => void;
  /** A session started in `projectId` while another thread was picked: file it, show nothing new. */
  rememberProject: (sessionId: string, projectId: string) => void;
  markSeen: (sessionId: string, updatedMs: number) => void;
  /** A thread was deleted: forget everything kept about it. */
  forgetThread: (sessionId: string) => void;
  /** Move a thread out of the list; an open one gives way to its project's draft. */
  archiveThread: (sessionId: string) => void;
  /** Bring an archived thread back into its project's list. */
  restoreThread: (sessionId: string) => void;
  /**
   * Show a thread in its own column at `index` among all columns, the main one
   * included. A thread already in a side column moves there; `replace` swaps
   * out the column at `index` instead (on the main column it opens there).
   */
  placeColumn: (thread: SplitThread, index: number, replace?: boolean) => void;
  /** Close a side column. */
  closeColumn: (sessionId: string) => void;
  /** Close the main column: the side thread next to it takes its place. */
  closeMainColumn: () => void;
}

/** The side columns without `sessionId`; the same state when it had none. */
function withoutSplit(state: Pick<IdeThreadsState, "split" | "mainAt">, sessionId: string | null): Pick<IdeThreadsState, "split" | "mainAt"> {
  if (!sessionId || !state.split.some((thread) => thread.sessionId === sessionId)) return { split: state.split, mainAt: state.mainAt };
  const next = fromColumns(threadColumns(state.split, state.mainAt).filter((column) => column?.sessionId !== sessionId));
  write(SPLIT_KEY, next);
  return next;
}

export const useIdeThreadsStore = create<IdeThreadsState>((set, get) => ({
  layout: read(LAYOUT_KEY, parseLayout, "grid"),
  selection: read(SELECTION_KEY, parseSelection, { projectId: "", sessionId: null }),
  projectOf: read(PROJECT_OF_KEY, parseStringMap, {}),
  seen: read(SEEN_KEY, parseNumberMap, {}),
  archived: read(ARCHIVED_KEY, parseNumberMap, {}),
  focusNonce: 0,
  beforeTeamDraft: null,
  ...read(SPLIT_KEY, parseSplit, { split: [], mainAt: 0 }),

  setLayout: (layout) => {
    if (get().layout === layout) return;
    write(LAYOUT_KEY, layout);
    set({ layout });
  },
  openThread: (sessionId, projectId) => {
    const selection = { projectId, sessionId };
    write(SELECTION_KEY, selection);
    // A thread shows in one column only: picked for the main one, it leaves its side column.
    set({ selection, ...withoutSplit(get(), sessionId) });
  },
  newThread: (projectId) => {
    const selection = { projectId, sessionId: null };
    write(SELECTION_KEY, selection);
    set((state) => ({ selection, focusNonce: state.focusNonce + 1 }));
  },
  openTeam: (teamId, projectId) => {
    const selection = { projectId, sessionId: null, team: teamId };
    write(SELECTION_KEY, selection);
    set({ selection });
  },
  newTeam: (projectId) => {
    const selection = { projectId, sessionId: null, team: TEAM_DRAFT };
    const current = get().selection;
    const beforeTeamDraft = current.team === TEAM_DRAFT ? get().beforeTeamDraft : current;
    set((state) => ({ selection, beforeTeamDraft, focusNonce: state.focusNonce + 1 }));
  },
  cancelTeamDraft: () => {
    if (get().selection.team !== TEAM_DRAFT) return;
    const back = get().beforeTeamDraft;
    const selection = back ?? { projectId: get().selection.projectId, sessionId: null };
    write(SELECTION_KEY, selection);
    set({ selection, beforeTeamDraft: null });
  },
  openMemberThread: (sessionId, projectId, teamId) => {
    const selection = { projectId, sessionId, fromTeam: teamId };
    write(SELECTION_KEY, selection);
    set({ selection, ...withoutSplit(get(), sessionId) });
  },
  adoptThread: (sessionId, projectId) => {
    const selection = { projectId, sessionId };
    const projectOf = projectId ? bounded({ ...get().projectOf, [sessionId]: projectId }) : get().projectOf;
    write(SELECTION_KEY, selection);
    write(PROJECT_OF_KEY, projectOf);
    set({ selection, projectOf, ...withoutSplit(get(), sessionId) });
  },
  rememberProject: (sessionId, projectId) => {
    const projectOf = bounded({ ...get().projectOf, [sessionId]: projectId });
    write(PROJECT_OF_KEY, projectOf);
    set({ projectOf });
  },
  markSeen: (sessionId, updatedMs) => {
    if ((get().seen[sessionId] ?? 0) >= updatedMs) return;
    const { [sessionId]: _previous, ...rest } = get().seen;
    const seen = bounded({ ...rest, [sessionId]: updatedMs });
    write(SEEN_KEY, seen);
    set({ seen });
  },
  forgetThread: (sessionId) => {
    const { [sessionId]: _project, ...projectOf } = get().projectOf;
    const { [sessionId]: _seen, ...seen } = get().seen;
    const { [sessionId]: _archived, ...archived } = get().archived;
    write(PROJECT_OF_KEY, projectOf);
    write(SEEN_KEY, seen);
    write(ARCHIVED_KEY, archived);
    const selection = get().selection.sessionId === sessionId
      ? { projectId: get().selection.projectId, sessionId: null }
      : get().selection;
    write(SELECTION_KEY, selection);
    set({ projectOf, seen, archived, selection, ...withoutSplit(get(), sessionId) });
  },
  archiveThread: (sessionId) => {
    const { [sessionId]: _previous, ...rest } = get().archived;
    const archived = bounded({ ...rest, [sessionId]: Date.now() }, MAX_ARCHIVED);
    write(ARCHIVED_KEY, archived);
    const selection = get().selection.sessionId === sessionId
      ? { projectId: get().selection.projectId, sessionId: null }
      : get().selection;
    write(SELECTION_KEY, selection);
    set({ archived, selection, ...withoutSplit(get(), sessionId) });
  },
  restoreThread: (sessionId) => {
    if (!(sessionId in get().archived)) return;
    const { [sessionId]: _archived, ...archived } = get().archived;
    write(ARCHIVED_KEY, archived);
    set({ archived });
  },
  placeColumn: (thread, index, replace = false) => {
    const state = get();
    // The main column's thread is already on screen.
    if (thread.sessionId === state.selection.sessionId) return;
    const columns = threadColumns(state.split, state.mainAt);
    const from = columns.findIndex((column) => column?.sessionId === thread.sessionId);
    let at = Math.max(0, Math.min(index, columns.length));
    // A thread already in a column only moves; replacing is for a new one when every column is taken.
    if (replace && from < 0) {
      const slot = Math.min(at, columns.length - 1);
      if (columns[slot] === null) {
        get().openThread(thread.sessionId, thread.projectId);
        return;
      }
      columns.splice(slot, 1, thread);
    } else {
      if (from >= 0) {
        columns.splice(from, 1);
        if (from < at) at -= 1;
      } else if (columns.length >= MAX_THREAD_COLUMNS) {
        return;
      }
      columns.splice(at, 0, thread);
    }
    const next = fromColumns(columns);
    write(SPLIT_KEY, next);
    set(next);
  },
  closeColumn: (sessionId) => {
    set(withoutSplit(get(), sessionId));
  },
  closeMainColumn: () => {
    const { split, mainAt } = get();
    if (split.length === 0) return;
    // The neighbour on the right moves in, else the one on the left.
    const heir = split[mainAt] ?? split[mainAt - 1];
    get().openThread(heir.sessionId, heir.projectId);
  },
}));
