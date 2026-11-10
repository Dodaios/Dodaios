import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, Check, ChevronDown, FolderPlus } from "lucide-react";
import { prepareGit } from "@/lib/gitApi";
import { useTeamThreads } from "@/lib/teamThreadsApi";
import type { AgentChatSession } from "@/lib/agentChatApi";
import { useEventStore } from "@/store/events";
import { fill, translate, useT } from "@/i18n";
import { useIdeProjectsStore } from "@/store/ideProjects";
import { useIdeThreadsStore, type SplitThread, type ThreadSelection } from "@/store/ideThreads";
import { useThreadTerminalsStore } from "@/store/threadTerminals";
import { openSubagentOf, useThreadSubagentsStore, type SubagentRow } from "@/store/threadSubagents";
import { ThreadRunsOn } from "./ThreadRunsOn";
import { ThreadBranchBar, type ThreadCheckout } from "./ThreadBranchBar";
import { ThreadComposer } from "./ThreadComposer";
import { ThreadHeader } from "./ThreadHeader";
import { ThreadMenuItem, ThreadPopover } from "./ThreadPopover";
import { ThreadTimeline } from "./ThreadTimeline";
import { OpenSubagent, SubagentDock, SubagentHeader } from "./ThreadSubagents";
import { useRecalledMessages, withoutRecalled } from "./recalledMessages";
import { fetchDiscoveredAgents, listSubagents, mergeDiscovered, subagentPath, subagentTurn, type DiscoveredAgent } from "./subagents";
import { projectIdFor, rememberedSeat, useThreadChat, useThreadChatStore } from "./threadModel";
import { TeamThreadView } from "./team/TeamThreadView";

/**
 * The IDE's thread layout: one conversation with a coding agent at a time.
 *
 * A thread is the agent's own CLI session driven through its binary, so its
 * tools, skills, MCP servers, permissions and login are the CLI's. The view
 * opens the thread picked in the sidebar, or a draft in a project whose first
 * message starts the thread — in the project's checkout or a fresh worktree.
 */
export function ThreadView({ onScreen, column }: {
  onScreen: boolean;
  /** A side column's thread; absent for the main column, which shows what the sidebar picked. */
  column?: SplitThread;
}) {
  const t = useT();
  // The main column's store, or the side column's own (from its provider).
  const chatStore = useThreadChat();
  const pushToast = useEventStore((state) => state.pushToast);
  const projects = useIdeProjectsStore((state) => state.projects);
  const activeWorkspaceId = useIdeProjectsStore((state) => state.activeWorkspaceId);
  const connectProject = useIdeProjectsStore((state) => state.connectProject);
  const picked = useIdeThreadsStore((state) => state.selection);
  const selection = useMemo<ThreadSelection>(
    () => (column ? { projectId: column.projectId, sessionId: column.sessionId } : picked),
    [column?.projectId, column?.sessionId, picked],
  );
  const projectOf = useIdeThreadsStore((state) => state.projectOf);
  const sidebarFocus = useIdeThreadsStore((state) => state.focusNonce);
  // A side column never takes the focus a sidebar click asks for.
  const focusNonce = column ? 0 : sidebarFocus;
  // The thread list is the sidebar's, kept fresh there; a side column's own store holds one thread.
  const sessions = useThreadChatStore((state) => state.sessions);
  const activeSessionId = chatStore((state) => state.activeSessionId);
  const activeSession = chatStore((state) => state.activeSession);
  const timeline = chatStore((state) => state.timeline);
  const recalled = useRecalledMessages((state) => (activeSessionId ? state.bySession[activeSessionId] : undefined));
  const draft = chatStore((state) => state.draft);
  const catalog = chatStore((state) => state.catalog);
  const lastError = chatStore((state) => state.lastError);
  const [checkout, setCheckout] = useState<ThreadCheckout>("current");
  const [base, setBase] = useState("");
  const [projectMenu, setProjectMenu] = useState(false);
  const [composerHeight, setComposerHeight] = useState(160);
  // The sub-agent whose conversation shows instead of the main thread's, by its spawn
  // call. It lives in a store so the sidebar's sub-agent rows open it too.
  const openAgent = useThreadSubagentsStore((state) => openSubagentOf(state.open, selection.sessionId));
  // This column's thread: a side column opens its own sub-agents, not the sidebar's pick.
  const ownSessionId = selection.sessionId;
  const setOpenAgent = useCallback((id: string | null) => {
    if (ownSessionId) useThreadSubagentsStore.getState().openAgent(ownSessionId, id);
  }, [ownSessionId]);
  // Sub-agents the CLI filed on its own (Codex), read for the open thread.
  const [discovered, setDiscovered] = useState<{ sessionId: string; agents: DiscoveredAgent[] } | null>(null);
  const projectAnchor = useRef<HTMLButtonElement | null>(null);
  // The draft whose first message is on its way: its session belongs to this project.
  const startingIn = useRef<string | null>(null);

  const visible = useMemo(() => projects.filter((project) => !project.archived && !project.scratch), [projects]);
  const session = selection.sessionId
    ? (activeSession?.session_id === selection.sessionId ? activeSession : sessions.find((row) => row.session_id === selection.sessionId) ?? null)
    : null;
  const fallbackProject = visible.find((project) => project.workspaces.some((workspace) => workspace.id === activeWorkspaceId)) ?? visible[0] ?? null;
  const project = visible.find((entry) => entry.id === selection.projectId)
    ?? (session ? visible.find((entry) => entry.id === projectIdFor(session, visible, projectOf)) : undefined)
    ?? fallbackProject;
  const folder = session?.cwd || project?.path || "";
  // A team thread on screen is neither a thread nor a thread's draft.
  const isDraft = selection.sessionId === null && !selection.team;
  const originatingProject = project?.id;
  const rememberCreated = useCallback((created: AgentChatSession) => {
    if (originatingProject) useIdeThreadsStore.getState().rememberProject(created.session_id, originatingProject);
  }, [originatingProject]);

  // The terminal drawer and its caption toggle open shells in this folder.
  useEffect(() => { if (!column) useThreadTerminalsStore.getState().setFolder(folder); }, [column, folder]);

  // Keep the store on what the sidebar picked. A draft's first message
  // creates its session: that is this project's thread now — unless the
  // person moved on while it was being created; then it only remembers where
  // it belongs, and the thread they picked is what shows.
  useEffect(() => {
    const store = chatStore.getState();
    const threads = useIdeThreadsStore.getState();
    const pending = startingIn.current;
    const created = pending && store.activeSessionId && store.activeSessionId !== selection.sessionId ? store.activeSessionId : null;
    if (pending && created) {
      startingIn.current = null;
      if (!selection.sessionId && !selection.team && selection.projectId === pending) {
        threads.adoptThread(created, pending);
        return;
      }
      threads.rememberProject(created, pending);
    } else if (pending && (selection.sessionId || selection.team)) {
      // The person opened another thread before the draft's thread existed:
      // the send files that thread under its project itself (onSessionCreated),
      // and a leftover mark must not refile or adopt a later thread.
      startingIn.current = null;
    }
    if (selection.sessionId) {
      if (store.activeSessionId !== selection.sessionId) store.openSession(selection.sessionId);
      return;
    }
    if (startingIn.current) return; // the draft's first message is on its way
    if (selection.team) return; // a team thread shows; the thread store keeps what it has
    if (store.activeSessionId || store.timeline.items.length > 0) store.newChat();
  }, [selection.sessionId, selection.projectId, selection.team, activeSessionId]);

  // The agents are listed the moment the view opens, not when a menu is.
  useEffect(() => {
    const store = chatStore.getState();
    if (!store.catalog || store.catalogStale) void store.loadCatalog();
  }, []);

  // A new draft starts in its project's own checkout, on the agent and model
  // the person picked last — never on whatever thread happened to be open.
  useEffect(() => {
    if (!isDraft) return;
    setCheckout("current");
    setBase("");
    // Never picked here yet: the seat of the newest thread is the last choice made.
    const store = chatStore.getState();
    const cli = new Set((store.catalog?.providers ?? []).filter((row) => row.agent).map((row) => row.id));
    const newest = [...store.sessions].filter((row) => cli.has(row.provider)).sort((x, y) => y.created_ms - x.created_ms)[0];
    const seat = rememberedSeat() ?? (newest
      ? { provider: newest.provider, model: newest.model, effort: newest.effort, permissionMode: newest.permission_mode }
      : null);
    const draftNow = chatStore.getState().draft;
    if (seat && (seat.provider !== draftNow.provider || seat.model !== draftNow.model
      || seat.effort !== draftNow.effort || seat.permissionMode !== draftNow.permissionMode)) {
      void chatStore.getState().setDraft(seat);
    }
  }, [isDraft, selection.projectId, sessions.length > 0, Boolean(catalog)]);

  // A draft runs in its project's folder.
  useEffect(() => {
    if (!isDraft || !project || activeSessionId || startingIn.current) return;
    if (chatStore.getState().draft.cwd !== project.path) void chatStore.getState().setDraft({ cwd: project.path });
  }, [isDraft, project, activeSessionId, draft.cwd]);

  // Keep the open thread marked as read.
  useEffect(() => {
    const row = sessions.find((entry) => entry.session_id === selection.sessionId);
    if (row && onScreen) useIdeThreadsStore.getState().markSeen(row.session_id, row.updated_ms);
  }, [sessions, selection.sessionId, onScreen]);

  // How tall the composer is, so the conversation scrolls clear of it. The
  // box only exists once the thread has messages — a draft's first send
  // mounts it later — so it is measured whenever it attaches, not on mount.
  const composerObserver = useRef<ResizeObserver | null>(null);
  const composerBox = useCallback((box: HTMLDivElement | null) => {
    composerObserver.current?.disconnect();
    composerObserver.current = null;
    if (!box) return;
    setComposerHeight(box.offsetHeight);
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => setComposerHeight(box.offsetHeight));
    observer.observe(box);
    composerObserver.current = observer;
  }, []);

  const prepareDraft = useCallback(async (): Promise<string | null> => {
    if (!project) {
      pushToast("error", translate("ide_threads.connect_folder_first"));
      return null;
    }
    startingIn.current = project.id;
    if (checkout !== "worktree") return project.path;
    try {
      const prepared = await prepareGit(project.path, { mode: "new_worktree", branch: "", base });
      if (prepared.message) pushToast("success", prepared.message);
      return prepared.folder;
    } catch (error) {
      startingIn.current = null;
      throw error;
    }
  }, [project, checkout, base, pushToast]);

  // A failed first send leaves the draft a draft.
  useEffect(() => {
    if (isDraft && !activeSessionId && lastError) startingIn.current = null;
  }, [isDraft, activeSessionId, lastError]);

  const running = timeline.items.some((item) => item.type === "turn" && item.status === "running");
  // Codex streams the main agent only; its sub-agents' steps come from its own files.
  const codexThread = Boolean(session && catalog?.providers.find((row) => row.id === session.provider)?.runner === "codex-cli");
  useEffect(() => {
    const id = selection.sessionId;
    if (!codexThread || !id || !onScreen) return;
    let stopped = false;
    const load = () => {
      fetchDiscoveredAgents(id)
        .then((agents) => { if (!stopped) setDiscovered({ sessionId: id, agents }); })
        // A failed read leaves the cards the stream reported; the next poll or visit tries again.
        .catch((error: unknown) => console.debug("thread sub-agents unavailable", error));
    };
    load();
    const timer = running ? window.setInterval(load, 4000) : undefined;
    return () => {
      stopped = true;
      if (timer !== undefined) window.clearInterval(timer);
    };
  }, [codexThread, selection.sessionId, running, onScreen]);
  const items = useMemo(() => {
    const shown = withoutRecalled(timeline.items, recalled);
    return discovered && discovered.sessionId === selection.sessionId
      ? mergeDiscovered(shown, discovered.agents, session?.vendor_session ?? "")
      : shown;
  }, [timeline.items, recalled, discovered, selection.sessionId, session?.vendor_session]);
  const agents = useMemo(() => listSubagents(items), [items]);
  const agentPath = useMemo(() => (openAgent ? subagentPath(agents, openAgent) : []), [agents, openAgent]);
  const agent = agentPath.length ? agentPath[agentPath.length - 1] : null;
  const agentItems = useMemo(() => (agent ? [subagentTurn(agent)] : []), [agent]);
  const userCount = timeline.items.filter((item) => item.type === "user").length;

  // The sidebar lists the open thread's sub-agents under it — the main
  // column's thread only; a side column never overwrites or clears those rows.
  useEffect(() => {
    if (column) return;
    const rows: SubagentRow[] = agents.map((entry) => ({
      id: entry.id, parentId: entry.parentId, depth: entry.depth, title: entry.title,
      agentType: entry.agentType, status: entry.status, waiting: entry.waiting,
    }));
    useThreadSubagentsStore.getState().publish(selection.team ? null : selection.sessionId, rows);
  }, [agents, selection.sessionId, selection.team, column]);
  useEffect(() => () => { if (!column) useThreadSubagentsStore.getState().publish(null, []); }, [column]);

  // Another thread, or a new message to the main agent, brings the main conversation back.
  useEffect(() => {
    if (column) return;
    const open = useThreadSubagentsStore.getState().open;
    if (open && open.sessionId !== selection.sessionId) useThreadSubagentsStore.getState().openAgent(open.sessionId, null);
  }, [selection.sessionId, column]);
  const sentCount = useRef(userCount);
  useEffect(() => {
    if (userCount > sentCount.current) setOpenAgent(null);
    sentCount.current = userCount;
  }, [userCount, setOpenAgent]);

  // Escape leaves a sub-agent's conversation for the one it came from.
  useEffect(() => {
    if (!openAgent || !onScreen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      const target = event.target as HTMLElement | null;
      if (target?.closest("textarea, input, [contenteditable=true], [role=dialog], [role=menu]")) return;
      const parent = agentPath.length > 1 ? agentPath[agentPath.length - 2].id : null;
      setOpenAgent(parent);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [openAgent, onScreen, agentPath]);

  if (!project) {
    return <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center" data-testid="thread-view-empty">
      <FolderPlus className="h-8 w-8 text-muted-foreground/70" />
      <h1 className="text-lg font-medium">{t("ide_threads.connect_a_project")}</h1>
      <p className="max-w-md text-sm text-muted-foreground">{t("ide_threads.empty_body")}</p>
      <button type="button" onClick={connectProject} className="mt-2 rounded-md border border-border px-3 py-1.5 text-sm hover:bg-secondary">{t("ide_threads.connect_folder")}</button>
    </div>;
  }

  if (selection.team) {
    return <TeamThreadView key={selection.team} team={selection.team} project={project} onScreen={onScreen} />;
  }

  const memberOf = selection.fromTeam || session?.team_id || "";
  const threadKey = selection.sessionId ?? `draft:${project.id}`;
  const [buildBefore, buildAfter = ""] = t("ide_threads.build_in").split("{project}");
  const empty = isDraft && timeline.items.length === 0;

  const runsOn = <ThreadRunsOn computerId={session?.computer_id ?? draft.computerId ?? ""} locked={running}
    onChange={(computerId) => void chatStore.getState().setDraft({ computerId })} />;
  // The branch bar tucks under the composer card, so it must come right after
  // it; the "Runs on" line sits below the bar.
  const strip = <>
    <ThreadBranchBar folder={folder} draft={isDraft} checkout={checkout} onCheckout={setCheckout}
      base={base} onBase={setBase} locked={running} />
    {runsOn}
  </>;

  return <div className="relative flex h-full min-h-0 flex-col" data-testid="thread-view">
    {memberOf && <BackToTeam teamId={memberOf} projectId={project.id} />}
    {session && !empty && <ThreadHeader session={session} projectId={project.id} folder={folder} workspaceId={activeWorkspaceId} />}
    {empty
      ? <div className="flex min-h-0 flex-1 flex-col items-center justify-center px-5 pb-10">
        <h2 className="text-center text-2xl font-normal tracking-tight text-foreground sm:text-3xl">
          {buildBefore}
          <button ref={projectAnchor} type="button" aria-haspopup="menu" aria-expanded={projectMenu} onClick={() => setProjectMenu(!projectMenu)}
            className="inline-flex items-center gap-1 rounded-md font-semibold text-foreground-strong hover:bg-secondary/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            data-testid="thread-project-picker">
            {project.name}<ChevronDown aria-hidden className="h-4 w-4 text-muted-foreground" />
          </button>{buildAfter}
        </h2>
        <ThreadPopover anchor={projectAnchor} open={projectMenu} onClose={() => setProjectMenu(false)} label={t("ide_threads.projects")} width={260}>
          <div role="menu">
            {visible.map((entry) => <ThreadMenuItem key={entry.id} label={entry.name} selected={entry.id === project.id}
              hint={entry.id === project.id ? <Check className="h-3.5 w-3.5" /> : undefined}
              onSelect={() => { setProjectMenu(false); useIdeThreadsStore.getState().newThread(entry.id); }} />)}
            <ThreadMenuItem icon={<FolderPlus className="h-3.5 w-3.5" />} label={t("ide_threads.connect_another")} onSelect={() => { setProjectMenu(false); connectProject(); }} />
          </div>
        </ThreadPopover>
        <div className="mt-7 w-full">
          <ThreadComposer threadKey={threadKey} prepareDraft={prepareDraft} onSessionCreated={rememberCreated} autoFocusNonce={focusNonce + (onScreen ? 1 : 0)} strip={strip} onScreen={onScreen} />
        </div>
      </div>
      : <OpenSubagent.Provider value={setOpenAgent}>
        {agent
          ? <ThreadTimeline items={agentItems} sessionId={`agent:${agent.id}`} bottomInset={composerHeight} folder={folder}
            lead={<SubagentHeader entry={agent} path={agentPath} onOpen={setOpenAgent} />} />
          : <ThreadTimeline items={items} sessionId={selection.sessionId} bottomInset={composerHeight} folder={folder} />}
        <div ref={composerBox} className="pointer-events-none absolute inset-x-0 bottom-0 bg-gradient-to-t from-background from-70% to-transparent px-5 pb-4 pt-6">
          <div className="pointer-events-auto">
            <ThreadComposer threadKey={threadKey} prepareDraft={prepareDraft} onSessionCreated={rememberCreated} autoFocusNonce={focusNonce} strip={strip} onScreen={onScreen}
              tray={<SubagentDock entries={agents} openId={agent ? agent.id : null} onOpen={setOpenAgent} />} />
          </div>
        </div>
      </OpenSubagent.Provider>}
  </div>;
}

/**
 * A team member's own thread leads back to its team: the members are kept out
 * of the thread list, so without this line the team could not be reached
 * from here again.
 */
function BackToTeam({ teamId, projectId }: { teamId: string; projectId: string }) {
  const t = useT();
  const title = useTeamThreads().data?.find((row) => row.team_id === teamId)?.title ?? "";
  return <div className="flex h-9 shrink-0 items-center border-b border-border px-3" data-testid="thread-back-to-team">
    <button type="button" onClick={() => useIdeThreadsStore.getState().openTeam(teamId, projectId)}
      className="flex min-w-0 items-center gap-1.5 rounded-md px-1.5 py-1 text-sm text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
      <ArrowLeft aria-hidden className="h-3.5 w-3.5 shrink-0" />
      <span className="truncate">{title ? fill(t("team_threads.room.back_named"), { title }) : t("team_threads.room.back")}</span>
    </button>
  </div>;
}
