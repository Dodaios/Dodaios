import { useEffect, useLayoutEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import { Archive, ChevronDown, ChevronRight, Folder, GitBranch, Loader2, Plus, Search, SquareTerminal, X } from "lucide-react";
import { fill, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { stopIdeRuntime, type IdeProject, type WorkspacePaneRow } from "@/lib/agenticIdeApi";
import type { AgentChatSession } from "@/lib/agentChatApi";
import { useEventStore } from "@/store/events";
import { useIdeChatStore } from "@/store/ideChat";
import { useIdeProjectsStore } from "@/store/ideProjects";
import { useIdeSidePanelStore } from "@/store/ideSidePanel";
import { useIdeThreadsStore } from "@/store/ideThreads";
import { useThreadSubagentsStore } from "@/store/threadSubagents";
import { useWorkspacePanes, useWorkspacePanesStore } from "@/store/workspacePanes";
import { usePaneReviewsStore } from "@/store/paneReviews";
import { paneTitleFrom, recapsFor, usePaneRecapPoll, usePaneRecapsStore } from "@/store/paneRecaps";
import { AgentMark } from "@/components/agentic/AgentMark";
import { GitHubIcon } from "../GitHubIcon";
import { PULL_REQUEST_TONE } from "../pullRequestTone";
import { gitHubTargetId, peekGitHubReading, threadGitHubTarget, useGitHubReadings, type GitHubTarget } from "../useSessionGitHub";
import { PULL_REQUEST_LOOK, type ThreadPullRequest } from "../threads/ThreadPullRequests";
import { isInside, projectIdFor, shortAge, threadOrderMs, threadStatus, threadTitle, threadWorktree, useThreadChatStore } from "../threads/threadModel";
import { openLinkInIdeBrowser } from "./browser/ideBrowserLinks";
import { agentSearchDocument, type AgentSearchDocument } from "./agentSearch";
import { useAgentSearch } from "./useAgentSearch";
import { dotKindFor, folderAgents, stateKeyFor } from "./agentStatus";
import {
  BOARD_COLUMNS,
  boardVerdict,
  gitHubSettled,
  sortBoardItems,
  type BoardActivity,
  type BoardColumn,
  type BoardItem,
  type BoardTone,
  type BoardVerdict,
} from "./agentBoard";

/** How often the "3m" readings move on; state changes arrive live anyway. */
const CLOCK_TICK_MS = 15_000;
/** How often the thread list is read while the thread sidebar is not there to do it. */
const THREADS_POLL_MS = 6_000;
/** Threads the board starts with, newest first; the rest wait behind "Show older". */
const SHOWN_THREADS = 40;
/** Pull requests a card names before it counts the rest. */
const SHOWN_REQUESTS = 4;
/** From this width the columns stand side by side; below it they are stacked. */
const WIDE_PX = 560;
const FOCUS_RING = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

function useClock(): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), CLOCK_TICK_MS);
    return () => window.clearInterval(timer);
  }, []);
  return now;
}

/** Whether the element is wide enough for columns side by side. */
function useWide(): [RefObject<HTMLElement>, boolean] {
  const ref = useRef<HTMLElement>(null);
  const [wide, setWide] = useState(true);
  useLayoutEffect(() => {
    const node = ref.current;
    if (!node || typeof ResizeObserver === "undefined") return;
    const measure = () => setWide(node.clientWidth >= WIDE_PX);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  return [ref, wide];
}

/** Which agents the board lists: the project in view, or every project. */
export type BoardScope = "project" | "all";

// v3: the board lists a project's threads too, so the choice is between
// projects and no longer between one workspace and its folder.
const SCOPE_KEY = "jarvis.agenticIde.agentsScope.v3";
const SCOPES: readonly BoardScope[] = ["project", "all"];

function storedScope(): BoardScope {
  try {
    return localStorage.getItem(SCOPE_KEY) === "all" ? "all" : "project";
  } catch {
    return "project";
  }
}

function useBoardScope(): [BoardScope, (scope: BoardScope) => void] {
  const [scope, setScope] = useState<BoardScope>(storedScope);
  const choose = (next: BoardScope) => {
    setScope(next);
    try {
      localStorage.setItem(SCOPE_KEY, next);
    } catch {
      /* a convenience only: the filter still works for this session */
    }
  };
  return [scope, choose];
}

/** The board's own colours for the two middle columns (light and dark), beside the status tokens. */
const TONE_TEXT: Record<BoardTone, string> = {
  building: "text-accent",
  checks: "text-[#bf3989] dark:text-[#f778ba]",
  review: "text-[#bc4c00] dark:text-[#f0883e]",
  ready: "text-success",
  attention: "text-warning",
  danger: "text-destructive",
  merged: PULL_REQUEST_TONE.merged,
  quiet: "text-muted-foreground",
};
const COLUMN_DOT: Record<BoardColumn, string> = {
  building: "bg-accent",
  checks: "bg-[#bf3989] dark:bg-[#f778ba]",
  review: "bg-[#bc4c00] dark:bg-[#f0883e]",
  ready: "bg-success",
};

interface Row {
  item: BoardItem;
  verdict: BoardVerdict;
}

/** One line under a card's title: a small mark, then where the work lives. */
function MetaLine({ icon, text, testId }: { icon: ReactNode; text: string; testId?: string }) {
  return <span data-testid={testId} className="flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground">
    <span aria-hidden className="flex h-3.5 w-3.5 shrink-0 items-center justify-center">{icon}</span>
    <span className="min-w-0 truncate">{text}</span>
  </span>;
}

/** A pull request on a card: GitHub's symbol in GitHub's colour and its number; a click opens it. */
function RequestChip({ request }: { request: ThreadPullRequest }) {
  const t = useT();
  const look = PULL_REQUEST_LOOK[request.state];
  const sized = request.additions > 0 || request.deletions > 0;
  const about = [request.title, t(look.label), sized ? `+${request.additions} −${request.deletions}` : ""].filter(Boolean).join(" · ");
  return <button type="button" disabled={!request.url} title={about}
    aria-label={`#${request.number} · ${t(look.label)}${request.title ? ` · ${request.title}` : ""}`}
    data-testid={`ide-agent-pr-${request.number}`} data-state={request.state}
    // WebView2 drops target=_blank: the IDE's Browser tab opens it.
    onClick={() => { if (request.url) void openLinkInIdeBrowser(request.url); }}
    className={cn(
      "relative z-10 -mx-1 flex items-center gap-1 rounded px-1 text-xs font-medium tabular-nums text-foreground-secondary transition-colors",
      "hover:bg-muted hover:text-foreground disabled:cursor-default", FOCUS_RING,
    )}>
    <GitHubIcon name={look.icon} width={14} height={14} className={cn("shrink-0", look.tone)} />
    #{request.number}
  </button>;
}

/**
 * What every coding agent of a project is doing, as a board.
 *
 * The side panel's Agents tab. Each thread and each terminal agent is a card:
 * its coding CLI's mark, its goal, the branch or pull requests its work lives
 * in, and a footer with its state and when it last moved. The cards stand in
 * four columns that follow from the work itself (see `agentBoard`): Building,
 * Checks, In review, Ready; work whose pull requests are merged folds into
 * "Finished" at the foot. A click on a card opens its thread or brings its
 * terminal forward; a click on a pull request opens it. A switch at the top
 * picks the project in view (the default) or every project.
 */
export function AgentsOverview() {
  const t = useT();
  const now = useClock();
  const [boardRef, wide] = useWide();
  const [scope, setScope] = useBoardScope();
  const [query, setQuery] = useState("");
  const [showOlder, setShowOlder] = useState(false);
  const [finishedOpen, setFinishedOpen] = useState(false);
  const [confirmStop, setConfirmStop] = useState(false);
  const [stopping, setStopping] = useState(false);

  const projects = useIdeProjectsStore((state) => state.projects);
  const activeWorkspaceId = useIdeProjectsStore((state) => state.activeWorkspaceId);
  const requestRefresh = useIdeProjectsStore((state) => state.requestRefresh);
  const connectProject = useIdeProjectsStore((state) => state.connectProject);
  const requestPane = useIdeChatStore((state) => state.requestPane);
  const spotlight = useIdeSidePanelStore((state) => state.spotlight);
  const setSpotlight = useIdeSidePanelStore((state) => state.setSpotlight);
  const pushToast = useEventStore((state) => state.pushToast);
  const panes = useWorkspacePanes();
  const panesLoaded = useWorkspacePanesStore((state) => state.loaded);
  usePaneRecapPoll();
  const recaps = usePaneRecapsStore((state) => state);
  const reviewed = usePaneReviewsStore((state) => state.reviewed);
  const markReviewed = usePaneReviewsStore((state) => state.markReviewed);

  const sessions = useThreadChatStore((state) => state.sessions);
  const catalog = useThreadChatStore((state) => state.catalog);
  const activeSessionId = useThreadChatStore((state) => state.activeSessionId);
  const layout = useIdeThreadsStore((state) => state.layout);
  const selection = useIdeThreadsStore((state) => state.selection);
  const projectOf = useIdeThreadsStore((state) => state.projectOf);
  const seen = useIdeThreadsStore((state) => state.seen);
  const archived = useIdeThreadsStore((state) => state.archived);

  // The thread sidebar keeps the thread list fresh while it is on screen; in
  // the grid layout nobody else does, so the board reads it itself.
  useEffect(() => {
    const store = useThreadChatStore.getState();
    if (!store.catalog || store.catalogStale) void store.loadCatalog();
    if (layout === "threads" && store.sessions.length > 0) return;
    void store.loadSessions();
    if (layout === "threads") return;
    const timer = window.setInterval(() => { void useThreadChatStore.getState().loadSessions(); }, THREADS_POLL_MS);
    return () => window.clearInterval(timer);
  }, [layout]);

  const visible = projects.filter((project) => !project.archived && !project.scratch);
  const projectById = (id: string | null | undefined) => visible.find((project) => project.id === id) ?? null;
  const workspaceProject = visible.find((project) => project.workspaces.some((workspace) => workspace.id === activeWorkspaceId)) ?? null;
  // The project in view: the open thread's in the thread layout, the front workspace's in the grid.
  const home = (layout === "threads"
    ? projectById(selection.projectId) ?? workspaceProject
    : workspaceProject ?? projectById(selection.projectId)) ?? null;
  const projectOfPane = (pane: WorkspacePaneRow): IdeProject | null =>
    visible.find((project) => project.workspaces.some((workspace) => workspace.id === pane.workspace_id))
    ?? visible.find((project) => Boolean(project.path) && isInside(pane.folder, project.path)) ?? null;

  const agentOf = new Map<string, { agent: string; label: string }>();
  for (const provider of catalog?.providers ?? []) {
    if (provider.agent) agentOf.set(provider.id, { agent: provider.agent, label: provider.label });
  }

  // Shell panes are not agents, and archived panes and threads are out of every list.
  const agentPanes = panes.filter((pane) => !pane.archived && pane.agent !== "shell");
  const panesIn: Record<BoardScope, WorkspacePaneRow[]> = {
    // Before the projects are known, the front workspace's folder stands in for its project.
    project: home ? agentPanes.filter((pane) => projectOfPane(pane)?.id === home.id) : folderAgents(panes, activeWorkspaceId),
    all: agentPanes,
  };
  const threads = sessions
    .filter((session) => !session.team_id && !(session.session_id in archived))
    .map((session) => ({ session, project: projectById(projectIdFor(session, visible, projectOf)) }))
    .filter((entry): entry is { session: AgentChatSession; project: IdeProject } => entry.project !== null)
    .sort((a, b) => threadOrderMs(b.session) - threadOrderMs(a.session));
  const threadsIn: Record<BoardScope, typeof threads> = {
    project: home ? threads.filter((entry) => entry.project.id === home.id) : [],
    all: threads,
  };
  const scopedPanes = panesIn[scope];
  const scopedThreads = threadsIn[scope];
  const openSessionId = selection.sessionId ?? activeSessionId;
  const waitingOn = (session: AgentChatSession) =>
    Boolean(session.pending_questions?.length) || Boolean(session.pending_approvals?.length);

  const paneTitle = (pane: WorkspacePaneRow) => paneTitleFrom(recapsFor(recaps, pane.workspace_id)?.[pane.name], pane);
  const documents: AgentSearchDocument[] = [
    ...scopedPanes.map((pane) => ({ ...agentSearchDocument(pane, paneTitle(pane)), id: `pane:${pane.history_id}` })),
    ...scopedThreads.map(({ session }) => ({
      id: `thread:${session.session_id}`,
      texts: [...new Set([threadTitle(session), session.preview ?? ""].map((text) => text.trim().slice(0, 1000)))].filter(Boolean),
    })),
  ];
  const searching = query.trim().length > 0;
  const search = useAgentSearch(query, documents);
  const matchRank = new Map(search.matches.map((match, index) => [match.id, index]));

  // A long project starts with its newest threads; one that works or asks is never left out.
  const listedThreads = searching
    ? scopedThreads.filter(({ session }) => matchRank.has(`thread:${session.session_id}`))
    : showOlder
      ? scopedThreads
      : scopedThreads.filter(({ session }, index) => index < SHOWN_THREADS || session.running || waitingOn(session));
  const older = scopedThreads.length - listedThreads.length;
  const listedPanes = searching ? scopedPanes.filter((pane) => matchRank.has(`pane:${pane.history_id}`)) : scopedPanes;

  const paneTarget = (pane: WorkspacePaneRow): GitHubTarget => ({ key: pane.workspace_id, pane: pane.name });
  const threadTarget = (session: AgentChatSession): GitHubTarget => {
    const target = threadGitHubTarget(session.session_id);
    const quiet = gitHubSettled(
      { running: Boolean(session.running), waiting: waitingOn(session), updatedMs: session.updated_ms },
      peekGitHubReading(target),
    );
    return { ...target, quiet };
  };
  const targets = [...listedPanes.map(paneTarget), ...listedThreads.map(({ session }) => threadTarget(session))];
  const readings = useGitHubReadings(targets);
  const statusOf = (target: GitHubTarget) => readings.get(gitHubTargetId(target))?.status ?? null;

  const items: BoardItem[] = [
    ...listedThreads.map(({ session, project }): BoardItem => {
      const status = threadStatus(session, seen, openSessionId);
      const activity: BoardActivity = status === "question" || status === "approval" ? "attention" : status === "running" ? "working" : "idle";
      const mark = agentOf.get(session.provider);
      return {
        id: `thread:${session.session_id}`,
        kind: "thread",
        title: threadTitle(session),
        agent: mark?.agent ?? "",
        agentLabel: mark?.label ?? session.provider,
        activity,
        activityKey: status === "question" ? "status.needs_answer" : status === "approval" ? "status.needs_approval"
          : status === "running" ? "status.working" : status === "unseen" ? "status.new_reply" : "status.idle",
        news: status === "unseen",
        project: scope === "all" ? project.name : "",
        place: threadWorktree(session.cwd, project.path) ?? "",
        status: statusOf(threadGitHubTarget(session.session_id)),
        atMs: threadOrderMs(session),
        thread: { sessionId: session.session_id, projectId: project.id, startedBy: session.started_by ?? "" },
      };
    }),
    ...listedPanes.map((pane): BoardItem => {
      const kind = dotKindFor(pane);
      const activity: BoardActivity = kind === "waiting" ? "attention" : kind === "error" ? "failed" : kind;
      const cli = pane.display_name || pane.agent;
      const seenAt = reviewed[pane.history_id];
      return {
        id: `pane:${pane.history_id}`,
        kind: "pane",
        title: paneTitle(pane) || cli,
        agent: pane.agent,
        agentLabel: cli,
        activity,
        activityKey: `state.${stateKeyFor(pane, kind)}`,
        // A finished job nobody has looked at since it settled.
        news: activity === "idle" && pane.worked && !(seenAt !== undefined && seenAt >= (pane.activity_since || 0)),
        project: scope === "all" ? projectOfPane(pane)?.name ?? "" : "",
        place: [pane.workspace_name, pane.name].filter(Boolean).join(" · "),
        status: statusOf(paneTarget(pane)),
        atMs: (pane.last_output_at || pane.activity_since || pane.started_at || 0) * 1000,
        pane,
      };
    }),
  ];
  const rows: Row[] = sortBoardItems(items).map((item) => ({ item, verdict: boardVerdict(item) }));
  const columns: Record<BoardColumn, Row[]> = { building: [], checks: [], review: [], ready: [] };
  const finished: Row[] = [];
  for (const row of rows) (row.verdict.place === "finished" ? finished : columns[row.verdict.place]).push(row);
  finished.sort((a, b) => b.item.atMs - a.item.atMs);
  const matches = searching
    ? [...rows].sort((a, b) => (matchRank.get(a.item.id) ?? 0) - (matchRank.get(b.item.id) ?? 0))
    : [];

  const open = ({ item }: Row) => {
    if (item.thread) {
      // The thread's own conversation, not a sub-agent's that was open in it.
      useThreadSubagentsStore.getState().openAgent(item.thread.sessionId, null);
      useIdeThreadsStore.getState().setLayout("threads");
      useIdeThreadsStore.getState().openThread(item.thread.sessionId, item.thread.projectId);
    } else if (item.pane) {
      markReviewed(item.pane.history_id);
      setSpotlight({ workspaceId: item.pane.workspace_id, pane: item.pane.name });
      requestPane(item.pane.workspace_id, item.pane.name);
    }
  };
  const startThread = () => {
    const target = home ?? visible.find((project) => project.pinned) ?? visible[0];
    if (!target) { connectProject(); return; }
    useIdeThreadsStore.getState().setLayout("threads");
    useIdeThreadsStore.getState().newThread(target.id);
  };

  const card = (row: Row) => {
    const { item, verdict } = row;
    const selected = item.thread
      ? layout === "threads" && selection.sessionId === item.thread.sessionId
      : spotlight !== null && spotlight.workspaceId === item.pane?.workspace_id && spotlight.pane === item.pane?.name;
    const stateLabel = t(`ide_side_panel.agents.${verdict.label}`);
    const requests = verdict.requests.slice(0, SHOWN_REQUESTS);
    const branch = verdict.branch || (item.kind === "thread" ? item.place : "");
    // A thread at rest can leave the board; one that works or asks stays where it is seen.
    const canArchive = item.thread !== undefined && item.activity === "idle";
    return (
      <li key={item.id} data-testid="ide-agent-card" data-item={item.id} data-kind={item.kind}
        data-place={verdict.place} data-activity={item.activity}
        data-pane={item.pane?.name} data-workspace={item.pane?.workspace_id}
        className={cn(
          "group relative flex flex-col rounded-lg border bg-card text-left transition-[border-color,background-color] duration-150 motion-reduce:transition-none",
          selected ? "border-accent bg-accent/[0.06]" : "border-border/70 hover:border-border hover:bg-muted/40",
        )}>
        <div className="flex flex-1 flex-col gap-1.5 px-3 pb-2.5 pt-3">
          <div className="flex min-w-0 items-start gap-2.5">
            <span className="mt-px flex h-5 w-5 shrink-0 items-center justify-center">
              {item.agent
                ? <AgentMark agent={item.agent} label={item.agentLabel} variant="plain" size="md" />
                : <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-muted-foreground/60" />}
            </span>
            {/* The title is the card's button; its hit area covers the whole card. */}
            <button type="button" onClick={() => open(row)} aria-current={selected ? "true" : undefined}
              aria-label={`${item.title}, ${item.agentLabel}, ${stateLabel}`} title={item.title}
              data-testid="ide-agent-title"
              className={cn(
                "min-w-0 flex-1 text-left text-sm font-semibold leading-snug text-foreground outline-none",
                "after:absolute after:inset-0 after:rounded-lg focus-visible:after:ring-2 focus-visible:after:ring-ring",
              )}>
              <span className="line-clamp-2">{item.title}</span>
            </button>
          </div>
          {(item.project || item.kind === "pane" || branch || requests.length > 0) && (
            <div className="flex flex-col gap-1 pl-[30px]">
              {item.project && <MetaLine icon={<Folder className="h-3.5 w-3.5" strokeWidth={1.75} />} text={item.project} testId="ide-agent-project" />}
              {item.kind === "pane" && <MetaLine icon={<SquareTerminal className="h-3.5 w-3.5" strokeWidth={1.75} />} text={item.place} testId="ide-agent-terminal" />}
              {branch && <MetaLine icon={<GitBranch className="h-3.5 w-3.5" strokeWidth={1.75} />} text={branch} testId="ide-agent-branch" />}
              {requests.length > 0 && (
                <span className="flex flex-wrap items-center gap-x-3 gap-y-1" data-testid="ide-agent-prs">
                  {requests.map((request) => <RequestChip key={request.number} request={request} />)}
                  {verdict.requests.length > requests.length && (
                    <span className="text-xs tabular-nums text-muted-foreground">+{verdict.requests.length - requests.length}</span>
                  )}
                </span>
              )}
            </div>
          )}
        </div>
        <div className="flex items-center justify-between gap-2 border-t border-border/60 px-3 py-1.5 text-xs">
          <span data-testid="ide-agent-state" data-tone={verdict.tone}
            className={cn("flex min-w-0 items-center gap-1.5 font-medium", TONE_TEXT[verdict.tone])}>
            {verdict.spin && <Loader2 aria-hidden className="h-3 w-3 shrink-0 animate-spin motion-reduce:animate-none" />}
            <span className="truncate">{stateLabel}</span>
          </span>
          {item.atMs > 0 && <span className="shrink-0 tabular-nums text-muted-foreground">{shortAge(item.atMs, now)}</span>}
        </div>
        {canArchive && item.thread && (
          <button type="button" aria-label={`${t("ide_threads.archive")}: ${item.title}`} title={t("ide_threads.archive")}
            data-testid="ide-agent-archive"
            onClick={() => useIdeThreadsStore.getState().archiveThread(item.thread!.sessionId)}
            className={cn(
              "absolute right-1.5 top-1.5 z-10 flex h-6 w-6 items-center justify-center rounded-md border border-border/70 bg-card text-muted-foreground",
              "opacity-0 transition-opacity hover:text-foreground focus-visible:opacity-100 group-hover:opacity-100 [@media(hover:none)]:opacity-100",
              FOCUS_RING,
            )}>
            <Archive aria-hidden className="h-3.5 w-3.5" strokeWidth={1.75} />
          </button>
        )}
      </li>
    );
  };

  // Closing the app only detaches from the agents (they live in a background
  // host), so ending them is a separate, deliberate action with its own confirm.
  const stopAll = async () => {
    setStopping(true);
    try {
      await stopIdeRuntime();
      requestRefresh();
    } catch (error) {
      pushToast("error", (error as Error).message);
    } finally {
      setStopping(false);
      setConfirmStop(false);
    }
  };

  const known = home !== null || activeWorkspaceId !== null || visible.length > 0;
  const loading = !panesLoaded && sessions.length === 0;
  const busy = search.status === "loading" || search.status === "searching";

  return (
    <section ref={boardRef} data-testid="ide-workspace-agents" data-wide={wide ? "true" : "false"}
      data-project={home?.id} aria-label={t("ide_side_panel.agents.aria")}
      className="flex h-full min-h-0 flex-col">
      {known && (
        <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-border/60 px-3 py-2">
          <div role="radiogroup" aria-label={t("ide_side_panel.agents.scope.aria")} data-testid="ide-agents-scope"
            className="flex shrink-0 rounded-md border border-border/60 bg-muted/40 p-0.5">
            {SCOPES.map((option) => (
              <button key={option} type="button" role="radio" aria-checked={scope === option}
                onClick={() => setScope(option)} data-testid={`ide-agents-scope-${option}`}
                title={option === "project" ? home?.name : undefined}
                className={cn(
                  "rounded px-2 py-1 text-xs font-medium transition-colors duration-150 motion-reduce:transition-none", FOCUS_RING,
                  scope === option ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
                )}>
                {t(`ide_side_panel.agents.scope.${option}`)}
                <span data-testid={`ide-agents-scope-count-${option}`} className="ml-1.5 tabular-nums opacity-70">
                  {panesIn[option].length + threadsIn[option].length}
                </span>
              </button>
            ))}
          </div>
          <div role="search" title={t("ide_side_panel.agents.search.hint")}
            className="flex h-8 min-w-[140px] flex-1 items-center gap-2 rounded-md border border-border/60 bg-background px-2.5 focus-within:ring-2 focus-within:ring-ring">
            <Search aria-hidden className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            <input type="search" value={query} maxLength={500}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Escape" && query) {
                  event.preventDefault();
                  event.stopPropagation();
                  setQuery("");
                }
              }}
              aria-label={t("ide_side_panel.agents.search.label")}
              placeholder={t("ide_side_panel.agents.search.placeholder")}
              className="h-full min-w-0 flex-1 bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground [&::-webkit-search-cancel-button]:hidden" />
            {query && (
              <button type="button" onClick={() => setQuery("")} aria-label={t("ide_side_panel.agents.search.clear")}
                className={cn("rounded p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground", FOCUS_RING)}>
                <X aria-hidden className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
          <button type="button" onClick={startThread} data-testid="ide-agents-new-thread"
            className={cn(
              "flex h-8 shrink-0 items-center gap-1.5 rounded-md border border-border bg-background px-2.5 text-xs font-medium text-foreground transition-colors hover:bg-muted",
              FOCUS_RING,
            )}>
            <Plus aria-hidden className="h-3.5 w-3.5" />
            {t("ide_threads.new_thread")}
          </button>
        </div>
      )}

      {!known ? (
        <p className="px-4 py-3 text-sm text-muted-foreground">{t("ide_side_panel.agents.no_project")}</p>
      ) : searching ? (
        <div className="scrollbar-jarvis min-h-0 flex-1 overflow-y-auto p-3" aria-busy={busy}>
          <p role="status" className="mb-2 flex items-center gap-2 px-1 text-xs text-muted-foreground">
            {busy && <Loader2 aria-hidden className="h-3.5 w-3.5 shrink-0 animate-spin motion-reduce:animate-none" />}
            {search.status === "loading" ? t("ide_side_panel.agents.search.loading")
              : search.status === "searching" ? t("ide_side_panel.agents.search.searching")
              : search.status === "error" ? t("ide_side_panel.agents.search.error")
              : matches.length === 0 ? t("ide_side_panel.agents.search.empty")
              : fill(t("ide_side_panel.agents.search.results"), { count: String(matches.length) })}
          </p>
          {search.status === "error" && (
            <button type="button" onClick={search.retry}
              className={cn("mb-2 rounded-md border border-border px-3 py-1.5 text-xs text-foreground hover:bg-muted", FOCUS_RING)}>
              {t("ide_side_panel.agents.search.retry")}
            </button>
          )}
          {matches.length > 0 && (
            <ul data-testid="ide-agents-matches" className="grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-2">{matches.map(card)}</ul>
          )}
        </div>
      ) : loading ? (
        <p role="status" data-testid="ide-agents-loading" className="flex items-center gap-2 px-4 py-3 text-sm text-muted-foreground">
          <Loader2 aria-hidden className="h-4 w-4 shrink-0 animate-spin motion-reduce:animate-none" />
          {t("ide_side_panel.agents.loading")}
        </p>
      ) : (
        <>
          <div data-testid="ide-agents-board"
            className={cn("scrollbar-jarvis min-h-0 flex-1", wide ? "flex overflow-x-auto" : "overflow-y-auto")}>
            {BOARD_COLUMNS.map((column, index) => {
              const cards = columns[column];
              const name = t(`ide_side_panel.agents.columns.${column}`);
              return (
                <section key={column} data-testid={`ide-agents-column-${column}`} aria-label={name}
                  className={cn(wide && "flex min-h-0 min-w-[208px] flex-1 basis-0 flex-col", wide && index > 0 && "border-l border-border/60")}>
                  <h3 className="flex h-10 shrink-0 items-center gap-2 px-3 text-sm font-medium">
                    <span aria-hidden className={cn("h-2 w-2 shrink-0 rounded-full", COLUMN_DOT[column])} />
                    <span className={cn("min-w-0 flex-1 truncate", TONE_TEXT[column])}>{name}</span>
                    <span data-testid={`ide-agents-column-count-${column}`} className="shrink-0 text-xs tabular-nums text-muted-foreground">
                      {cards.length}
                    </span>
                  </h3>
                  {cards.length > 0 ? (
                    <ul className={cn("space-y-2 px-2 pb-3", wide && "scrollbar-jarvis min-h-0 flex-1 overflow-y-auto")}>{cards.map(card)}</ul>
                  ) : wide && (
                    <p className="px-3 text-xs text-muted-foreground/80">{t(`ide_side_panel.agents.column_empty.${column}`)}</p>
                  )}
                </section>
              );
            })}
          </div>
          {finishedOpen && finished.length > 0 && (
            <div data-testid="ide-agents-finished-list" className="scrollbar-jarvis max-h-[45%] shrink-0 overflow-y-auto border-t border-border/60 p-2">
              <ul className="grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-2">{finished.map(card)}</ul>
            </div>
          )}
        </>
      )}

      {known && (
        <div data-testid="ide-agents-foot" className="flex min-h-9 shrink-0 flex-wrap items-center gap-x-3 gap-y-1 border-t border-border/60 px-3 py-1.5 text-xs text-muted-foreground">
          {!searching && finished.length > 0 && (
            <button type="button" aria-expanded={finishedOpen} onClick={() => setFinishedOpen((value) => !value)}
              data-testid="ide-agents-finished"
              className={cn("flex items-center gap-1 rounded py-0.5 pr-1 hover:text-foreground", FOCUS_RING)}>
              {finishedOpen ? <ChevronDown aria-hidden className="h-3.5 w-3.5" /> : <ChevronRight aria-hidden className="h-3.5 w-3.5" />}
              {t("ide_side_panel.agents.finished")}
              <span className="tabular-nums">{finished.length}</span>
            </button>
          )}
          {!searching && older > 0 && (
            <button type="button" onClick={() => setShowOlder(true)} data-testid="ide-agents-older"
              className={cn("rounded px-1 py-0.5 hover:text-foreground", FOCUS_RING)}>
              {fill(t("ide_side_panel.agents.show_older"), { count: String(older) })}
            </button>
          )}
          {panes.length > 0 && (
            <div data-testid="ide-agents-runtime" className="ml-auto flex items-center gap-2">
              {confirmStop ? (
                <div role="alertdialog" aria-label={t("ide_side_panel.agents.stop_all")} className="flex flex-wrap items-center gap-2">
                  <span className="text-foreground">{t("ide_side_panel.agents.stop_confirm")}</span>
                  <button type="button" disabled={stopping} onClick={() => void stopAll()} data-testid="ide-agents-stop-confirm"
                    className="rounded-md bg-destructive px-2 py-0.5 font-medium text-destructive-foreground hover:bg-destructive/90 disabled:opacity-60">
                    {t("ide_side_panel.agents.stop_confirm_yes")}
                  </button>
                  <button type="button" disabled={stopping} onClick={() => setConfirmStop(false)}
                    className="rounded-md border border-border px-2 py-0.5 text-foreground hover:bg-muted">
                    {t("ide_side_panel.agents.stop_cancel")}
                  </button>
                </div>
              ) : (
                <button type="button" onClick={() => setConfirmStop(true)} data-testid="ide-agents-stop-all"
                  title={t("ide_side_panel.agents.runtime_note")}
                  className={cn("rounded px-1 py-0.5 hover:text-destructive", FOCUS_RING)}>
                  {t("ide_side_panel.agents.stop_all")}
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
