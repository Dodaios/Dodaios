import { Fragment, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Archive, ArchiveRestore, Check, ChevronDown, ChevronRight, Columns2, Folder, FolderOpen, FolderPlus, GitBranch, Loader2, Mic, MoreHorizontal, Pencil, Plus, Search, SquarePen, SquarePlus, Trash2, Users, X } from "lucide-react";
import { AgentMark } from "@/components/agentic/AgentMark";
import { patchAgentChatSession, type AgentChatSession } from "@/lib/agentChatApi";
import type { IdeProject } from "@/lib/agenticIdeApi";
import { cn } from "@/lib/utils";
import { fill, useT } from "@/i18n";
import { useRunLocale } from "@/components/runs/format";
import { useEventStore } from "@/store/events";
import { useIdeProjectsStore } from "@/store/ideProjects";
import { useQuickSwitcher } from "@/store/quickSwitcher";
import { useQuickSwitchSettings } from "@/store/quickSwitchSettings";
import { MAX_THREAD_COLUMNS, TEAM_DRAFT, useIdeThreadsStore } from "@/store/ideThreads";
import { useTeamThreads, type TeamThreadRow } from "@/lib/teamThreadsApi";
import { openSubagentOf, useThreadSubagentsStore } from "@/store/threadSubagents";
import { ThreadMenuItem, ThreadMenuSeparator, ThreadPopover } from "./ThreadPopover";
import { SubagentFoldToggle, ThreadTreeSubagents } from "./ThreadTreeSubagents";
import { ThreadPullRequests } from "./ThreadPullRequests";
import { THREAD_DRAG_MIME, THREAD_PROJECT_DRAG_MIME, projectIdFor, setDraggedThread, shortAge, threadStatus, threadTitle, threadWorktree, threadsByProject, useThreadChatStore, type ThreadStatus } from "./threadModel";

const EXPANSION_KEY = "jarvis.ide.threadExpansion.v1";
/** Threads a project shows before "Show more": enough to fill a tall sidebar. */
const FOLDED_COUNT = 20;
/** How often the list asks for fresh session rows while it is on screen. */
const POLL_MS = 4000;
const FOCUS_RING = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";
/** One row of the list: the same height, inset and type for actions, projects and threads. */
const ROW = "flex min-h-8 min-w-0 items-center gap-2.5 rounded-md px-2 text-left text-base";
/** Where a thread's title starts: the row inset, the leading mark and the gap after it. */
const TITLE_INSET = "pl-[34px]";
/** A small action that only shows while its row is hovered or focused. */
const HOVER_ACTION = cn(
  "flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-[opacity,color,background-color] hover:bg-background/70 hover:text-foreground",
  "opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 [@media(hover:none)]:opacity-100",
  FOCUS_RING,
);
/**
 * A start row at the top of the list, drawn like the app's main navigation:
 * a bright label after an 18px icon, no frame. Inset, icon and gap still add
 * up to TITLE_INSET, so the labels line up with the projects' names.
 */
const ACTION_ROW = cn(
  "flex min-h-8 w-full min-w-0 items-center gap-2 rounded-lg px-2 text-left text-base text-foreground transition-colors hover:bg-secondary",
  FOCUS_RING,
);
const ACTION_ICON = "h-[18px] w-[18px] shrink-0";

function readExpansion(): Record<string, boolean> {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(EXPANSION_KEY) ?? "{}");
    if (!value || typeof value !== "object" || Array.isArray(value)) return {};
    return Object.fromEntries(Object.entries(value).filter(([, open]) => typeof open === "boolean")) as Record<string, boolean>;
  } catch { return {}; /* an optional preference: the defaults stay usable */ }
}

function saveExpansion(value: Record<string, boolean>): void {
  try { localStorage.setItem(EXPANSION_KEY, JSON.stringify(value)); }
  catch { /* storage blocked — the choice holds for this session only */ }
}

/** The quiet mark at a row's end: what the thread is doing, else whose it is. */
function StatusMark({ status }: { status: ThreadStatus }) {
  const t = useT();
  if (status === "approval") {
    return <span role="img" aria-label={t("ide_threads.waiting_approval")} title={t("ide_threads.waiting_approval")}
      className="h-2 w-2 shrink-0 rounded-full bg-warning" />;
  }
  if (status === "running") {
    return <Loader2 role="img" aria-label={t("ide_threads.sub_status_running")} className="h-3.5 w-3.5 shrink-0 animate-spin text-muted-foreground" />;
  }
  if (status === "unseen") {
    return <span role="img" aria-label={t("ide_threads.new_activity")} title={t("ide_threads.new_activity")} className="h-2 w-2 shrink-0 rounded-full bg-accent" />;
  }
  return null;
}

/** A quiet heading over a group of rows, with its own small actions on the right. */
function SectionLabel({ label, children }: { label: string; children?: ReactNode }) {
  return <div className="flex min-h-8 items-end justify-between gap-2 pb-1 pl-2 pr-1 pt-4 text-sm text-muted-foreground">
    <span className="truncate">{label}</span>
    {children && <div className="flex items-center gap-0.5">{children}</div>}
  </div>;
}

/**
 * The sidebar while the IDE shows threads: every project with its threads,
 * newest activity first, each named by the title its coding CLI gave the
 * conversation and marked with that CLI's logo. A project row opens and
 * folds; its "+" starts a new thread in it. A thread dragged onto the thread
 * view opens side by side; from the row menu it is archived into a folded
 * "Archived" list under its project, from where it comes back.
 */
export function ThreadTree() {
  const t = useT();
  const locale = useRunLocale();
  const projects = useIdeProjectsStore((state) => state.projects);
  const connectProject = useIdeProjectsStore((state) => state.connectProject);
  const toggleVoice = useIdeProjectsStore((state) => state.toggleVoice);
  // In this layout search is a row of the list, not the field atop the sidebar.
  const searchOn = useQuickSwitchSettings((state) => state.enabled);
  const pushToast = useEventStore((state) => state.pushToast);
  const sessions = useThreadChatStore((state) => state.sessions);
  const catalog = useThreadChatStore((state) => state.catalog);
  const activeSessionId = useThreadChatStore((state) => state.activeSessionId);
  const selection = useIdeThreadsStore((state) => state.selection);
  const projectOf = useIdeThreadsStore((state) => state.projectOf);
  const seen = useIdeThreadsStore((state) => state.seen);
  const openThread = useIdeThreadsStore((state) => state.openThread);
  const newThread = useIdeThreadsStore((state) => state.newThread);
  const openTeam = useIdeThreadsStore((state) => state.openTeam);
  const newTeam = useIdeThreadsStore((state) => state.newTeam);
  const teams = useTeamThreads().data;
  const forgetThread = useIdeThreadsStore((state) => state.forgetThread);
  const archived = useIdeThreadsStore((state) => state.archived);
  const archiveThread = useIdeThreadsStore((state) => state.archiveThread);
  const restoreThread = useIdeThreadsStore((state) => state.restoreThread);
  const split = useIdeThreadsStore((state) => state.split);
  const placeColumn = useIdeThreadsStore((state) => state.placeColumn);
  const [expansion, setExpansion] = useState(readExpansion);
  const [showAll, setShowAll] = useState<Record<string, boolean>>({});
  const [renaming, setRenaming] = useState<{ sessionId: string; title: string } | null>(null);
  const [menu, setMenu] = useState<{ sessionId: string; projectId: string } | null>(null);
  const [archiveOpen, setArchiveOpen] = useState<Record<string, boolean>>({});
  const [dragged, setDragged] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  // Threads whose sub-agent rows the person folded away; open by default.
  const [subagentsFolded, setSubagentsFolded] = useState<Record<string, boolean>>({});
  const subagentsOwner = useThreadSubagentsStore((state) => state.sessionId);
  const subagentRows = useThreadSubagentsStore((state) => state.rows);
  const openSubagent = useThreadSubagentsStore((state) => openSubagentOf(state.open, selection.sessionId));
  const menuAnchor = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const store = useThreadChatStore.getState();
    if (!store.catalog || store.catalogStale) void store.loadCatalog();
    void store.loadSessions();
    const timer = window.setInterval(() => { void useThreadChatStore.getState().loadSessions(); }, POLL_MS);
    return () => window.clearInterval(timer);
  }, []);

  const visible = useMemo(() => projects.filter((project) => !project.archived && !project.scratch), [projects]);
  // A team thread's members are read inside their team, not as threads of their own.
  const grouped = useMemo(
    () => threadsByProject(sessions.filter((session) => !session.team_id), visible, projectOf),
    [sessions, visible, projectOf],
  );
  const teamsOf = useMemo(() => {
    const map = new Map<string, TeamThreadRow[]>();
    for (const team of teams ?? []) {
      const projectId = projectIdFor({ session_id: team.team_id, cwd: team.cwd }, visible, projectOf);
      if (projectId) map.set(projectId, [...(map.get(projectId) ?? []), team]);
    }
    return map;
  }, [teams, visible, projectOf]);
  const agentOf = useMemo(() => {
    const map = new Map<string, { agent: string; label: string }>();
    for (const provider of catalog?.providers ?? []) {
      if (provider.agent) map.set(provider.id, { agent: provider.agent, label: provider.label });
    }
    return map;
  }, [catalog]);
  const openSessionId = selection.sessionId ?? activeSessionId;

  const setProjectOpen = (id: string, open: boolean) => setExpansion((previous) => {
    const next = { ...previous, [id]: open };
    saveExpansion(next);
    return next;
  });

  const rename = async (session: AgentChatSession, title: string) => {
    const clean = title.trim();
    setRenaming(null);
    if (!clean || clean === threadTitle(session)) return;
    setBusy(session.session_id);
    try {
      await patchAgentChatSession(session.session_id, { title: clean });
      await useThreadChatStore.getState().loadSessions();
    } catch (error) {
      pushToast("error", error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(null);
    }
  };

  const clearDrag = () => { setDragged(null); setDraggedThread(null); };

  const remove = async (sessionId: string) => {
    setConfirmDelete(null);
    setBusy(sessionId);
    try {
      await useThreadChatStore.getState().removeSession(sessionId);
      forgetThread(sessionId);
    } finally {
      setBusy(null);
    }
  };

  /** A new thread or team goes into the project in view, else the first one; with none, a folder is connected first. */
  const startIn = (start: (projectId: string) => void) => {
    const current = visible.find((project) => project.id === selection.projectId);
    const target = current ?? visible.find((project) => project.pinned) ?? visible[0];
    if (!target) { connectProject(); return; }
    setProjectOpen(target.id, true);
    start(target.id);
  };

  const projectRow = (project: IdeProject) => {
    const all = grouped.get(project.id) ?? [];
    // Newest activity first, as threadsByProject sorts them.
    const threads = all.filter((thread) => !(thread.session_id in archived));
    const stored = all.filter((thread) => thread.session_id in archived)
      .sort((a, b) => (archived[b.session_id] ?? 0) - (archived[a.session_id] ?? 0));
    const archiveShown = archiveOpen[project.id] ?? false;
    const teamRows = teamsOf.get(project.id) ?? [];
    const draftHere = selection.sessionId === null && !selection.team && selection.projectId === project.id;
    const teamDraftHere = selection.team === TEAM_DRAFT && selection.projectId === project.id;
    const open = expansion[project.id] ?? (threads.length > 0 || teamRows.length > 0 || draftHere || teamDraftHere);
    const shown = showAll[project.id] ? threads : threads.slice(0, FOLDED_COUNT);
    const running = threads.filter((thread) => thread.running).length;
    return <div key={project.id} className="mb-px" data-testid={`thread-project-${project.id}`}>
      <div className="group relative flex min-h-8 items-center rounded-md pr-1 transition-colors hover:bg-muted">
        <button type="button" aria-expanded={open} aria-label={fill(t(open ? "ide_projects.collapse_named" : "ide_projects.expand_named"), { target: project.name })}
          onClick={() => setProjectOpen(project.id, !open)} title={project.path}
          className={cn(ROW, "flex-1 text-foreground-secondary group-hover:text-foreground", FOCUS_RING)}>
          {open
            ? <FolderOpen aria-hidden className="h-4 w-4 shrink-0 text-muted-foreground" strokeWidth={1.75} />
            : <Folder aria-hidden className="h-4 w-4 shrink-0 text-muted-foreground" strokeWidth={1.75} />}
          <span className="min-w-0 flex-1 truncate">{project.name}</span>
          {!open && running > 0 && <Loader2 aria-label={fill(t("ide_threads.count_working"), { count: running })} className="h-3.5 w-3.5 shrink-0 animate-spin text-muted-foreground" />}
        </button>
        <button type="button" aria-label={fill(t("ide_threads.new_thread_in"), { project: project.name })} title={t("ide_threads.new_thread")}
          data-testid={`thread-new-${project.id}`}
          onClick={() => { setProjectOpen(project.id, true); newThread(project.id); }}
          className={HOVER_ACTION}>
          <SquarePen className="h-3.5 w-3.5" strokeWidth={1.75} />
        </button>
        <button type="button" aria-label={fill(t("team_threads.new_in"), { project: project.name })} title={t("team_threads.new")}
          data-testid={`team-thread-new-${project.id}`}
          onClick={() => { setProjectOpen(project.id, true); newTeam(project.id); }}
          className={HOVER_ACTION}>
          <Users className="h-3.5 w-3.5" strokeWidth={1.75} />
        </button>
      </div>
      {open && <div className="mb-2 flex flex-col gap-px">
        {teamDraftHere && <div aria-current="page" className={cn(ROW, "bg-muted text-muted-foreground")}>
          <span className="flex h-4 w-4 shrink-0 items-center justify-center"><Users aria-hidden className="h-3.5 w-3.5" /></span>
          <span className="min-w-0 flex-1 truncate">{t("team_threads.new")}</span>
        </div>}
        {teamRows.map((team) => {
          // A member's own thread, opened from the team, keeps its team marked.
          const selected = selection.team === team.team_id || selection.fromTeam === team.team_id;
          return <button key={team.team_id} type="button" aria-current={selected ? "page" : undefined}
            data-testid={`team-thread-row-${team.team_id}`}
            onClick={() => openTeam(team.team_id, project.id)} title={team.title}
            className={cn(
              ROW, "py-1 transition-colors hover:bg-muted hover:text-foreground", FOCUS_RING,
              selected ? "bg-muted text-foreground-strong" : "text-foreground-secondary",
            )}>
            <span className="flex h-4 w-4 shrink-0 items-center justify-center"><Users aria-hidden className="h-3.5 w-3.5 text-muted-foreground" /></span>
            <span className="min-w-0 flex-1 truncate">{team.title}</span>
            {team.state === "running"
              ? <Loader2 aria-label={t("team_threads.state.running")} className="h-3.5 w-3.5 shrink-0 animate-spin text-muted-foreground" />
              : team.state === "needs_input"
                ? <span aria-label={t("team_threads.state.needs_input")} className="h-2 w-2 shrink-0 rounded-full bg-warning" />
                : team.state === "done"
                  ? <Check aria-label={t("team_threads.state.done")} className="h-3.5 w-3.5 shrink-0 text-success" />
                  : <span className="text-micro tabular-nums text-muted-foreground">{shortAge(team.updated_ms)}</span>}
          </button>;
        })}
        {draftHere && <div aria-current="page" className={cn(ROW, "bg-muted text-muted-foreground")}>
          <span className="flex h-4 w-4 shrink-0 items-center justify-center"><SquarePen aria-hidden className="h-3.5 w-3.5" strokeWidth={1.75} /></span>
          <span className="min-w-0 flex-1 truncate">{t("ide_threads.new_thread")}</span>
        </div>}
        {shown.map((session) => {
          const selected = session.session_id === openSessionId && selection.sessionId !== null;
          const status = threadStatus(session, seen, openSessionId);
          const mark = agentOf.get(session.provider);
          const worktree = threadWorktree(session.cwd, project.path);
          const menuOpen = menu?.sessionId === session.session_id;
          if (renaming?.sessionId === session.session_id) {
            return <form key={session.session_id} className="flex min-h-8 items-center gap-1 pl-[30px] pr-1"
              onSubmit={(event) => { event.preventDefault(); void rename(session, renaming.title); }}>
              <input autoFocus aria-label={fill(t("ide_projects.rename_named"), { target: threadTitle(session) })} value={renaming.title} maxLength={120}
                onChange={(event) => setRenaming({ sessionId: session.session_id, title: event.target.value })}
                onKeyDown={(event) => { if (event.key === "Escape") { event.stopPropagation(); setRenaming(null); } }}
                onBlur={() => void rename(session, renaming.title)}
                className="min-w-0 flex-1 rounded border border-input bg-background px-2 py-1 text-sm text-foreground outline-none focus:ring-2 focus:ring-ring" />
              <button type="submit" aria-label={t("ide_threads.save_name")} className="rounded p-1 text-muted-foreground hover:text-foreground"><Check className="h-4 w-4" /></button>
              <button type="button" aria-label={t("ide_threads.cancel_renaming")} onMouseDown={(event) => event.preventDefault()} onClick={() => setRenaming(null)}
                className="rounded p-1 text-muted-foreground hover:text-foreground"><X className="h-4 w-4" /></button>
            </form>;
          }
          // The open thread lists the sub-agents its coding agent spawned under it.
          const subRows = selected && subagentsOwner === session.session_id ? subagentRows : [];
          const subOpen = subRows.length > 0 && !subagentsFolded[session.session_id];
          const onSubagent = selected && openSubagent !== null && subRows.some((row) => row.id === openSubagent);
          return <Fragment key={session.session_id}><div data-testid={`thread-row-${session.session_id}`}
            draggable
            onDragStart={(event) => {
              // The list keeps its date order; dropped on the thread view it opens side by side.
              event.dataTransfer.setData(THREAD_DRAG_MIME, session.session_id);
              event.dataTransfer.setData(THREAD_PROJECT_DRAG_MIME, project.id);
              event.dataTransfer.effectAllowed = "move";
              setDraggedThread(session.session_id);
              setDragged(session.session_id);
            }}
            onDragEnd={clearDrag}
            className={cn(
              "group/thread relative flex min-h-8 items-center rounded-md transition-colors hover:bg-muted",
              ((selected && !onSubagent) || menuOpen) && "bg-muted",
              dragged === session.session_id && "opacity-40",
            )}
            onContextMenu={(event) => {
              event.preventDefault();
              // Keep the app-wide edit menu (EditContextMenu) from opening on top.
              event.stopPropagation();
              menuAnchor.current = event.currentTarget;
              setMenu({ sessionId: session.session_id, projectId: project.id });
            }}>
            {subRows.length > 0 && <SubagentFoldToggle open={subOpen} count={subRows.length} title={threadTitle(session)}
              onToggle={() => setSubagentsFolded((current) => ({ ...current, [session.session_id]: subOpen }))} />}
            <button type="button" aria-current={selected ? (onSubagent ? "true" : "page") : undefined}
              onClick={() => {
                // The thread's own row leads back from a sub-agent to the main conversation.
                useThreadSubagentsStore.getState().openAgent(session.session_id, null);
                openThread(session.session_id, project.id);
              }}
              onDoubleClick={() => setRenaming({ sessionId: session.session_id, title: threadTitle(session) })}
              title={threadTitle(session)}
              className={cn(
                ROW, "flex-1 py-1", FOCUS_RING,
                selected ? "text-foreground-strong" : "text-foreground-secondary group-hover/thread:text-foreground",
              )}>
              {/* The coding agent's own logo leads the row, where a plain list keeps a bullet. */}
              <span className="flex h-4 w-4 shrink-0 items-center justify-center">
                {mark
                  ? <AgentMark agent={mark.agent} label={mark.label} variant="plain" size="sm" />
                  : <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-muted-foreground/60" />}
              </span>
              <span className="min-w-0 flex-1 truncate">{threadTitle(session)}</span>
              {/* Marks on the right, one column each: its pull requests, where it works, what it is doing. */}
              <ThreadPullRequests sessionId={session.session_id} />
              {worktree && <span role="img" aria-label={fill(t("ide_threads.in_worktree"), { name: worktree })}
                title={fill(t("ide_threads.in_worktree"), { name: worktree })}
                data-testid={`thread-worktree-${session.session_id}`} className="flex shrink-0 items-center">
                <GitBranch aria-hidden className="h-3.5 w-3.5 text-muted-foreground" strokeWidth={1.75} />
              </span>}
              <span className="flex w-3.5 shrink-0 items-center justify-center">
                {busy === session.session_id
                  ? <Loader2 aria-hidden className="h-3.5 w-3.5 shrink-0 animate-spin text-muted-foreground" />
                  : <StatusMark status={status} />}
              </span>
            </button>
            <div className={cn(
              "absolute inset-y-0 right-0 flex items-center gap-1 rounded-r-md bg-gradient-to-l from-muted from-60% to-transparent pl-5 pr-1 transition-opacity",
              menuOpen ? "opacity-100" : "pointer-events-none opacity-0 group-hover/thread:pointer-events-auto group-hover/thread:opacity-100 group-focus-within/thread:pointer-events-auto group-focus-within/thread:opacity-100 [@media(hover:none)]:pointer-events-auto [@media(hover:none)]:opacity-100",
            )}>
              <span className="text-micro tabular-nums text-muted-foreground" title={new Date(session.updated_ms).toLocaleString(locale)}>{shortAge(session.updated_ms)}</span>
              <button type="button" aria-label={fill(t("ide_threads.thread_actions_for"), { target: threadTitle(session) })} aria-haspopup="menu" aria-expanded={menuOpen}
                onClick={(event) => {
                  menuAnchor.current = event.currentTarget;
                  setMenu(menuOpen ? null : { sessionId: session.session_id, projectId: project.id });
                }}
                className="rounded p-1 text-muted-foreground hover:bg-background/70 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                <MoreHorizontal className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
          {subOpen && <ThreadTreeSubagents rows={subRows} openId={onSubagent ? openSubagent : null} threadTitle={threadTitle(session)}
            onOpen={(id) => useThreadSubagentsStore.getState().openAgent(session.session_id, id)} />}
          </Fragment>;
        })}
        {threads.length > FOLDED_COUNT && <button type="button"
          onClick={() => setShowAll((current) => ({ ...current, [project.id]: !current[project.id] }))}
          className={cn("flex min-h-7 items-center rounded-md text-left text-sm text-muted-foreground hover:text-foreground", TITLE_INSET, FOCUS_RING)}>
          {showAll[project.id] ? t("ide_threads.show_less") : fill(t("ide_threads.show_more"), { count: threads.length - FOLDED_COUNT })}
        </button>}
        {threads.length === 0 && !draftHere && !teamDraftHere && <button type="button" onClick={() => newThread(project.id)}
          className={cn("flex min-h-7 items-center gap-2 rounded-md text-left text-sm text-muted-foreground hover:text-foreground", TITLE_INSET, FOCUS_RING)}>
          <Plus aria-hidden className="h-3.5 w-3.5" />{t("ide_threads.start_thread")}
        </button>}
        {stored.length > 0 && <button type="button" aria-expanded={archiveShown}
          data-testid={`thread-archived-${project.id}`}
          onClick={() => setArchiveOpen((current) => ({ ...current, [project.id]: !archiveShown }))}
          className={cn("flex min-h-7 items-center gap-1 rounded-md pl-[30px] text-left text-sm text-muted-foreground hover:text-foreground", FOCUS_RING)}>
          {archiveShown ? <ChevronDown aria-hidden className="h-3.5 w-3.5" /> : <ChevronRight aria-hidden className="h-3.5 w-3.5" />}
          {fill(t("ide_threads.archived_count"), { count: stored.length })}
        </button>}
        {archiveShown && stored.map((session) => {
          const selected = session.session_id === openSessionId && selection.sessionId !== null;
          const menuOpen = menu?.sessionId === session.session_id;
          return <div key={session.session_id} data-testid={`thread-archived-row-${session.session_id}`}
            className={cn("group/thread relative flex min-h-8 items-center rounded-md transition-colors hover:bg-muted", (selected || menuOpen) && "bg-muted")}
            onContextMenu={(event) => {
              event.preventDefault();
              event.stopPropagation();
              menuAnchor.current = event.currentTarget;
              setMenu({ sessionId: session.session_id, projectId: project.id });
            }}>
            <button type="button" aria-current={selected ? "page" : undefined}
              onClick={() => openThread(session.session_id, project.id)} title={threadTitle(session)}
              className={cn(ROW, "flex-1 py-1 text-muted-foreground", TITLE_INSET, FOCUS_RING)}>
              <span className="min-w-0 flex-1 truncate">{threadTitle(session)}</span>
              {busy === session.session_id
                ? <Loader2 aria-hidden className="h-3.5 w-3.5 shrink-0 animate-spin text-muted-foreground" />
                : <span className="shrink-0 text-micro tabular-nums transition-opacity group-hover/thread:opacity-0 [@media(hover:none)]:opacity-0">{shortAge(session.updated_ms)}</span>}
            </button>
            <div className={cn(
              "absolute inset-y-0 right-0 flex items-center rounded-r-md bg-gradient-to-l from-muted from-60% to-transparent pl-5 pr-1 transition-opacity",
              menuOpen ? "opacity-100" : "pointer-events-none opacity-0 group-hover/thread:pointer-events-auto group-hover/thread:opacity-100 group-focus-within/thread:pointer-events-auto group-focus-within/thread:opacity-100 [@media(hover:none)]:pointer-events-auto [@media(hover:none)]:opacity-100",
            )}>
              <button type="button" aria-label={fill(t("ide_threads.restore_named"), { target: threadTitle(session) })} title={t("ide_threads.restore")}
                onClick={() => restoreThread(session.session_id)}
                className="rounded p-1 text-muted-foreground hover:bg-background/70 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                <ArchiveRestore className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>;
        })}
      </div>}
    </div>;
  };

  const menuSession = menu ? sessions.find((session) => session.session_id === menu.sessionId) ?? null : null;
  const menuArchived = menuSession !== null && menuSession.session_id in archived;
  // A thread that is working or waiting for an answer stays in view: archived, nobody would see it ask.
  const menuBusy = Boolean(menuSession?.running) || Boolean(menuSession?.pending_approvals?.length);
  // "Open side by side": not for the thread the main column shows, nor when every column is taken.
  const menuInMain = menuSession !== null && selection.sessionId === menuSession.session_id;
  const menuInSide = menuSession !== null && split.some((thread) => thread.sessionId === menuSession.session_id);
  const columnsFull = split.length + 1 >= MAX_THREAD_COLUMNS;

  return <div data-testid="ide-thread-tree" className="flex-1 px-2 pb-3 pt-2">
    {/* What one starts from here, as rows: a thread, a search, a team, a voice call. */}
    <div role="group" aria-label={t("ide_threads.layout_threads")} className="flex flex-col gap-px">
      <button type="button" data-testid="thread-tree-new-thread" onClick={() => startIn(newThread)} className={ACTION_ROW}>
        <Plus aria-hidden className={ACTION_ICON} strokeWidth={1.75} />
        <span className="min-w-0 flex-1 truncate">{t("ide_threads.new_thread")}</span>
      </button>
      {searchOn && <button type="button" data-testid="thread-tree-search" onClick={() => useQuickSwitcher.getState().show()} className={ACTION_ROW}>
        <Search aria-hidden className={ACTION_ICON} strokeWidth={1.75} />
        <span className="min-w-0 flex-1 truncate">{t("quick_switch.sidebar_search")}</span>
      </button>}
      <button type="button" data-testid="thread-tree-new-team" onClick={() => startIn(newTeam)} className={ACTION_ROW}>
        <Users aria-hidden className={ACTION_ICON} strokeWidth={1.75} />
        <span className="min-w-0 flex-1 truncate">{t("team_threads.new")}</span>
      </button>
      <button type="button" data-testid="thread-tree-voice" onClick={toggleVoice} className={ACTION_ROW}>
        <Mic aria-hidden className={ACTION_ICON} strokeWidth={1.75} />
        <span className="min-w-0 flex-1 truncate">Dodaios Live</span>
      </button>
    </div>
    {visible.some((project) => project.pinned) && <>
      <SectionLabel label={t("ide_projects.pinned")} />
      {visible.filter((project) => project.pinned).map(projectRow)}
    </>}
    <SectionLabel label={t("ide_threads.projects")}>
      <button type="button" aria-label={t("ide_projects.connect_title")} title={t("ide_projects.connect_folder_title")} onClick={connectProject}
        className={cn("flex h-6 w-6 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground", FOCUS_RING)}>
        <FolderPlus aria-hidden className="h-3.5 w-3.5" strokeWidth={1.75} />
      </button>
    </SectionLabel>
    {visible.filter((project) => !project.pinned).map(projectRow)}
    {visible.length === 0 && <p className="px-2 py-2 text-sm text-muted-foreground">{t("ide_projects.empty")}</p>}

    <ThreadPopover anchor={menuAnchor} open={menu !== null && menuSession !== null} onClose={() => { setMenu(null); setConfirmDelete(null); }}
      label={t("ide_threads.thread_actions")} width={220}>
      {menu && menuSession && (confirmDelete === menu.sessionId
        ? <div className="p-2">
          <p className="text-sm text-foreground">{t("ide_threads.delete_confirm")}</p>
          <p className="mt-1 text-xs text-muted-foreground">{t("ide_threads.delete_body")}</p>
          <div className="mt-3 flex justify-end gap-2">
            <button type="button" onClick={() => setConfirmDelete(null)} className="rounded-md px-2.5 py-1 text-sm text-muted-foreground hover:bg-secondary">{t("common.cancel")}</button>
            <button type="button" onClick={() => { const id = menu.sessionId; setMenu(null); void remove(id); }}
              className="rounded-md bg-destructive px-2.5 py-1 text-sm text-destructive-foreground">{t("common.delete")}</button>
          </div>
        </div>
        : <div role="menu">
          <ThreadMenuItem icon={<Pencil className="h-3.5 w-3.5" />} label={t("ide_threads.rename")}
            onSelect={() => { setRenaming({ sessionId: menuSession.session_id, title: threadTitle(menuSession) }); setMenu(null); }} />
          <ThreadMenuItem icon={<Columns2 className="h-3.5 w-3.5" />} label={t("ide_threads.open_side_by_side")}
            disabled={menuInMain || menuInSide || columnsFull}
            onSelect={() => { placeColumn({ sessionId: menuSession.session_id, projectId: menu.projectId }, split.length + 1); setMenu(null); }} />
          <ThreadMenuItem icon={<SquarePlus className="h-3.5 w-3.5" />} label={t("ide_threads.new_thread_here")}
            onSelect={() => { newThread(menu.projectId); setMenu(null); }} />
          {menuArchived
            ? <ThreadMenuItem icon={<ArchiveRestore className="h-3.5 w-3.5" />} label={t("ide_threads.restore")}
              onSelect={() => { restoreThread(menuSession.session_id); setMenu(null); }} />
            : <ThreadMenuItem icon={<Archive className="h-3.5 w-3.5" />} label={t("ide_threads.archive")} disabled={menuBusy}
              onSelect={() => { archiveThread(menuSession.session_id); setMenu(null); }} />}
          <ThreadMenuSeparator />
          <ThreadMenuItem icon={<Trash2 className="h-3.5 w-3.5" />} label={t("common.delete")} danger disabled={Boolean(menuSession.running)}
            onSelect={() => setConfirmDelete(menu.sessionId)} />
        </div>)}
    </ThreadPopover>
  </div>;
}
